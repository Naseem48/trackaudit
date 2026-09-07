"""What an artist actually released, from a public catalogue.

Self-hosted music tools measure completeness against MusicBrainz, because that
is what Lidarr indexes. For a great deal of music - German rap, Turkish pop,
Afrobeats, most things not sung in English - MusicBrainz is badly incomplete,
so the library reports itself complete while whole releases are missing. Not
missing: *invisible*, because a tool cannot show you a gap it does not know is
there.

Deezer's public API is the yardstick used here. It carries the commercial
catalogue, needs no key, no account and no signup, and can therefore be used by
anyone who installs this without asking them to register for anything.

Providers are small enough to add: implement :class:`Catalogue`.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, Iterable, List, NamedTuple, Optional

from .match import identity, normalize

USER_AGENT = "trackaudit (+https://github.com/Naseem48/trackaudit)"


class Recording(NamedTuple):
    """One released recording, as the catalogue describes it."""

    title: str
    release: str
    year: str
    duration: float = 0.0

    @property
    def id(self):
        return identity(self.title)


class Artist(NamedTuple):
    id: str
    name: str
    followers: int = 0


class CatalogueError(RuntimeError):
    pass


class Catalogue:
    """Interface a catalogue provider must implement."""

    name = "catalogue"

    def find_artist(self, name: str) -> Optional[Artist]:
        raise NotImplementedError

    def recordings(self, artist: Artist) -> List[Recording]:
        raise NotImplementedError


class Deezer(Catalogue):
    """Deezer's public API. No credentials, rate-limited politely."""

    name = "deezer"
    BASE = "https://api.deezer.com"

    def __init__(self, delay: float = 0.12, retries: int = 4,
                 timeout: float = 30.0, overrides: Optional[Dict] = None):
        self.delay = delay
        self.retries = retries
        self.timeout = timeout
        # Artist ids confirmed by hand, so an upstream rename can never
        # silently swap one artist for another with a similar name.
        self.overrides = dict(overrides or {})
        self._last = 0.0

    def _get(self, path: str) -> dict:
        for attempt in range(self.retries):
            gap = self.delay - (time.monotonic() - self._last)
            if gap > 0:
                time.sleep(gap)
            self._last = time.monotonic()
            req = urllib.request.Request(self.BASE + path,
                                         headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    payload = json.loads(r.read().decode("utf-8"))
            except (urllib.error.URLError, ValueError, OSError) as exc:
                if attempt == self.retries - 1:
                    raise CatalogueError("deezer %s: %s" % (path, exc))
                time.sleep(1.5 * (attempt + 1))
                continue
            # Deezer signals quota exhaustion in the body, with HTTP 200.
            if isinstance(payload, dict) and payload.get("error"):
                code = (payload["error"] or {}).get("code")
                if code in (4, "4"):            # too many requests
                    time.sleep(2.0 * (attempt + 1))
                    continue
                raise CatalogueError("deezer %s: %s" % (path, payload["error"]))
            return payload
        raise CatalogueError("deezer %s: gave up after %d tries"
                             % (path, self.retries))

    def find_artist(self, name: str) -> Optional[Artist]:
        """Resolve a name to an artist.

        An exact name match wins; among equally exact matches the one with the
        larger following wins. A search for a common stage name returns several
        unrelated acts, and follower count separates them reliably.
        """
        if name in self.overrides:
            return Artist(str(self.overrides[name]), name, 0)
        query = urllib.parse.quote(name)
        payload = self._get("/search/artist?q=%s&limit=10" % query)
        best, best_score = None, -1
        for row in payload.get("data", []):
            exact = normalize(row.get("name", "")) == normalize(name)
            score = (1_000_000 if exact else 0) + int(row.get("nb_fan") or 0)
            if score > best_score:
                best, best_score = row, score
        if not best:
            return None
        return Artist(str(best["id"]), best.get("name", name),
                      int(best.get("nb_fan") or 0))

    def _albums(self, artist: Artist) -> Iterable[dict]:
        url = "/artist/%s/albums?limit=100" % artist.id
        while url:
            payload = self._get(url)
            for album in payload.get("data", []):
                yield album
            nxt = payload.get("next")
            url = nxt.replace(self.BASE, "") if nxt else None

    def recordings(self, artist: Artist) -> List[Recording]:
        """Every distinct recording the catalogue lists for this artist.

        Deduplicated by recording identity, because the same track appears on
        the album, the deluxe edition and a compilation, and counting it three
        times would overstate what is missing.
        """
        out: List[Recording] = []
        seen = set()
        for album in self._albums(artist):
            detail = self._get("/album/%s" % album["id"])
            for track in (detail.get("tracks") or {}).get("data", []):
                title = track.get("title") or ""
                key = identity(title)
                if not key or key in seen:
                    continue
                seen.add(key)
                out.append(Recording(
                    title=title,
                    release=album.get("title") or detail.get("title") or "",
                    year=(album.get("release_date")
                          or detail.get("release_date") or "")[:4],
                    duration=float(track.get("duration") or 0.0)))
        return out


PROVIDERS = {"deezer": Deezer}


def get(name: str = "deezer", **kwargs) -> Catalogue:
    try:
        return PROVIDERS[name](**kwargs)
    except KeyError:
        raise CatalogueError("unknown catalogue provider: %s (have: %s)"
                             % (name, ", ".join(sorted(PROVIDERS))))
