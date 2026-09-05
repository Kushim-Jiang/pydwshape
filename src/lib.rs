// dwtshape — DirectWriteCore step-by-step shaping tracer (Rust).
//
// EVERYTHING runs on DWriteCore (app-local, version-pinned, hijack-proof):
// the authoritative final glyphs + positions AND the per-lookup trace.
//
// The per-lookup trace is captured by self-hooking one internal function of
// DWriteCore's Rust `otls` engine — the GSUB/GPOS single-lookup dispatcher:
//
//   DWriteCore 2.1.1.2605, RVA 0x6d280
//   prologue (verified): 41 57 41 56 41 55 41 54 56 57 55 53 48 81 ec ...
//
// On entry:
//   arg5 (5th stack arg, [rsp+0x28]) = glyph-buffer object
//     [obj+0x08] = pointer to glyph records (8-byte stride; gid = u16@0)
//     [obj+0x10] = glyph record count
// The buffer content at each entry is the run state BEFORE that lookup, so
// diffing consecutive entries reproduces the substitution timeline exactly
// (verified: matches TextShaping/HarfBuzz for the Mongolian golden case).
//
// Output schema = babelsoft `/api/opentype/shape` engine result (Crowbar
// stages), DirectWrite-analogue of the HarfBuzz/HarfRust engines. No system
// TextShaping / dwrite is used at all.

#![allow(non_snake_case)]
#![allow(clippy::missing_safety_doc)]

use std::cell::RefCell;
use std::env;
use std::ffi::{c_void, CString};
use std::ptr;

use serde_json::{json, Value};
use windows::core::{Interface, PCSTR, PCWSTR};
use windows::Win32::Foundation::BOOL;
use windows::Win32::Graphics::DirectWrite::{
    DWRITE_FACTORY_TYPE_SHARED, DWRITE_FONT_FACE_TYPE_UNKNOWN, DWRITE_FONT_FEATURE,
    DWRITE_FONT_FEATURE_TAG, DWRITE_FONT_SIMULATIONS_NONE, DWRITE_GLYPH_OFFSET,
    DWRITE_SCRIPT_ANALYSIS, DWRITE_SCRIPT_PROPERTIES, DWRITE_SCRIPT_SHAPES,
    DWRITE_SHAPING_GLYPH_PROPERTIES, DWRITE_SHAPING_TEXT_PROPERTIES, DWRITE_TYPOGRAPHIC_FEATURES,
    IDWriteFactory, IDWriteFontFace, IDWriteFontFile, IDWriteTextAnalyzer, IDWriteTextAnalyzer1,
};
use windows::Win32::System::LibraryLoader::{GetProcAddress, LoadLibraryW};
use windows::Win32::System::Memory::{
    VirtualAlloc, VirtualFree, VirtualProtect, MEM_COMMIT, MEM_RELEASE, MEM_RESERVE,
    PAGE_EXECUTE_READWRITE, PAGE_PROTECTION_FLAGS,
};

// ---------------------------------------------------------------------------
// Hook registry (DWriteCore.dll 2.1.1.2605) — the per-lookup dispatcher.
// ---------------------------------------------------------------------------
const DWC_LOOKUP_RVA: u64 = 0x6d280;
const SIG_DWC_LOOKUP: [u8; 12] = [
    0x41, 0x57, 0x41, 0x56, 0x41, 0x55, 0x41, 0x54, 0x56, 0x57, 0x55, 0x53,
];

// ---------------------------------------------------------------------------
// Trace capture state (single-threaded: our own thread drives shaping).
// ---------------------------------------------------------------------------
#[derive(Clone, PartialEq)]
struct GlyphRec {
    gid: u16,
    flags: u16,
    idx: u16,
}

#[derive(Clone)]
struct SnapEvt {
    table: String,
    n: u32,
    recs: Vec<GlyphRec>,
}

struct Ctx {
    active: bool,
    table: String,
    lookup_n: u32,
    snaps: Vec<SnapEvt>,
    msgs: Vec<String>,
}

thread_local! {
    static ST: RefCell<Ctx> = RefCell::new(Ctx {
        active: false,
        table: "GSUB".into(),
        lookup_n: 0,
        snaps: Vec::new(),
        msgs: Vec::new(),
    });
}

unsafe fn rd_u16(p: *const u8, off: usize) -> u16 {
    ptr::read_unaligned(p.add(off) as *const u16)
}
unsafe fn rd_u64(p: *const u8, off: usize) -> u64 {
    ptr::read_unaligned(p.add(off) as *const u64)
}

// --- DWriteCore per-lookup onEnter ------------------------------------------
// arg = glyph-buffer object (5th stack arg). [obj+8]=records, [obj+0x10]=count.
extern "C" fn on_dwc_lookup(buf: u64) -> u64 {
    ST.with(|s| {
        let mut st = s.borrow_mut();
        if !st.active || buf == 0 {
            return;
        }
        let obj = buf as *const u8;
        let recptr = unsafe { rd_u64(obj, 0x08) };
        let count = unsafe { rd_u64(obj, 0x10) } as usize;
        if recptr == 0 || count == 0 || count > 4096 {
            return;
        }
        st.lookup_n += 1;
        let n = st.lookup_n;
        let base = recptr as *const u8;
        let mut recs: Vec<GlyphRec> = Vec::with_capacity(count.min(4096));
        for i in 0..count {
            let o = i * 8;
            recs.push(GlyphRec {
                gid: unsafe { rd_u16(base, o) },
                flags: unsafe { rd_u16(base, o + 2) },
                idx: unsafe { rd_u16(base, o + 4) },
            });
        }
        let table = st.table.clone();
        st.snaps.push(SnapEvt { table, n, recs });
    });
    0
}

