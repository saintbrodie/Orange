import threading
import time
from collections import defaultdict, deque


class SlidingWindowRateLimiter:
    """Small in-process limiter suitable for Orange's LAN-facing helper endpoints."""

    def __init__(self):
        self._events = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_seconds: float = 60.0) -> bool:
        if limit <= 0:
            return True
        now = time.monotonic()
        cutoff = now - max(1.0, float(window_seconds))
        bucket_key = str(key or "unknown")
        with self._lock:
            bucket = self._events[bucket_key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                return False
            bucket.append(now)

            # Opportunistic cleanup prevents a long-lived server from retaining
            # keys for clients that disappeared months ago.
            if len(self._events) > 2048:
                stale = [name for name, values in self._events.items() if not values or values[-1] <= cutoff]
                for name in stale[:512]:
                    self._events.pop(name, None)
            return True

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
