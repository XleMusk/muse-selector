"""Command line entrypoint for the offline Hong Kong hardware selector."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .application import search as run_search
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
    parser.add_argument("--version", action="version", version=f"muse-selector {__version__}")
    parser.add_argument("--query", required=True, help="natural-language hardware query")
    parser.add_argument("--fixture", default=None, help="offline eBay response fixture; omit to use live read-only API")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--offset", type=int, default=0, help="single Browse page offset; no automatic pagination")
    parser.add_argument("--environment", choices=("sandbox", "production"), default=None)
    parser.add_argument("--format", choices=("json", "markdown", "comparison"), default="markdown")
    args = parser.parse_args()
    fixture = Path(args.fixture) if args.fixture else None
    search_kwargs = {"limit": args.limit, "offset": args.offset}
    if args.environment is not None:
        search_kwargs["environment"] = args.environment
    payload = run_search(args.query, fixture, **search_kwargs)
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    elif args.format == "comparison":
        print(render_comparison(payload))
    else:
        print(render_markdown(payload))
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())

