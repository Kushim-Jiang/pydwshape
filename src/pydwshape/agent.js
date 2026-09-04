// pydwshape agent — hooks TextShaping.dll's OTLS shaping engine and emits a
// structured, feature-level trace via send().
//
// Event protocol (all JSON-serializable):
//   {t:'hello',  base, size, version, addr_source}
//   {t:'run_start', run, table}                 // GSUB or GPOS top-level bracket
//   {t:'feature',  run, phase, table, count, features:[tags]}
//   {t:'lookup',   run, phase, n, table, glyphs:[...], changed:[...]|null}
//   {t:'run_end',  run, table}
//   {t:'gpos_start', run, table}
//   {t:'gpos_end',  run, table}                 // one dw.shape() is complete
//   {t:'ready',   addr_source}
//   {t:'fatal',   msg}
//
// Hook targets (TextShaping.dll):
//   ShapingGetGlyphs / ShapingGetGlyphPositions  — run brackets (exported)
//   ApplyFeatures(tag, otlFeatureSet*, ...)      — feature phases
//   ApplyLookup(tag, otlList*, otlList* glyphs, ...) — per-lookup glyph snapshots
//
// ApplyFeatures / ApplyLookup are NOT exports. The orchestrator resolves their
// RVAs offline (package RVA registry) and injects them through the
// __DWSHAPE_CFG__ token below; the agent computes base + RVA itself and
// verifies the first bytes before hooking — never a blind hook.
'use strict';

var cfg = {};
try { cfg = JSON.parse(__DWSHAPE_CFG__); } catch (e) { cfg = {}; }

function u16(p) { try { return p.readU16(); } catch (e) { return -1; } }
function u32(p) { try { return p.readU32(); } catch (e) { return -1; } }

function tag4(v) {
    v = v >>> 0;
    var c = String.fromCharCode(v & 0xff, (v >> 8) & 0xff, (v >> 16) & 0xff, (v >> 24) & 0xff);
    return /^[\x20-\x7e]{4}$/.test(c) ? c : null;
}

function emit(o) { try { send(o); } catch (e) {} }

function hexAt(p, n) {
    try {
        var b = p.readByteArray(n);
        var out = '';
        for (var i = 0; i < n; i++) out += ('0' + b[i].toString(16)).slice(-2);
        return out;
    } catch (e) { return null; }
}

function symAddr(name) {
    var m = Process.getModuleByName('TextShaping.dll');
    if (!m) return null;
    try {
        for (var i = 0; i < m.enumerateSymbols().length; i++) {
            var s = m.enumerateSymbols()[i];
            if (s.name === name) return s.address;
        }
    } catch (e) {}
    return null;
}

