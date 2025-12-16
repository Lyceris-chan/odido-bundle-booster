from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from typing import Optional


DEFAULT_API_KEY = os.getenv("API_KEY") or os.getenv("ODIDO_API_KEY")
DEFAULT_BUNDLE_CODE = "A0DAY01"


@dataclass
class AppConfig:
    api_key: Optional[str] = DEFAULT_API_KEY or "changeme"
    bundle_size_mb: float = 1024.0
    absolute_min_threshold_mb: float = 100.0
    estimator_window_minutes: int = 60
    estimator_max_events: int = 24
    min_check_interval_minutes: int = 1
    max_check_interval_minutes: int = 60
    lead_time_minutes: int = 30
    auto_renew_enabled: bool = True
    default_bundle_valid_hours: int = 24 * 30
    log_level: str = "INFO"
    # Odido API integration settings
    bundle_code: str = DEFAULT_BUNDLE_CODE
    odido_user_id: Optional[str] = None
    odido_token: Optional[str] = None
    use_real_odido_api: bool = False

    def update_from_dict(self, data: dict) -> None:
        for key, value in data.items():
            if not hasattr(self, key):
                continue
            if key in {"api_key", "log_level", "bundle_code", "odido_user_id", "odido_token"}:
                setattr(self, key, str(value) if value is not None else None)
            elif key in {
                "bundle_size_mb",
                "absolute_min_threshold_mb",
                "lead_time_minutes",
                "min_check_interval_minutes",
                "max_check_interval_minutes",
                "estimator_window_minutes",
                "estimator_max_events",
                "default_bundle_valid_hours",
            }:
                setattr(self, key, float(value) if "mb" in key else int(value))
            elif key in {"auto_renew_enabled", "use_real_odido_api"}:
                setattr(self, key, bool(value))

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AppConfig":
        obj = cls()
        obj.update_from_dict(data)
        return obj


@dataclass
class BundleState:
    remaining_mb: float = 0.0
    used_today_mb: float = 0.0
    total_used_mb: float = 0.0
    expiry_ts: Optional[float] = None
    next_check_ts: Optional[float] = None
    next_reset_ts: Optional[float] = None
    estimated_depletion_ts: Optional[float] = None
    last_check_ts: Optional[float] = None

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "BundleState":
        state = cls()
        for key, value in data.items():
            if hasattr(state, key):
                setattr(state, key, value)
        return state


def load_initial_config() -> AppConfig:
    return AppConfig()
