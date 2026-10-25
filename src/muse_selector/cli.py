"""Command line entrypoint for the offline Hong Kong hardware selector."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .pipeline import run_search
from .result_card import render_comparison, render_markdown


def _configure_console_encoding() -> None:
    """Keep localized result reports readable on Windows console code pages."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError):
                # Test streams and detached handles may not support reconfigure.
                pass


def main() -> int:
    _configure_console_encoding()
    parser = argparse.ArgumentParser(description="Read-only Hong Kong hardware search")
    parser.add_argument("--query", required=True, help="natural-language hardware query")
    parser.add_argument("--fixture", default=None, help="offline eBay response fixture; omit to use live read-only API")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--environment", choices=("sandbox", "production"), default=None)
    parser.add_argument("--format", choices=("json", "markdown", "comparison"), default="markdown")
    args = parser.parse_args()
    fixture = Path(args.fixture) if args.fixture else None
    previous_environment = os.environ.get("EBAY_ENVIRONMENT")
    try:
        if args.environment is not None:
            os.environ["EBAY_ENVIRONMENT"] = args.environment
        payload = run_search(args.query, fixture, limit=args.limit)
    finally:
        if previous_environment is None:
            os.environ.pop("EBAY_ENVIRONMENT", None)
        else:
            os.environ["EBAY_ENVIRONMENT"] = previous_environment
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    elif args.format == "comparison":
        print(render_comparison(payload))
    else:
        print(render_markdown(payload))
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())

