"""Read-only eBay Browse API connector for Hong Kong hardware discovery.

Fixture mode is the default for local development. Live calls are opt-in and
require official application credentials; the module intentionally exposes no
write operations.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


class ConnectorUnavailable(RuntimeError):
    """Raised when the connector cannot run in the requested read-only mode."""


@dataclass(frozen=True)
class EbayConnectorConfig:
    marketplace_id: str = "EBAY_HK"
    delivery_country: str = "HK"
    api_base: str = "https://api.ebay.com"
    token_url: str = "https://api.ebay.com/identity/v1/oauth2/token"
    timeout_seconds: float = 15.0
    default_limit: int = 20
    default_buying_option: str = "FIXED_PRICE"

    def __post_init__(self) -> None:
        if self.marketplace_id != "EBAY_HK":
            raise ValueError("MVP connector is locked to EBAY_HK")
        if self.delivery_country != "HK":
            raise ValueError("MVP connector is locked to delivery country HK")
        if self.default_buying_option != "FIXED_PRICE":
            raise ValueError("MVP connector is read-only fixed-price search")
        for name, value in (("api_base", self.api_base), ("token_url", self.token_url)):
            parsed = urllib.parse.urlparse(value)
            if parsed.scheme != "https" or parsed.hostname != "api.ebay.com":
                raise ValueError(f"{name} must use the official https://api.ebay.com host")

    @classmethod
    def from_env(cls) -> "EbayConnectorConfig":
        return cls(
            marketplace_id=os.getenv("EBAY_MARKETPLACE_ID", "EBAY_HK"),
            delivery_country=os.getenv("EBAY_DELIVERY_COUNTRY", "HK"),
            api_base=os.getenv("EBAY_API_BASE", "https://api.ebay.com").rstrip("/"),
            token_url=os.getenv("EBAY_TOKEN_URL", "https://api.ebay.com/identity/v1/oauth2/token"),
            timeout_seconds=float(os.getenv("EBAY_TIMEOUT_SECONDS", "15")),
            default_limit=int(os.getenv("EBAY_DEFAULT_LIMIT", "20")),
        )


class EbayBrowseConnector:
    """A read-only implementation of eBay ``item_summary/search``."""

    source_id = "ebay.browse.hk.v1"

    def __init__(
        self,
        config: EbayConnectorConfig | None = None,
        *,
        fixture_path: str | Path | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        opener: Any | None = None,
    ) -> None:
        self.config = config or EbayConnectorConfig.from_env()
        self.fixture_path = Path(fixture_path) if fixture_path else None
        self.client_id = client_id if client_id is not None else os.getenv("EBAY_CLIENT_ID")
        self.client_secret = client_secret if client_secret is not None else os.getenv("EBAY_CLIENT_SECRET")
        self.opener = opener or urllib.request.build_opener()
        self._token: str | None = None

    @property
    def live_enabled(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @staticmethod
    def _fetch_timestamp() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def search(self, search_spec: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Search listings and return canonical-ish dictionaries."""
        live = self.fixture_path is None
        payload = self._load_fixture() if not live else self._live_search(search_spec)
        fetched_at = self._fetch_timestamp() if live else None
        items = payload.get("itemSummaries", [])
        if not isinstance(items, list):
            raise ValueError("eBay response itemSummaries must be a list")
        listings = [self._normalize_item(item, fetched_at=fetched_at) for item in items if isinstance(item, dict)]
        return self._apply_local_constraints(listings, search_spec)

    def _load_fixture(self) -> dict[str, Any]:
        if not self.fixture_path or not self.fixture_path.exists():
            raise ConnectorUnavailable(f"fixture not found: {self.fixture_path}")
        try:
            return json.loads(self.fixture_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConnectorUnavailable(f"invalid eBay fixture: {exc}") from exc

    def _live_search(self, search_spec: Mapping[str, Any]) -> dict[str, Any]:
        if not self.live_enabled:
            raise ConnectorUnavailable(
                "eBay live connector disabled: set EBAY_CLIENT_ID and EBAY_CLIENT_SECRET, "
                "or pass fixture_path for offline mode"
            )
        token = self._application_token()
        params = self._query_params(search_spec)
        url = f"{self.config.api_base}/buy/browse/v1/item_summary/search?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Accept-Language": "zh-HK",
                "X-EBAY-C-MARKETPLACE-ID": self.config.marketplace_id,
                # eBay recommends contextualLocation for more accurate
                # delivery estimates; HK does not use postal codes here.
                "X-EBAY-C-ENDUSERCTX": "contextualLocation=country%3DHK",
            },
        )
        try:
            with self.opener.open(request, timeout=self.config.timeout_seconds) as response:
                status = getattr(response, "status", 200)
                body = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise ConnectorUnavailable(f"eBay Browse API HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ConnectorUnavailable(f"eBay Browse API unavailable: {exc}") from exc
        if status >= 400:
            raise ConnectorUnavailable(f"eBay Browse API HTTP {status}")
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ConnectorUnavailable("eBay Browse API returned invalid JSON") from exc

    def _application_token(self) -> str:
        if self._token:
            return self._token
        raw = f"{self.client_id}:{self.client_secret}".encode("utf-8")
        auth = base64.b64encode(raw).decode("ascii")
        data = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "scope": "https://api.ebay.com/oauth/api_scope",
        }).encode("ascii")
        request = urllib.request.Request(
            self.config.token_url,
            data=data,
            method="POST",
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        try:
            with self.opener.open(request, timeout=self.config.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            raise ConnectorUnavailable(f"eBay OAuth token request failed: {exc}") from exc
        token = payload.get("access_token")
        if not token:
            raise ConnectorUnavailable("eBay OAuth response did not contain access_token")
        self._token = str(token)
        return self._token

    def _query_params(self, search_spec: Mapping[str, Any]) -> dict[str, str]:
        query = str(
            search_spec.get("query")
            or search_spec.get("keywords")
            or search_spec.get("text")
            or "computer hardware"
        ).strip()
        if not query:
            raise ValueError("SearchSpec query cannot be empty")
        limit = int(search_spec.get("limit", self.config.default_limit))
        limit = max(1, min(limit, 200))
        params: dict[str, str] = {"q": query, "limit": str(limit)}
        if search_spec.get("offset") is not None:
            params["offset"] = str(max(0, int(search_spec["offset"])))
        category_id = search_spec.get("category_id") or search_spec.get("categoryId")
        if category_id:
            params["category_ids"] = str(category_id)
        params["filter"] = ",".join([
            f"deliveryCountry:{self.config.delivery_country}",
            f"buyingOptions:{{{self.config.default_buying_option}}}",
        ])
        return params

    def _normalize_item(self, item: Mapping[str, Any], *, fetched_at: str | None = None) -> dict[str, Any]:
        price = item.get("price") if isinstance(item.get("price"), dict) else {}
        seller = item.get("seller") if isinstance(item.get("seller"), dict) else {}
        shipping = item.get("shippingOptions")
        if not isinstance(shipping, list):
            shipping = []
        observed_at = item.get("itemCreationDate") or fetched_at
        evidence_fields = {
            "title": item.get("title"),
            "url": item.get("itemWebUrl"),
            "price": price,
            "condition": item.get("condition"),
            "seller": seller,
            "shippingOptions": shipping,
        }
        evidence = [
            {
                "field": field,
                "value": value,
                "source_id": self.source_id,
                "source_url": item.get("itemWebUrl"),
                "observed_at": observed_at,
                "status": "confirmed" if value not in (None, "", [], {}) else "unknown",
            }
            for field, value in evidence_fields.items()
        ]
        value = price.get("value")
        try:
            numeric_price = float(value) if value is not None else None
        except (TypeError, ValueError):
            numeric_price = None
        return {
            "source_id": self.source_id,
            "listing_id": item.get("itemId"),
            "title": item.get("title"),
            "url": item.get("itemWebUrl"),
            "price": {"value": numeric_price, "currency": price.get("currency")},
            "condition": item.get("condition") or "unknown",
            "availability": item.get("estimatedAvailabilityStatus") or "unknown",
            "seller": {
                "username": seller.get("username"),
                "feedback_percentage": seller.get("feedbackPercentage"),
            },
            "shipping_options": shipping,
            "source_observed_at": observed_at,
            "evidence": evidence,
            "raw": dict(item),
        }

    @staticmethod
    def _apply_local_constraints(
        listings: list[dict[str, Any]], search_spec: Mapping[str, Any]
    ) -> list[dict[str, Any]]:
        budget = search_spec.get("budget_max")
        if budget is None and isinstance(search_spec.get("budget"), dict):
            budget = search_spec["budget"].get("max")
        if budget is None:
            return listings
        try:
            max_price = float(budget)
        except (TypeError, ValueError):
            return listings
        filtered: list[dict[str, Any]] = []
        for listing in listings:
            value = listing.get("price", {}).get("value")
            if value is None or float(value) <= max_price:
                filtered.append(listing)
        return filtered

