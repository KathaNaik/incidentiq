"""A conservative guard on the one endpoint that costs money.

The deployment is public and `POST /incidents/{id}/investigations` is the only route that
calls a paid model. Without a limit, a script can spend real money in a loop.

This is deliberately the smallest thing that works, and it is worth being honest about
what it is and is not:

- **In-process.** Vercel runs several instances, so the effective limit is the configured
  one multiplied by however many instances are live. It is a brake on casual abuse, not
  a quota. A correct distributed limit needs shared state, and standing up Redis to rate
  limit a portfolio demo would cost more than the thing it protects.
- **Keyed on the forwarded client address**, which is spoofable. Again: a brake.
- **Memory-bounded.** Old windows are evicted on write, so a stream of distinct keys
  cannot grow the map without limit.

Everything expensive that follows this check is already gated by something stronger:
investigations are one bounded call, actions require explicit human approval, and
execution is simulated.
"""

import threading
import time
from collections import deque
from dataclasses import dataclass, field

from fastapi import HTTPException, Request, status

#: Beyond this many distinct keys, the oldest idle ones are dropped. Sized well above any
#: plausible reviewer traffic and well below anything that would matter for memory.
MAX_TRACKED_KEYS = 4096


@dataclass
class RateLimiter:
    """A fixed-window counter per key."""

    limit: int
    window_seconds: int
    _hits: dict[str, deque[float]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def check(self, key: str, now: float | None = None) -> tuple[bool, int]:
        """Records an attempt. Returns (allowed, seconds until retry)."""
        now = time.monotonic() if now is None else now
        cutoff = now - self.window_seconds

        with self._lock:
            self._evict(cutoff)
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= cutoff:
                hits.popleft()

            if len(hits) >= self.limit:
                return False, max(1, int(hits[0] + self.window_seconds - now))

            hits.append(now)
            return True, 0

    def _evict(self, cutoff: float) -> None:
        if len(self._hits) <= MAX_TRACKED_KEYS:
            return
        stale = [key for key, hits in self._hits.items() if not hits or hits[-1] <= cutoff]
        for key in stale:
            del self._hits[key]


def client_key(request: Request) -> str:
    """Best available identity for an anonymous caller.

    `x-forwarded-for` is set by the platform's proxy; its first entry is the client. It
    can be forged, which is why this is a brake rather than an authorization boundary —
    the honest name for what it does.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def enforce(limiter: RateLimiter, request: Request, what: str) -> None:
    """Raises 429 with a Retry-After when the caller is over the limit."""
    allowed, retry_after = limiter.check(client_key(request))
    if allowed:
        return
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=(
            f"Too many {what} from this client. This is a public demo with a "
            f"conservative limit so that anyone can try it. Try again in "
            f"{retry_after} seconds."
        ),
        headers={"Retry-After": str(retry_after)},
    )
