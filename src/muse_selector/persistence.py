"""SQLite persistence and read-only watch tasks for the MVP.

The store keeps normalized run payloads and watch specifications. It never
stores credentials and never exposes an external write operation.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

from .application import search as run_search
from .watch_contracts import RefreshJob
from .watch_contracts import WatchEvent, WatchSpec


_UNSET = object()


def _refresh_job(
    watch_id: str,
    revision: int,
    run_id: str,
    payload: Mapping[str, Any],
    started_at: str,
    finished_at: str,
) -> RefreshJob:
    failed_statuses = {"source_unavailable", "invalid_query", "policy_blocked", "needs_clarification"}
    failed = payload.get("status") in failed_statuses
    return RefreshJob(
        job_id=f"{watch_id}:{revision}:{run_id}",
        watch_id=watch_id,
        status="failed" if failed else "complete",
        run_id=run_id,
        started_at=started_at,
        finished_at=finished_at,
        error=str(payload.get("message")) if failed and payload.get("message") else None,
    )


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _normalize_thresholds(value: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalize local watch thresholds without creating external side effects."""

    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("watch thresholds must be an object")
    allowed = {"price_max", "stock_required", "max_delivery_days"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"unsupported watch threshold(s): {unknown}")
    result: dict[str, Any] = {}
    if "price_max" in value and value["price_max"] is not None:
        try:
            amount = Decimal(str(value["price_max"]))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("price_max must be a non-negative number") from exc
        if not amount.is_finite() or amount < 0:
            raise ValueError("price_max must be a non-negative number")
        result["price_max"] = f"{amount.quantize(Decimal('0.01')):.2f}"
    if "stock_required" in value:
        if not isinstance(value["stock_required"], bool):
            raise ValueError("stock_required must be boolean")
        result["stock_required"] = value["stock_required"]
    if "max_delivery_days" in value and value["max_delivery_days"] is not None:
        days = value["max_delivery_days"]
        if isinstance(days, bool) or not isinstance(days, int) or days < 0:
            raise ValueError("max_delivery_days must be a non-negative integer")
        result["max_delivery_days"] = days
    return result


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


