"""Persistent read-only watch runner for the Hong Kong hardware MVP."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

from .persistence import SelectorStore


def default_watch_id(query: str, fixture: str | Path | None = None) -> str:
    """Return a stable id for an implicit watch invocation."""

    identity = f"{query.strip()}\x00{fixture or ''}".encode("utf-8")
    return f"watch_{hashlib.sha256(identity).hexdigest()[:16]}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a read-only Muse Selector watch")
    parser.add_argument("--db", default="data/selector.sqlite3")
    parser.add_argument("--query", required=True)
    parser.add_argument("--fixture", default=None, help="offline fixture; omit for live read-only API")
    parser.add_argument("--watch-id", default=None)
    parser.add_argument("--interval-seconds", type=int, default=900)
    parser.add_argument("--once", action="store_true", help="refresh once and exit")
    args = parser.parse_args()
    if args.interval_seconds <= 0:
        parser.error("--interval-seconds must be positive")

    store = SelectorStore(Path(args.db))
    # Keep the implicit watch stable across process restarts so rerunning the
    # same command does not create duplicate persistent watch rows. Callers
    # that need parallel watches can still provide an explicit --watch-id.
    watch_id = args.watch_id or default_watch_id(args.query, args.fixture)
    existing = {item["watch_id"] for item in store.list_watches()}
    if watch_id not in existing:
        store.add_watch(
            args.query,
            Path(args.fixture) if args.fixture else None,
            interval_seconds=args.interval_seconds,
            watch_id=watch_id,
        )

    while True:
        result = store.refresh_watch(watch_id)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        if args.once:
            return 0 if result["payload"].get("ok") else 2
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())

