"""Command line entrypoint for the offline Hong Kong hardware selector."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline import run_search
from .result_card import render_markdown


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Hong Kong hardware search")
    parser.add_argument("--query", required=True, help="natural-language hardware query")
    parser.add_argument("--fixture", default=None, help="offline eBay response fixture; omit to use live read-only API")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    args = parser.parse_args()
    fixture = Path(args.fixture) if args.fixture else None
    payload = run_search(args.query, fixture, limit=args.limit)
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_markdown(payload))
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())

