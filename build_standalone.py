#!/usr/bin/env python3
"""Build the self-contained copy of the Tax Dollar Tracker.

tax-dollar-tracker.html loads Chart.js from the jsdelivr CDN at runtime.
Publishers commonly block third-party script hosts via Content-Security-Policy,
and the app has no guard around `new Chart(...)`: if the library is missing the
call throws, which aborts handleCalculate before the results panel is ever
shown. The reader sees a dead Calculate button and no error.

This script inlines the library so the page makes zero external requests.
Nothing else about the page is changed.

Run after any edit to tax-dollar-tracker.html:

    python3 build_standalone.py
"""
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent
SRC = REPO / "tax-dollar-tracker.html"
LIB = REPO / "lobbyist/static/vendor/chart.umd.min.js"
OUT = REPO / "tax-dollar-tracker-standalone.html"
HANDOFF = REPO / "tax-dollar-tracker-handoff/tax-dollar-tracker.html"

CDN_TAG = (
    '<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/'
    'chart.umd.min.js"></script>'
)

for path in (SRC, LIB):
    if not path.exists():
        sys.exit(f"FAIL: missing {path}")

html = SRC.read_text(encoding="utf-8")
lib = LIB.read_text(encoding="utf-8")

if "Chart.js v4.4.1" not in lib:
    sys.exit("FAIL: vendored library is not Chart.js v4.4.1.")
if html.count(CDN_TAG) != 1:
    sys.exit(f"FAIL: expected exactly 1 CDN script tag, found {html.count(CDN_TAG)}.")

# Defensive: a literal </script inside the JS would close the block early.
lib = lib.replace("</script", r"<\/script")

banner = (
    "<!-- Chart.js v4.4.1 (MIT) inlined below, replacing a runtime request to\n"
    "     https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js\n"
    "     This page now makes zero external requests. Nothing else was changed. -->"
)

out = html.replace(CDN_TAG, f"{banner}\n<script>\n{lib}\n</script>")

# The page must not load anything over the network. Documentary <a href> links
# in Sources & Notes are fine — those are links a reader clicks, not resources.
for attr in ("src=", "poster="):
    if f'{attr}"http' in out:
        sys.exit(f"FAIL: an external {attr} survived the inlining.")

OUT.write_text(out, encoding="utf-8")
written = [OUT]
if HANDOFF.parent.is_dir():
    HANDOFF.write_text(out, encoding="utf-8")
    written.append(HANDOFF)

print(f"chart.js  {len(LIB.read_bytes()):>9,} bytes inlined")
for path in written:
    print(f"wrote     {len(path.read_bytes()):>9,} bytes  {path.relative_to(REPO)}")
