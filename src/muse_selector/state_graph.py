"""Deterministic, read-only execution graph for one selector task.

The graph wraps the existing pipeline instead of duplicating filtering logic.
Its checkpoint contains the completed result payload, so a replay can return a
previous result without invoking a connector again.
"""

from __future__ import annotations

import hashlib
import json
import argparse
from pathlib import Path
from typing import Any, Mapping

from .contracts import RESULT_SCHEMA_VERSION
from .application import search as run_search


STATE_GRAPH_SCHEMA_VERSION = "muse.selector.execution.v1"
STAGES = ("parse", "fanout", "normalize", "filter", "rank", "verify", "present")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def execution_id_for_request(
    query: str,
    fixture_path: str | Path | None = None,
    *,
    limit: int = 10,
    offset: int = 0,
    environment: str | None = None,
) -> str:
    request = {
        "query": query,
        "fixture_path": str(fixture_path) if fixture_path is not None else None,
        "limit": limit,
        "offset": offset,
        "environment": environment,
    }
    digest = hashlib.sha256(_canonical(request).encode("utf-8")).hexdigest()[:32]
    return f"exec_{digest}"


def _failed_stage(payload: Mapping[str, Any]) -> str | None:
    status = payload.get("status")
    if status in {"policy_blocked", "invalid_query", "needs_clarification"}:
        return "parse"
    if status == "source_unavailable":
        return "fanout"
    return None


def _stage_records(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    failed = _failed_stage(payload)
    records: list[dict[str, Any]] = []
    failed_seen = False
    for name in STAGES:
        if failed_seen:
            status = "skipped"
        elif name == failed:
            status = "failed"
            failed_seen = True
        else:
            status = "complete"
        records.append({"name": name, "status": status, "read_only": True})
    return records


def run_search_graph(
    query: str,
    fixture_path: str | Path | None = None,
    *,
    limit: int = 10,
    offset: int = 0,
    environment: str | None = None,
    checkpoint: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run or replay one deterministic, read-only task graph.

    A checkpoint must belong to the same request and contain a prior payload.
    Replaying it does not call ``run_search`` or any connector.
    """

    execution_id = execution_id_for_request(
        query,
        fixture_path,
        limit=limit,
        offset=offset,
        environment=environment,
    )
    resumed = checkpoint is not None
    if checkpoint is not None:
        if not isinstance(checkpoint, Mapping):
            raise ValueError("checkpoint must be an object")
        if checkpoint.get("execution_id") != execution_id:
            raise ValueError("checkpoint belongs to a different execution request")
        payload = checkpoint.get("payload")
        if not isinstance(payload, Mapping):
            raise ValueError("checkpoint payload is required")
        payload = dict(payload)
    else:
        payload = run_search(
            query,
            fixture_path,
            limit=limit,
            offset=offset,
            environment=environment,
        )

    payload_fingerprint = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
    result = dict(payload)
    result["execution"] = {
        "schema_version": STATE_GRAPH_SCHEMA_VERSION,
        "execution_id": execution_id,
        "resumed_from_checkpoint": resumed,
        "current_stage": "present" if payload.get("ok") else (_failed_stage(payload) or "present"),
        "stages": _stage_records(payload),
        "checkpoint": {
            "execution_id": execution_id,
            "completed_stage": "present" if payload.get("ok") else (_failed_stage(payload) or "present"),
            "payload_fingerprint": payload_fingerprint,
            "payload": payload,
        },
        "read_only": True,
    }
    result.setdefault("schema_version", RESULT_SCHEMA_VERSION)
    return result


def run_state_graph(
    query: str,
    fixture_path: str | Path | None = None,
    *,
    environment: str | None = None,
    limit: int = 10,
    offset: int = 0,
    checkpoint: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the compact W6 execution envelope used by callers."""

    result = run_search_graph(
        query,
        fixture_path,
        limit=limit,
        offset=offset,
        environment=environment,
        checkpoint=checkpoint,
    )
    execution = result["execution"]
    payload = {key: value for key, value in result.items() if key != "execution"}
    return {
        "schema_version": STATE_GRAPH_SCHEMA_VERSION,
        "run_id": execution["execution_id"],
        "status": payload.get("status", "unknown"),
        "stages": execution["stages"],
        "payload": payload,
        "checkpoint": execution["checkpoint"],
        "resumed_from_checkpoint": execution["resumed_from_checkpoint"],
        "read_only": True,
    }


__all__ = [
    "STATE_GRAPH_SCHEMA_VERSION",
    "STAGES",
    "execution_id_for_request",
    "run_state_graph",
    "run_search_graph",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a read-only Muse Selector execution graph")
    parser.add_argument("--query", required=True, help="explicit hardware query")
    parser.add_argument("--fixture", default=None, help="offline eBay fixture")
    parser.add_argument("--environment", choices=("sandbox", "production"), default=None)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--checkpoint", default=None, help="JSON checkpoint file to replay")
    args = parser.parse_args()
    checkpoint = None
    if args.checkpoint:
        try:
            checkpoint = json.loads(Path(args.checkpoint).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            parser.error(f"checkpoint must be readable JSON: {exc}")
    result = run_state_graph(
        args.query,
        Path(args.fixture) if args.fixture else None,
        environment=args.environment,
        limit=args.limit,
        offset=args.offset,
        checkpoint=checkpoint,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("payload", {}).get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
