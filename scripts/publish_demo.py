#!/usr/bin/env python3
"""Turn a real trackaudit report into the published demo page.

The demo on GitHub Pages is a *real* report from a real library, not a mockup
built from invented data - a fabricated demo would be both dishonest and
useless, since the whole claim of this tool is that the numbers it finds are
ones nothing else reports.

Two things are changed on the way out, and nothing else:

1. Absolute paths are shortened. The report quotes the file it found as
   evidence, and those paths name the machine's mount points. The findings do
   not depend on them, so ``/mnt/ssd/music/library`` becomes ``/music``.
2. A banner is added saying what the reader is looking at, so nobody mistakes
   a real audit for a marketing screenshot.

Counts, artists, titles, verdicts and completeness figures are untouched.

    python scripts/publish_demo.py report.html docs/index.html \\
        --strip /mnt/ssd/music/library
"""
from __future__ import annotations

import argparse
import html
import sys

BANNER = (
    '<div style="background:var(--card);border:1px solid var(--line);'
    'border-left:3px solid var(--accent);border-radius:8px;padding:14px 16px;'
    'margin:0 0 22px">'
    '<div style="font-weight:600;margin-bottom:4px">'
    'This is a real audit, not a mockup.</div>'
    '<div style="color:var(--dim);font-size:12.5px">'
    '%s'
    ' Every count, artist and verdict below is what trackaudit actually'
    ' returned. The only change made for publication is that filesystem'
    ' paths were shortened to <span style="font-family:ui-monospace,'
    'SFMono-Regular,Menlo,monospace">/music</span>, so this page does not'
    ' publish a server\'s disk layout. Nothing else was altered, and'
    ' nothing in the library was modified to produce it &mdash; trackaudit'
    ' does not write unless asked.'
    '</div></div>'
)

DEFAULT_NOTE = (
    "It was produced by running trackaudit against a real music library"
    " with Lidarr attached."
)


def scrub(text: str, strip: list, replacement: str = "/music") -> str:
    # Longest first: /mnt/ssd/music/library must go before /mnt/ssd/music,
    # or the tail of the longer path survives as a fragment.
    for prefix in sorted(strip, key=len, reverse=True):
        text = text.replace(html.escape(prefix, quote=True), replacement)
        text = text.replace(prefix, replacement)
    return text


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("source", help="report produced by trackaudit")
    p.add_argument("dest", help="where to write the published page")
    p.add_argument("--strip", action="append", default=[], metavar="PREFIX",
                   help="path prefix to shorten to /music (repeatable)")
    p.add_argument("--note", default=DEFAULT_NOTE,
                   help="first sentence of the banner")
    p.add_argument("--no-banner", action="store_true")
    args = p.parse_args(argv)

    with open(args.source, encoding="utf-8") as fh:
        text = fh.read()

    if args.strip:
        text = scrub(text, args.strip)

    if not args.no_banner:
        anchor = "<div class=wrap>"
        if anchor not in text:
            print("error: %r not found - report format changed?" % anchor,
                  file=sys.stderr)
            return 1
        text = text.replace(anchor, anchor + (BANNER % html.escape(args.note)),
                            1)

    for prefix in args.strip:
        if prefix in text:
            print("error: %r survived scrubbing" % prefix, file=sys.stderr)
            return 1

    with open(args.dest, "w", encoding="utf-8") as fh:
        fh.write(text)
    print("wrote %s (%d bytes)" % (args.dest, len(text)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
