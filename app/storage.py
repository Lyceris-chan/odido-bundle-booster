from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import List, Tuple

from .config import AppConfig, BundleState, load_initial_config

DB_PATH = os.getenv("APP_DB_PATH", "/data/odido.db")


class Storage:
    def __init__(self, db_path: str = DB_PATH) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        Path(os.path.dirname(db_path)).mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS kv (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS usage_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    amount_mb REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS idempotency (
                    key TEXT PRIMARY KEY,
                    created_ts REAL NOT NULL,
                    note TEXT
                )
                """
            )
            conn.commit()
        if self._load_raw("config") is None:
            self.save_config(load_initial_config())
        if self._load_raw("state") is None:
            self.save_state(BundleState())

    @contextmanager
    def _connect(self):
        with self._lock:
            conn = sqlite3.connect(self.db_path, timeout=30)
            try:
                yield conn
            finally:
                conn.close()

    def _load_raw(self, key: str):
        with self._connect() as conn:
            cur = conn.execute("SELECT value FROM kv WHERE key=?", (key,))
            row = cur.fetchone()
            return json.loads(row[0]) if row else None

    def _save_raw(self, key: str, value: dict) -> None:
        payload = json.dumps(value)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, payload),
            )
            conn.commit()

    def load_config(self) -> AppConfig:
        data = self._load_raw("config")
        if data is None:
            return load_initial_config()
        return AppConfig.from_dict(data)

    def save_config(self, config: AppConfig) -> None:
        self._save_raw("config", config.as_dict())

    def load_state(self) -> BundleState:
        data = self._load_raw("state")
        if data is None:
            return BundleState()
        return BundleState.from_dict(data)

    def save_state(self, state: BundleState) -> None:
        self._save_raw("state", state.as_dict())

    def record_usage(self, ts: float, amount: float) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO usage_events(ts, amount_mb) VALUES(?, ?)",
                (ts, amount),
            )
            conn.commit()

    def recent_usage(self, since_ts: float) -> List[Tuple[float, float]]:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT ts, amount_mb FROM usage_events WHERE ts >= ? ORDER BY ts DESC",
                (since_ts,),
            )
            return cur.fetchall()

    def recent_usage_by_limit(self, limit: int) -> List[Tuple[float, float]]:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT ts, amount_mb FROM usage_events ORDER BY ts DESC LIMIT ?",
                (limit,),
            )
            return cur.fetchall()

    def append_log(self, ts: float, level: str, message: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO logs(ts, level, message) VALUES(?, ?, ?)",
                (ts, level, message),
            )
            conn.commit()

    def recent_logs(self, limit: int = 200) -> List[Tuple[float, str, str]]:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT ts, level, message FROM logs ORDER BY ts DESC LIMIT ?",
                (limit,),
            )
            return cur.fetchall()

    def register_idempotency(self, key: str, note: str, ts: float) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO idempotency(key, created_ts, note) VALUES(?, ?, ?)",
                (key, ts, note),
            )
            conn.commit()

    def has_idempotency(self, key: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("SELECT 1 FROM idempotency WHERE key=?", (key,))
            return cur.fetchone() is not None
