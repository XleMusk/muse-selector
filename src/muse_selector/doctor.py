"""Offline installation and fixture diagnostics for Muse Selector.

The doctor command deliberately never contacts a marketplace.  It verifies the
local Python/package setup and, when a fixture is supplied, exercises the same
read-only pipeline used by the CLI.  Credential checks report presence only;
secret values are never included in the result.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .connectors.ebay import credential_env_names, credential_state as ebay_credential_state
from .application import search as run_search


DEFAULT_QUERY = "香港预算 HKD 7000 以内的迷你主机"
DOCTOR_SCHEMA_VERSION = "muse.doctor.v1"


def _check(name: str, ok: bool, detail: str, *, skipped: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"name": name, "ok": bool(ok), "detail": detail}
    if skipped:
        result["skipped"] = True
    return result


def _credential_state(environment: str | None = None) -> dict[str, str]:
    selected = environment if environment in {"production", "sandbox"} else os.getenv("EBAY_ENVIRONMENT", "production")
    if selected not in {"production", "sandbox"}:
        selected = "production"
    return {
        "ebay": ebay_credential_state(selected),
        "zhuanzhuan": "present" if bool(os.getenv("ZHUANZHUAN_MCP_TOKEN")) else "missing",
    }


def _runtime_info() -> dict[str, str]:
    """Return stable, credential-free information about the running CLI."""

    return {
        "package_version": __version__,
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(aliased=True),
        "executable": str(Path(sys.executable).resolve()),
    }


def _ebay_target(environment: str | None = None) -> dict[str, Any]:
    """Describe the selected official eBay target without making a request.

    The doctor command is intentionally offline.  Reporting the resolved host
    here makes a sandbox/production smoke run auditable while keeping the
    credential and network boundary unchanged.
    """

    selected = str(environment if environment is not None else os.getenv("EBAY_ENVIRONMENT", "production")).strip().lower()
    if selected not in {"production", "sandbox"}:
        return {
            "environment": "invalid",
            "api_host": None,
            "token_path": "/identity/v1/oauth2/token",
            "credential_env": None,
            "read_only": True,
        }
    host = "api.ebay.com" if selected == "production" else "api.sandbox.ebay.com"
    client_id_var, client_secret_var = credential_env_names(selected)
    return {
        "environment": selected,
        "api_host": host,
        "token_path": "/identity/v1/oauth2/token",
        "credential_env": {
            "scoped": [client_id_var, client_secret_var],
            "legacy_fallback": ["EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET"],
        },
        "read_only": True,
    }


def run_doctor(
    fixture_path: str | Path | None = None,
    *,
    query: str = DEFAULT_QUERY,
    limit: int = 10,
    environment: str | None = None,
) -> dict[str, Any]:
    """Return a deterministic local readiness report.

    A fixture check is optional so an installed package can be diagnosed
    outside a source checkout.  Supplying a fixture validates the full offline
    result contract and catches broken fixture paths or malformed data.
    """

    checks: list[dict[str, Any]] = []
    ebay_target = _ebay_target(environment)
    checks.append(_check(
        "ebay_environment",
        ebay_target["environment"] in {"production", "sandbox"},
        str(ebay_target["environment"]),
    ))
    version = sys.version_info
    python_ok = (version.major, version.minor) >= (3, 10)
    checks.append(_check("python", python_ok, platform.python_version()))

    try:
        import muse_selector  # noqa: F401  # local import is the check itself

        checks.append(_check("package_import", True, "muse_selector import ok"))
    except Exception as exc:  # pragma: no cover - import failures are environment-specific
        checks.append(_check("package_import", False, f"{type(exc).__name__}: {exc}"))

    if fixture_path is None:
        checks.append(_check("fixture_pipeline", True, "no fixture supplied", skipped=True))
    else:
        path = Path(fixture_path)
        if not path.is_file():
            checks.append(_check("fixture_pipeline", False, f"fixture not found: {path}"))
        elif isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            checks.append(_check("fixture_pipeline", False, "limit must be a positive integer"))
        else:
            try:
                payload = run_search(query, path, limit=limit)
                cards = payload.get("recommended") or []
                coverage_ok = all(float(card.get("evidence_coverage", 0)) >= 0.95 for card in cards)
                pipeline_ok = (
                    payload.get("ok") is True
                    and payload.get("read_only") is True
                    and isinstance(cards, list)
                    and bool(cards)
                    and coverage_ok
                )
                detail = f"{len(cards)} recommended card(s); status={payload.get('status', 'unknown')}"
                checks.append(_check("fixture_pipeline", pipeline_ok, detail))
            except Exception as exc:  # malformed fixture should be reported, not hidden
                checks.append(_check("fixture_pipeline", False, f"{type(exc).__name__}: {exc}"))

    ok = all(item["ok"] for item in checks if not item.get("skipped"))
    return {
        "schema_version": DOCTOR_SCHEMA_VERSION,
        "ok": ok,
        "status": "healthy" if ok else "unhealthy",
        "read_only": True,
        "runtime": _runtime_info(),
        "ebay_target": ebay_target,
        "checks": checks,
        "credential_state": _credential_state(ebay_target.get("environment")),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline Muse Selector installation and fixture diagnostics")
    parser.add_argument("--version", action="version", version=f"muse-doctor {__version__}")
    parser.add_argument("--fixture", default=None, help="optional offline eBay fixture to validate")
    parser.add_argument("--query", default=DEFAULT_QUERY, help="query used for the optional fixture check")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--environment", choices=("sandbox", "production"), default=None)
    args = parser.parse_args()
    report = run_doctor(args.fixture, query=args.query, limit=args.limit, environment=args.environment)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