function main() {
    var ts = Process.getModuleByName('TextShaping.dll');
    if (!ts) { emit({ t: 'fatal', msg: 'TextShaping.dll not loaded in the worker' }); return; }
    emit({ t: 'hello', base: ts.base.toString(), size: ts.size,
           version: cfg.version || '', addr_source: cfg.addr_source || 'rva' });

    // ---- resolve ApplyFeatures / ApplyLookup ---------------------------------
    // symbols first (opt-in, needs PDB on _NT_SYMBOL_PATH); otherwise compute
    // base + RVA from the injected offline registry and verify the bytes.
    function resolveAddr(name, rvaHex, signature) {
        var a = null;
        if (cfg.symbols) a = symAddr(name);
        if (!a && rvaHex) a = ts.base.add(parseInt(rvaHex, 16));
        if (!a) return { addr: null, why: name + ' address unavailable' };
        if (signature) {
            var got = hexAt(a, signature.length / 2);
            if (got !== signature) {
                return { addr: null, why: name + ' signature mismatch at ' + a +
                         ' (got ' + got + ', want ' + signature + ') — build not supported, ' +
                         'see tools/ghidra/README.md to extend the RVA registry' };
            }
        }
        return { addr: a };
    }

    var af = resolveAddr('ApplyFeatures', cfg.af_rva, cfg.sig_af);
    var al = resolveAddr('ApplyLookup', cfg.al_rva, cfg.sig_al);
    if (!af.addr) { emit({ t: 'fatal', msg: af.why }); return; }
    if (!al.addr) { emit({ t: 'fatal', msg: al.why }); return; }

    var run = 0;       // per top-level bracket (ShapingGetGlyphs / Positions)
    var phaseN = 0;    // per-run feature-phase counter
    var table = '?';
    var lookupN = 0;   // per-run lookup counter
    var prevG = null;  // previous glyph snapshot for per-lookup diff

    // ---- GSUB run bracket -----------------------------------------------------
    var sgg = ts.getExportByName('ShapingGetGlyphs');
    if (sgg) {
        Interceptor.attach(sgg, {
            onEnter: function () {
                run++; phaseN = 0; lookupN = 0; prevG = null; table = 'GSUB';
                emit({ t: 'run_start', run: run, table: 'GSUB' });
            },
            onLeave: function () { emit({ t: 'run_end', run: run, table: 'GSUB' }); }
        });
    } else {
        emit({ t: 'fatal', msg: 'ShapingGetGlyphs export missing' });
        return;
    }

    // ---- feature phases --------------------------------------------------------
    Interceptor.attach(af.addr, {
        onEnter: function (args) {
            var t0 = args[0].toInt32();
            var tbl = tag4(t0) || table;
            table = tbl;
            phaseN++;
            var fs = args[1];
            var data = null, rec = -1, count = -1;
            try { data = fs.readPointer(); } catch (e) {}
            rec = u16(fs.add(8));
            count = u16(fs.add(0xc));
            var feats = [];
            if (data && !data.isNull() && rec >= 6 && rec <= 64 && count > 0 && count < 500) {
                for (var i = 0; i < count; i++) {
                    var v = u32(data.add(i * rec));
                    var nm = tag4(v);
                    feats.push(nm || ('#' + i + '=0x' + (v >>> 0).toString(16)));
                }
            }
            emit({ t: 'feature', run: run, phase: phaseN, table: tbl, count: count, features: feats });
        }
    });

    // ---- per-lookup glyph snapshots -------------------------------------------
    Interceptor.attach(al.addr, {
        onEnter: function (args) {
            lookupN++;
            var gl = args[2]; // otlList of glyph records (rec=8: [gid,flags,idx,?])
            var data = null, count = 0;
            try { data = gl.readPointer(); } catch (e) {}
            count = u16(gl.add(0xc));
            if (!data || data.isNull() || count <= 0 || count > 5000) return;
            var gids = [];
            for (var i = 0; i < count; i++) gids.push(u16(data.add(i * 8)));
            var changed = null;
            if (prevG && prevG.length === gids.length) {
                changed = [];
                for (var j = 0; j < gids.length; j++) {
                    if (gids[j] !== prevG[j]) changed.push([j, prevG[j], gids[j]]);
                }
            }
            emit({ t: 'lookup', run: run, phase: phaseN, n: lookupN, table: table,
                   glyphs: gids, changed: changed });
            prevG = gids.slice();
        }
    });

    // ---- GPOS run bracket (also the one-shape completion signal) ---------------
    var sgp = ts.getExportByName('ShapingGetGlyphPositions');
    if (sgp) {
        Interceptor.attach(sgp, {
            onEnter: function () {
                run++; phaseN = 0; lookupN = 0; prevG = null; table = 'GPOS';
                emit({ t: 'run_start', run: run, table: 'GPOS' });
                emit({ t: 'gpos_start', run: run, table: 'GPOS' });
            },
            onLeave: function () {
                emit({ t: 'gpos_end', run: run, table: 'GPOS' });
                emit({ t: 'run_end', run: run, table: 'GPOS' });
            }
        });
    }

    emit({ t: 'ready', addr_source: cfg.addr_source || 'rva' });
}

setTimeout(main, 0);
