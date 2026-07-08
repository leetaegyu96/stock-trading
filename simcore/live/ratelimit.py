"""동기 토큰버킷 레이트리미터."""
from __future__ import annotations
import time
from typing import Callable


class RateLimiter:
    def __init__(self, rate_per_sec: float,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.capacity = max(1.0, rate_per_sec)
        self.rate = rate_per_sec
        self.tokens = self.capacity
        self.clock = clock
        self.sleep = sleep
        self.last = clock()

    def acquire(self) -> None:
        while True:
            now = self.clock()
            self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.rate)
            self.last = now
            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return
            self.sleep((1.0 - self.tokens) / self.rate)
