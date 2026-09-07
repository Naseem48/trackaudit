"""The matcher, checked against the corpus and against its own edge cases."""
from __future__ import annotations

import json
import pathlib

import pytest

from trackaudit import match

CORPUS = json.loads(
    (pathlib.Path(__file__).parent / "corpus.json").read_text(encoding="utf-8"))


def _ids(cases):
    return ["%s|%s" % (c["a"], c["b"]) for c in cases]


@pytest.mark.parametrize("case", CORPUS["cases"], ids=_ids(CORPUS["cases"]))
def test_corpus(case):
    got = match.compare(case["a"], case["b"])
    assert got == case["verdict"], (
        "%r vs %r: expected %s, got %s (%s)"
        % (case["a"], case["b"], case["verdict"], got, case["why"]))


@pytest.mark.parametrize("case", CORPUS["cases"], ids=_ids(CORPUS["cases"]))
def test_corpus_is_symmetric(case):
    """A verdict must not depend on argument order."""
    forward = match.compare(case["a"], case["b"])
    backward = match.compare(case["b"], case["a"])
    assert forward == backward


@pytest.mark.parametrize("case", CORPUS["filenames"],
                         ids=[c["file"] for c in CORPUS["filenames"]])
def test_filename_titles(case):
    assert match.title_from_filename(case["file"]) == case["title"]


def test_identity_separates_qualifiers():
    """The bug that let one file satisfy four catalogue entries."""
    base = match.identity("Rockin' in the Free World")
    variants = [match.identity("Rockin' in the Free World (%s)" % q)
                for q in ("edit", "live", "LP version")]
    assert len({base, *variants}) == 4


def test_identity_ignores_credits_and_case():
    assert match.identity("Neymar") == match.identity("NEYMAR (feat. Ufo361)")


def test_identity_is_hashable_and_falsey_when_empty():
    assert not match.identity("")
    assert match.identity("x") in {match.identity("x")}


def test_track_number_strip_is_conservative():
    assert match.strip_track_number("95 BPM") == "95 BPM"
    assert match.strip_track_number("365 Tage") == "365 Tage"
    assert match.strip_track_number("01 Intro") == "Intro"
    assert match.strip_track_number("1. Intro") == "Intro"
    assert match.strip_track_number("12 - Intro") == "Intro"
    assert match.strip_track_number("1995") == "1995"


def test_duration_vetoes_a_title_match():
    assert match.compare("One", "One", 260.0, 262.0) == match.SAME
    assert match.compare("One", "One", 260.0, 210.0) == match.DIFFERENT


def test_zero_duration_means_unknown():
    """Catalogues use 0 for 'no idea'; it must not veto anything."""
    assert match.compare("One", "One", 0, 300.0) == match.SAME


def test_uncertain_is_never_same():
    verdict = match.compare("ZUN9A", "Zunga")
    assert verdict == match.UNCERTAIN
    assert verdict != match.SAME


def test_empty_titles_are_different():
    assert match.compare("", "") == match.DIFFERENT
    assert match.compare("Song", "") == match.DIFFERENT


def test_qualifiers_only_read_where_appendable():
    assert match.qualifiers("Live Is Life") == frozenset()
    assert match.qualifiers("Song (Live)") == frozenset({"live"})
    assert match.qualifiers("Song - Live") == frozenset({"live"})


def test_qualifier_keeps_the_whole_phrase():
    assert match.qualifiers("X (Part 1)") != match.qualifiers("X (Part 2)")


def test_similarity_bounds():
    assert match.similarity("a b", "a b") == 1.0
    assert match.similarity("abc", "xyz") == 0.0
    assert match.similarity("", "x") == 0.0
