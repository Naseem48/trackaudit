"""What Lidarr believes, read through its API.

Optional. Without it trackaudit still answers the main question - what did the
artist release that you do not have - by comparing the catalogue against the
disk. With it, three more classes of problem become visible, all of which are
disagreements between the app and the filesystem rather than gaps in either.

Two things reliably trip people up here, so both are handled explicitly:

* Lidarr usually runs in a container and reports *container* paths. Comparing
  those to host paths marks the entire library as unmanaged. ``path_map``
  translates them.
* Lidarr's ``wanted/missing`` endpoint is album-level. Track-level truth needs
  the track endpoint, one call per album.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, NamedTuple, Optional, Tuple

from .match import Identity, identity


class ArrError(RuntimeError):
    pass


class ArrTrack(NamedTuple):
    track_id: int
    album_id: int
    album: str
    album_type: str
    title: str
    has_file: bool
    file_path: Optional[str]
    duration: float

    @property
    def id(self) -> Identity:
        return identity(self.title)


class ArrArtist(NamedTuple):
    id: int
    name: str
    path: Optional[str]
    tracks: List[ArrTrack]
    files: frozenset


def api_key_from_config(config_path: str) -> str:
    """Read the API key out of a Lidarr ``config.xml``."""
    with open(config_path, encoding="utf-8", errors="ignore") as handle:
        found = re.search(r"<ApiKey>([^<]+)</ApiKey>", handle.read())
    if not found:
        raise ArrError("no <ApiKey> in %s" % config_path)
    return found.group(1)


class Lidarr:
    def __init__(self, url: str, api_key: str,
                 path_map: Optional[Tuple[str, str]] = None,
                 timeout: float = 180.0):
        self.base = url.rstrip("/")
        if not self.base.endswith("/api/v1"):
            self.base += "/api/v1"
        self.api_key = api_key
        self.path_map = path_map
        self.timeout = timeout

    # -- plumbing -----------------------------------------------------------

    def _call(self, path: str, method: str = "GET", body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.base + path, data=data, method=method,
            headers={"X-Api-Key": self.api_key,
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read()
        except urllib.error.HTTPError as exc:
            raise ArrError("%s %s -> HTTP %s" % (method, path, exc.code))
        except urllib.error.URLError as exc:
            raise ArrError("%s %s -> %s" % (method, path, exc.reason))
        return json.loads(raw) if raw else None

    def to_host(self, path: Optional[str]) -> Optional[str]:
        """Translate a path as Lidarr reports it into a path on this host."""
        if not path or not self.path_map:
            return path
        src, dst = self.path_map
        if path.startswith(src):
            return os.path.normpath(dst + path[len(src):])
        return path

    def ping(self) -> str:
        status = self._call("/system/status")
        return (status or {}).get("version", "unknown")

    # -- reading ------------------------------------------------------------

    def artists(self, monitored_only: bool = True,
                only: Optional[str] = None) -> List[dict]:
        rows = self._call("/artist") or []
        if monitored_only:
            rows = [a for a in rows if a.get("monitored")]
        if only:
            needle = only.lower()
            rows = [a for a in rows if needle in a.get("artistName", "").lower()]
        return rows

    def artist_detail(self, artist: dict) -> ArrArtist:
        artist_id = artist["id"]
        files = self._call("/trackfile?artistId=%d" % artist_id) or []
        file_by_id = {f["id"]: self.to_host(f["path"]) for f in files}

        tracks: List[ArrTrack] = []
        for album in self._call("/album?artistId=%d" % artist_id) or []:
            if not album.get("monitored"):
                continue
            stats = album.get("statistics") or {}
            # An album Lidarr has not fetched a tracklist for yet reports zero
            # tracks; treating that as "everything missing" is pure noise.
            if not stats.get("totalTrackCount"):
                continue
            rows = self._call("/track?artistId=%d&albumId=%d"
                              % (artist_id, album["id"])) or []
            for track in rows:
                tracks.append(ArrTrack(
                    track_id=track["id"],
                    album_id=album["id"],
                    album=album.get("title") or "",
                    album_type=album.get("albumType") or "",
                    title=track.get("title") or "",
                    has_file=bool(track.get("hasFile")),
                    file_path=file_by_id.get(track.get("trackFileId")),
                    duration=float(track.get("duration") or 0) / 1000.0))

        return ArrArtist(
            id=artist_id,
            name=artist.get("artistName") or "",
            path=self.to_host(artist.get("path")),
            tracks=tracks,
            files=frozenset(v for v in file_by_id.values() if v))

    # -- writing (only ever called behind --apply) --------------------------

    def set_monitored(self, album_ids: List[int], monitored: bool,
                      chunk: int = 20) -> Tuple[int, List[Tuple[int, str]]]:
        """Monitor or unmonitor albums, in chunks.

        Lidarr answers 500 to a large batch, and one rejected id must not cost
        the rest their change, so a failed chunk is retried one at a time.
        """
        done, failed = 0, []
        for start in range(0, len(album_ids), chunk):
            group = album_ids[start:start + chunk]
            try:
                self._call("/album/monitor", "PUT",
                           {"albumIds": group, "monitored": monitored})
                done += len(group)
            except ArrError:
                for one in group:
                    try:
                        self._call("/album/monitor", "PUT",
                                   {"albumIds": [one], "monitored": monitored})
                        done += 1
                    except ArrError as exc:
                        failed.append((one, str(exc)))
        return done, failed

    def refresh_artist(self, artist_id: int) -> None:
        """Make Lidarr look at the disk again.

        The command is ``RefreshArtist``. There is no ``RescanArtist``, despite
        what the UI wording suggests; sending that returns a 500 with
        "Sequence contains no matching element".
        """
        self._call("/command", "POST",
                   {"name": "RefreshArtist", "artistId": artist_id})
