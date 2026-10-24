import httpx
import pytest

from app.siege.liquipedia import LiquipediaClient, LiquipediaError, RateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.sleeps.append(s)
        self.now += s


def make_client(handler, clock: FakeClock, **kw) -> tuple[LiquipediaClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        req.extensions["sent_at"] = clock.now
        return handler(req)

    limiter = RateLimiter(2.0, clock=clock, sleep=clock.sleep)
    client = LiquipediaClient(
        "https://liquipedia.net/rainbowsix/api.php",
        "TestApp/0.1 (https://example.com; test@example.com)",
        limiter,
        transport=httpx.MockTransport(record),
        **kw,
    )
    return client, seen


def revisions_payload(*pages, normalized=()):
    return {"query": {"normalized": list(normalized), "pages": list(pages)}}


def page(title, revid, content=None):
    rev = {"revid": revid, "timestamp": "2026-10-24T15:05:34Z"}
    if content is not None:
        rev["slots"] = {"main": {"content": content}}
    return {"title": title, "revisions": [rev]}


def test_requests_are_spaced_at_least_two_seconds_apart():
    clock = FakeClock()
    client, seen = make_client(lambda r: httpx.Response(200, json=revisions_payload(page("A", 1))), clock)
    for _ in range(4):
        client.get_revisions(["A"])
    times = [r.extensions["sent_at"] for r in seen]
    assert all(b - a >= 2.0 for a, b in zip(times, times[1:], strict=False))


def test_sends_identifying_user_agent_and_gzip():
    clock = FakeClock()
    client, seen = make_client(lambda r: httpx.Response(200, json=revisions_payload(page("A", 1))), clock)
    client.get_revisions(["A"])
    assert "test@example.com" in seen[0].headers["User-Agent"]
    assert "gzip" in seen[0].headers["Accept-Encoding"]
    assert seen[0].url.params["action"] == "query"  # never action=parse


def test_revisions_follow_title_normalization_and_report_missing_pages():
    clock = FakeClock()
    payload = revisions_payload(
        page("BLAST Major/2026/May", 894678),
        {"title": "Nope", "missing": True},
        normalized=[{"from": "BLAST_Major/2026/May", "to": "BLAST Major/2026/May"}],
    )
    client, _ = make_client(lambda r: httpx.Response(200, json=payload), clock)
    revs = client.get_revisions(["BLAST_Major/2026/May", "Nope"])
    assert revs["BLAST_Major/2026/May"] is not None
    assert revs["BLAST_Major/2026/May"].revid == 894678
    assert revs["Nope"] is None


def test_get_page_returns_wikitext():
    clock = FakeClock()
    payload = revisions_payload(page("P", 7, content="{{Match|finished=true}}"))
    client, _ = make_client(lambda r: httpx.Response(200, json=payload), clock)
    p = client.get_page("P")
    assert (p.revid, p.wikitext) == (7, "{{Match|finished=true}}")


def test_429_waits_for_retry_after_then_succeeds():
    clock = FakeClock()
    responses = iter(
        [
            httpx.Response(429, headers={"Retry-After": "30"}),
            httpx.Response(200, json=revisions_payload(page("A", 1))),
        ]
    )
    client, seen = make_client(lambda r: next(responses), clock)
    assert client.get_revisions(["A"])["A"] is not None
    assert len(seen) == 2
    assert seen[1].extensions["sent_at"] - seen[0].extensions["sent_at"] >= 30


def test_gives_up_after_max_retries():
    clock = FakeClock()
    client, seen = make_client(lambda r: httpx.Response(503), clock, max_retries=2)
    with pytest.raises(LiquipediaError, match="503"):
        client.get_revisions(["A"])
    assert len(seen) == 3


def test_api_error_and_client_errors_are_not_retried():
    clock = FakeClock()
    client, seen = make_client(lambda r: httpx.Response(200, json={"error": {"code": "badvalue"}}), clock)
    with pytest.raises(LiquipediaError, match="badvalue"):
        client.get_revisions(["A"])
    client2, seen2 = make_client(lambda r: httpx.Response(403), clock)
    with pytest.raises(LiquipediaError, match="403"):
        client2.get_revisions(["A"])
    assert len(seen) == 1 and len(seen2) == 1
