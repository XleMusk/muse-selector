"""Offline-first end-to-end search pipeline for the Hong Kong MVP."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .connectors.ebay import ConnectorUnavailable, EbayBrowseConnector
from .contracts import Evidence, Listing
from .filtering import filter_listings
from .query_parser import PolicyBlockedError, parse_query
from .result_card import build_card


_RAM_TITLE = re.compile(r"(\d+)\s*GB\s*(?:RAM|内存|(?=\s+\d+(?:GB|TB)\s*(?:NVMe|SSD)))", re.I)
_STORAGE_TITLE = re.compile(r"(\d+(?:\.\d+)?)\s*(GB|TB)\s*(?:NVMe|SSD|存储)", re.I)
_VRAM_TITLE = re.compile(r"RTX\s*\d+\D+(\d+)\s*GB", re.I)
_ALLOWED_SOURCE_HOSTS = {"ebay.com.hk", "www.ebay.com.hk", "ebay.com", "www.ebay.com"}


def _allowed_source_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and (parsed.hostname or "").lower() in _ALLOWED_SOURCE_HOSTS


def _extract_specs(title: str) -> dict[str, Any]:
    specs: dict[str, Any] = {}
    ram = _RAM_TITLE.search(title)
    if ram:
        specs["ram_gb"] = int(ram.group(1))
    storage = _STORAGE_TITLE.search(title)
    if storage:
        specs["storage_gb"] = int(float(storage.group(1)) * (1024 if storage.group(2).upper() == "TB" else 1))
    vram = _VRAM_TITLE.search(title)
    if vram:
        specs["vram_gb"] = int(vram.group(1))
    if re.search(r"USB\s*4", title, re.I):
        specs["usb4"] = True
    return specs


def _query_matches_title(query: str, title: str) -> bool:
    """Apply a small deterministic relevance gate before ranking.

    The first fixture is intentionally heterogeneous. A budget match alone must
    not make a dock or enclosure look like a mini PC recommendation.
    """

    q = query.lower()
    t = title.lower()
    groups = (
        (("mini pc", "迷你主机", "迷你电脑"), ("mini pc", "mini computer", "迷你", "主机")),
        (("扩展坞", "dock", "enclosure", "usb4"), ("扩展坞", "dock", "enclosure", "usb4")),
        (("显卡", "gpu", "显存", "rtx", "gtx"), ("显卡", "gpu", "显存", "rtx", "gtx")),
        (("笔记本", "轻薄本", "laptop"), ("笔记本", "轻薄本", "laptop")),
    )
    for needles, matches in groups:
        if any(needle in q for needle in needles):
            return any(match in t for match in matches)
    return True


def _to_listing(row: dict[str, Any]) -> tuple[Listing | None, list[Evidence], str | None]:
    url = row.get("url")
    if not url:
        return None, [], "missing_source_url"
    if not _allowed_source_url(str(url)):
        return None, [], "untrusted_source_url"
    price = row.get("price") or {}
    if str(price.get("currency") or "HKD") != "HKD":
        return None, [], "currency_mismatch"
    shipping = row.get("shipping_options") or []
    shipping_value = None
    if shipping and isinstance(shipping[0], dict):
        shipping_value = (shipping[0].get("shippingCost") or {}).get("value")
    feedback = (row.get("seller") or {}).get("feedback_percentage")
    flags: list[str] = []
    try:
        if feedback is not None and float(feedback) < 90:
            flags.append("seller_feedback_low")
    except (TypeError, ValueError):
        flags.append("seller_feedback_unknown")
    if row.get("availability") == "unknown":
        flags.append("availability_unknown")
    if price.get("value") is None:
        flags.append("price_unknown")
    evidence: list[Evidence] = []
    for index, item in enumerate(row.get("evidence") or []):
        if not item.get("source_url") or not _allowed_source_url(str(item["source_url"])):
            continue
        evidence.append(Evidence(
            evidence_id=f"{row['listing_id']}:ev:{index}",
            source_id=str(item.get("source_id") or row.get("source_id")),
            source_url=str(item["source_url"]),
            field=str(item.get("field") or "unknown"),
            value=item.get("value"),
            observed_at=str(item.get("observed_at") or "unknown"),
            status=str(item.get("status") or "unknown"),
            confidence=1.0 if item.get("status") == "confirmed" else 0.5,
        ))
    listing = Listing(
        listing_id=str(row["listing_id"]),
        source_id=str(row["source_id"]),
        title=str(row.get("title") or "unknown"),
        url=str(url),
        region="HK",
        currency=str(price.get("currency") or "HKD"),
        price=price.get("value"),
        shipping_cost=shipping_value,
        stock_status={"IN_STOCK": "in_stock", "OUT_OF_STOCK": "out_of_stock"}.get(str(row.get("availability")), "unknown"),
        condition={"New": "new", "Used": "used", "Refurbished": "refurbished"}.get(str(row.get("condition")), "unknown"),
        specs=_extract_specs(str(row.get("title") or "")),
        evidence_ids=tuple(item.evidence_id for item in evidence),
        source_observed_at=str(row.get("source_observed_at") or "unknown"),
        risk_flags=tuple(flags),
    )
    return listing, evidence, None


def run_search(query: str, fixture_path: str | Path | None = None, *, limit: int = 10) -> dict[str, Any]:
    """Run a fully offline search and return serializable result cards."""

    try:
        spec = parse_query(query)
    except PolicyBlockedError as exc:
        return {
            "ok": False,
            "status": "policy_blocked",
            "message": str(exc),
            "search_spec": None,
            "recommended": [],
            "rejected": [],
            "dropped": [],
            "source": "policy.guard",
            "read_only": True,
        }
    connector = EbayBrowseConnector(fixture_path=fixture_path)
    try:
        rows = connector.search(spec.to_dict())
    except ConnectorUnavailable as exc:
        return {
            "ok": False,
            "status": "source_unavailable",
            "message": str(exc),
            "search_spec": spec.to_dict(),
            "recommended": [],
            "rejected": [],
            "dropped": [],
            "source": "ebay.browse.hk.v1",
            "read_only": True,
        }
    listings: list[Listing] = []
    evidence_by_id: dict[str, list[Evidence]] = {}
    dropped: list[dict[str, str]] = []
    for row in rows:
        listing, evidence, reason = _to_listing(row)
        if reason or listing is None:
            dropped.append({"listing_id": str(row.get("listing_id", "unknown")), "reason": reason or "invalid_source_record"})
            continue
        if not _query_matches_title(spec.query, listing.title):
            listing = Listing(
                listing_id=listing.listing_id,
                source_id=listing.source_id,
                title=listing.title,
                url=listing.url,
                region=listing.region,
                currency=listing.currency,
                price=listing.price,
                shipping_cost=listing.shipping_cost,
                tax=listing.tax,
                stock_status=listing.stock_status,
                condition=listing.condition,
                specs=listing.specs,
                product_id=listing.product_id,
                evidence_ids=listing.evidence_ids,
                source_observed_at=listing.source_observed_at,
                risk_flags=tuple((*listing.risk_flags, "query_mismatch")),
            )
        listings.append(listing)
        evidence_by_id[listing.listing_id] = evidence
    accepted, decisions = filter_listings(spec, listings)
    accepted = sorted(accepted, key=lambda item: (item.landed_cost is None, item.landed_cost or 0, item.listing_id))[:limit]
    accepted_ids = {item.listing_id for item in accepted}
    decision_by_id = {item.listing_id: item for item in decisions}
    rejected = [
        {"listing_id": item.listing_id, "reasons": list(decision_by_id[item.listing_id].reasons)}
        for item in listings
        if item.listing_id not in accepted_ids
    ]
    return {
        "ok": True,
        "status": "complete",
        "search_spec": spec.to_dict(),
        "recommended": [build_card(item, evidence_by_id[item.listing_id]).to_dict() for item in accepted],
        "rejected": rejected,
        "dropped": dropped,
        "source": "ebay.browse.hk.v1",
        "read_only": True,
    }

