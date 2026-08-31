"""The guard on the only endpoint that spends money."""

import pytest

from app.limits import MAX_TRACKED_KEYS, RateLimiter


def test_requests_under_the_limit_are_allowed() -> None:
    limiter = RateLimiter(limit=3, window_seconds=60)

    assert [limiter.check("a", now=0)[0] for _ in range(3)] == [True, True, True]


def test_the_limit_is_enforced() -> None:
    limiter = RateLimiter(limit=2, window_seconds=60)
    limiter.check("a", now=0)
    limiter.check("a", now=1)

    allowed, retry_after = limiter.check("a", now=2)

    assert allowed is False
    assert 0 < retry_after <= 60


def test_clients_are_counted_separately() -> None:
    """One reviewer exhausting their budget must not lock out the next."""
    limiter = RateLimiter(limit=1, window_seconds=60)
    limiter.check("a", now=0)

    assert limiter.check("b", now=0)[0] is True


def test_the_window_slides() -> None:
    limiter = RateLimiter(limit=1, window_seconds=10)
    limiter.check("a", now=0)

    assert limiter.check("a", now=5)[0] is False
    assert limiter.check("a", now=11)[0] is True


def test_tracked_keys_are_bounded() -> None:
    """A stream of distinct spoofed keys must not grow the map without limit."""
    limiter = RateLimiter(limit=1, window_seconds=10)

    for index in range(MAX_TRACKED_KEYS + 500):
        limiter.check(f"key-{index}", now=float(index))

    assert len(limiter._hits) <= MAX_TRACKED_KEYS + 1


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"x-forwarded-for": "203.0.113.7"}, "203.0.113.7"),
        ({"x-forwarded-for": "203.0.113.7, 10.0.0.1"}, "203.0.113.7"),
        ({}, "testclient"),
    ],
)
def test_the_client_key_prefers_the_forwarded_address(headers, expected) -> None:
    from fastapi import APIRouter, FastAPI, Request
    from fastapi.testclient import TestClient

    from app.limits import client_key

    app = FastAPI()
    router = APIRouter()

    @router.get("/whoami")
    def whoami(request: Request) -> dict:
        return {"key": client_key(request)}

    app.include_router(router)

    response = TestClient(app).get("/whoami", headers=headers)

    assert response.json()["key"] == expected
