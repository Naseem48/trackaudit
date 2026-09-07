"""Find out what your music library is actually missing.

Library managers measure completeness against their own metadata source. When
that source is incomplete - which it very often is outside English-language
music - the library reports itself complete while whole releases are missing.

trackaudit compares three sources that disagree: a commercial catalogue, the
files on disk, and (optionally) what your library manager believes.
"""
__version__ = "0.1.0"

from .match import (  # noqa: F401
    SAME, DIFFERENT, UNCERTAIN, Identity, compare, identity, normalize,
    qualifiers, similarity, strip_track_number, title_from_filename,
)

__all__ = [
    "__version__",
    "SAME", "DIFFERENT", "UNCERTAIN",
    "Identity", "compare", "identity", "normalize", "qualifiers",
    "similarity", "strip_track_number", "title_from_filename",
]
