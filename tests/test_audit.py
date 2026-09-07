"""The audit engine, driven by fakes.

No network and no Lidarr: the catalogue and the app are both stubbed, so these
tests pin the *logic* - which disagreement produces which finding - rather than
anyone's live data.
"""
from __future__ import annotations

import pathlib

import pytest

from trackaudit.arr import ArrArtist, ArrTrack
from trackaudit.audit import Audit
from trackaudit.catalogue import Artist, Catalogue, Recording
from trackaudit.library import Library


class FakeCatalogue(Catalogue):
    name = "fake"

    def __init__(self, records):
        self.records = records

    def find_artist(self, name):
        return Artist("1", name, 100)

    def recordings(self, artist):
        return [r if isinstance(r, Recording) else Recording(*r)
                for r in self.records]


class FakeArr:
    """Just enough of the Lidarr client for the audit to consume."""

    def __init__(self, artist: ArrArtist):
        self.artist = artist
        self.refreshed = []
        self.monitor_calls = []

    def artists(self, monitored_only=True, only=None):
        return [{"id": self.artist.id, "artistName": self.artist.name,
                 "path": self.artist.path, "monitored": True}]

    def artist_detail(self, row):
        return self.artist

    def refresh_artist(self, artist_id):
        self.refreshed.append(artist_id)

    def set_monitored(self, ids, monitored, chunk=20):
        self.monitor_calls.append((list(ids), monitored))
        return len(ids), []


def build_library(tmp_path, files):
    root = tmp_path / "library"
    for rel in files:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"\0" * 16)
    return Library.scan(str(root))


def track(title, has_file=False, album="Album", album_type="Album",
          path=None, album_id=1, duration=0.0):
    return ArrTrack(track_id=abs(hash(title)) % 10_000, album_id=album_id,
                    album=album, album_type=album_type, title=title,
                    has_file=has_file, file_path=path, duration=duration)


def codes(audit):
    return sorted(f.code for f in audit.findings)


# -- catalogue vs disk -------------------------------------------------------

def test_missing_when_catalogue_has_it_and_disk_does_not(tmp_path):
    lib = build_library(tmp_path, ["Samra/Album/Samra - Album - 01 - Owned.flac"])
    cat = FakeCatalogue([("Owned", "Album", "2020", 0),
                         ("Not Owned", "Album", "2020", 0)])
    audit = Audit(lib, cat).run(["Samra"])
    assert codes(audit) == ["missing"]
    assert audit.findings[0].title == "Not Owned"


def test_owned_count_and_percentage(tmp_path):
    lib = build_library(tmp_path, ["A/Al/A - Al - 01 - One.flac",
                                   "A/Al/A - Al - 02 - Two.flac"])
    cat = FakeCatalogue([("One", "Al", "2020", 0), ("Two", "Al", "2020", 0),
                         ("Three", "Al", "2020", 0), ("Four", "Al", "2020", 0)])
    audit = Audit(lib, cat).run(["A"])
    report = audit.artists[0]
    assert (report.owned, report.catalogue_total, report.missing) == (2, 4, 2)
    assert report.percent == 50.0


def test_collaboration_filed_under_another_artist_is_not_missing(tmp_path):
    lib = build_library(tmp_path, ["Kurdo/Blanco/Kurdo - Blanco - 05 - Paranoia.flac"])
    cat = FakeCatalogue([("Paranoia", "Blanco", "2017", 0)])
    audit = Audit(lib, cat).run(["Samra"])
    assert codes(audit) == ["filed_elsewhere"]


def test_live_version_in_catalogue_does_not_match_the_studio_file(tmp_path):
    lib = build_library(tmp_path, ["Q/A/Q - A - 01 - Who Wants to Live Forever.flac"])
    cat = FakeCatalogue([("Who Wants to Live Forever (Live in Budapest)",
                          "Live", "1987", 0)])
    audit = Audit(lib, cat).run(["Q"])
    assert codes(audit) == ["missing"]


# -- disk vs app -------------------------------------------------------------

def test_ghost_when_file_exists_but_app_has_no_record(tmp_path):
    lib = build_library(tmp_path, ["Samra/Muede/Samra - Muede - 01 - Muede.flac"])
    arr = FakeArr(ArrArtist(id=1, name="Samra", path=str(pathlib.Path(lib.root) / "Samra"),
                            tracks=[track("Muede")], files=frozenset()))
    audit = Audit(lib, None, arr).run()
    assert "ghost" in codes(audit)
    ghost = [f for f in audit.findings if f.code == "ghost"][0]
    assert ghost.applicable is True
    assert ghost.artist_id == 1


def test_duplicate_entry_when_the_only_copy_is_already_assigned(tmp_path):
    """The finding that separates a real fix from a destructive one."""
    lib = build_library(tmp_path, ["AK/Wo/AK - Wo - 02 - Habibi.flac"])
    owned = lib.tracks[0].path
    arr = FakeArr(ArrArtist(
        id=12, name="AK", path=str(pathlib.Path(lib.root) / "AK"),
        tracks=[track("Habibi", has_file=True, album="Wo", album_type="Single",
                      path=owned, album_id=687),
                track("Habibi", has_file=False, album="Habibi",
                      album_type="Single", album_id=1203)],
        files=frozenset({owned})))
    audit = Audit(lib, None, arr).run()
    dupes = [f for f in audit.findings if f.code == "duplicate_entry"]
    assert len(dupes) == 1
    assert dupes[0].album_id == 1203
    assert dupes[0].applicable is True
    assert "ghost" not in codes(audit)


