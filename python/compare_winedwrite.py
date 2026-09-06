"""compare_winedwrite — regression matrix for the Wine DWrite port.

Runs three engines on a corpus with **no explicit script** (all auto-detect):
  1. winedwrite   — this port's shared lib (python/winedwrite_shaper.py)
  2. DWriteCore   — native dwtshape (target/debug/dwtshape.exe)
  3. HarfBuzz     — uharfbuzz (babelsoft venv)
and compares final glyph ids. Mongolian must match DWriteCore byte-identically.

Run with a python that has uharfbuzz (babelsoft venv):
  & 'D:\\Github\\babelsoft-py\\.venv\\Scripts\\python.exe' python/compare_winedwrite.py
"""
import json
import os
import subprocess
import sys

from winedwrite_shaper import shape_with_winedwrite

DWC = r"D:\Github\pydwshape\target\debug\dwtshape.exe"
WF = r"C:\Windows\Fonts"

CASES = [
    ("mongolian-short", r"D:\Github\mongolian-utn\temp\hudum.otf",
     "\u1830\u1820\u1822\u182C\u1820\u1828", [675, 281, 303, 471, 281, 351]),
    ("mongolian-long", r"D:\Github\mongolian-utn\temp\hudum.otf",
     "\u1830\u1820\u1822\u182C\u1820\u1828 \u1830\u1822\u182D\u1830\u1822\u182D"
     "\u1830\u1822\u182D\u1830\u1822\u182D\u1820",
     [675, 281, 303, 471, 281, 351, 11, 675, 302, 571, 677, 302, 571, 677, 302,
      571, 677, 302, 575, 278]),
    ("latin", os.path.join(WF, "arial.ttf"), "AVATAR Office", None),
    ("arabic", os.path.join(WF, "segoeui.ttf"), "\u0633\u0644\u0627\u0645", None),
    ("hebrew", os.path.join(WF, "segoeui.ttf"), "\u05e9\u05dc\u05d5\u05dd", None),
    ("devanagari", os.path.join(WF, "Nirmala.ttc"), "\u0915\u0930\u094d\u092e", None),
]

import uharfbuzz as hb


def dwc_shape(font, text):
    env = dict(os.environ)
    env.setdefault("DWCORE_DLL", r"D:\Github\pydwshape\build\dwc_poc\DWriteCore.dll")
    r = subprocess.run([DWC, "--font", font, "--text", text],
                       capture_output=True, env=env)
    if r.returncode:
        raise RuntimeError(r.stderr.decode("utf-8", "replace")[-300:])
    return [g["g"] for g in json.loads(r.stdout.decode("utf-8"))["final"]]


def hb_shape(font_path, text):
    with open(font_path, "rb") as f:
        data = f.read()
    face = hb.Face(data)
    font = hb.Font(face)
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(font, buf)
    return [g.codepoint for g in buf.glyph_infos]


def main():
    print(f"{'case':<18} {'nW':>3} {'==DWC':>6} {'==HB':>5} {'golden':>7}  note")
    allok = True
    for label, font, text, golden in CASES:
        if not os.path.exists(font):
            print(f"{label:<18}  (skip: {font})")
            continue
        try:
            w = shape_with_winedwrite(font, text)
        except Exception as e:  # noqa
            print(f"{label:<18}  ERROR {e}")
            allok = False
            continue
        wg = [g["g"] for g in w["final"]]
        det = w.get("messages") and None
        note = ""
        same_dwc = same_hb = None
        try:
            same_dwc = wg == dwc_shape(font, text)
        except Exception as e:
            note = f"dwc err {e}"
        try:
            same_hb = wg == hb_shape(font, text)
        except Exception as e:
            note = (note + " " if note else "") + f"hb err {e}"
        ok_golden = True if golden is None else wg == golden
        caseok = True
        if label.startswith("mongolian"):
            caseok = same_dwc is True and ok_golden
            if not caseok:
                allok = False
        elif same_dwc is False and same_hb is False:
            note = "differs from DWC and HB (info)"
        print(f"{label:<18} {len(wg):>3} {str(same_dwc):>6} {str(same_hb):>5} "
              f"{'OK' if ok_golden else 'BAD':>7}  {note}")
    print("\nPASS" if allok else "\nFAILURES ABOVE")
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main())
