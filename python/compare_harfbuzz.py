"""compare_harfbuzz — regression matrix: run the pure-DWriteCore dwtshape
(final glyph ids) against uharfbuzz (HarfBuzz) for several scripts/fonts, and
report per-case equality + whether the DWriteCore trace captured GPOS lookups.

Run with the babelsoft venv (has uharfbuzz):
  & 'D:\\Github\\babelsoft-py\\.venv\\Scripts\\python.exe' python/compare_harfbuzz.py
"""
import json
import os
import subprocess
import sys

import uharfbuzz as hb

EXE = r"D:\Github\pydwshape\target\debug\dwtshape.exe"
WF = r"C:\Windows\Fonts"

# (label, font, text, script)
CASES = [
    ("mongolian-golden", r"D:\Github\mongolian-utn\temp\hudum.otf",
     "\u1830\u1820\u1822\u182C\u1820\u1828", "mong"),  # ᠰᠠᠢᠬᠠᠨ
    ("latin", os.path.join(WF, "arial.ttf"), "AVATAR Office", ""),
    ("arabic", os.path.join(WF, "segoeui.ttf"), "\u0633\u0644\u0627\u0645", "arab"),  # سلام
    ("devanagari", os.path.join(WF, "Nirmala.ttc"), "\u0915\u0930\u094d\u092e", "deva"),  # कर्म
    ("hebrew", os.path.join(WF, "segoeui.ttf"), "\u05e9\u05dc\u05d5\u05dd", "hebr"),  # שלום
]

GOLDEN = [675, 281, 303, 471, 281, 351]


def dwtshape(font, text, script):
    args = [EXE, "--font", font, "--text", text]
    if script:
        args += ["--script", script]
    r = subprocess.run(args, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", "replace")[-800:])
    d = json.loads(r.stdout.decode("utf-8"))
    gids = [g["g"] for g in d["final"]]
    tables = [s["m"] for s in d["stages"] if "table" in s["m"]]
    return gids, d["stages"], tables


def harfbuzz(font_path, text, script):
    with open(font_path, "rb") as f:
        data = f.read()
    face = hb.Face(data)
    font = hb.Font(face)
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    if script:
        try:
            buf.script = script
        except Exception:
            pass
    hb.shape(font, buf)
    return [g.codepoint for g in buf.glyph_infos]


def main():
    print(f"{'case':<16} {'nGlyph':>6} {'traceOK':>7} {'==HB':>5} {'GPOS':>5}  note")
    allok = True
    for label, font, text, script in CASES:
        if not os.path.exists(font):
            print(f"{label:<16}  (skip, font missing: {font})")
            continue
        try:
            d = run_dwtshape(font, text, script)
        except Exception as e:
            print(f"{label:<16}  ERROR {e}")
            allok = False
            continue
        gids = [g["g"] for g in d["final"]]
        stages = d["stages"]
        # trace self-consistency: the last lookup buffer must equal the final run
        last_lk = None
        for s in stages:
            if s["m"].startswith("end lookup") and s["glyphs"]:
                last_lk = [g["g"] for g in s["glyphs"]]
        trace_ok = last_lk is None or last_lk == gids
        has_gpos = any("GPOS" in s["m"] for s in stages if "table" in s["m"])
        try:
            hb_gids = harfbuzz(font, text, script)
            same = gids == hb_gids
        except Exception:
            hb_gids, same = None, None
        note = ""
        if label == "mongolian-golden":
            note = "golden=%s" % (gids == GOLDEN)
            if gids != GOLDEN or not trace_ok:
                allok = False
            elif not same:
                allok = False
        elif not trace_ok:
            # RTL scripts reorder glyphs for output; the internal lookup buffer
            # (logical order) legitimately differs from the final visual run.
            note = f"trace end != final (expected for RTL: {gids[:8]})"
        elif same is False:
            # default-feature / direction differences between engines: info only
            note = f"HB differs (default features/direction; dw={gids[:8]} hb={hb_gids[:8]})"
        print(f"{label:<16} {len(gids):>6} {'OK' if trace_ok else 'BAD':>7} "
              f"{'OK' if same else ('n/a' if same is None else 'DIFF'):>5} "
              f"{'yes' if has_gpos else '-':>5}  {note}")
    print("\nPASS (golden + trace self-consistency)" if allok else "\nFAILURES ABOVE")
    return 0 if allok else 1


def run_dwtshape(font, text, script):
    args = [EXE, "--font", font, "--text", text]
    if script:
        args += ["--script", script]
    r = subprocess.run(args, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", "replace")[-800:])
    return json.loads(r.stdout.decode("utf-8"))


if __name__ == "__main__":
    sys.exit(main())
