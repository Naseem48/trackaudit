"""What is actually on disk.

Deliberately dumb: it walks a directory and reads file names. No tag library,
no dependency, nothing to install. Tags are frequently wrong in exactly the
libraries that most need auditing - that is often *why* they need auditing -
and the file name is what the user sees in their player.

Layout assumed is the one every *arr and beets produces:

    <root>/<Artist>/<Album>/<Artist> - <Album> - 04 - <Title>.flac

Only the artist level matters; everything below it is walked.
"""
from __future__ import annotations

import os
from typing import Dict, Iterator, List, NamedTuple, Optional

from .match import Identity, identity, title_from_filename

LOSSLESS_EXT = frozenset({".flac", ".wav", ".ape", ".alac", ".aiff", ".wv"})
LOSSY_EXT = frozenset({".mp3", ".m4a", ".aac", ".ogg", ".opus", ".wma"})
AUDIO_EXT = LOSSLESS_EXT | LOSSY_EXT


class Track(NamedTuple):
    path: str
    title: str
    artist_dir: str
    ext: str
    size: int

    @property
    def lossless(self) -> bool:
        return self.ext in LOSSLESS_EXT

    @property
    def id(self) -> Identity:
        return identity(self.title)


class Library:
    """An indexed view of the audio files under a root directory."""

    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        self.tracks: List[Track] = []
        self.by_artist: Dict[str, List[Track]] = {}
        self.by_identity: Dict[Identity, List[Track]] = {}
        self.by_path: Dict[str, Track] = {}

    @classmethod
    def scan(cls, root: str, follow_symlinks: bool = False) -> "Library":
        lib = cls(root)
        if not os.path.isdir(lib.root):
            raise NotADirectoryError(lib.root)
        for entry in sorted(os.listdir(lib.root)):
            artist_path = os.path.join(lib.root, entry)
            if not os.path.isdir(artist_path):
                continue
            lib.by_artist[entry] = list(
                lib._walk(artist_path, entry, follow_symlinks))
        for tracks in lib.by_artist.values():
            for track in tracks:
                lib.tracks.append(track)
                lib.by_path[track.path] = track
                lib.by_identity.setdefault(track.id, []).append(track)
        return lib

    def _walk(self, path: str, artist_dir: str,
              follow_symlinks: bool) -> Iterator[Track]:
        for dirpath, _dirs, files in os.walk(path, followlinks=follow_symlinks):
            for name in sorted(files):
                ext = os.path.splitext(name)[1].lower()
                if ext not in AUDIO_EXT:
                    continue
                full = os.path.join(dirpath, name)
                try:
                    size = os.lstat(full).st_size
                except OSError:
                    size = 0
                yield Track(path=full, title=title_from_filename(name),
                            artist_dir=artist_dir, ext=ext, size=size)

    # -- lookups ------------------------------------------------------------

    def find(self, title: str,
             artist_dir: Optional[str] = None) -> List[Track]:
        """Tracks matching a title exactly by identity.

        With ``artist_dir`` the search is scoped to one artist's folder; without
        it the whole library is searched, which is what catches a collaboration
        filed under whoever was credited first.
        """
        hits = self.by_identity.get(identity(title), [])
        if artist_dir is None:
            return list(hits)
        return [t for t in hits if t.artist_dir == artist_dir]

    def artists(self) -> List[str]:
        return [a for a, tracks in sorted(self.by_artist.items()) if tracks]

    @property
    def lossless_count(self) -> int:
        return sum(1 for t in self.tracks if t.lossless)

    @property
    def bytes(self) -> int:
        return sum(t.size for t in self.tracks)

    def __len__(self) -> int:
        return len(self.tracks)
