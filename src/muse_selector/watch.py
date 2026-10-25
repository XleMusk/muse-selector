"""Persistent read-only watch runner for the Hong Kong hardware MVP."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

from .persistence import SelectorStore


def default_watch_id(query: str, fixture: str | Path | None = None) -> str:
    """Return a stable id for an implicit watch invocation."""

    identity = f"{query.strip()}\x00{fixture or ''}".encode("utf-8")
    return f"watch_{hashlib.sha256(identity).hexdigest()[:16]}"


def _refresh_with_environment(store: SelectorStore, watch_id: str, environment: str | None) -> dict:
    previous_environment = os.environ.get("EBAY_ENVIRONMENT")
    try:
        if environment is not None:
            os.environ["EBAY_ENVIRONMENT"] = environment
        return store.refresh_watch(watch_id)
    finally:
        if previous_environment is None:
            os.environ.pop("EBAY_ENVIRONMENT", None)
        else:
            os.environ["EBAY_ENVIRONMENT"] = previous_environment


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a read-only Muse Selector watch")
    parser.add_argument("--db", default="data/selector.sqlite3")
    parser.add_argument("--action", choices=("refresh", "pause", "resume", "update", "replay"), default="refresh")
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
    parser.add_argument("--once", action="store_true", help="refresh once and exit")
    args = parser.parse_args()
    if args.interval_seconds is not None and args.interval_seconds <= 0:
        parser.error("--interval-seconds must be positive")
    if args.live and args.action != "update":
        parser.error("--live is only valid with --action update")

    store = SelectorStore(Path(args.db))
    if args.action != "refresh":
        if not args.watch_id:
            parser.error("--watch-id is required for --action " + args.action)
        if args.once:
            parser.error("--once is only valid with --action refresh")
        if args.action == "pause":
            store.pause_watch(args.watch_id)
            result = {"action": "pause", "watch": store.get_watch(args.watch_id)}
        elif args.action == "resume":
            store.resume_watch(args.watch_id)
            result = {"action": "resume", "watch": store.get_watch(args.watch_id)}
        elif args.action == "replay":
            result = {"action": "replay", "watch_id": args.watch_id, "payload": store.replay_watch(args.watch_id)}
        else:
            if args.query is None and args.fixture is None and not args.live and args.interval_seconds is None:
                parser.error("--action update requires --query, --fixture or --interval-seconds")
            kwargs = {}
            if args.query is not None:
                kwargs["query"] = args.query
            if args.fixture is not None:
                kwargs["fixture_path"] = Path(args.fixture)
            elif args.live:
                kwargs["fixture_path"] = None
            if args.interval_seconds is not None:
                kwargs["interval_seconds"] = args.interval_seconds
            result = {"action": "update", "watch": store.update_watch(args.watch_id, **kwargs)}
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if not args.watch_id and not args.query:
        parser.error("--query is required when --watch-id is omitted")
    # Keep the implicit watch stable across process restarts so rerunning the
    # same command does not create duplicate persistent watch rows. Callers
    # that need parallel watches can still provide an explicit --watch-id.
    watch_id = args.watch_id or default_watch_id(args.query or "", args.fixture)
    existing = store.get_watch(watch_id)
    if existing is None:
        interval_seconds = args.interval_seconds or 900
        store.add_watch(
            args.query or "",
            Path(args.fixture) if args.fixture else None,
            interval_seconds=interval_seconds,
            watch_id=watch_id,
        )
        existing = store.get_watch(watch_id)
    interval_seconds = args.interval_seconds or int(existing["interval_seconds"])

    while True:
        result = _refresh_with_environment(store, watch_id, args.environment)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        if args.once:
            return 0 if result["payload"].get("ok") else 2
        time.sleep(interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())

