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
        self._last_sync_ts: Optional[float] = None

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
        first_cycle = True
        while not self._stop.is_set():
            now = time.time()
            should_sync = (
                first_cycle
                or self.service.state.remaining_mb == 0
                or self._last_sync_ts is None
                or (now - self._last_sync_ts) >= 300
            )
            if should_sync:
                self._sync_remaining_from_api()
                first_cycle = False

            result = self.service.run_check_cycle()
            sleep_seconds = result["next_interval_minutes"] * 60
            reset_ts = self.service.state.next_reset_ts
            now = time.time()
            if reset_ts:
                until_reset = max(reset_ts - now, 0)
                sleep_seconds = min(sleep_seconds, until_reset)
            self._stop.wait(timeout=sleep_seconds)

    def _sync_remaining_from_api(self) -> None:
        try:
            api = self.service._get_odido_api()
        except Exception as exc:  # pragma: no cover - defensive logging
            self.service._log(
                "ERROR", f"Failed to initialize Odido API client for sync: {exc}"
            )
            self._last_sync_ts = time.time()
            return

        if not api.is_configured:
            self.service._log(
                "INFO", "Odido API not configured - skipping remaining data sync"
            )
            self._last_sync_ts = time.time()
            return

        try:
            remaining_mb = api.get_remaining_data_mb()
            with self.service._lock:
                self.service.state.remaining_mb = remaining_mb
                self.service.storage.save_state(self.service.state)
            self.service._log(
                "INFO", f"Synced remaining data from Odido API: {remaining_mb} MB"
            )
        except Exception as exc:  # pragma: no cover - best effort sync
            self.service._log(
                "ERROR", f"Failed to sync remaining data from Odido API: {exc}"
            )
        finally:
            self._last_sync_ts = time.time()
