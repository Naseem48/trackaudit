"""Compare the catalogue, the disk and the app, and name the disagreements.

Three sources, each answering a different question:

    A  the catalogue   what the artist released      (Deezer)
    B  the disk        what you actually have        (a walk)
    C  the app         what your library manager believes  (Lidarr, optional)

The interesting findings are the ones no single source can see. "Lidarr says
this is missing" is not a finding; "Lidarr says this is missing and the file is
right there" is. Each finding names *which* disagreement it is, because the
remedies have nothing in common: a lost file wants a rescan, a duplicate entry
wants one of the two entries retired, and an invisible release wants a
downloader.

Nothing here writes. :func:`Audit.applicable` returns the findings that could
be applied, and the CLI applies them only when asked, after a snapshot.
"""
from __future__ import annotations

import time
from typing import Dict, List, NamedTuple, Optional

from . import match
from .catalogue import Catalogue, CatalogueError, Recording
from .library import Library, Track

# code -> (label, severity, explanation)
FINDING_TYPES = {
    "ghost": (
        "The app lost the file", "high",
        "The file is on disk and the app has no record of it, so it is "
        "missing from your library for no reason. A rescan usually recovers "
        "it."),
    "orphan": (
        "Not in the library", "medium",
        "On disk with no entry in the app at all, so it does not appear in "
        "any player fed by it."),
    "duplicate_entry": (
        "Two entries, one recording", "medium",
        "A single and an album track that are the same recording. One file "
        "cannot satisfy both entries, so one of them stays missing forever "
        "however many times you re-download it."),
    "invisible": (
        "The app cannot see it", "medium",
        "Genuinely released, but absent from the app's metadata source, so it "
        "cannot even be shown to you as missing. This is the gap that makes a "
        "library report itself complete when it is not."),
    "missing": (
        "Released, not owned", "low",
        "In the catalogue and not on disk."),
    "filed_elsewhere": (
        "Under another artist", "low",
        "Found under a different artist's folder - usually a collaboration "
        "filed under whoever was credited first."),
    "lossy_duplicate": (
        "Lossy beside lossless", "low",
        "A lossy copy sitting next to a lossless one of the same recording."),
    "uncertain_match": (
        "Too close to call", "low",
        "The titles are close enough that a wrong guess would mis-file a "
        "track, so nothing was decided. Confirm by hand."),
}

ORDER = ["ghost", "orphan", "duplicate_entry", "invisible", "missing",
         "filed_elsewhere", "lossy_duplicate", "uncertain_match"]

# Titles that collide across unrelated artists. Searching the whole library for
# a collaboration is what catches a track filed under the other credited
# artist, but almost every rap album has an "Intro", so matching one of these
# outside the artist's own folder says nothing at all.
GENERIC_TITLES = frozenset({
    "intro", "outro", "skit", "interlude", "prolog", "prologue", "epilog",
    "epilogue", "vorwort", "bonus", "bonus track", "untitled", "hidden track",
    "reprise", "overture", "theme", "instrumental", "freestyle", "part 1",
    "part 2", "intermission", "interlude 1", "interlude 2",
})


class Finding(NamedTuple):
    code: str
    artist: str
    title: str
    detail: str
    evidence: str = ""
    release: str = ""
    action: str = ""
    applicable: bool = False
    album_id: Optional[int] = None
    artist_id: Optional[int] = None

    def as_dict(self) -> dict:
        out = self._asdict()
        label, severity, _why = FINDING_TYPES[self.code]
        out["label"] = label
        out["severity"] = severity
        return out


class ArtistReport(NamedTuple):
    name: str
    catalogue_total: int
    owned: int
    findings: List[Finding]
    error: str = ""

    @property
    def missing(self) -> int:
        return max(self.catalogue_total - self.owned, 0)

    @property
    def percent(self) -> float:
        if not self.catalogue_total:
            return 0.0
        return round(100.0 * self.owned / self.catalogue_total, 1)


