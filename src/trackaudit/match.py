"""Decide whether two track titles name the same recording.

This is the hard part of auditing a music library, and it is much harder than
string similarity suggests. The pairs that matter most are the ones that look
almost identical:

    "Who Wants to Live Forever" / "Who Wants to Live Forever (Live in Budapest)"
    "Let There Be Rock (Part 1)" / "Let There Be Rock (Part 2)"

Those are not typos to be smoothed over. They are different recordings, and
treating them as one is how a library ends up with one file standing in for two
catalogue entries - or worse, with an importer rewriting the tags of an album
track because it believed the track was a single.

Every rule here was written in response to a real failure:

    qualifiers are read only where they can be appended, because a song called
      "Live Is Life" is not a live recording

    the whole qualifying phrase is compared, not the keyword that triggered it,
      because "(Part 1)" and "(Part 2)" are both merely "part"

    leading track numbers are stripped conservatively, because a greedy pattern
      turns "95 BPM" into "BPM" and "365 Tage" into "Tage"

    durations, when both are known, can veto a match the strings agreed on

The module has no dependencies and no I/O, so it can be imported by anything.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from typing import FrozenSet, NamedTuple, Optional

__all__ = [
    "SAME", "DIFFERENT", "UNCERTAIN",
    "Identity", "identity", "normalize", "qualifiers", "compare",
    "strip_track_number", "title_from_filename", "similarity",
]

SAME = "same"
DIFFERENT = "different"
UNCERTAIN = "uncertain"

# Words that mark a genuinely different recording of the same song. "part" is
# here because two parts of a track are not one track, and neither is the
# combined version.
_QUALIFIER_WORDS = (
    "live", "unplugged", "acoustic", "remix", "rmx", "edit", "version",
    "mix", "instrumental", "karaoke", "demo", "remaster", "remastered",
    "reprise", "radio", "extended", "part", "pt", "skit", "intro", "outro",
    "interlude", "snippet", "freestyle", "session", "bonus", "alternate",
    "deluxe", "orchestral", "piano", "slowed", "sped", "reverb", "rerecorded",
    "cover", "mono", "stereo", "single", "album", "original", "clean",
    "explicit", "dub", "vip", "bootleg", "medley", "continuous",
)
_QUALIFIER = re.compile(r"\b(%s)\b" % "|".join(_QUALIFIER_WORDS), re.I)

# Credits change who is listed, not which recording it is.
_CREDIT = re.compile(
    r"\b(feat|ft|featuring|with|prod|produced\s+by|w)\b\.?\s.*", re.I)

_BRACKET = re.compile(r"[\(\[\{]([^\)\]\}]*)[\)\]\}]")

# A leading track number, matched narrowly on purpose.
#
# The obvious pattern - r"^\d{1,4}[.\)]?\s+" - also eats the start of any title
# that opens with a number, which silently renamed "95 BPM" to "BPM" and
# "365 Tage" to "Tage" and made both look missing. A number only counts as a
# track number when punctuation follows it, or when it is zero-padded.
_TRACK_NO = re.compile(r"^\s*(?:\d{1,4}\s*[.)\-]\s+|\d{1,4}\s*[.)]\s*|0\d{1,3}\s+)")

_SEPARATOR = re.compile(r"\s+[-–—]\s+")
_NOISE = re.compile(r"[^a-z0-9à-ɏ]+")

# Two recordings whose stated durations differ by more than this are not the
# same recording, whatever their titles say.
DURATION_TOLERANCE = 8.0

# Titles this different are not worth asking about.
UNCERTAIN_FLOOR = 0.34

# Character-level closeness above which two titles are suspiciously alike -
# leetspeak ("ZUN9A" / "Zunga"), a plural, a typo. Too close to call different,
# nowhere near safe enough to call same.
CLOSE_SPELLING = 0.75

# Conjunctions are dropped rather than translated, so "Ich & Du", "Ich und Du"
# and "Ich and Du" all reduce alike without picking a language.
_CONJUNCTIONS = frozenset({"and", "und", "et", "en"})

# German (and Nordic) vowels get written three ways depending on who typed
# them: "Müde", "Muede", "Mude". Collapsing the digraph to the bare vowel makes
# all three agree. It also turns "Poesie" into "Posie", which is harmless
# because the same rule is applied to both sides of every comparison.
_DIGRAPH = re.compile(
    r"(?<=[a-z])(?:ue|oe|ae)"      # digraph after a letter: Goethe
    r"|(?:ue|oe|ae)(?=[a-z])")     # digraph before a letter: ueber

_TRANSLIT = {
    "ß": "ss", "æ": "ae", "ø": "o", "å": "aa", "þ": "th", "ð": "d",
    "œ": "oe", "ł": "l", "đ": "d", "ħ": "h", "ı": "i",
}


def _fold(text: str) -> str:
    """Lowercase and flatten the spellings that vary between catalogues.

    Deezer, MusicBrainz and whoever tagged the file rarely agree, so all of
    "Weiße Orchideen" / "Weisse Orchideen" and "Sonne über Berlin" / "Sonne
    ueber Berlin" have to fold together. Sharp s and the Nordic letters do not
    decompose under NFKD, so they are mapped explicitly; the vowel digraphs are
    collapsed so a spelled-out umlaut matches a real one.
    """
    text = text.lower()
    for src, dst in _TRANSLIT.items():
        text = text.replace(src, dst)
    text = _DIGRAPH.sub(lambda m: m.group(0)[0], text)
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def strip_track_number(text: str) -> str:
    """Remove a leading track number, and only a leading track number."""
    return _TRACK_NO.sub("", text or "", count=1)


def normalize(title: str) -> str:
    """The comparable body of a title, with brackets and credits removed.

    This is deliberately *not* an identity: it throws away the qualifier, so
    "Song", "Song (Live)" and "Song (Remix)" all normalize alike. Use
    :func:`identity` to tell recordings apart.
    """
    text = _fold(title or "")
    text = text.replace("&", " and ")
    text = _BRACKET.sub(" ", text)
    text = _CREDIT.sub(" ", text)
    words = _NOISE.sub(" ", text).split()
    return " ".join(w for w in words if w not in _CONJUNCTIONS)


def qualifiers(title: str) -> FrozenSet[str]:
    """The qualifying phrases of a title, as a comparable signature.

    Only places where a qualifier can legitimately be *appended* are scanned -
    bracketed groups, and segments after a trailing dash. Scanning the whole
    title instead reports the song "Live Is Life" as a live recording.

    The full phrase is kept rather than the keyword that matched it, so
    "(Part 1)" and "(Part 2)" produce different signatures. Comparing keywords
    alone made them identical, which let one album track satisfy two separate
    catalogue entries.
    """
    raw = title or ""
    segments = list(_BRACKET.findall(raw))
    segments += _SEPARATOR.split(_BRACKET.sub(" ", raw))[1:]

    signature = set()
    for segment in segments:
        if not _QUALIFIER.search(segment):
            continue
        words = _NOISE.sub(" ", _fold(segment)).split()
        # Drop filler so "(Live in Budapest)" and "(Live at Budapest)" agree.
        words = [w for w in words if w not in ("the", "a", "an", "in", "at",
                                               "on", "from", "of", "version")]
        if words:
            signature.add(" ".join(words))
    return frozenset(signature)


class Identity(NamedTuple):
    """A hashable identity for one recording: the title *and* its qualifier.

    Grouping by the normalized title alone collapses "Rockin' in the Free
    World", "(edit)", "(live)" and "(LP version)" into a single entry, and any
    code that indexes by it will treat four distinct recordings as one.
    """

    title: str
    qualifier: FrozenSet[str]

    def __bool__(self) -> bool:
        return bool(self.title)


def identity(title: str) -> Identity:
    """Identity of a recording, safe to use as a dict key or in a set."""
    return Identity(normalize(title), qualifiers(title))


def similarity(a: str, b: str) -> float:
    """Jaccard overlap of the normalized word sets, 0.0 to 1.0."""
    ta, tb = set(normalize(a).split()), set(normalize(b).split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / float(len(ta | tb))


def compare(a: str, b: str,
            duration_a: Optional[float] = None,
            duration_b: Optional[float] = None) -> str:
    """Compare two titles: ``SAME``, ``DIFFERENT`` or ``UNCERTAIN``.

    ``UNCERTAIN`` is a real answer, not a failure. It means the rules cannot
    separate these two safely, and callers must treat it as "do not touch" -
    never as a match. Guessing here is what corrupts a library; declining to
    guess costs nothing.

    Durations, when both are known, are checked *after* the titles agree: a
    catalogue full-length and a radio edit often carry the same title, and only
    the running time gives them away. A duration of zero is treated as unknown,
    because that is how catalogues encode "we do not know".
    """
    ia, ib = identity(a), identity(b)
    if not ia.title or not ib.title:
        return DIFFERENT

    # A disagreement about the qualifier settles it, whatever the titles say.
    if ia.qualifier != ib.qualifier:
        return DIFFERENT

    if ia.title == ib.title:
        if duration_a and duration_b:
            if abs(float(duration_a) - float(duration_b)) > DURATION_TOLERANCE:
                return DIFFERENT
        return SAME

    # Character-level closeness catches what word overlap cannot: a stylised
    # spelling or a single changed letter shares no whole word with its twin,
    # yet is far too close to declare a different song.
    close = difflib.SequenceMatcher(None, ia.title, ib.title).ratio()
    if close < CLOSE_SPELLING and similarity(a, b) < UNCERTAIN_FLOOR:
        return DIFFERENT

    # Same qualifier, similar but not equal titles: word order, punctuation and
    # spelling differences live here alongside genuinely different songs.
    if duration_a and duration_b:
        if abs(float(duration_a) - float(duration_b)) > DURATION_TOLERANCE:
            return DIFFERENT

    return UNCERTAIN


def title_from_filename(filename: str) -> str:
    """Best guess at the track title in a file name.

    Handles the common "Artist - Album - 04 - Title.flac" layout and the bare
    "04 - Title.flac", and strips bracketed rip tags such as "[FLAC]" that
    would otherwise read as qualifiers.
    """
    stem = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if "." in stem:
        stem = stem.rsplit(".", 1)[0]
    stem = re.sub(r"\[[^\]]*\]", " ", stem)
    parts = _SEPARATOR.split(stem)
    candidate = parts[-1] if len(parts) >= 2 else stem
    return strip_track_number(candidate).strip()