// ---------------------------------------------------------------------------
// Minimal inline-hook engine: 12-byte absolute-jump patch + trampoline, and a
// stub that calls `on_dwc_lookup(arg5)` preserving rcx/rdx/r8/r9.
// ---------------------------------------------------------------------------
fn abs_jmp(dst: u64) -> Vec<u8> {
    // mov rax, imm64 ; jmp rax
    let mut v = vec![0x48, 0xB8];
    v.extend_from_slice(&dst.to_le_bytes());
    v.extend_from_slice(&[0xFF, 0xE0]);
    v
}

unsafe fn alloc_near(module: u64, size: usize) -> *mut c_void {
    let hint_start = (module + 0x1000 + 0xFFF) & !0xFFF;
    for i in 0..1024u64 {
        let hint = hint_start.wrapping_add(i * 0x10000);
        let p = VirtualAlloc(
            Some(hint as *const c_void),
            size,
            MEM_COMMIT | MEM_RESERVE,
            PAGE_EXECUTE_READWRITE,
        );
        if !p.is_null() {
            let d = (p as i64 - module as i64).unsigned_abs();
            if d <= i32::MAX as u64 {
                return p;
            }
            let _ = VirtualFree(p, 0, MEM_RELEASE);
        }
    }
    panic!("could not allocate scratch page near module {module:#x}");
}

unsafe fn install_dwc_hook(
    block: *mut c_void,
    block_size: usize,
    target: u64,
    orig: &[u8],
    tramp_off: usize,
    stub_off: usize,
) {
    let block_base = block as u64;
    let tramp = block_base + tramp_off as u64;
    let stub = block_base + stub_off as u64;
    assert!(
        stub_off + 160 <= block_size && tramp_off + 32 <= block_size,
        "hook layout exceeds block"
    );

    // trampoline: original[0..12] + abs jmp target+12
    let mut t: Vec<u8> = Vec::new();
    t.extend_from_slice(&orig[..12]);
    t.extend_from_slice(&abs_jmp(target + 12));
    ptr::copy_nonoverlapping(t.as_ptr(), tramp as *mut u8, t.len());

    // stub (calls on_dwc_lookup with arg5 = [entry rsp + 0x28]):
    let mut s: Vec<u8> = Vec::new();
    s.extend_from_slice(&[0x4C, 0x8B, 0x54, 0x24, 0x28]); // mov r10,[rsp+0x28]  (arg5)
    s.extend_from_slice(&[0x48, 0x83, 0xEC, 0x48]); // sub rsp,0x48
    s.extend_from_slice(&[0x48, 0x89, 0x4C, 0x24, 0x20]); // mov [rsp+20],rcx
    s.extend_from_slice(&[0x48, 0x89, 0x54, 0x24, 0x28]); // mov [rsp+28],rdx
    s.extend_from_slice(&[0x4C, 0x89, 0x44, 0x24, 0x30]); // mov [rsp+30],r8
    s.extend_from_slice(&[0x4C, 0x89, 0x4C, 0x24, 0x38]); // mov [rsp+38],r9
    let logfn: extern "C" fn(u64) -> u64 = on_dwc_lookup;
    s.extend_from_slice(&[0x4C, 0x89, 0xD1]); // mov rcx,r10  (arg1 = buf)
    s.extend_from_slice(&[0x48, 0xB8]);
    s.extend_from_slice(&(logfn as usize as u64).to_le_bytes());
    s.extend_from_slice(&[0xFF, 0xD0]); // call rax
    s.extend_from_slice(&[0x48, 0x8B, 0x4C, 0x24, 0x20]); // mov rcx,[rsp+20]
    s.extend_from_slice(&[0x48, 0x8B, 0x54, 0x24, 0x28]); // mov rdx,[rsp+28]
    s.extend_from_slice(&[0x4C, 0x8B, 0x44, 0x24, 0x30]); // mov r8,[rsp+30]
    s.extend_from_slice(&[0x4C, 0x8B, 0x4C, 0x24, 0x38]); // mov r9,[rsp+38]
    s.extend_from_slice(&[0x48, 0x83, 0xC4, 0x48]); // add rsp,0x48
    s.extend_from_slice(&abs_jmp(tramp));
    ptr::copy_nonoverlapping(s.as_ptr(), stub as *mut u8, s.len());

    // patch target: abs_jmp(stub) (12 bytes)
    let patch = abs_jmp(stub);
    let mut old = PAGE_PROTECTION_FLAGS(0);
    let page = (target & !0xFFF) as *const c_void;
    VirtualProtect(page, 0x1000, PAGE_EXECUTE_READWRITE, &mut old).ok();
    ptr::copy_nonoverlapping(patch.as_ptr(), target as *mut u8, patch.len());
    let _ = VirtualProtect(page, 0x1000, old, &mut old);
}

