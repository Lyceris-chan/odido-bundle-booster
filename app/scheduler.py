from __future__ import annotations

import threading
import time
from typing import Optional

from .service import BundleService


class Scheduler:
    def __init__(self, service: BundleService) -> None:
        self.service = service
        self.thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self.thread:
            self.thread.join(timeout=5)

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            result = self.service.run_check_cycle()
            sleep_seconds = result["next_interval_minutes"] * 60
            reset_ts = self.service.state.next_reset_ts
            now = time.time()
            if reset_ts:
                until_reset = max(reset_ts - now, 0)
                sleep_seconds = min(sleep_seconds, until_reset)
            self._stop.wait(timeout=sleep_seconds)
