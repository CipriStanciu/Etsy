"""Rate limiting for the Etsy API client.

Etsy's published guidance caps apps at **10 requests per second**; the
Fragrance Bot pipeline additionally enforces a **minimum 150 ms spacing**
between any two requests (well under 10/s, deterministic for the mock
verification). This module combines both:

* a token bucket (capacity = max_qps, refill = max_qps per second) for the
  hard 10 req/s ceiling, and
* a minimum-interval constraint that guarantees >= 150 ms between requests.

``RateLimiter.wait()`` blocks the calling thread until a request is allowed.
It is thread-safe (the client is shared by nothing today, but cheap to make
safe) and intentionally dependent on ``time.monotonic`` only.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

# Hard floor between requests (seconds). Etsy allows ~10 req/s; 150 ms is a
# much tighter spacing chosen by the team so bursts never approach the limit.
DEFAULT_MIN_INTERVAL = 0.15
DEFAULT_MAX_QPS = 10.0


class RateLimiter:
    """Token bucket + minimum-interval pacing for outbound requests."""

    def __init__(
        self,
        min_interval: float = DEFAULT_MIN_INTERVAL,
        max_qps: float = DEFAULT_MAX_QPS,
    ) -> None:
        if min_interval <= 0 or max_qps <= 0:
            raise ValueError("min_interval and max_qps must be positive")
        self._min_interval = float(min_interval)
        self._max_qps = float(max_qps)
        self._tokens = float(max_qps)  # start full
        self._last_wait = 0.0          # monotonic() of last allowed request
        self._lock = threading.Lock()
        self._request_count = 0
        self._last_request_at: Optional[float] = None
        self.recorded_sends: list = []  # wait-completion times (verification)

    # -- public API ---------------------------------------------------------
    def wait(self) -> None:
        """Block until the next request may be sent (spacing + bucket)."""
        with self._lock:
            now = time.monotonic()
            sleep_needed = 0.0

            # minimum spacing between requests
            gap = now - self._last_wait if self._last_wait else self._min_interval
            if gap < self._min_interval:
                sleep_needed = self._min_interval - gap

            # token bucket: refill since the last call, then check for a token
            self._tokens = min(
                self._max_qps, self._tokens + (now - self._last_wait) * self._max_qps
            )
            if self._tokens < 1.0:
                bucket_sleep = (1.0 - self._tokens) / self._max_qps
                sleep_needed = max(sleep_needed, bucket_sleep)

            if sleep_needed > 0.0:
                time.sleep(sleep_needed)
                now = time.monotonic()
                self._tokens = min(
                    self._max_qps,
                    self._tokens + sleep_needed * self._max_qps,
                )

            self._tokens -= 1.0
            self._last_wait = now
            self._request_count += 1
            self._last_request_at = now
            self.recorded_sends.append(now)

    # -- observability (tests / logging) ------------------------------------
    @property
    def request_count(self) -> int:
        with self._lock:
            return self._request_count

    @property
    def min_interval(self) -> float:
        return self._min_interval

    @property
    def last_request_at(self) -> Optional[float]:
        with self._lock:
            return self._last_request_at