// ---------------------------------------------------------------------------
// sfnt helpers: upem / glyph_count.
// ---------------------------------------------------------------------------
fn be16(d: &[u8], o: usize) -> u16 {
    ((d[o] as u16) << 8) | d[o + 1] as u16
}
fn be32(d: &[u8], o: usize) -> u32 {
    ((d[o] as u32) << 24) | ((d[o + 1] as u32) << 16) | ((d[o + 2] as u32) << 8) | d[o + 3] as u32
}

fn sfnt_meta(data: &[u8]) -> (u32, u32) {
    if data.len() < 12 {
        return (2048, 0);
    }
    let tag = &data[0..4];
    let num = if tag == b"ttcf" {
        if data.len() < 16 {
            return (2048, 0);
        }
        let of = be32(data, 8) as usize;
        if of + 12 > data.len() {
            return (2048, 0);
        }
        be16(data, of + 4) as usize
    } else if tag == b"OTTO" || tag == b"\x00\x01\x00\x00" || tag == b"true" || tag == b"typ1" {
        0
    } else {
        return (2048, 0);
    };
    let ntables = be16(data, num + 4) as usize;
    let mut head_off: Option<usize> = None;
    let mut maxp_off: Option<usize> = None;
    for i in 0..ntables {
        let rec = num + 12 + i * 16;
        if rec + 16 > data.len() {
            break;
        }
        match &data[rec..rec + 4] {
            b"head" => head_off = Some(be32(data, rec + 8) as usize),
            b"maxp" => maxp_off = Some(be32(data, rec + 8) as usize),
            _ => {}
        }
    }
    let upem = head_off
        .filter(|&o| o + 20 <= data.len())
        .map(|o| be16(data, o + 18))
        .unwrap_or(2048) as u32;
    let nglyphs = maxp_off
        .filter(|&o| o + 6 <= data.len())
        .map(|o| be16(data, o + 4))
        .unwrap_or(0) as u32;
    (upem, nglyphs)
}

// ---------------------------------------------------------------------------
// DWriteCore driver.
// ---------------------------------------------------------------------------
struct Engine {
    analyzer: IDWriteTextAnalyzer,
    analyzer1: IDWriteTextAnalyzer1,
    face: IDWriteFontFace,
}

unsafe fn make_engine(dll_path: &str, font_path: &str) -> Engine {
    let w: Vec<u16> = dll_path.encode_utf16().chain(std::iter::once(0)).collect();
    let lib = LoadLibraryW(PCWSTR(w.as_ptr())).expect("LoadLibraryW(DWriteCore) failed");
    let name = CString::new("DWriteCoreCreateFactory").unwrap();
    let proc = GetProcAddress(lib, PCSTR(name.as_ptr() as *const u8))
        .expect("GetProcAddress(DWriteCoreCreateFactory) failed");
    type F = extern "system" fn(i32, *const windows::core::GUID, *mut *mut c_void)
        -> windows::core::HRESULT;
    let create: F = std::mem::transmute(proc);
    let mut raw: *mut c_void = ptr::null_mut();
    create(DWRITE_FACTORY_TYPE_SHARED.0, &IDWriteFactory::IID, &mut raw)
        .ok()
        .expect("DWriteCoreCreateFactory failed");
    let factory = IDWriteFactory::from_raw(raw);
    let analyzer: IDWriteTextAnalyzer = factory.CreateTextAnalyzer().expect("analyzer");
    let analyzer1: IDWriteTextAnalyzer1 = analyzer.cast().expect("no IDWriteTextAnalyzer1");
    let pwide: Vec<u16> = font_path
        .encode_utf16()
        .chain(std::iter::once(0))
        .collect();
    let fontfile: IDWriteFontFile = factory
        .CreateFontFileReference(PCWSTR(pwide.as_ptr()), None)
        .expect("font file ref");
    let face: IDWriteFontFace = factory
        .CreateFontFace(
            DWRITE_FONT_FACE_TYPE_UNKNOWN,
            &[Some(fontfile)],
            0,
            DWRITE_FONT_SIMULATIONS_NONE,
        )
        .expect("font face");
    Engine {
        analyzer,
        analyzer1,
        face,
    }
}

fn resolve_script(analyzer1: &IDWriteTextAnalyzer1, tag: &str) -> u16 {
    let mut b = [0u8; 4];
    let src = tag.as_bytes();
    for i in 0..4 {
        let c = src.get(i).copied().unwrap_or(b' ');
        b[i] = if i == 0 {
            c.to_ascii_uppercase()
        } else {
            c.to_ascii_lowercase()
        };
    }
    let want = u32::from_le_bytes(b);
    for s in 0u32..0x10000 {
        let analysis = DWRITE_SCRIPT_ANALYSIS {
            script: s as u16,
            shapes: DWRITE_SCRIPT_SHAPES(0),
        };
        let mut props = DWRITE_SCRIPT_PROPERTIES::default();
        unsafe {
            if analyzer1.GetScriptProperties(analysis, &mut props).is_ok()
                && props.isoScriptCode != 0
                && props.isoScriptCode == want
            {
                return s as u16;
            }
        }
    }
    panic!("script tag '{tag}' not found");
}