class Audit:
    def __init__(self, library: Library,
                 catalogue: Optional[Catalogue] = None,
                 arr=None):
        self.library = library
        self.catalogue = catalogue
        self.arr = arr
        self.artists: List[ArtistReport] = []
        self.generated = 0

    # -- the three comparisons ---------------------------------------------

    def _catalogue_vs_disk(self, artist_name: str, artist_dir: Optional[str],
                           records: List[Recording],
                           arr_ids=None) -> List[Finding]:
        """A vs B, and A vs C: what was released that you do not have."""
        out: List[Finding] = []
        for rec in records:
            hits = self.library.find(rec.title, artist_dir)
            if hits:
                continue
            # It may be filed under a collaborator; that is not missing.
            # Generic titles are excluded: one artist's "Intro" matching
            # another's proves nothing and would bury the real findings.
            elsewhere = []
            if match.normalize(rec.title) not in GENERIC_TITLES:
                elsewhere = self.library.find(rec.title)
            if elsewhere:
                out.append(Finding(
                    code="filed_elsewhere", artist=artist_name,
                    title=rec.title, release=rec.release,
                    detail="filed under %s" % elsewhere[0].artist_dir,
                    evidence=elsewhere[0].path, action="review"))
                continue
            # If the app has no entry for it either, it is invisible - a
            # stronger and more useful statement than merely missing.
            code = "missing"
            detail = "released %s" % (rec.year or "?")
            action = "download"
            if arr_ids is not None and rec.id not in arr_ids:
                code = "invisible"
                detail = ("released %s, and the app has no entry for it"
                          % (rec.year or "?"))
                action = "fetch manually"
            out.append(Finding(code=code, artist=artist_name, title=rec.title,
                               release=rec.release, detail=detail,
                               action=action))
        return out

    def _disk_vs_arr(self, arr_artist, artist_dir: str) -> List[Finding]:
        """B vs C: the app and the filesystem disagree."""
        out: List[Finding] = []
        tracks = self.library.by_artist.get(artist_dir, [])

        for entry in arr_artist.tracks:
            if entry.has_file:
                continue
            hit, uncertain = None, None
            for track in tracks:
                verdict = match.compare(entry.title, track.title,
                                        entry.duration or None, None)
                if verdict == match.SAME:
                    hit = track
                    break
                if verdict == match.UNCERTAIN and uncertain is None:
                    uncertain = track

            if hit is None:
                if uncertain is not None:
                    out.append(Finding(
                        code="uncertain_match", artist=arr_artist.name,
                        title=entry.title, release=entry.album,
                        detail="looks like %r on disk" % uncertain.title,
                        evidence=uncertain.path, action="confirm by hand"))
                continue

            # A file the app has already assigned to some other track is not a
            # lost file. It is one recording that two entries both want, and no
            # rescan can give it to both.
            if hit.path in arr_artist.files:
                is_single = entry.album_type == "Single"
                out.append(Finding(
                    code="duplicate_entry", artist=arr_artist.name,
                    title=entry.title, release=entry.album,
                    detail="the only copy is already assigned elsewhere",
                    evidence=hit.path,
                    action="retire this entry" if is_single else "review",
                    applicable=is_single, album_id=entry.album_id))
            else:
                out.append(Finding(
                    code="ghost", artist=arr_artist.name, title=entry.title,
                    release=entry.album,
                    detail="on disk, but the app has no file for it",
                    evidence=hit.path, action="rescan",
                    applicable=True, artist_id=arr_artist.id))

        for track in tracks:
            if track.path not in arr_artist.files:
                out.append(Finding(
                    code="orphan", artist=arr_artist.name, title=track.title,
                    detail="on disk, no entry in the app",
                    evidence=track.path, action="import"))
        return out

    def _disk_only(self, artist_name: str, artist_dir: str) -> List[Finding]:
        """B alone: problems visible from the filesystem by itself."""
        out: List[Finding] = []
        groups: Dict[object, List[Track]] = {}
        for track in self.library.by_artist.get(artist_dir, []):
            groups.setdefault(track.id, []).append(track)
        for tracks in groups.values():
            lossless = [t for t in tracks if t.lossless]
            lossy = [t for t in tracks if not t.lossless]
            if lossless and lossy:
                out.append(Finding(
                    code="lossy_duplicate", artist=artist_name,
                    title=tracks[0].title,
                    detail="lossy copy beside %s"
                           % lossless[0].ext.lstrip("."),
                    evidence=lossy[0].path, action="delete the lossy copy"))
        return out

    # -- driver -------------------------------------------------------------

    def run(self, names: Optional[List[str]] = None,
            progress=None) -> "Audit":
        arr_artists = {}
        if self.arr is not None:
            for row in self.arr.artists(only=None):
                arr_artists[row.get("artistName", "")] = row

        if names:
            targets = list(names)
        elif arr_artists:
            targets = sorted(arr_artists)
        else:
            targets = self.library.artists()

        for name in targets:
            if progress:
                progress(name)
            findings: List[Finding] = []
            error = ""
            arr_detail = None
            artist_dir = name if name in self.library.by_artist else None

            if name in arr_artists and self.arr is not None:
                try:
                    arr_detail = self.arr.artist_detail(arr_artists[name])
                    if arr_detail.path:
                        candidate = arr_detail.path.replace("\\", "/") \
                            .rstrip("/").rsplit("/", 1)[-1]
                        if candidate in self.library.by_artist:
                            artist_dir = candidate
                except Exception as exc:            # noqa: BLE001
                    error = "app: %s" % exc

            if artist_dir is None:
                # Nothing on disk under this name; still worth auditing the
                # catalogue, so fall back to a directory-less comparison.
                artist_dir = name

            records: List[Recording] = []
            if self.catalogue is not None:
                try:
                    found = self.catalogue.find_artist(name)
                    if found is None:
                        error = error or "not found in %s" % self.catalogue.name
                    else:
                        records = self.catalogue.recordings(found)
                except CatalogueError as exc:
                    error = error or str(exc)

            arr_ids = None
            if arr_detail is not None:
                arr_ids = {t.id for t in arr_detail.tracks}
                findings += self._disk_vs_arr(arr_detail, artist_dir)

            if records:
                findings += self._catalogue_vs_disk(name, artist_dir, records,
                                                    arr_ids)
            findings += self._disk_only(name, artist_dir)

            owned = 0
            if records:
                owned = sum(1 for r in records
                            if self.library.find(r.title, artist_dir)
                            or self.library.find(r.title))
            self.artists.append(ArtistReport(
                name=name, catalogue_total=len(records), owned=owned,
                findings=findings, error=error))

        self.generated = int(time.time())
        return self

    # -- results ------------------------------------------------------------

    @property
    def findings(self) -> List[Finding]:
        out: List[Finding] = []
        for report in self.artists:
            out += report.findings
        return out

    def counts(self) -> Dict[str, int]:
        counts = {code: 0 for code in ORDER}
        for finding in self.findings:
            counts[finding.code] = counts.get(finding.code, 0) + 1
        return counts

    def applicable(self) -> List[Finding]:
        return [f for f in self.findings if f.applicable]

    def as_dict(self) -> dict:
        return {
            "generated": self.generated,
            "library": {"root": self.library.root,
                        "tracks": len(self.library),
                        "lossless": self.library.lossless_count,
                        "bytes": self.library.bytes},
            "counts": self.counts(),
            "artists": [{"name": a.name, "catalogue": a.catalogue_total,
                         "owned": a.owned, "missing": a.missing,
                         "percent": a.percent, "error": a.error,
                         "findings": len(a.findings)}
                        for a in self.artists],
            "findings": [f.as_dict() for f in self.findings],
        }
