from __future__ import annotations

import time
from typing import Iterable, Tuple


class ConsumptionEstimator:
    def __init__(self, window_minutes: int = 60, max_events: int = 24):
        self.window_minutes = window_minutes
        self.max_events = max_events

    def rate_mb_per_minute(self, usage_events: Iterable[Tuple[float, float]]) -> float:
        now = time.time()
        window_seconds = self.window_minutes * 60
        total = 0.0
        earliest = None
        count = 0
        for ts, amount in usage_events:
            if now - ts > window_seconds:
                continue
            total += amount
            earliest = ts if earliest is None else min(earliest, ts)
            count += 1
            if count >= self.max_events:
                break
        if total <= 0 or earliest is None:
            return 0.0
        elapsed = max((now - earliest) / 60.0, 1e-6)
        return total / elapsed