struct ShapeResult {
    glyphs: Vec<u16>,
    glyphprops: Vec<DWRITE_SHAPING_GLYPH_PROPERTIES>,
    textprops: Vec<DWRITE_SHAPING_TEXT_PROPERTIES>,
    cluster_map: Vec<u16>,
}

unsafe fn run_getglyphs(
    engine: &Engine,
    text: &[u16],
    script: u16,
    rtl: bool,
    locale: Option<&str>,
    feats: Option<&[DWRITE_FONT_FEATURE]>,
) -> ShapeResult {
    let analysis = DWRITE_SCRIPT_ANALYSIS {
        script,
        shapes: DWRITE_SCRIPT_SHAPES(1),
    };
    let len = text.len() as u32;
    let max = (len * 4 + 16).max(64);
    let mut clusters = vec![0u16; len as usize];
    let mut textprops = vec![DWRITE_SHAPING_TEXT_PROPERTIES::default(); max as usize];
    let mut glyphs = vec![0u16; max as usize];
    let mut gprops = vec![DWRITE_SHAPING_GLYPH_PROPERTIES::default(); max as usize];
    let mut actual = 0u32;

    let locale_wide: Vec<u16>;
    let locale_ptr = match locale {
        Some(l) => {
            locale_wide = l.encode_utf16().chain(std::iter::once(0)).collect();
            PCWSTR(locale_wide.as_ptr())
        }
        None => PCWSTR::null(),
    };

    ST.with(|s| {
        let mut st = s.borrow_mut();
        st.active = true;
        st.table = "GSUB".into();
        st.lookup_n = 0;
    });
    // GetGlyphs uses the typographic-features model:
    //   features = &[*const DWRITE_TYPOGRAPHIC_FEATURES] ; ranges = [textLength]
    let mut feat_owned: Vec<DWRITE_FONT_FEATURE> = feats.map(|s| s.to_vec()).unwrap_or_default();
    let mut typo_box: Option<Box<DWRITE_TYPOGRAPHIC_FEATURES>> = None;
    let mut feats_arr: Option<Box<[*const DWRITE_TYPOGRAPHIC_FEATURES; 1]>> = None;
    let mut feats_pp: Option<*const *const DWRITE_TYPOGRAPHIC_FEATURES> = None;
    let mut range_lens_pp: Option<*const u32> = None;
    let mut feat_ranges: u32 = 0;
    if !feat_owned.is_empty() {
        let typo = Box::new(DWRITE_TYPOGRAPHIC_FEATURES {
            features: feat_owned.as_mut_ptr(),
            featureCount: feat_owned.len() as u32,
        });
        let typo_ptr: *const DWRITE_TYPOGRAPHIC_FEATURES = &*typo;
        typo_box = Some(typo);
        feats_arr = Some(Box::new([typo_ptr]));
        feats_pp = Some(feats_arr.as_ref().unwrap().as_ptr());
        let range_lens = vec![len];
        range_lens_pp = Some(range_lens.as_ptr());
        feat_ranges = 1;
        std::mem::forget(range_lens); // keep alive through the call below
    }
    let _ = (&typo_box, &feats_arr);
    engine
        .analyzer
        .GetGlyphs(
            PCWSTR(text.as_ptr()),
            len,
            &engine.face,
            BOOL(0),
            BOOL(rtl as i32),
            &analysis,
            locale_ptr,
            None, // numberSubstitution
            feats_pp,
            range_lens_pp,
            feat_ranges,
            max,
            clusters.as_mut_ptr(),
            textprops.as_mut_ptr(),
            glyphs.as_mut_ptr(),
            gprops.as_mut_ptr(),
            &mut actual,
        )
        .expect("GetGlyphs failed");
    ST.with(|s| s.borrow_mut().active = false);

    glyphs.truncate(actual as usize);
    gprops.truncate(actual as usize);
    textprops.truncate(len as usize);
    ShapeResult {
        glyphs,
        glyphprops: gprops,
        textprops,
        cluster_map: clusters,
    }
}

