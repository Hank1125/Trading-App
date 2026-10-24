"""Read-only client for the Liquipedia Rainbow Six MediaWiki API.

Follows https://liquipedia.net/api-terms-of-use: a descriptive User-Agent with contact
info, gzip, one reused HTTP connection, at most one request per `min_interval` seconds
(>= 2 s), and no `action=parse`. Wikitext is only fetched when a page's revision changed.
"""

import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

import httpx

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class LiquipediaError(Exception):
    pass


@dataclass(frozen=True)
class Revision:
    title: str
    revid: int
    timestamp: str


@dataclass(frozen=True)
class Page:
    title: str
    revid: int
    timestamp: str
    wikitext: str


class RateLimiter:
    """Blocks so that consecutive acquire() calls are at least `min_interval` seconds apart."""

    def __init__(
        self,
        min_interval: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None
        self._lock = threading.Lock()

    def acquire(self, extra_delay: float = 0.0) -> None:
        with self._lock:
            if self._last is not None:
                wait = self._last + self.min_interval - self._clock()
                wait = max(wait, extra_delay)
                if wait > 0:
                    self._sleep(wait)
            elif extra_delay > 0:
                self._sleep(extra_delay)
            self._last = self._clock()


class LiquipediaClient:
    def __init__(
        self,
        api_url: str,
        user_agent: str,
        limiter: RateLimiter,
        transport: httpx.BaseTransport | None = None,
        max_retries: int = 3,
        timeout: float = 20.0,
    ) -> None:
        self._api_url = api_url
        self._limiter = limiter
        self._max_retries = max_retries
        self._http = httpx.Client(
            headers={"User-Agent": user_agent, "Accept-Encoding": "gzip"},
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def _get(self, params: dict[str, str]) -> dict[str, Any]:
        params = {**params, "format": "json", "formatversion": "2"}
        delay = 0.0
        for attempt in range(self._max_retries + 1):
            self._limiter.acquire(extra_delay=delay)
            try:
                resp = self._http.get(self._api_url, params=params)
            except httpx.TransportError as e:
                if attempt == self._max_retries:
                    raise LiquipediaError(f"network error: {type(e).__name__}") from None
                delay = 2.0 ** (attempt + 1)
                continue
            if resp.status_code in RETRYABLE_STATUS and attempt < self._max_retries:
                delay = _retry_after(resp) or 2.0 ** (attempt + 1)
                continue
            if resp.status_code != 200:
                raise LiquipediaError(f"HTTP {resp.status_code}")
            data: dict[str, Any] = resp.json()
            if "error" in data:
                raise LiquipediaError(f"API error: {data['error'].get('code', 'unknown')}")
            return data
        raise LiquipediaError("retries exhausted")  # pragma: no cover - loop always returns or raises

    def get_revisions(self, titles: Iterable[str]) -> dict[str, Revision | None]:
        """Latest revision per requested title (None if the page doesn't exist). One request per 50 titles."""
        titles = list(titles)
        out: dict[str, Revision | None] = {}
        for i in range(0, len(titles), 50):
            batch = titles[i : i + 50]
            data = self._get(
                {
                    "action": "query",
                    "prop": "revisions",
                    "rvprop": "ids|timestamp",
                    "titles": "|".join(batch),
                }
            )
            out.update(_map_pages(batch, data, lambda p: _revision(p)))
        return out

    def get_page(self, title: str) -> Page:
        data = self._get(
            {
                "action": "query",
                "prop": "revisions",
                "rvprop": "ids|timestamp|content",
                "rvslots": "main",
                "titles": title,
            }
        )
        page = _map_pages([title], data, _page)[title]
        if page is None:
            raise LiquipediaError(f"page not found: {title}")
        return page


def _retry_after(resp: httpx.Response) -> float | None:
    value = resp.headers.get("Retry-After", "")
    return float(value) if value.isdigit() else None


def _revision(p: dict[str, Any]) -> Revision:
    rev = p["revisions"][0]
    return Revision(title=p["title"], revid=int(rev["revid"]), timestamp=rev["timestamp"])


def _page(p: dict[str, Any]) -> Page:
    rev = p["revisions"][0]
    return Page(
        title=p["title"],
        revid=int(rev["revid"]),
        timestamp=rev["timestamp"],
        wikitext=rev["slots"]["main"]["content"],
    )


def _map_pages[T](
    requested: list[str], data: dict[str, Any], build: Callable[[dict[str, Any]], T]
) -> dict[str, T | None]:
    """Map API pages back to the titles the caller asked for, following MediaWiki title normalization."""
    query = data.get("query", {})
    normalized = {n["from"]: n["to"] for n in query.get("normalized", [])}
    by_title = {p["title"]: p for p in query.get("pages", [])}
    out: dict[str, T | None] = {}
    for title in requested:
        p = by_title.get(normalized.get(title, title))
        out[title] = None if p is None or p.get("missing") or "revisions" not in p else build(p)
    return out


_shared_limiter: RateLimiter | None = None


def client_from_settings() -> LiquipediaClient:
    """Client using the configured endpoint/User-Agent and one process-wide rate limiter."""
    from app.config import get_settings

    global _shared_limiter
    s = get_settings()
    _shared_limiter = _shared_limiter or RateLimiter(s.liquipedia_min_interval_seconds)
    return LiquipediaClient(s.liquipedia_api_url, s.liquipedia_user_agent, _shared_limiter)
