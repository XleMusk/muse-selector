"""SQLite persistence and read-only watch tasks for the MVP.

The store keeps normalized run payloads and watch specifications. It never
stores credentials and never exposes an external write operation.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .pipeline import run_search


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def run_id_for_payload(payload: Mapping[str, Any]) -> str:
    """Derive an idempotent run id from the complete read-only result."""

    digest = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()[:32]
    return f"run_{digest}"


def _watch_stable_value(value: Any, key: str | None = None) -> Any:
    """Normalize volatile observation clocks before comparing watch results."""

    if key in {"observed_at", "source_observed_at", "created_at", "last_refreshed_at"}:
        return "__volatile_timestamp__"
    if isinstance(value, Mapping):
        return {str(k): _watch_stable_value(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_watch_stable_value(item) for item in value]
    return value


def watch_content_fingerprint(payload: Mapping[str, Any]) -> str:
    """Hash result content while ignoring observation-clock fields."""

    stable = _watch_stable_value(dict(payload))
    return hashlib.sha256(_canonical(stable).encode("utf-8")).hexdigest()


class SelectorStore:
    """Small SQLite store for runs, result cards and read-only watch specs."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA foreign_keys = ON;
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    read_only INTEGER NOT NULL CHECK (read_only = 1),
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS result_cards (
                    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                    listing_id TEXT NOT NULL,
                    card_json TEXT NOT NULL,
                    PRIMARY KEY (run_id, listing_id)
                );
                CREATE TABLE IF NOT EXISTS watches (
                    watch_id TEXT PRIMARY KEY,
                    query TEXT NOT NULL,
                    fixture_path TEXT,
                    interval_seconds INTEGER NOT NULL CHECK (interval_seconds > 0),
                    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
                    created_at TEXT NOT NULL,
                    last_run_id TEXT,
                    last_refreshed_at TEXT
                );
                """
            )

    def save_run(self, payload: Mapping[str, Any], *, run_id: str | None = None) -> tuple[str, bool]:
        """Persist a result exactly once and return ``(run_id, inserted)``."""

        if payload.get("read_only") is not True:
            raise ValueError("only read-only payloads can be persisted")
        if payload.get("status") not in {"complete", "policy_blocked", "needs_clarification", "source_unavailable"}:
            raise ValueError("unsupported run status")
        payload_dict = dict(payload)
        resolved_id = run_id or run_id_for_payload(payload_dict)
        serialized = _canonical(payload_dict)
        with self._connect() as conn:
            existing = conn.execute("SELECT payload_json FROM runs WHERE run_id = ?", (resolved_id,)).fetchone()
            if existing is not None:
                if existing["payload_json"] != serialized:
                    raise ValueError("run_id already exists with different payload")
                return resolved_id, False
            conn.execute(
                "INSERT INTO runs(run_id, created_at, status, source_id, read_only, payload_json) VALUES (?, ?, ?, ?, 1, ?)",
                (resolved_id, _now(), str(payload_dict.get("status")), str(payload_dict.get("source", "unknown")), serialized),
            )
            for card in payload_dict.get("recommended", []) or []:
                conn.execute(
                    "INSERT INTO result_cards(run_id, listing_id, card_json) VALUES (?, ?, ?)",
                    (resolved_id, str(card["listing_id"]), _canonical(card)),
                )
        return resolved_id, True

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT payload_json FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def list_cards(self, run_id: str) -> list[dict[str, Any]]:
        """Read the result cards stored for a run in deterministic order."""

        with self._connect() as conn:
            rows = conn.execute(
                "SELECT card_json FROM result_cards WHERE run_id = ? ORDER BY listing_id",
                (run_id,),
            ).fetchall()
        return [json.loads(row["card_json"]) for row in rows]

    def add_watch(self, query: str, fixture_path: str | Path | None = None, *, interval_seconds: int = 900, watch_id: str | None = None) -> str:
        if not query.strip():
            raise ValueError("watch query must be non-empty")
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        resolved_id = watch_id or f"watch_{uuid.uuid4().hex[:16]}"
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO watches(watch_id, query, fixture_path, interval_seconds, enabled, created_at) VALUES (?, ?, ?, ?, 1, ?)",
                (resolved_id, query.strip(), str(fixture_path) if fixture_path is not None else None, int(interval_seconds), _now()),
            )
        return resolved_id

    def list_watches(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM watches"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY created_at, watch_id"
        with self._connect() as conn:
            rows = conn.execute(sql).fetchall()
        return [dict(row) for row in rows]

    def disable_watch(self, watch_id: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE watches SET enabled = 0 WHERE watch_id = ?", (watch_id,))

    def refresh_watch(self, watch_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM watches WHERE watch_id = ?", (watch_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown watch_id: {watch_id}")
        if not row["enabled"]:
            raise ValueError(f"watch is disabled: {watch_id}")
        payload = run_search(row["query"], row["fixture_path"])
        previous_run_id = row["last_run_id"]
        if previous_run_id:
            previous_payload = self.get_run(previous_run_id)
            if previous_payload and watch_content_fingerprint(previous_payload) == watch_content_fingerprint(payload):
                with self._connect() as conn:
                    conn.execute(
                        "UPDATE watches SET last_refreshed_at = ? WHERE watch_id = ?",
                        (_now(), watch_id),
                    )
                return {"watch_id": watch_id, "run_id": previous_run_id, "changed": False, "payload": payload}
        run_id, inserted = self.save_run(payload)
        with self._connect() as conn:
            conn.execute(
                "UPDATE watches SET last_run_id = ?, last_refreshed_at = ? WHERE watch_id = ?",
                (run_id, _now(), watch_id),
            )
        return {"watch_id": watch_id, "run_id": run_id, "changed": inserted, "payload": payload}