unsafe fn run_getplacements(
    engine: &Engine,
    text: &[u16],
    res: &ShapeResult,
    script: u16,
    rtl: bool,
    locale: Option<&str>,
    upem: f32,
    feats: Option<&[DWRITE_FONT_FEATURE]>,
) -> Vec<(i32, i32, i32, i32)> {
    let analysis = DWRITE_SCRIPT_ANALYSIS {
        script,
        shapes: DWRITE_SCRIPT_SHAPES(1),
    };
    let n = res.glyphs.len() as u32;
    if n == 0 {
        return Vec::new();
    }
    let len = text.len() as u32;
    let mut advances = vec![0f32; n as usize];
    let mut offsets = vec![DWRITE_GLYPH_OFFSET {
        advanceOffset: 0.0,
        ascenderOffset: 0.0,
    }; n as usize];

    let locale_wide: Vec<u16>;
    let locale_ptr = match locale {
        Some(l) => {
            locale_wide = l.encode_utf16().chain(std::iter::once(0)).collect();
            PCWSTR(locale_wide.as_ptr())
        }
        None => PCWSTR::null(),
    };

    ST.with(|s| {
        let mut st = s.borrow_mut();
        st.active = true;
        st.table = "GPOS".into();
        st.lookup_n = 0;
    });
    // GetGlyphPlacements uses the typographic-features model.
    let mut feat_owned: Vec<DWRITE_FONT_FEATURE> = feats.map(|s| s.to_vec()).unwrap_or_default();
    let mut typo_box: Option<Box<DWRITE_TYPOGRAPHIC_FEATURES>> = None;
    let mut feats_arr: Option<Box<[*const DWRITE_TYPOGRAPHIC_FEATURES; 1]>> = None;
    let mut feats_pp: Option<*const *const DWRITE_TYPOGRAPHIC_FEATURES> = None;
    let mut range_lens_pp: Option<*const u32> = None;
    let mut feat_ranges: u32 = 0;
    if !feat_owned.is_empty() {
        let typo = Box::new(DWRITE_TYPOGRAPHIC_FEATURES {
            features: feat_owned.as_mut_ptr(),
            featureCount: feat_owned.len() as u32,
        });
        let typo_ptr: *const DWRITE_TYPOGRAPHIC_FEATURES = &*typo;
        typo_box = Some(typo);
        feats_arr = Some(Box::new([typo_ptr]));
        feats_pp = Some(feats_arr.as_ref().unwrap().as_ptr());
        let range_lens = vec![len];
        range_lens_pp = Some(range_lens.as_ptr());
        feat_ranges = 1;
        std::mem::forget(range_lens); // keep alive through the call below
    }
    let _ = (&typo_box, &feats_arr);
    let ret = engine.analyzer.GetGlyphPlacements(
        PCWSTR(text.as_ptr()),
        res.cluster_map.as_ptr(),
        res.textprops.as_ptr() as *mut DWRITE_SHAPING_TEXT_PROPERTIES,
        len,
        res.glyphs.as_ptr(),
        res.glyphprops.as_ptr(),
        n,
        &engine.face,
        upem,
        BOOL(0),
        BOOL(rtl as i32),
        &analysis,
        locale_ptr,
        feats_pp,
        range_lens_pp,
        feat_ranges,
        advances.as_mut_ptr(),
        offsets.as_mut_ptr(),
    );
    ST.with(|s| s.borrow_mut().active = false);
    ret.expect("GetGlyphPlacements failed");

    let mut out = Vec::with_capacity(n as usize);
    for i in 0..n as usize {
        out.push((
            advances[i].round() as i32,
            0,
            offsets[i].advanceOffset.round() as i32,
            offsets[i].ascenderOffset.round() as i32,
        ));
    }
    out
}

// ---------------------------------------------------------------------------
// Crowbar-style assembly.
// ---------------------------------------------------------------------------
fn recs_to_glyphs(recs: &[GlyphRec]) -> Value {
    Value::Array(
        recs.iter()
            .map(|g| {
                json!({
                    "g": g.gid,
                    "cl": g.idx,
                    "dx": 0, "dy": 0, "ax": 0, "ay": 0,
                    "flags": g.flags,
                })
            })
            .collect(),
    )
}

fn buf_key(glyphs: &Value) -> String {
    serde_json::to_string(glyphs).unwrap_or_default()
}

struct RawRow {
    m: String,
    glyphs: Value,
    depth: i32,
    effective: bool,
}

fn assemble(rows: Vec<RawRow>, show_all_lookups: bool) -> (Vec<RawRow>, Value) {
    let mut depth = 0i32;
    let mut start_ids: Vec<usize> = Vec::new();
    let mut start_bufs: Vec<String> = Vec::new();
    let mut rows = rows;
    for ix in 0..rows.len() {
        let m = rows[ix].m.clone();
        if m.starts_with("start lookup") || m.starts_with("recursing to lookup") {
            depth += 1;
            start_ids.push(ix);
            start_bufs.push(buf_key(&rows[ix].glyphs));
        }
        rows[ix].depth = depth;
        if m.starts_with("end lookup") || m.starts_with("recursed to lookup") {
            depth -= 1;
            if let Some(sid) = start_ids.pop() {
                if start_bufs.pop().as_deref() != Some(&buf_key(&rows[ix].glyphs)) {
                    for i in sid..=ix {
                        rows[i].effective = true;
                    }
                }
            }
        }
    }
    let noise = ["attaching", "replacing", "multiplying", "kerning"];
    let mut filtered: Vec<RawRow> = Vec::new();
    let mut last_buf = String::new();
    for mut r in rows {
        if r.m.contains("start table") {
            r.glyphs = Value::Array(Vec::new());
            filtered.push(r);
            continue;
        }
        if !show_all_lookups && noise.iter().any(|w| r.m.contains(w)) {
            continue;
        }
        let b = buf_key(&r.glyphs);
        if show_all_lookups || b != last_buf || r.effective {
            last_buf = b;
            filtered.push(r);
        }
    }
    let final_glyphs = filtered.last().map(|r| r.glyphs.clone()).unwrap_or(Value::Null);
    (filtered, final_glyphs)
}

