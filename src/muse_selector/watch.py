"""Persistent read-only watch runner for the Hong Kong hardware MVP."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

from .contracts import RESULT_SCHEMA_VERSION
from .persistence import SelectorStore


def _print_result(result: dict) -> None:
    """Print one versioned, read-only watch action envelope."""

    body = dict(result)
    body.setdefault("schema_version", RESULT_SCHEMA_VERSION)
    print(json.dumps(body, ensure_ascii=False, indent=2, sort_keys=True))


def _print_error(action: str, status: str, message: str) -> int:
    """Print a structured read-only CLI error instead of a traceback."""

    _print_result(
        {
            "action": action,
            "ok": False,
            "status": status,
            "message": message,
            "read_only": True,
        }
    )
    return 2


def _exception_message(exc: BaseException) -> str:
    """Return a clean single-value message for structured CLI errors."""

    return str(exc.args[0]) if exc.args else str(exc)


def default_watch_id(
    query: str,
    fixture: str | Path | None = None,
    environment: str | None = None,
) -> str:
    """Return a stable id for an implicit watch invocation."""

    identity = f"{query.strip()}\x00{fixture or ''}".encode("utf-8")
    if environment is not None:
        identity += f"\x00{environment}".encode("utf-8")
    return f"watch_{hashlib.sha256(identity).hexdigest()[:16]}"


def _refresh_with_environment(store: SelectorStore, watch_id: str, environment: str | None) -> dict:
    return store.refresh_watch(watch_id, environment=environment)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a read-only Muse Selector watch")
    parser.add_argument("--db", default="data/selector.sqlite3")
    parser.add_argument(
        "--action",
        choices=("refresh", "pause", "resume", "update", "replay", "status", "list", "changes", "events"),
        default="refresh",
    )
    parser.add_argument("--query", default=None)
    fixture_group = parser.add_mutually_exclusive_group()
    fixture_group.add_argument("--fixture", default=None, help="offline fixture; omit for live read-only API")
    fixture_group.add_argument(
        "--live",
        action="store_true",
        help="for --action update, clear a stored fixture and use the live read-only API",
    )
    parser.add_argument("--environment", choices=("sandbox", "production"), default=None)
    parser.add_argument("--watch-id", default=None)
    parser.add_argument("--interval-seconds", type=int, default=None)
    parser.add_argument("--limit", type=int, default=100, help="maximum change events for --action changes")
    parser.add_argument("--offset", type=int, default=0, help="change event offset for --action changes")
    parser.add_argument("--include-payload", action="store_true", help="include replayable payloads for --action changes")
    parser.add_argument("--price-max", default=None, help="local price threshold for --action refresh/update")
    parser.add_argument("--stock-required", action="store_true", help="emit local events when a card is in stock")
    parser.add_argument("--max-delivery-days", type=int, default=None, help="local delivery threshold for --action refresh/update")
    parser.add_argument("--clear-thresholds", action="store_true", help="clear local watch thresholds on update")
    parser.add_argument("--once", action="store_true", help="refresh once and exit")
    args = parser.parse_args()
    if args.interval_seconds is not None and args.interval_seconds <= 0:
        parser.error("--interval-seconds must be positive")
    if args.live and args.action != "update":
        parser.error("--live is only valid with --action update")
    if args.limit <= 0 or args.limit > 1000:
        parser.error("--limit must be between 1 and 1000")
    if args.offset < 0:
        parser.error("--offset must be non-negative")
    if args.include_payload and args.action != "changes":
        parser.error("--include-payload is only valid with --action changes")
    if args.clear_thresholds and args.action != "update":
        parser.error("--clear-thresholds is only valid with --action update")
    thresholds = {}
    if args.price_max is not None:
        thresholds["price_max"] = args.price_max
    if args.stock_required:
        thresholds["stock_required"] = True
    if args.max_delivery_days is not None:
        thresholds["max_delivery_days"] = args.max_delivery_days

    store = SelectorStore(Path(args.db))
    if args.action == "list":
        if args.watch_id:
            parser.error("--watch-id is not valid for --action list")
        if args.once:
            parser.error("--once is only valid for --action refresh")
        result = {
            "action": "list",
            "read_only": True,
            "watches": store.list_watches(),
        }
        _print_result(result)
        return 0
    if args.action != "refresh":
        if not args.watch_id:
            parser.error("--watch-id is required for --action " + args.action)
        if args.once:
            parser.error("--once is only valid with --action refresh")
        if args.action == "changes":
            try:
                changes = store.list_watch_changes(
                    args.watch_id,
                    limit=args.limit,
                    offset=args.offset,
                    include_payload=args.include_payload,
                )
            except KeyError as exc:
                return _print_error("changes", "watch_not_found", _exception_message(exc))
            result = {
                "action": "changes",
                "watch_id": args.watch_id,
                "read_only": True,
                "changes": changes,
                "limit": args.limit,
                "offset": args.offset,
            }
            _print_result(result)
            return 0
        if args.action == "events":
            try:
                events = [
                    event.to_dict()
                    for event in store.list_watch_event_models(args.watch_id, limit=args.limit, offset=args.offset)
                ]
            except KeyError as exc:
                return _print_error("events", "watch_not_found", _exception_message(exc))
            _print_result({
                "action": "events",
                "watch_id": args.watch_id,
                "read_only": True,
                "events": events,
                "limit": args.limit,
                "offset": args.offset,
            })
            return 0
        if args.action == "pause":
            try:
                store.pause_watch(args.watch_id)
            except KeyError as exc:
                return _print_error("pause", "watch_not_found", _exception_message(exc))
            result = {"action": "pause", "watch": store.get_watch(args.watch_id)}
        elif args.action == "resume":
            try:
                store.resume_watch(args.watch_id)
            except KeyError as exc:
                return _print_error("resume", "watch_not_found", _exception_message(exc))
            result = {"action": "resume", "watch": store.get_watch(args.watch_id)}
        elif args.action == "replay":
            try:
                payload = store.replay_watch(args.watch_id)
            except KeyError as exc:
                return _print_error("replay", "watch_not_found", _exception_message(exc))
            except ValueError as exc:
                return _print_error("replay", "watch_unavailable", _exception_message(exc))
            result = {"action": "replay", "watch_id": args.watch_id, "payload": payload}
        elif args.action == "status":
            watch = store.get_watch(args.watch_id)
            if watch is None:
                return _print_error("status", "watch_not_found", f"unknown watch_id: {args.watch_id}")
            result = {
                "action": "status",
                "watch": watch,
                "read_only": True,
            }
            if watch.get("last_run_id"):
                try:
                    result["payload"] = store.replay_run(str(watch["last_run_id"]))
                except KeyError as exc:
                    return _print_error("status", "watch_unavailable", _exception_message(exc))
        else:
            if (
                args.query is None
                and args.fixture is None
                and not args.live
                and args.interval_seconds is None
                and args.environment is None
            ):
                parser.error("--action update requires --query, --fixture, --live, --interval-seconds or --environment")
            kwargs = {}
            if args.query is not None:
                kwargs["query"] = args.query
            if args.fixture is not None:
                kwargs["fixture_path"] = Path(args.fixture)
            elif args.live:
                kwargs["fixture_path"] = None
            if args.interval_seconds is not None:
                kwargs["interval_seconds"] = args.interval_seconds
            if args.environment is not None:
                kwargs["environment"] = args.environment
            if args.clear_thresholds or thresholds:
                kwargs["thresholds"] = {} if args.clear_thresholds else thresholds
            try:
                updated_watch = store.update_watch(args.watch_id, **kwargs)
            except KeyError as exc:
                return _print_error("update", "watch_not_found", _exception_message(exc))
            except ValueError as exc:
                return _print_error("update", "invalid_watch", _exception_message(exc))
            result = {"action": "update", "watch": updated_watch}
        _print_result(result)
        return 0

    if not args.watch_id and not args.query:
        parser.error("--query is required when --watch-id is omitted")
    # Keep the implicit watch stable across process restarts so rerunning the
    # same command does not create duplicate persistent watch rows. Callers
    # that need parallel watches can still provide an explicit --watch-id.
    selected_environment = args.environment or os.environ.get("EBAY_ENVIRONMENT", "production").strip().lower()
    if selected_environment not in {"production", "sandbox"}:
        parser.error("environment must be production or sandbox")
    watch_id = args.watch_id or default_watch_id(args.query or "", args.fixture, args.environment)
    existing = store.get_watch(watch_id)
    if existing is None and args.watch_id and args.query is None:
        return _print_error("refresh", "watch_not_found", f"unknown watch_id: {watch_id}")
    if existing is None:
        interval_seconds = args.interval_seconds or 900
        store.add_watch(
            args.query or "",
            Path(args.fixture) if args.fixture else None,
            interval_seconds=interval_seconds,
            watch_id=watch_id,
            environment=selected_environment,
            thresholds=thresholds or None,
        )
        existing = store.get_watch(watch_id)
    interval_seconds = args.interval_seconds or int(existing["interval_seconds"])

    while True:
        result = _refresh_with_environment(store, watch_id, args.environment or existing.get("environment", "production"))
        _print_result(result)
        if args.once:
            return 0 if result["payload"].get("ok") else 2
        time.sleep(interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())