def test_album_type_duplicate_is_reported_but_not_applicable(tmp_path):
    lib = build_library(tmp_path, ["AK/Wo/AK - Wo - 02 - Habibi.flac"])
    owned = lib.tracks[0].path
    arr = FakeArr(ArrArtist(
        id=12, name="AK", path=str(pathlib.Path(lib.root) / "AK"),
        tracks=[track("Habibi", has_file=True, path=owned, album_id=1),
                track("Habibi", has_file=False, album_type="Album", album_id=2)],
        files=frozenset({owned})))
    audit = Audit(lib, None, arr).run()
    dupes = [f for f in audit.findings if f.code == "duplicate_entry"]
    assert dupes and dupes[0].applicable is False
    assert audit.applicable() == []


def test_orphan_when_file_has_no_entry(tmp_path):
    lib = build_library(tmp_path, ["Samra/EP/Samra - EP - 01 - Mosaik.flac"])
    arr = FakeArr(ArrArtist(id=1, name="Samra",
                            path=str(pathlib.Path(lib.root) / "Samra"),
                            tracks=[], files=frozenset()))
    audit = Audit(lib, None, arr).run()
    assert codes(audit) == ["orphan"]


def test_invisible_when_released_but_app_has_no_entry(tmp_path):
    """The headline finding: a gap the manager cannot even show you."""
    lib = build_library(tmp_path, ["Samra/A/Samra - A - 01 - Known.flac"])
    known = lib.tracks[0].path
    arr = FakeArr(ArrArtist(id=1, name="Samra",
                            path=str(pathlib.Path(lib.root) / "Samra"),
                            tracks=[track("Known", has_file=True, path=known)],
                            files=frozenset({known})))
    cat = FakeCatalogue([("Known", "A", "2020", 0),
                         ("Boese Jungs", "Single", "2021", 0)])
    audit = Audit(lib, cat, arr).run()
    invisible = [f for f in audit.findings if f.code == "invisible"]
    assert len(invisible) == 1
    assert invisible[0].title == "Boese Jungs"


def test_uncertain_match_is_reported_and_never_applied(tmp_path):
    lib = build_library(tmp_path, ["S/A/S - A - 01 - Zunga.flac"])
    arr = FakeArr(ArrArtist(id=1, name="S",
                            path=str(pathlib.Path(lib.root) / "S"),
                            tracks=[track("ZUN9A")], files=frozenset()))
    audit = Audit(lib, None, arr).run()
    # It is also an orphan - the file has no entry - and both are true.
    assert "uncertain_match" in codes(audit)
    assert "ghost" not in codes(audit)
    assert audit.applicable() == []


# -- disk alone --------------------------------------------------------------

def test_lossy_beside_lossless(tmp_path):
    lib = build_library(tmp_path, ["S/A/S - A - 01 - Song.flac",
                                   "S/A/S - A - 01 - Song.mp3"])
    audit = Audit(lib).run(["S"])
    assert codes(audit) == ["lossy_duplicate"]
    assert audit.findings[0].evidence.endswith(".mp3")


def test_lossless_only_is_not_a_finding(tmp_path):
    lib = build_library(tmp_path, ["S/A/S - A - 01 - Song.flac"])
    assert Audit(lib).run(["S"]).findings == []


# -- serialisation -----------------------------------------------------------

def test_as_dict_is_json_safe(tmp_path):
    import json
    lib = build_library(tmp_path, ["S/A/S - A - 01 - Song.flac"])
    cat = FakeCatalogue([("Song", "A", "2020", 0), ("Other", "A", "2021", 0)])
    payload = Audit(lib, cat).run(["S"]).as_dict()
    assert json.loads(json.dumps(payload))["counts"]["missing"] == 1


@pytest.mark.parametrize("code", ["ghost", "orphan", "duplicate_entry",
                                  "invisible", "missing", "filed_elsewhere",
                                  "lossy_duplicate", "uncertain_match"])
def test_every_code_has_a_description(code):
    from trackaudit.audit import FINDING_TYPES, ORDER
    assert code in FINDING_TYPES and code in ORDER
    label, severity, why = FINDING_TYPES[code]
    assert label and why and severity in ("high", "medium", "low")


def test_generic_titles_do_not_match_across_artists(tmp_path):
    """One artist's "Intro" says nothing about another's."""
    lib = build_library(tmp_path, ["Kurdo/Slum/Kurdo - Slum - 01 - Intro.flac"])
    cat = FakeCatalogue([("Intro", "Album", "2020", 0)])
    audit = Audit(lib, cat).run(["Samra"])
    assert codes(audit) == ["missing"]


def test_distinctive_titles_still_match_across_artists(tmp_path):
    lib = build_library(tmp_path,
                        ["Capital Bra/BL2/Capital Bra - BL2 - 03 - Tranquillo.flac"])
    cat = FakeCatalogue([("Tranquillo", "Berlin lebt 2", "2019", 0)])
    audit = Audit(lib, cat).run(["Samra"])
    assert codes(audit) == ["filed_elsewhere"]