fn glyph_clusters(cluster_map: &[u16], glyph_count: usize) -> Vec<u32> {
    let mut out: Vec<u32> = vec![0; glyph_count];
    for j in 0..glyph_count {
        let mut best: u32 = 0;
        for (i, &g) in cluster_map.iter().enumerate() {
            if (g as usize) <= j {
                best = i as u32;
            } else {
                break;
            }
        }
        out[j] = best;
    }
    out
}

fn resolve_dwcore(explicit: &Option<String>) -> String {
    if let Some(p) = explicit {
        if !p.is_empty() {
            return p.clone();
        }
    }
    if let Ok(p) = env::var("DWCORE_DLL") {
        if !p.is_empty() {
            return p;
        }
    }
    let mut cands: Vec<std::path::PathBuf> = Vec::new();
    if let Ok(exe) = env::current_exe() {
        if let Some(d) = exe.parent() {
            cands.push(d.join("DWriteCore.dll"));
        }
    }
    cands.push(std::path::PathBuf::from("build/dwc_poc/DWriteCore.dll"));
    cands.push(std::path::PathBuf::from("DWriteCore.dll"));
    for c in &cands {
        if c.exists() {
            return c.to_string_lossy().into_owned();
        }
    }
    panic!("DWriteCore.dll not found — pass --dwcore <path> or set DWCORE_DLL");
}

fn u16_at(d: &[u8], o: usize) -> u16 {
    u16::from_le_bytes([d[o], d[o + 1]])
}
fn u32_at(d: &[u8], o: usize) -> u32 {
    u32::from_le_bytes([d[o], d[o + 1], d[o + 2], d[o + 3]])
}

/// Relocate the hook target by scanning the PE's raw sections for the prologue
/// signature, so a future DWriteCore build that moved the dispatcher is still
/// found instead of failing hard. Returns the module-relative RVA.
fn pe_lookup_rva_for_sig(path: &str, sig: &[u8]) -> Option<u64> {
    let d = std::fs::read(path).ok()?;
    if d.len() < 0x40 || &d[0..2] != b"MZ" {
        return None;
    }
    let e_lfanew = u32_at(&d, 0x3C) as usize;
    if e_lfanew + 24 > d.len() || &d[e_lfanew..e_lfanew + 4] != b"PE\0\0" {
        return None;
    }
    let nsec = u16_at(&d, e_lfanew + 6) as usize;
    let optsz = u16_at(&d, e_lfanew + 20) as usize;
    let base = e_lfanew + 24 + optsz;
    for i in 0..nsec {
        let o = base + i * 40;
        if o + 40 > d.len() {
            break;
        }
        let va = u32_at(&d, o + 12) as usize;
        let roff = u32_at(&d, o + 20) as usize;
        let chars = u32_at(&d, o + 36);
        if roff == 0 || chars & 0x2000_0000 == 0 {
            continue; // non-executable / empty
        }
        let avail = d.len().saturating_sub(roff);
        let blob = &d[roff..roff + avail.min(0x4_0000)];
        if blob.len() < sig.len() {
            continue;
        }
        for j in 0..=blob.len() - sig.len() {
            if &blob[j..j + sig.len()] == sig {
                return Some((va + j) as u64);
            }
        }
    }
    None
}

fn parse_features(s: &str) -> Option<Vec<DWRITE_FONT_FEATURE>> {
    let t = s.trim();
    if t.is_empty() {
        return None;
    }
    let mut v = Vec::new();
    for tok in t.split(',') {
        let tok = tok.trim();
        if tok.is_empty() {
            continue;
        }
        let (tag, on) = if let Some(r) = tok.strip_prefix('+') {
            (r.to_string(), 1u32)
        } else if let Some(r) = tok.strip_prefix('-') {
            (r.to_string(), 0u32)
        } else if let Some((a, b)) = tok.split_once('=') {
            let p = b.trim().parse::<u32>().unwrap_or(1);
            (a.trim().to_string(), p)
        } else {
            (tok.to_string(), 1u32)
        };
        if tag.len() != 4 {
            continue;
        }
        let b = tag.as_bytes();
        // DWRITE_FONT_FEATURE_TAG stores the 4CC little-endian, e.g. 'kern'
        // (k=0x6B first byte) == 0x6E72654B (see DWRITE_FONT_FEATURE_TAG_KERNING).
        let num = u32::from_le_bytes([b[0], b[1], b[2], b[3]]);
        v.push(DWRITE_FONT_FEATURE {
            nameTag: DWRITE_FONT_FEATURE_TAG(num),
            parameter: on,
        });
    }
    if v.is_empty() {
        None
    } else {
        Some(v)
    }
}

// ---------------------------------------------------------------------------
// Library API + CLI.
// ---------------------------------------------------------------------------
pub struct ShapeOpts {
    pub font: String,
    pub text: String,
    pub script: String,
    pub language: String,
    pub direction: String,
    pub show_all: bool,
    pub dwcore: Option<String>,
    pub features_arg: String,
}

