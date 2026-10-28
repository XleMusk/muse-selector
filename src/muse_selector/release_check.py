"""Offline release readiness and Go/No-Go evidence check."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Mapping

from .connectors.ebay import credential_env_names, credential_state


RELEASE_SCHEMA_VERSION = "muse.selector.release.v1"
_ARTIFACTS = {
    "regression": "examples/regression_result.json",
    "faults": "examples/fault_result.json",
    "metrics": "examples/metrics_result.json",
    "shadow": "examples/shadow_result.json",
}
_LIVE_SMOKE_EVIDENCE = "examples/live_smoke_result.json"
_DOCUMENTS = ("README.md", "acceptance_matrix.md", "remaining_execution_plan.md", "release_runbook.md")


def _read_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    return (dict(value), None) if isinstance(value, dict) else (None, "artifact must be a JSON object")


def _valid_live_smoke_evidence(value: Mapping[str, Any] | None) -> bool:
    if not isinstance(value, Mapping):
        return False
    metadata = value.get("source_metadata")
    capability = value.get("source_capability")
    capability_ok = (
        isinstance(capability, Mapping)
        and capability.get("source_id") == "ebay.browse.hk.v1"
        and capability.get("access_mode") == "official_api"
        and capability.get("status") == "ready"
        and capability.get("read_only") is True
        and capability.get("listing_search") is True
    )
    recommended_count = value.get("recommended_count", 0)
    coverage = value.get("evidence_coverage_min")
    latency = metadata.get("latency_ms") if isinstance(metadata, Mapping) else None
    latency_ok = isinstance(latency, (int, float)) and latency >= 0
    coverage_ok = (
        recommended_count == 0
        or isinstance(coverage, (int, float))
        and float(coverage) >= 0.95
    )
    return (
        value.get("schema_version") == "muse.selector.v1"
        and value.get("ok") is True
        and value.get("status") == "complete"
        and value.get("source") == "ebay.browse.hk.v1"
        and value.get("read_only") is True
        and isinstance(metadata, Mapping)
        and metadata.get("environment") in {"production", "sandbox"}
        and capability_ok
        and coverage_ok
        and latency_ok
    )


def run_release_check(root: str | Path | None = None, *, require_live: bool = False) -> dict[str, Any]:
    base = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    checks: dict[str, dict[str, Any]] = {}
    for name, relative in _ARTIFACTS.items():
        path = base / relative
        artifact, error = _read_json(path)
        checks[name] = {
            "path": relative,
            "exists": path.is_file(),
            "ok": error is None and bool(artifact and artifact.get("ok") is True),
            "error": error,
        }
    for relative in _DOCUMENTS:
        path = base / relative
        checks[f"document:{relative}"] = {"path": relative, "exists": path.is_file(), "ok": path.is_file()}

    local_ready = all(item["ok"] for item in checks.values())
    live_evidence_path = base / _LIVE_SMOKE_EVIDENCE
    live_evidence, live_evidence_error = _read_json(live_evidence_path) if live_evidence_path.is_file() else (None, None)
    real_smoke_recorded = _valid_live_smoke_evidence(live_evidence)
    selected_environment = str(os.getenv("EBAY_ENVIRONMENT", "production")).strip().lower()
    if selected_environment not in {"production", "sandbox"}:
        selected_environment = "production"
    client_id_var, client_secret_var = credential_env_names(selected_environment)
    live_gate = {
        "status": "external_gate_pending",
        "environment": selected_environment,
        "credential_env": {
            "scoped": [client_id_var, client_secret_var],
            "legacy_fallback": ["EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET"],
        },
        "credential_state": credential_state(selected_environment),
        "official_approval_recorded": False,
        "real_smoke_recorded": real_smoke_recorded,
        "evidence_file": _LIVE_SMOKE_EVIDENCE if live_evidence_path.is_file() else None,
        "evidence_error": live_evidence_error,
        "reason": "official production approval is not recorded in this workspace" if real_smoke_recorded else "official production approval, keyset and real read-only smoke are not recorded in this workspace",
    }
    go = local_ready and live_gate["official_approval_recorded"] and live_gate["real_smoke_recorded"]
    result = {
        "schema_version": RELEASE_SCHEMA_VERSION,
        "ok": local_ready,
        "local_ready": local_ready,
        "go": go,
        "status": "go" if go else "local_ready_external_gate_pending" if local_ready else "local_not_ready",
        "read_only": True,
        "require_live": require_live,
        "checks": checks,
        "live_gate": live_gate,
    }
    if require_live and not go:
        result["ok"] = False
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Check offline Muse Selector release readiness")
    parser.add_argument("--root", default=None, help="repository root containing examples and release documents")
    parser.add_argument("--require-live", action="store_true", help="fail unless official live gate is recorded")
    args = parser.parse_args()
    result = run_release_check(args.root, require_live=args.require_live)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