def watch_change_summary(
    previous_payload: Mapping[str, Any] | None,
    current_payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Describe recommendation changes without exposing volatile timestamps.

    The summary is derived from persisted result-card content and is returned
    by a watch refresh.  It is intentionally not part of the stored payload,
    so run IDs and replay remain deterministic for the same source result.
    """

    def cards_by_id(payload: Mapping[str, Any] | None) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            return {}
        cards = payload.get("recommended")
        if not isinstance(cards, list):
            return {}
        result: dict[str, Any] = {}
        for card in cards:
            if not isinstance(card, Mapping):
                continue
            listing_id = card.get("listing_id")
            if listing_id in (None, ""):
                continue
            result[str(listing_id)] = _watch_stable_value(dict(card))
        return result

    previous_cards = cards_by_id(previous_payload)
    current_cards = cards_by_id(current_payload)
    previous_ids = set(previous_cards)
    current_ids = set(current_cards)
    changed = sorted(
        listing_id
        for listing_id in previous_ids & current_ids
        if previous_cards[listing_id] != current_cards[listing_id]
    )
    previous_status = previous_payload.get("status") if isinstance(previous_payload, Mapping) else None
    current_status = current_payload.get("status") if isinstance(current_payload, Mapping) else None
    return {
        "has_previous": previous_payload is not None,
        "status_changed": previous_payload is not None and previous_status != current_status,
        "added_listing_ids": sorted(current_ids - previous_ids),
        "removed_listing_ids": sorted(previous_ids - current_ids),
        "changed_listing_ids": changed,
    }


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

    @contextmanager
    def _connection(self):
        """Open, commit/rollback, and always close one SQLite connection."""

        connection = self._connect()
        try:
            yield connection
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()

    def _init_schema(self) -> None:
        with self._connection() as conn:
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
                    source_rank INTEGER NOT NULL DEFAULT 0,
                    card_json TEXT NOT NULL,
                    PRIMARY KEY (run_id, listing_id)
                );
                CREATE TABLE IF NOT EXISTS watches (
                    watch_id TEXT PRIMARY KEY,
                    query TEXT NOT NULL,
                    fixture_path TEXT,
                    environment TEXT NOT NULL DEFAULT 'production',
                    interval_seconds INTEGER NOT NULL CHECK (interval_seconds > 0),
                    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
                    revision INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    last_run_id TEXT,
                    last_refreshed_at TEXT,
                    last_change_summary_json TEXT,
                    thresholds_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS watch_changes (
                    change_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    watch_id TEXT NOT NULL REFERENCES watches(watch_id) ON DELETE CASCADE,
                    observed_at TEXT NOT NULL,
                    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                    changed INTEGER NOT NULL CHECK (changed IN (0, 1)),
                    summary_json TEXT NOT NULL,
                    UNIQUE (watch_id, run_id)
                );
                CREATE INDEX IF NOT EXISTS idx_watch_changes_watch_id
                    ON watch_changes(watch_id, change_id DESC);
                CREATE TABLE IF NOT EXISTS watch_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    watch_id TEXT NOT NULL REFERENCES watches(watch_id) ON DELETE CASCADE,
                    observed_at TEXT NOT NULL,
                    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                    event_key TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE (watch_id, event_key)
                );
                CREATE INDEX IF NOT EXISTS idx_watch_events_watch_id
                    ON watch_events(watch_id, event_id DESC);
                """
            )
            # Migrate databases created before optimistic refresh validation
            # was introduced.  SQLite has no ADD COLUMN IF NOT EXISTS.
            watch_columns = {row["name"] for row in conn.execute("PRAGMA table_info(watches)")}
            if "revision" not in watch_columns:
                conn.execute("ALTER TABLE watches ADD COLUMN revision INTEGER NOT NULL DEFAULT 0")
            if "last_change_summary_json" not in watch_columns:
                conn.execute("ALTER TABLE watches ADD COLUMN last_change_summary_json TEXT")
            if "environment" not in watch_columns:
                conn.execute("ALTER TABLE watches ADD COLUMN environment TEXT NOT NULL DEFAULT 'production'")
            if "thresholds_json" not in watch_columns:
                conn.execute("ALTER TABLE watches ADD COLUMN thresholds_json TEXT NOT NULL DEFAULT '{}'")
            card_columns = {row["name"] for row in conn.execute("PRAGMA table_info(result_cards)")}
            if "source_rank" not in card_columns:
                conn.execute("ALTER TABLE result_cards ADD COLUMN source_rank INTEGER NOT NULL DEFAULT 0")

    def save_run(self, payload: Mapping[str, Any], *, run_id: str | None = None) -> tuple[str, bool]:
        """Persist a result exactly once and return ``(run_id, inserted)``."""

        if payload.get("read_only") is not True:
            raise ValueError("only read-only payloads can be persisted")
        if payload.get("status") not in {"complete", "policy_blocked", "needs_clarification", "invalid_query", "source_unavailable"}:
            raise ValueError("unsupported run status")
        payload_dict = dict(payload)
        resolved_id = run_id or run_id_for_payload(payload_dict)
        serialized = _canonical(payload_dict)
        with self._connection() as conn:
            return self._save_run_connection(conn, payload_dict, resolved_id, serialized)

    def _save_run_connection(
        self,
        conn: sqlite3.Connection,
        payload_dict: Mapping[str, Any],
        resolved_id: str,
        serialized: str | None = None,
    ) -> tuple[str, bool]:
        """Insert a run atomically on an existing SQLite connection."""

        serialized = serialized or _canonical(payload_dict)
        cursor = conn.execute(
            "INSERT OR IGNORE INTO runs(run_id, created_at, status, source_id, read_only, payload_json) VALUES (?, ?, ?, ?, 1, ?)",
            (resolved_id, _now(), str(payload_dict.get("status")), str(payload_dict.get("source", "unknown")), serialized),
        )
        existing = conn.execute("SELECT payload_json FROM runs WHERE run_id = ?", (resolved_id,)).fetchone()
        if existing is None:  # pragma: no cover - INSERT OR IGNORE cannot omit a valid row
            raise RuntimeError("run insert did not produce a row")
        if existing["payload_json"] != serialized:
            raise ValueError("run_id already exists with different payload")
        inserted = cursor.rowcount == 1
        if inserted:
            for card in payload_dict.get("recommended", []) or []:
                source_rank = card.get("source_rank", 0)
                if isinstance(source_rank, bool) or not isinstance(source_rank, int) or source_rank < 0:
                    source_rank = 0
                conn.execute(
                    "INSERT INTO result_cards(run_id, listing_id, source_rank, card_json) VALUES (?, ?, ?, ?)",
                    (resolved_id, str(card["listing_id"]), source_rank, _canonical(card)),
                )
        return resolved_id, inserted

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute("SELECT payload_json FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def list_cards(self, run_id: str) -> list[dict[str, Any]]:
        """Read the result cards stored for a run in deterministic order."""

        with self._connection() as conn:
            rows = conn.execute(
                "SELECT card_json FROM result_cards WHERE run_id = ? ORDER BY source_rank, listing_id",
                (run_id,),
            ).fetchall()
        return [json.loads(row["card_json"]) for row in rows]

    def add_watch(
        self,
        query: str,
        fixture_path: str | Path | None = None,
        *,
        interval_seconds: int = 900,
        watch_id: str | None = None,
        environment: str = "production",
        thresholds: Mapping[str, Any] | None = None,
    ) -> str:
        if not query.strip():
            raise ValueError("watch query must be non-empty")
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        if environment not in {"production", "sandbox"}:
            raise ValueError("environment must be production or sandbox")
        normalized_thresholds = _normalize_thresholds(thresholds)
        resolved_id = watch_id or f"watch_{uuid.uuid4().hex[:16]}"
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO watches(watch_id, query, fixture_path, environment, interval_seconds, enabled, revision, created_at, thresholds_json) VALUES (?, ?, ?, ?, ?, 1, 0, ?, ?)",
                (resolved_id, query.strip(), str(fixture_path) if fixture_path is not None else None, environment, int(interval_seconds), _now(), _canonical(normalized_thresholds)),
            )
        return resolved_id

    def list_watches(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM watches"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY created_at, watch_id"
        with self._connection() as conn:
            rows = conn.execute(sql).fetchall()
        return [self._watch_dict(row) for row in rows]

    @staticmethod
    def _watch_dict(row: sqlite3.Row | Mapping[str, Any]) -> dict[str, Any]:
        """Return a watch row with its persisted change summary decoded."""

        result = dict(row)
        encoded = result.pop("last_change_summary_json", None)
        if encoded:
            try:
                result["last_change_summary"] = json.loads(encoded)
            except (TypeError, ValueError):
                # A malformed legacy value must not make read-only status
                # endpoints fail; expose the absence of a usable summary.
                result["last_change_summary"] = None
        else:
            result["last_change_summary"] = None
        encoded_thresholds = result.pop("thresholds_json", None)
        if encoded_thresholds:
            try:
                result["thresholds"] = json.loads(encoded_thresholds)
            except (TypeError, ValueError):
                result["thresholds"] = {}
        else:
            result["thresholds"] = {}
        return result

    def get_watch(self, watch_id: str) -> dict[str, Any] | None:
        """Return one persisted watch specification without executing it."""

        with self._connection() as conn:
            row = conn.execute("SELECT * FROM watches WHERE watch_id = ?", (watch_id,)).fetchone()
        return self._watch_dict(row) if row else None

    def get_watch_spec(self, watch_id: str) -> WatchSpec | None:
        """Return the typed watch contract without refreshing it."""

        watch = self.get_watch(watch_id)
        return WatchSpec.from_mapping(watch) if watch is not None else None

    def disable_watch(self, watch_id: str) -> None:
        with self._connection() as conn:
            cursor = conn.execute("UPDATE watches SET enabled = 0, revision = revision + 1 WHERE watch_id = ?", (watch_id,))
        if cursor.rowcount == 0:
            raise KeyError(f"unknown watch_id: {watch_id}")

    def pause_watch(self, watch_id: str) -> None:
        """Pause a watch while preserving its last successful checkpoint."""

        self.disable_watch(watch_id)

    def resume_watch(self, watch_id: str) -> None:
        """Resume a paused watch without creating a run until refresh."""

        with self._connection() as conn:
            cursor = conn.execute("UPDATE watches SET enabled = 1, revision = revision + 1 WHERE watch_id = ?", (watch_id,))
        if cursor.rowcount == 0:
            raise KeyError(f"unknown watch_id: {watch_id}")

    def update_watch(
        self,
        watch_id: str,
        *,
        query: str | None = None,
        fixture_path: str | Path | None | object = _UNSET,
        interval_seconds: int | None = None,
        environment: str | None = None,
        thresholds: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Apply a user edit and clear the checkpoint when its input changes.

        The previous run remains available for replay.  The next refresh uses
        the edited query/source and creates a new deterministic run if the
        result differs.
        """

        current = self.get_watch(watch_id)
        if current is None:
            raise KeyError(f"unknown watch_id: {watch_id}")
        updates: list[str] = []
        values: list[Any] = []
        input_changed = False
        if query is not None:
            if not query.strip():
                raise ValueError("watch query must be non-empty")
            updates.append("query = ?")
            values.append(query.strip())
            input_changed = query.strip() != current["query"]
        if fixture_path is not _UNSET:
            normalized_fixture = str(fixture_path) if fixture_path is not None else None
            updates.append("fixture_path = ?")
            values.append(normalized_fixture)
            input_changed = normalized_fixture != current["fixture_path"]
        if interval_seconds is not None:
            if interval_seconds <= 0:
                raise ValueError("interval_seconds must be positive")
            updates.append("interval_seconds = ?")
            values.append(int(interval_seconds))
        if environment is not None:
            if environment not in {"production", "sandbox"}:
                raise ValueError("environment must be production or sandbox")
            updates.append("environment = ?")
            values.append(environment)
            input_changed = input_changed or environment != current.get("environment", "production")
        if thresholds is not None:
            normalized_thresholds = _normalize_thresholds(thresholds)
            updates.append("thresholds_json = ?")
            values.append(_canonical(normalized_thresholds))
        if input_changed:
            updates.extend(["last_run_id = NULL", "last_refreshed_at = NULL", "last_change_summary_json = NULL"])
        if updates:
            updates.append("revision = revision + 1")
            values.append(watch_id)
            with self._connection() as conn:
                conn.execute(f"UPDATE watches SET {', '.join(updates)} WHERE watch_id = ?", values)
        updated = self.get_watch(watch_id)
        if updated is None:  # pragma: no cover - row cannot disappear inside this call
            raise KeyError(f"unknown watch_id: {watch_id}")
        return updated

    def replay_run(self, run_id: str) -> dict[str, Any]:
        """Return a stored read-only result without calling a connector."""

        payload = self.get_run(run_id)
        if payload is None:
            raise KeyError(f"unknown run_id: {run_id}")
        return payload

    def replay_watch(self, watch_id: str) -> dict[str, Any]:
        """Replay the latest checkpoint for a watch without side effects."""

        watch = self.get_watch(watch_id)
        if watch is None:
            raise KeyError(f"unknown watch_id: {watch_id}")
        if not watch["last_run_id"]:
            raise ValueError(f"watch has no completed run: {watch_id}")
        return self.replay_run(str(watch["last_run_id"]))

    def list_watch_changes(
        self,
        watch_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
        include_payload: bool = False,
    ) -> list[dict[str, Any]]:
        """Return the persisted distinct run checkpoints for a watch.

        A refresh that observes the same deterministic run does not create a
        duplicate history row.  This gives local consumers a compact,
        restart-safe change feed while preserving replay through ``run_id``.
        """

        if limit <= 0 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        if offset < 0:
            raise ValueError("offset must be non-negative")
        if self.get_watch(watch_id) is None:
            raise KeyError(f"unknown watch_id: {watch_id}")
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT change_id, watch_id, observed_at, run_id, changed, summary_json
                FROM watch_changes
                WHERE watch_id = ?
                ORDER BY change_id DESC
                LIMIT ? OFFSET ?
                """,
                (watch_id, int(limit), int(offset)),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            try:
                summary = json.loads(row["summary_json"])
            except (TypeError, ValueError):
                summary = None
            item: dict[str, Any] = {
                "change_id": int(row["change_id"]),
                "watch_id": row["watch_id"],
                "observed_at": row["observed_at"],
                "run_id": row["run_id"],
                "changed": bool(row["changed"]),
                "change_summary": summary,
            }
            if include_payload:
                payload = self.get_run(str(row["run_id"]))
                if payload is not None:
                    item["payload"] = payload
            result.append(item)
        return result

    @staticmethod
    def _threshold_events(
        payload: Mapping[str, Any],
        thresholds: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        """Derive local read-only threshold events from recommended cards."""

        if not isinstance(payload, Mapping) or not isinstance(thresholds, Mapping):
            return []
        events: list[dict[str, Any]] = []
        for card in payload.get("recommended") or []:
            if not isinstance(card, Mapping) or not card.get("listing_id"):
                continue
            listing_id = str(card["listing_id"])
            if thresholds.get("price_max") is not None:
                try:
                    price = Decimal(str(card.get("landed_cost")))
                    maximum = Decimal(str(thresholds["price_max"]))
                except (InvalidOperation, TypeError, ValueError):
                    price = maximum = None
                if price is not None and maximum is not None and price <= maximum:
                    value = f"{price.quantize(Decimal('0.01')):.2f}"
                    events.append({
                        "event_key": f"price_max:{listing_id}:{thresholds['price_max']}:{value}",
                        "event_type": "price_max_reached",
                        "listing_id": listing_id,
                        "details": {"landed_cost": value, "price_max": thresholds["price_max"]},
                    })
            if thresholds.get("stock_required") is True and card.get("stock_status") in {"in_stock", "preorder"}:
                status = str(card.get("stock_status"))
                events.append({
                    "event_key": f"stock_required:{listing_id}:{status}",
                    "event_type": "stock_available",
                    "listing_id": listing_id,
                    "details": {"stock_status": status},
                })
            if thresholds.get("max_delivery_days") is not None:
                days = card.get("delivery_max_days")
                if isinstance(days, int) and not isinstance(days, bool) and days <= int(thresholds["max_delivery_days"]):
                    events.append({
                        "event_key": f"delivery:{listing_id}:{thresholds['max_delivery_days']}:{days}",
                        "event_type": "delivery_within_limit",
                        "listing_id": listing_id,
                        "details": {"delivery_max_days": days, "max_delivery_days": thresholds["max_delivery_days"]},
                    })
        return events

    def list_watch_events(self, watch_id: str, *, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        """Read the deduplicated local threshold event feed without refreshing."""

        if limit <= 0 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        if offset < 0:
            raise ValueError("offset must be non-negative")
        if self.get_watch(watch_id) is None:
            raise KeyError(f"unknown watch_id: {watch_id}")
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT event_id, watch_id, observed_at, run_id, event_key, event_type, payload_json FROM watch_events WHERE watch_id = ? ORDER BY event_id DESC LIMIT ? OFFSET ?",
                (watch_id, int(limit), int(offset)),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            try:
                details = json.loads(row["payload_json"])
            except (TypeError, ValueError):
                details = None
            result.append({
                "event_id": int(row["event_id"]),
                "watch_id": row["watch_id"],
                "observed_at": row["observed_at"],
                "run_id": row["run_id"],
                "event_key": row["event_key"],
                "event_type": row["event_type"],
                "details": details,
            })
        return result

    def list_watch_event_models(self, watch_id: str, *, limit: int = 100, offset: int = 0) -> list[WatchEvent]:
        """Return the same event feed as typed domain objects."""

        return [WatchEvent.from_mapping(item) for item in self.list_watch_events(watch_id, limit=limit, offset=offset)]

    def refresh_watch(self, watch_id: str, *, environment: str | None = None) -> dict[str, Any]:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM watches WHERE watch_id = ?", (watch_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown watch_id: {watch_id}")
        if not row["enabled"]:
            raise ValueError(f"watch is disabled: {watch_id}")
        initial_revision = int(row["revision"])
        started_at = _now()
        selected_environment = environment or row["environment"] or "production"
        if selected_environment not in {"production", "sandbox"}:
            raise ValueError("environment must be production or sandbox")
        configured_environment = str(os.environ.get("EBAY_ENVIRONMENT", "production")).strip().lower()
        if configured_environment == selected_environment:
            payload = run_search(row["query"], row["fixture_path"])
        else:
            payload = run_search(row["query"], row["fixture_path"], environment=selected_environment)
        payload_dict = dict(payload)
        run_id = run_id_for_payload(payload_dict)
        serialized = _canonical(payload_dict)
        auto_paused = payload_dict.get("status") in {
            "source_unavailable",
            "invalid_query",
            "policy_blocked",
            "needs_clarification",
        }

        # Keep run insertion, result-card insertion and checkpoint advancement
        # in one transaction.  A process crash or a SQLite error during the
        # checkpoint update must roll back the newly inserted run as well,
        # otherwise a later restart sees an orphan run that was never the
        # watch's committed observation.
        with self._connection() as conn:
            # Serialize the final validation and checkpoint write with any
            # concurrent watch mutation.  An update that committed while the
            # search was running is rejected and the transaction rolls back.
            conn.execute("BEGIN IMMEDIATE")
            current = conn.execute("SELECT * FROM watches WHERE watch_id = ?", (watch_id,)).fetchone()
            if current is None:
                raise KeyError(f"unknown watch_id: {watch_id}")
            if not current["enabled"]:
                raise ValueError(f"watch is disabled: {watch_id}")
            if int(current["revision"]) != initial_revision:
                raise ValueError(f"watch changed during refresh: {watch_id}")

            previous_run_id = current["last_run_id"]
            previous_payload = None
            if previous_run_id:
                previous = conn.execute(
                    "SELECT payload_json FROM runs WHERE run_id = ?", (previous_run_id,)
                ).fetchone()
                previous_payload = json.loads(previous["payload_json"]) if previous else None
            change_summary = watch_change_summary(previous_payload, payload)
            encoded_change_summary = _canonical(change_summary)
            try:
                thresholds = json.loads(current["thresholds_json"] or "{}")
            except (TypeError, ValueError):
                thresholds = {}
            threshold_events = self._threshold_events(payload, thresholds)

            def persist_threshold_events(event_run_id: str, observed_at: str) -> list[dict[str, Any]]:
                inserted_events: list[dict[str, Any]] = []
                for event in threshold_events:
                    details = dict(event.get("details") or {})
                    cursor = conn.execute(
                        "INSERT OR IGNORE INTO watch_events(watch_id, observed_at, run_id, event_key, event_type, payload_json) VALUES (?, ?, ?, ?, ?, ?)",
                        (watch_id, observed_at, event_run_id, str(event["event_key"]), str(event["event_type"]), _canonical(details)),
                    )
                    if cursor.rowcount == 1:
                        inserted_events.append({
                            "watch_id": watch_id,
                            "run_id": event_run_id,
                            "event_key": event["event_key"],
                            "event_type": event["event_type"],
                            "listing_id": event.get("listing_id"),
                            "details": details,
                            "observed_at": observed_at,
                        })
                return inserted_events

            if previous_payload and watch_content_fingerprint(previous_payload) == watch_content_fingerprint(payload):
                observed_at = _now()
                conn.execute(
                    "UPDATE watches SET enabled = ?, last_refreshed_at = ?, last_change_summary_json = ? WHERE watch_id = ?",
                    (0 if auto_paused else 1, observed_at, encoded_change_summary, watch_id),
                )
                # Backfill the first checkpoint for databases upgraded from a
                # schema that had last_change_summary but no history table.
                conn.execute(
                    """
                    INSERT OR IGNORE INTO watch_changes(
                        watch_id, observed_at, run_id, changed, summary_json
                    ) VALUES (?, ?, ?, 0, ?)
                    """,
                    (watch_id, observed_at, str(previous_run_id), encoded_change_summary),
                )
                events = persist_threshold_events(str(previous_run_id), observed_at)
                refresh_job = _refresh_job(
                    watch_id,
                    initial_revision,
                    str(previous_run_id),
                    payload,
                    started_at,
                    observed_at,
                )
                return {
                    "watch_id": watch_id,
                    "run_id": previous_run_id,
                    "changed": False,
                    "change_summary": change_summary,
                    "events": events,
                    "refresh_job": refresh_job.to_dict(),
                    "auto_paused": auto_paused,
                    "payload": payload,
                }

            run_id, inserted = self._save_run_connection(conn, payload_dict, run_id, serialized)
            observed_at = _now()
            conn.execute(
                "UPDATE watches SET enabled = ?, last_run_id = ?, last_refreshed_at = ?, last_change_summary_json = ? WHERE watch_id = ?",
                (0 if auto_paused else 1, run_id, observed_at, encoded_change_summary, watch_id),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO watch_changes(
                    watch_id, observed_at, run_id, changed, summary_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (watch_id, observed_at, run_id, int(inserted), encoded_change_summary),
            )
            events = persist_threshold_events(run_id, observed_at)
        refresh_job = _refresh_job(watch_id, initial_revision, run_id, payload, started_at, observed_at)
        return {
            "watch_id": watch_id,
            "run_id": run_id,
            "changed": inserted,
            "change_summary": change_summary,
            "events": events,
            "refresh_job": refresh_job.to_dict(),
            "auto_paused": auto_paused,
            "payload": payload,
        }