/// Shape `text` with the font at `font` and return the babelsoft
/// `/api/opentype/shape` engine JSON. Loads + hooks DWriteCore for the
/// duration of the call, then restores the original bytes, so it is safe to
/// call repeatedly from a long-lived process (e.g. a Python wheel). All
/// shaping is DWriteCore-native (no system TextShaping/dwrite). Windows-only.
pub fn shape_json(opts: ShapeOpts) -> Result<String, String> {
    let ShapeOpts {
        font,
        text,
        script,
        language,
        direction,
        show_all,
        dwcore,
        features_arg,
    } = opts;
    let data = std::fs::read(&font).map_err(|e| format!("read font: {e}"))?;
    let (upem, glyph_count) = sfnt_meta(&data);

    unsafe {
        // Load DWriteCore, verify + hook its per-lookup dispatcher (0x6d280).
        // If a newer DWriteCore moved the dispatcher, relocate by scanning the
        // DLL's executable sections for the prologue signature.
        let dwc_path = resolve_dwcore(&dwcore);
        let dwc_base = load_base(&dwc_path);
        let mut rva = DWC_LOOKUP_RVA;
        let mut got = [0u8; 12];
        let t0 = dwc_base + rva;
        ptr::copy_nonoverlapping(t0 as *const u8, got.as_mut_ptr(), 12);
        if got != SIG_DWC_LOOKUP {
            match pe_lookup_rva_for_sig(&dwc_path, &SIG_DWC_LOOKUP) {
                Some(r) => {
                    eprintln!(
                        "note: DWriteCore lookup dispatcher moved 0x{DWC_LOOKUP_RVA:x} -> 0x{r:x}; re-verified"
                    );
                    rva = r;
                    let t2 = dwc_base + rva;
                    ptr::copy_nonoverlapping(t2 as *const u8, got.as_mut_ptr(), 12);
                    assert_eq!(got, SIG_DWC_LOOKUP, "relocated signature mismatch");
                }
                None => panic!(
                    "DWriteCore lookup dispatcher signature not found at 0x{DWC_LOOKUP_RVA:x} nor in any executable section — this DWriteCore build is unsupported"
                ),
            }
        }
        let target = dwc_base + rva;

        let block = alloc_near(dwc_base, 0x200);
        install_dwc_hook(block, 0x200, target, &got, 0x00, 0x80);

        let engine = make_engine(&dwc_path, &font);
        let script_num = if !script.is_empty() && script != "auto" {
            resolve_script(&engine.analyzer1, &script)
        } else {
            0
        };
        let rtl = direction == "rtl";
        let locale = if language.is_empty() {
            None
        } else {
            Some(language.as_str())
        };
        let text_utf16: Vec<u16> = text.encode_utf16().collect();
        let feats = parse_features(&features_arg);

        ST.with(|s| {
            let mut st = s.borrow_mut();
            st.snaps.clear();
            st.msgs.clear();
            st.msgs.push("engine=dwritecore-native per-lookup (otls)".into());
            st.msgs.push(format!("DWriteCore={dwc_path}"));
        });

        // GSUB pass (per-lookup hook fires, table=GSUB).
        let gres = run_getglyphs(
            &engine,
            &text_utf16,
            script_num,
            rtl,
            locale,
            feats.as_deref(),
        );
        // GPOS pass (hook fires if there are GPOS lookups, table=GPOS) + positions.
        let positions = run_getplacements(
            &engine,
            &text_utf16,
            &gres,
            script_num,
            rtl,
            locale,
            upem as f32,
            feats.as_deref(),
        );

        let (snaps, msgs) = ST.with(|s| {
            let st = s.borrow();
            (st.snaps.clone(), st.msgs.clone())
        });

        // ---- Build raw rows ------------------------------------------------
        let text_glyphs: Value = Value::Array(
            text.chars()
                .enumerate()
                .map(|(ci, c)| {
                    json!({
                        "g": c as u32,
                        "cl": ci,
                        "dx": 0, "dy": 0, "ax": 0, "ay": 0, "flags": 0,
                    })
                })
                .collect(),
        );
        let mut rows: Vec<RawRow> = Vec::new();
        rows.push(RawRow {
            m: "Start of shaping".into(),
            glyphs: text_glyphs,
            depth: 0,
            effective: true,
        });
        rows.push(RawRow {
            m: "start table GSUB (DWriteCore)".into(),
            glyphs: Value::Null,
            depth: 0,
            effective: false,
        });
        let mut last_table = String::from("GSUB");
        for (idx, snap) in snaps.iter().enumerate() {
            if snap.table != last_table {
                rows.push(RawRow {
                    m: "end table GSUB (DWriteCore)".into(),
                    glyphs: if idx > 0 {
                        recs_to_glyphs(&snaps[idx - 1].recs)
                    } else {
                        Value::Array(Vec::new())
                    },
                    depth: 0,
                    effective: false,
                });
                rows.push(RawRow {
                    m: "start table GPOS (DWriteCore)".into(),
                    glyphs: Value::Null,
                    depth: 0,
                    effective: false,
                });
                last_table = snap.table.clone();
            }
            if idx == 0 {
                continue;
            }
            let prev = &snaps[idx - 1];
            if prev.recs == snap.recs {
                continue;
            }
            let tag = format!(
                "lookup {} {} (DWriteCore)",
                prev.n,
                if prev.table == "GPOS" { "GPOS" } else { "GSUB" }
            );
            rows.push(RawRow {
                m: format!("start {tag}"),
                glyphs: recs_to_glyphs(&prev.recs),
                depth: 0,
                effective: false,
            });
            rows.push(RawRow {
                m: format!("end {tag}"),
                glyphs: recs_to_glyphs(&snap.recs),
                depth: 0,
                effective: false,
            });
        }

        // ---- Final glyphs (DWriteCore authoritative) -----------------------
        let nfin = gres.glyphs.len();
        // Cluster: same source as the stage rows (otls record idx) when the
        // last captured snapshot matches the final run length, else fall back
        // to inverting DirectWrite's clusterMap.
        let final_cl: Vec<u32> = match snaps.last() {
            Some(last) if last.recs.len() == nfin => last.recs.iter().map(|r| r.idx as u32).collect(),
            _ => glyph_clusters(&gres.cluster_map, nfin),
        };
        let mut final_glyphs = Vec::with_capacity(nfin);
        for j in 0..nfin {
            let (ax, ay, dx, dy) = positions.get(j).copied().unwrap_or((0, 0, 0, 0));
            final_glyphs.push(json!({
                "g": gres.glyphs[j],
                "cl": final_cl[j],
                "dx": dx, "dy": dy, "ax": ax, "ay": ay,
                "flags": 0,
            }));
        }
        let final_val: Value = Value::Array(final_glyphs.clone());
        rows.push(RawRow {
            m: "End of shaping".into(),
            glyphs: final_val.clone(),
            depth: 0,
            effective: true,
        });

        let (filtered, final_from_stages) = assemble(rows, show_all);
        let mut stages: Vec<Value> = Vec::new();
        for r in &filtered {
            stages.push(json!({
                "m": r.m,
                "glyphs": r.glyphs,
                "depth": r.depth,
                "effective": r.effective,
            }));
        }
        let final_use = if final_from_stages.is_array() {
            final_from_stages
        } else {
            final_val
        };

        let result = json!({
            "upem": upem,
            "glyph_count": glyph_count,
            "stages": stages,
            "final": final_use,
            "messages": msgs,
            "engine": "directwrite",
            "render_engine": "dwritecore",
        });
        let out = serde_json::to_string_pretty(&result).unwrap();

        // Restore the patched bytes + free the scratch block so a long-lived
        // process can call shape_json() again safely (wheel usage).
        let mut old = PAGE_PROTECTION_FLAGS(0);
        let page = (target & !0xFFF) as *const c_void;
        VirtualProtect(page, 0x1000, PAGE_EXECUTE_READWRITE, &mut old).ok();
        ptr::copy_nonoverlapping(got.as_ptr(), target as *mut u8, got.len());
        let _ = VirtualProtect(page, 0x1000, old, &mut old);
        let _ = VirtualFree(block, 0, MEM_RELEASE);
        Ok(out)
    }
}

