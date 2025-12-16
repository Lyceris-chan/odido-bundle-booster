from __future__ import annotations

import logging
import os
import time
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from .config import AppConfig, BundleState
from .estimator import ConsumptionEstimator
from .storage import Storage

logger = logging.getLogger("odido.service")


class BundleService:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage
        self.config = storage.load_config()
        self.state = storage.load_state()
        self.estimator = ConsumptionEstimator(
            window_minutes=self.config.estimator_window_minutes,
            max_events=self.config.estimator_max_events,
        )
        self._lock = threading.Lock()
        self._ensure_reset_schedule()
        self._log("INFO", "Service initialized")

    def _log(self, level: str, message: str) -> None:
        ts = time.time()
        self.storage.append_log(ts, level, message)
        getattr(logger, level.lower(), logger.info)(message)

    def _ensure_reset_schedule(self) -> None:
        if not self.state.next_reset_ts:
            self.state.next_reset_ts = self._next_midnight_ts()
            self.storage.save_state(self.state)

    @staticmethod
    def _next_midnight_ts() -> float:
        now = datetime.now()
        tomorrow = now.date() + timedelta(days=1)
        midnight = datetime.combine(tomorrow, datetime.min.time())
        return midnight.timestamp()

    def update_config(self, data: dict) -> AppConfig:
        with self._lock:
            self.config.update_from_dict(data)
            self.storage.save_config(self.config)
            self.estimator = ConsumptionEstimator(
                window_minutes=self.config.estimator_window_minutes,
                max_events=self.config.estimator_max_events,
            )
            self._log("INFO", "Configuration updated")
            return self.config

    def _apply_daily_reset_if_needed(self) -> None:
        now_ts = time.time()
        if self.state.next_reset_ts and now_ts >= self.state.next_reset_ts:
            self.state.used_today_mb = 0.0
            self.state.next_reset_ts = self._next_midnight_ts()
            self.storage.save_state(self.state)
            self._log("INFO", "Daily usage reset")

    def simulate_usage(self, amount_mb: float, ts: Optional[float] = None) -> BundleState:
        ts = ts or time.time()
        with self._lock:
            self._apply_daily_reset_if_needed()
            self.state.used_today_mb += amount_mb
            self.state.total_used_mb += amount_mb
            self.state.remaining_mb = max(self.state.remaining_mb - amount_mb, 0.0)
            self.storage.record_usage(ts, amount_mb)
            self.storage.save_state(self.state)
            self._log("INFO", f"Usage recorded: {amount_mb} MB")
            return self.state

    def manual_add_bundle(self, amount_mb: Optional[float], idempotency_key: Optional[str]) -> BundleState:
        amount = amount_mb if amount_mb is not None else self.config.bundle_size_mb
        key = idempotency_key or f"manual-{int(time.time())}-{amount}"
        with self._lock:
            if self.storage.has_idempotency(key):
                self._log("INFO", f"Idempotent add ignored for key {key}")
                return self.state
            self.storage.register_idempotency(key, "manual_add", time.time())
            self._add_bundle(amount)
            self._log("INFO", f"Bundle added manually: {amount} MB")
            return self.state

    def _add_bundle(self, amount: float) -> None:
        self.state.remaining_mb += amount
        if not self.state.expiry_ts:
            self.state.expiry_ts = (datetime.now() + timedelta(hours=self.config.default_bundle_valid_hours)).timestamp()
        self.storage.save_state(self.state)

    def _get_odido_api(self):
        """Create an Odido API client using configured credentials."""
        from .odido_api import OdidoAPI
        return OdidoAPI(
            user_id=self.config.odido_user_id or os.getenv("ODIDO_USER_ID"),
            access_token=self.config.odido_token or os.getenv("ODIDO_TOKEN"),
        )

    def _renew_with_real_api(self) -> bool:
        """Attempt to renew bundle using the real Odido API."""
        from .odido_api import OdidoAPIError, OdidoAuthError
        
        api = self._get_odido_api()
        if not api.is_configured:
            self._log("ERROR", "Odido API not configured - auto-renewal disabled. Set ODIDO_USER_ID and ODIDO_TOKEN environment variables")
            return False
        
        try:
            buying_code = self.config.bundle_code
            result = api.buy_bundle(buying_code=buying_code)
            if result.get("success"):
                self._log("INFO", f"Bundle purchased via Odido API with code: {buying_code}")
                # Update local state with the configured bundle size
                self._add_bundle(self.config.bundle_size_mb)
                return True
            else:
                self._log("WARNING", f"Odido API purchase returned unexpected result: {result}")
                return False
        except OdidoAuthError as e:
            self._log("ERROR", f"Odido API authentication failed: {e}")
            return False
        except OdidoAPIError as e:
            self._log("ERROR", f"Odido API error: {e}")
            return False
        except Exception as e:
            self._log("ERROR", f"Unexpected error during Odido API renewal: {e}")
            return False

    def _renew_with_retry(self) -> None:
        """
        Attempt to renew bundle via the Odido API with up to 3 retries using exponential backoff.
        
        Returns without action if all attempts fail. Check logs for error details.
        """
        retries = 3
        backoff = 2
        
        for attempt in range(retries):
            try:
                if self._renew_with_real_api():
                    return
            except Exception as exc:  # pragma: no cover
                self._log("ERROR", f"Renewal attempt {attempt+1} failed: {exc}")
            
            if attempt < retries - 1:
                time.sleep(backoff ** attempt)
        
        self._log("ERROR", "All renewal attempts failed - check Odido API credentials and network connectivity")

    def compute_consumption_rate(self) -> float:
        window_start = time.time() - (self.config.estimator_window_minutes * 60)
        usage_events = self.storage.recent_usage(window_start)
        return self.estimator.rate_mb_per_minute(usage_events)

    def estimated_time_to_depletion_minutes(self, rate: float) -> Optional[float]:
        if rate <= 0:
            return None
        return self.state.remaining_mb / rate

    def compute_next_check_minutes(self, rate: float) -> float:
        if rate <= 0:
            return float(self.config.max_check_interval_minutes)
        eta = self.estimated_time_to_depletion_minutes(rate)
        if eta is None:
            return float(self.config.max_check_interval_minutes)
        interval = eta / 4
        interval = max(float(self.config.min_check_interval_minutes), interval)
        interval = min(float(self.config.max_check_interval_minutes), interval)
        return interval

    def should_auto_renew(self, rate: float) -> bool:
        if not self.config.auto_renew_enabled:
            return False
        eta = self.estimated_time_to_depletion_minutes(rate)
        if self.state.remaining_mb <= self.config.absolute_min_threshold_mb:
            return True
        if eta is not None and eta <= self.config.lead_time_minutes:
            return True
        return False

    def run_check_cycle(self) -> Dict[str, Any]:
        with self._lock:
            self._apply_daily_reset_if_needed()
            rate = self.compute_consumption_rate()
            eta = self.estimated_time_to_depletion_minutes(rate)
            if self.should_auto_renew(rate):
                self._renew_with_retry()
            next_interval_minutes = self.compute_next_check_minutes(rate)
            next_check_ts = time.time() + (next_interval_minutes * 60)
            self.state.last_check_ts = time.time()
            self.state.next_check_ts = next_check_ts
            self.state.estimated_depletion_ts = (time.time() + eta * 60) if eta else None
            self.storage.save_state(self.state)
            self._log("DEBUG", f"Check completed. Rate={rate:.3f} MB/min interval={next_interval_minutes} minutes")
            return {
                "rate": rate,
                "eta_minutes": eta,
                "next_interval_minutes": next_interval_minutes,
            }

    def status(self) -> Dict[str, Any]:
        rate = self.compute_consumption_rate()
        eta = self.estimated_time_to_depletion_minutes(rate)
        return {
            "config": self.config.as_dict(),
            "state": self.state.as_dict(),
            "consumption_rate_mb_per_min": rate,
            "estimated_time_to_depletion_minutes": eta,
            "logs": self.logs(limit=20),
        }

    def logs(self, limit: int = 100):
        log_rows = self.storage.recent_logs(limit)
        return [
            {"ts": ts, "level": level, "message": message}
            for ts, level, message in log_rows
        ]

