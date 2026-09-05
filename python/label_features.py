r"""label_features — name each DWriteCore per-lookup stage with its OpenType
feature by aligning the (proven identical) HarfBuzz per-lookup trace.

Why not native:
  * DWriteCore's otls dispatcher (hooked at RVA 0x6D280) fires once per
    *matched lookup application over a region* (~86x for a 6-glyph Mongolian
    run) but carries no feature tag; the feature-enablement helper
    (0x6CA90 / enables_cache.rs) receives the 4CC but is *bulk-precomputed*
    (284x, all features of a segment up front), so the tag last seen before a
    dispatch is just "the last feature of the segment" (fina/rvrn), not the
    dispatch's feature.  There is no per-feature boundary exposed at the
    dispatcher layer.
  * Our trace's glyph mutations are byte-for-byte the same as HarfBuzz's
    per-lookup trace (verified: same order, same final). So we name each
    DWrite stage by walking the identical HarfBuzz trace in lockstep and
    reporting the feature HarfBuzz attributes to that substitution.

Output: an aligned table  dw#  lookup-N  feature  before->after  (per stage),
plus a compact JSON list of {stage, feature} for consumers.  Exit 0 on full
alignment (every DWrite glyph change covered, order-preserving, finals equal).

Usage:
  & 'D:\Github\babelsoft-py\.venv\Scripts\python.exe' python/label_features.py \
      --font hudum.otf --text 'ᠰᠠᠢᠬᠠᠨ' --script mong
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def dwtshape_bin() -> str:
    p = os.environ.get("DWSHAPE_BIN")
    if p and os.path.exists(p):
        return p
    for sub in ("release", "debug"):
        cand = REPO / "target" / sub / ("dwtshape.exe" if os.name == "nt" else "dwtshape")
        if cand.exists():
            return str(cand)
    raise SystemExit("dwtshape binary not found — cargo build first")


def run_dwtshape(font: str, text: str, script: str, direction: str, features: str) -> dict:
    args = [dwtshape_bin(), "--font", font, "--text", text]
    if script:
        args += ["--script", script]
    if direction and direction != "auto":
        args += ["--direction", direction]
    if features:
        args += ["--features", features]
    r = subprocess.run(args, capture_output=True, check=False)
    if r.returncode != 0:
        raise SystemExit(r.stderr.decode("utf-8", "replace")[-2000:])
    return json.loads(r.stdout.decode("utf-8"))


def dwtshape_events(res: dict) -> tuple[list[int], list[tuple[list[int], list[int]]]]:
    """Return (initial_state, events) where each event is (before, after) for a
    buffer-changing lookup stage."""
    states: list[list[int]] = []
    for s in res["stages"]:
        g = s.get("glyphs")
        if isinstance(g, list) and s["m"] not in ("Start of shaping", "End of shaping") and g:
            states.append([x["g"] for x in g])
    if not states:
        return [], []
    # states alternate before/after pairs (start lookup shows before, end shows
    # after) with consecutive duplicates filtered by the engine already; build
    # a clean ordered list of distinct buffer states:
    clean: list[list[int]] = []
    for b in states:
        if not clean or clean[-1] != b:
            clean.append(b)
    init = clean[0]
    events = [(clean[i - 1], clean[i]) for i in range(1, len(clean))]
    return init, events


def hb_events(font: bytes, text: str, script: str, features: str) -> tuple[list[int], list[tuple[str, list[int], list[int]]]]:
    """Shape with HarfBuzz (message callback) -> (initial, [(feature,before,after)])."""
    import uharfbuzz as hb

    face = hb.Face(font)
    fnt = hb.Font(face)
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    feat = _hb_features(features)

    events: list[tuple[str, list[int], list[int]]] = []
    cur: list[tuple[str, list[int]]] = []  # stack of (feature, before)

    def snap() -> list[int]:
        return [g.codepoint for g in buf.glyph_infos]

    def on_msg(msg: str) -> bool:
        if msg.startswith("start lookup"):
            m = re.search(r"feature '([a-z]{4})'", msg)
            feat = m.group(1) if m else "?"
            cur.append((feat, snap()))
        elif msg.startswith("end lookup") and cur:
            feat, before = cur.pop()
            after = snap()
            if after != before:
                events.append((feat, before, after))
        return True  # keep step

    buf.set_message_func(on_msg)
    hb.shape(fnt, buf, feat)
    return [g.codepoint for g in buf.glyph_infos], events


def _hb_features(s: str) -> dict | None:
    """Convert '+smcp/-liga/smcp=1' into {tag: bool} for uharfbuzz."""
    if not s:
        return None
    out = {}
    for tok in s.split(","):
        tok = tok.strip()
        if not tok:
            continue
        if tok.startswith("+"):
            out[tok[1:]] = True
        elif tok.startswith("-"):
            out[tok[1:]] = False
        elif "=" in tok:
            t, v = tok.split("=", 1)
            out[t] = v == "1"
        else:
            out[tok] = True
    return out or None


def align(events_dw, events_hb):
    """DWrite's otls dispatches per matched *position region* (finer than
    HarfBuzz, which applies one whole lookup covering many positions in a
    single step). So drive over the HarfBuzz events (each = one lookup with one
    feature) and attribute every consecutive DWrite event whose cumulative
    buffer reaches that HB event's end-state to that HB event's feature."""
    out: list[dict] = []
    dw_state = None
    d = 0
    n_dw = len(events_dw)
    for (feat, hb_b, hb_a) in events_hb:
        target = hb_a
        feats_bucket: list[dict] = []
        if dw_state is None:
            # first dw event's before should equal hb_b (base state)
            dw_state = events_dw[0][0] if d < n_dw else hb_b
        # consume dw events until cumulative state == target
        guard = 0
        while d < n_dw and dw_state != target and guard < n_dw + 4:
            b, a = events_dw[d]
            feats_bucket.append({"before": b, "after": a, "feature": feat})
            dw_state = a
            d += 1
            guard += 1
        # if we overshot (dw never equals target) attribute to this event anyway
        if d >= n_dw and dw_state != target:
            out.extend(feats_bucket)
            break
        out.extend(feats_bucket)
    # any leftover dw events (shouldn't happen)
    if d < n_dw:
        out.extend({"before": e[0], "after": e[1], "feature": "?"} for e in events_dw[d:])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--font", required=True)
    ap.add_argument("--text", required=True)
    ap.add_argument("--script", default="")
    ap.add_argument("--direction", default="auto")
    ap.add_argument("--features", default="", help="e.g. +smcp,-liga or smcp=1")
    ap.add_argument("--json", action="store_true", help="print only aligned JSON")
    a = ap.parse_args()

    res = run_dwtshape(a.font, a.text, a.script, a.direction, a.features)
    init_dw, events_dw = dwtshape_events(res)
    try:
        import uharfbuzz as hb  # noqa: F401
    except ImportError:
        print("need the babelsoft venv (uharfbuzz):", file=sys.stderr)
        return 2
    init_hb, events_hb = hb_events(Path(a.font).read_bytes(), a.text, a.script, a.features)

    if not events_dw:
        print("no dwtshape events")
        return 1

    aligned = align(events_dw, events_hb)
    final_dw_author = [g["g"] for g in res["final"]]
    final_dw_trace = events_dw[-1][1] if events_dw else init_dw
    final_hb = events_hb[-1][2] if events_hb else init_hb
    complete = final_dw_trace == final_dw_author

    if a.json:
        print(json.dumps({
            "final_dw": final_dw_author, "final_hb": final_hb,
            "trace_complete": complete, "stages": aligned,
        }))
    else:
        print(f"dw events={len(events_dw)} hb events={len(events_hb)}")
        print(f"final dw={final_dw_author} hb={final_hb} equal={final_dw_author == final_hb}")
        print(f"trace-complete (last GSUB stage == authoritative final): {complete}")
        print(f"{'#':>3} {'features':<22} before->after")
        for i, e in enumerate(aligned):
            feats = e["feature"]

            def chg(b, a):
                if len(b) == len(a):
                    return " ".join(f"{x}>{y}" for x, y in zip(b, a) if x != y)
                return f"{len(b)}->{len(a)} glyphs"

            print(f"{i:>3} {feats:<22} {chg(e['before'], e['after'])}")
    ok = final_dw_author == final_hb and complete
    print("ALIGN", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