pub fn run_cli(argv: &[String]) -> i32 {
    let mut font = String::new();
    let mut text = String::new();
    let mut script = String::new();
    let mut language = String::new();
    let mut direction = String::from("auto");
    let mut show_all = false;
    let mut out_file: Option<String> = None;
    let mut dwcore: Option<String> = None;
    let mut features_arg = String::new();
    let mut i = 1;
    while i < argv.len() {
        let a = &argv[i];
        let next = |i: &mut usize| {
            *i += 1;
            argv.get(*i).cloned()
        };
        match a.as_str() {
            "--font" => font = next(&mut i).unwrap_or_default(),
            "--text" => text = next(&mut i).unwrap_or_default(),
            "--script" => script = next(&mut i).unwrap_or_default(),
            "--language" => language = next(&mut i).unwrap_or_default(),
            "--direction" => direction = next(&mut i).unwrap_or_default(),
            "--show-all-lookups" => show_all = true,
            "--out" => out_file = next(&mut i),
            "--dwcore" => dwcore = next(&mut i),
            "--features" => features_arg = next(&mut i).unwrap_or_default(),
            _ => {}
        }
        i += 1;
    }
    if font.is_empty() || text.is_empty() {
        eprintln!("usage: dwtshape --font <font> --text <text> [--script <iso15924>] [--language <bcp47>] [--direction auto|ltr|rtl] [--features +init,-kern] [--dwcore <DWriteCore.dll>] [--show-all-lookups] [--out <json>]");
        return 2;
    }
    let opts = ShapeOpts {
        font,
        text,
        script,
        language,
        direction,
        show_all,
        dwcore,
        features_arg,
    };
    match shape_json(opts) {
        Ok(out) => match out_file {
            Some(f) => match std::fs::write(&f, &out) {
                Ok(()) => 0,
                Err(e) => {
                    eprintln!("write out: {e}");
                    1
                }
            },
            None => {
                println!("{out}");
                0
            }
        },
        Err(e) => {
            eprintln!("dwtshape: {e}");
            1
        }
    }
}

unsafe fn load_base(path: &str) -> u64 {
    let w: Vec<u16> = path.encode_utf16().chain(std::iter::once(0)).collect();
    let lib = LoadLibraryW(PCWSTR(w.as_ptr())).expect("LoadLibraryW failed");
    lib.0 as u64
}
