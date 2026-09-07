"""Command line entry point.

Reporting is the default and the whole point. ``--apply`` exists, does only the
two things that are reversible and unambiguous, and writes an undo file before
it touches anything.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import List, Optional

from . import __version__
from .arr import ArrError, Lidarr, api_key_from_config
from .audit import ORDER, Audit
from .catalogue import CatalogueError, get as get_catalogue
from .library import Library
from .report import render, render_json


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="trackaudit",
        description="Find out what your music library is actually missing.",
        epilog="Reports by default; nothing is modified unless you pass "
               "--apply.")
    p.add_argument("--library", "-l", required=True,
                   help="root directory, containing one folder per artist")
    p.add_argument("--artist", "-a", action="append", default=None,
                   help="audit only this artist (repeatable)")
    p.add_argument("--out", "-o", default="trackaudit-report.html",
                   help="HTML report path (default: %(default)s)")
    p.add_argument("--json", dest="json_out", default=None,
                   help="also write the findings as JSON")
    p.add_argument("--catalogue", default="deezer",
                   help="catalogue provider, or 'none' to skip "
                        "(default: %(default)s)")
    p.add_argument("--artist-id", action="append", default=[],
                   metavar="NAME=ID",
                   help="pin a catalogue artist id, bypassing the search")

    arr = p.add_argument_group("library manager (optional)")
    arr.add_argument("--lidarr", metavar="URL",
                     help="Lidarr base URL, e.g. http://localhost:8686")
    arr.add_argument("--lidarr-key", help="Lidarr API key")
    arr.add_argument("--lidarr-config", metavar="PATH",
                     help="read the API key from a Lidarr config.xml")
    arr.add_argument("--path-map", metavar="FROM:TO",
                     help="translate container paths to host paths, e.g. "
                          "/music:/mnt/ssd/music -- required when Lidarr runs "
                          "in a container, or every file reads as unmanaged")

    act = p.add_argument_group("acting on findings")
    act.add_argument("--apply", action="store_true",
                     help="apply the reversible findings (rescan lost files, "
                          "retire duplicate single entries)")
    act.add_argument("--undo", metavar="FILE",
                     help="restore an undo file written by a previous --apply")

    p.add_argument("--quiet", "-q", action="store_true")
    p.add_argument("--version", action="version",
                   version="trackaudit %s" % __version__)
    return p


def _make_arr(args) -> Optional[Lidarr]:
    if not args.lidarr:
        return None
    key = args.lidarr_key
    if not key and args.lidarr_config:
        key = api_key_from_config(args.lidarr_config)
    if not key:
        key = os.environ.get("LIDARR_API_KEY")
    if not key:
        raise SystemExit("error: --lidarr needs --lidarr-key, "
                         "--lidarr-config, or $LIDARR_API_KEY")
    path_map = None
    if args.path_map:
        if ":" not in args.path_map:
            raise SystemExit("error: --path-map must look like FROM:TO")
        src, dst = args.path_map.split(":", 1)
        path_map = (src, dst)
    return Lidarr(args.lidarr, key, path_map=path_map)


def _apply(audit: Audit, arr: Lidarr, quiet: bool) -> int:
    findings = audit.applicable()
    if not findings:
        print("nothing to apply")
        return 0

    retire = sorted({f.album_id for f in findings
                     if f.code == "duplicate_entry" and f.album_id})
    rescan = sorted({f.artist_id for f in findings
                     if f.code == "ghost" and f.artist_id})

    undo_path = "trackaudit-undo-%s.json" % time.strftime("%Y%m%d-%H%M%S")
    with open(undo_path, "w", encoding="utf-8") as handle:
        json.dump({"generated": int(time.time()),
                   "remonitor_album_ids": retire}, handle, indent=1)
    print("undo file: %s" % undo_path)

    if retire:
        done, failed = arr.set_monitored(retire, False)
        print("retired %d duplicate entr%s"
              % (done, "y" if done == 1 else "ies"))
        for album_id, why in failed:
            print("  could not retire album %s: %s" % (album_id, why))
    for artist_id in rescan:
        arr.refresh_artist(artist_id)
    if rescan:
        print("queued a rescan for %d artist(s)" % len(rescan))
    if not quiet:
        print("undo with:  trackaudit --library ... --lidarr ... --undo %s"
              % undo_path)
    return 0


def _undo(path: str, arr: Optional[Lidarr]) -> int:
    if arr is None:
        raise SystemExit("error: --undo needs --lidarr too")
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    ids = data.get("remonitor_album_ids") or []
    if not ids:
        print("nothing to restore in %s" % path)
        return 0
    done, failed = arr.set_monitored(ids, True)
    print("restored %d album(s) from %s" % (done, path))
    for album_id, why in failed:
        print("  could not restore album %s: %s" % (album_id, why))
    return 1 if failed else 0


def main(argv: Optional[List[str]] = None) -> int:
    args = _parser().parse_args(argv)

    try:
        arr = _make_arr(args)
    except ArrError as exc:
        raise SystemExit("error: %s" % exc)

    if args.undo:
        return _undo(args.undo, arr)

    if arr is not None:
        try:
            version = arr.ping()
            if not args.quiet:
                print("lidarr %s at %s" % (version, args.lidarr))
        except ArrError as exc:
            raise SystemExit("error: cannot reach Lidarr: %s" % exc)

    try:
        library = Library.scan(args.library)
    except NotADirectoryError as exc:
        raise SystemExit("error: not a directory: %s" % exc)
    if not args.quiet:
        print("library: %d file(s), %d artist folder(s)"
              % (len(library), len(library.artists())))
    if not len(library):
        print("warning: no audio files found under %s" % library.root,
              file=sys.stderr)

    overrides = {}
    for item in args.artist_id:
        if "=" not in item:
            raise SystemExit("error: --artist-id must look like NAME=ID")
        name, value = item.split("=", 1)
        overrides[name] = value

    catalogue = None
    if args.catalogue.lower() != "none":
        try:
            catalogue = get_catalogue(args.catalogue, overrides=overrides)
        except CatalogueError as exc:
            raise SystemExit("error: %s" % exc)

    def progress(name):
        if not args.quiet:
            print("  %s" % name, flush=True)

    audit = Audit(library, catalogue, arr).run(args.artist, progress=progress)

    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(render(audit))
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as handle:
            handle.write(render_json(audit))

    counts = audit.counts()
    if not args.quiet:
        print()
        for code in ORDER:
            if counts.get(code):
                print("  %-16s %d" % (code, counts[code]))
    print("\nreport: %s" % os.path.abspath(args.out))
    if args.json_out:
        print("json:   %s" % os.path.abspath(args.json_out))

    applicable = audit.applicable()
    if applicable and not args.apply:
        print("%d finding(s) can be applied - re-run with --apply"
              % len(applicable))
    elif args.apply:
        if arr is None:
            raise SystemExit("error: --apply needs --lidarr")
        print()
        return _apply(audit, arr, args.quiet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
