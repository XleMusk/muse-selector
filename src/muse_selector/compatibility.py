"""Evidence-backed hardware compatibility matrices for result cards."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from .contracts import CompatibilityCheck

COMPATIBILITY_SCHEMA_VERSION = "muse.selector.compatibility.v1"


def _matches(required: Any, actual: Any) -> bool:
    if actual is None:
        return False
    if isinstance(required, bool):
        return bool(actual) is required
    if isinstance(required, (int, float, Decimal)) and not isinstance(required, bool):
        try:
            return Decimal(str(actual)) >= Decimal(str(required))
        except (InvalidOperation, TypeError, ValueError):
            return False
    if isinstance(required, (list, tuple, set)):
        return actual in required
    return str(required).strip().casefold() == str(actual).strip().casefold()


def _evidence_for_field(card: Mapping[str, Any], field: str) -> list[Mapping[str, Any]]:
    matches: list[Mapping[str, Any]] = []
    for evidence in card.get("evidence") or []:
        if not isinstance(evidence, Mapping) or evidence.get("status") != "confirmed":
            continue
        evidence_field = str(evidence.get("field") or "")
        value = evidence.get("value")
        if evidence_field in {field, f"specs.{field}"}:
            matches.append(evidence)
        elif evidence_field == "specs" and isinstance(value, Mapping) and field in value:
            matches.append(evidence)
    return matches


def build_compatibility_matrix(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Build a compatibility matrix without inferring missing specifications."""

    spec = payload.get("search_spec") if isinstance(payload.get("search_spec"), Mapping) else {}
    required = spec.get("required_specs") if isinstance(spec.get("required_specs"), Mapping) else {}
    items: list[dict[str, Any]] = []
    for card in payload.get("recommended") or []:
        if not isinstance(card, Mapping):
            continue
        specs = card.get("specs") if isinstance(card.get("specs"), Mapping) else {}
        requirements: list[dict[str, Any]] = []
        for field, expected in required.items():
            actual = specs.get(field)
            evidence = _evidence_for_field(card, str(field))
            evidence_ids = [str(item.get("evidence_id")) for item in evidence if item.get("evidence_id")]
            source_urls = [str(item.get("source_url")) for item in evidence if item.get("source_url")]
            if actual is None or not evidence:
                status = "unknown"
            elif _matches(expected, actual):
                status = "confirmed"
            else:
                status = "mismatch"
            requirements.append(
                CompatibilityCheck(
                    field=str(field),
                    required=expected,
                    actual=actual,
                    status=status,
                    evidence_ids=tuple(evidence_ids),
                    source_urls=tuple(source_urls),
                    rule_id=f"compatibility:{field}",
                ).to_dict()
            )
        statuses = {item["status"] for item in requirements}
        overall = "incompatible" if "mismatch" in statuses else "unknown" if "unknown" in statuses else "compatible"
        items.append({
            "listing_id": card.get("listing_id"),
            "product_id": card.get("product_id"),
            "source_id": card.get("source_id"),
            "url": card.get("url"),
            "overall_status": overall,
            "requirements": requirements,
        })
    return {
        "schema_version": COMPATIBILITY_SCHEMA_VERSION,
        "required_specs": dict(required),
        "source_order_preserved": True,
        "items": items,
    }


__all__ = ["COMPATIBILITY_SCHEMA_VERSION", "build_compatibility_matrix"]
