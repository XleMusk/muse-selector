"""Read-only client for the official Zhuanzhuan transfer MCP server.

The public Zhuanzhuan MCP server exposes two auxiliary capabilities that are
useful for mainland second-hand hardware discovery: ``recycle_valuation`` and
``open_recycle_entry``.  It is not a marketplace listing search API.  This
module speaks the official Streamable HTTP MCP protocol and deliberately
exposes only those two read-only tools.
"""

from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .ebay import ConnectorUnavailable, _NoRedirectHandler


_OFFICIAL_HOST = "mcp.zhuanzhuan.com"
_OFFICIAL_PATH = "/zai/zai-transfer"
_PROTOCOL_VERSION = "2025-11-25"
_VALUATION_STATUSES = {"valued", "need_input", "handoff", "degraded", "conflict", "failed"}
_MAX_RESPONSE_BYTES = 2_000_000


def _safe_http_url(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise ValueError(f"{name} must be an absolute HTTP(S) URL")
    parsed = urllib.parse.urlparse(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"{name} must be an absolute HTTP(S) URL") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 80, 443)
        or parsed.fragment
    ):
        raise ValueError(f"{name} must be an absolute HTTP(S) URL")
    return value


def _non_empty_text(value: Any, name: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    value = value.strip()
    if len(value) > maximum:
        raise ValueError(f"{name} exceeds the {maximum}-character limit")
    return value


@dataclass(frozen=True)
class ZhuanzhuanMcpConfig:
    """Fixed official endpoint and bounded MCP client settings."""

    endpoint: str = f"https://{_OFFICIAL_HOST}{_OFFICIAL_PATH}"
    timeout_seconds: float = 30.0
    protocol_version: str = _PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if self.protocol_version != _PROTOCOL_VERSION:
            raise ValueError(f"protocol_version must be {_PROTOCOL_VERSION}")
        if (
            not isinstance(self.timeout_seconds, (int, float))
            or isinstance(self.timeout_seconds, bool)
            or not math.isfinite(float(self.timeout_seconds))
            or self.timeout_seconds <= 0
            or self.timeout_seconds > 120
        ):
            raise ValueError("timeout_seconds must be a finite number between 0 and 120")
        parsed = urllib.parse.urlparse(self.endpoint)
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("endpoint must use the official Zhuanzhuan MCP endpoint") from exc
        if (
            parsed.scheme != "https"
            or parsed.hostname != _OFFICIAL_HOST
            or parsed.username is not None
            or parsed.password is not None
            or port not in (None, 443)
            or parsed.path.rstrip("/") != _OFFICIAL_PATH.rstrip("/")
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("endpoint must use the official Zhuanzhuan MCP endpoint")

    @classmethod
    def from_env(cls) -> "ZhuanzhuanMcpConfig":
        return cls(
            endpoint=os.getenv("ZHUANZHUAN_MCP_ENDPOINT", f"https://{_OFFICIAL_HOST}{_OFFICIAL_PATH}"),
            timeout_seconds=float(os.getenv("ZHUANZHUAN_MCP_TIMEOUT_SECONDS", "30")),
        )


class ZhuanzhuanMcpConnector:
    """Official, read-only Zhuanzhuan MCP tool client."""

    source_id = "zhuanzhuan.recommerce.mcp.v1"
    _TOOLS = {"recycle_valuation", "open_recycle_entry"}

    def __init__(
        self,
        config: ZhuanzhuanMcpConfig | None = None,
        *,
        token: str | None = None,
        opener: Any | None = None,
        client_name: str = "muse-selector",
        client_version: str = "0.1.0",
    ) -> None:
        self.config = config or ZhuanzhuanMcpConfig.from_env()
        self.token = token if token is not None else os.getenv("ZHUANZHUAN_MCP_TOKEN")
        self.opener = opener or urllib.request.build_opener(_NoRedirectHandler())
        self.client_name = _non_empty_text(client_name, "client_name", maximum=100)
        self.client_version = _non_empty_text(client_version, "client_version", maximum=100)
        self._session_id: str | None = None
        self._initialized = False

    @property
    def live_enabled(self) -> bool:
        return bool(isinstance(self.token, str) and self.token.strip())

    @staticmethod
    def _kill_switch_active() -> bool:
        return os.getenv("MUSE_SOURCE_ZHUANZHUAN_RECOMMERCE_MCP_DISABLED", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def _redact_error(self, message: Any) -> str:
        text = str(message)
        token = self.token
        if token:
            text = text.replace(str(token), "[redacted]")
        return text[:500]

    @staticmethod
    def _response_status(response: Any, context: str) -> int:
        status = getattr(response, "status", 200)
        if isinstance(status, bool) or not isinstance(status, int) or not 100 <= status <= 599:
            raise ConnectorUnavailable(f"Zhuanzhuan MCP {context} returned an invalid HTTP status")
        return status

    def _headers(self, *, accept: str = "application/json, text/event-stream") -> dict[str, str]:
        if not self.live_enabled:
            raise ConnectorUnavailable("Zhuanzhuan MCP disabled: set ZHUANZHUAN_MCP_TOKEN")
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": accept,
            "Content-Type": "application/json",
            "MCP-Protocol-Version": self.config.protocol_version,
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    def _post(self, payload: Mapping[str, Any], *, context: str, notification: bool = False) -> Any:
        request = urllib.request.Request(
            self.config.endpoint,
            data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            method="POST",
            headers=self._headers(accept="application/json, text/event-stream"),
        )
        try:
            with self.opener.open(request, timeout=self.config.timeout_seconds) as response:
                status = self._response_status(response, context)
                body = response.read(_MAX_RESPONSE_BYTES + 1)
                session_id = response.headers.get("Mcp-Session-Id") if getattr(response, "headers", None) else None
        except urllib.error.HTTPError as exc:
            detail = exc.read(_MAX_RESPONSE_BYTES).decode("utf-8", errors="replace")
            raise ConnectorUnavailable(self._redact_error(f"Zhuanzhuan MCP {context} HTTP {exc.code}: {detail}")) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ConnectorUnavailable(self._redact_error(f"Zhuanzhuan MCP {context} unavailable: {exc}")) from exc
        if len(body) > _MAX_RESPONSE_BYTES:
            raise ConnectorUnavailable(f"Zhuanzhuan MCP {context} response exceeded the size limit")
        if status >= 400:
            raise ConnectorUnavailable(f"Zhuanzhuan MCP {context} HTTP {status}")
        if session_id:
            self._session_id = str(session_id)
        if notification or status == 202 or not body:
            return None
        return self._decode_message(body, context)

    @staticmethod
    def _decode_message(body: bytes, context: str) -> Mapping[str, Any]:
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ConnectorUnavailable(f"Zhuanzhuan MCP {context} returned invalid UTF-8") from exc
        candidates = [text]
        # Streamable HTTP may use a single SSE message.  Parse only data lines
        # and keep the first JSON-RPC object; never execute or interpret text.
        data_lines = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
        if data_lines:
            candidates = data_lines
        for candidate in candidates:
            if not candidate or candidate == "[DONE]":
                continue
            try:
                payload = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, Mapping):
                return payload
        raise ConnectorUnavailable(f"Zhuanzhuan MCP {context} returned invalid JSON-RPC data")

    def _initialize(self) -> None:
        if self._initialized:
            return
        response = self._post(
            {
                "jsonrpc": "2.0",
                "id": "muse-init",
                "method": "initialize",
                "params": {
                    "protocolVersion": self.config.protocol_version,
                    "capabilities": {},
                    "clientInfo": {"name": self.client_name, "version": self.client_version},
                },
            },
            context="initialize",
        )
        if not isinstance(response, Mapping):
            raise ConnectorUnavailable("Zhuanzhuan MCP initialize returned an invalid response")
        if response.get("error"):
            raise ConnectorUnavailable(self._redact_error(f"Zhuanzhuan MCP initialize failed: {response['error']}"))
        result = response.get("result")
        if not isinstance(result, Mapping):
            raise ConnectorUnavailable("Zhuanzhuan MCP initialize returned no result")
        # The server may omit a session id for stateless Streamable HTTP.  A
        # separate initialized flag prevents repeating initialize without
        # sending a synthetic session header to the stateless server.
        self._initialized = True
        self._post(
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            context="initialized",
            notification=True,
        )

    def _call_tool(self, name: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        if name not in self._TOOLS:
            raise ValueError(f"unsupported Zhuanzhuan MCP tool: {name}")
        if self._kill_switch_active():
            raise ConnectorUnavailable("Zhuanzhuan MCP disabled by source kill switch")
        if not self.live_enabled:
            raise ConnectorUnavailable("Zhuanzhuan MCP disabled: set ZHUANZHUAN_MCP_TOKEN")
        self._initialize()
        response = self._post(
            {
                "jsonrpc": "2.0",
                "id": f"muse-{name}-{int(time.time() * 1000)}",
                "method": "tools/call",
                "params": {"name": name, "arguments": dict(arguments)},
            },
            context=name,
        )
        if not isinstance(response, Mapping):
            raise ConnectorUnavailable(f"Zhuanzhuan MCP {name} returned an invalid response")
        if response.get("error"):
            raise ConnectorUnavailable(self._redact_error(f"Zhuanzhuan MCP {name} failed: {response['error']}"))
        result = response.get("result")
        if not isinstance(result, Mapping):
            raise ConnectorUnavailable(f"Zhuanzhuan MCP {name} returned no result")
        if result.get("isError"):
            raise ConnectorUnavailable(self._redact_error(f"Zhuanzhuan MCP {name} returned an error result"))
        return self._extract_tool_payload(result, name)

    @classmethod
    def _extract_tool_payload(cls, result: Mapping[str, Any], name: str) -> Mapping[str, Any]:
        structured = result.get("structuredContent")
        if isinstance(structured, Mapping):
            payload: Any = structured
        else:
            payload = None
            content = result.get("content")
            if isinstance(content, list):
                for item in content:
                    if not isinstance(item, Mapping):
                        continue
                    if isinstance(item.get("json"), Mapping):
                        payload = item["json"]
                        break
                    if item.get("type") == "text" and isinstance(item.get("text"), str):
                        try:
                            candidate = json.loads(item["text"])
                        except json.JSONDecodeError:
                            continue
                        if isinstance(candidate, Mapping):
                            payload = candidate
                            break
        if not isinstance(payload, Mapping):
            raise ConnectorUnavailable(f"Zhuanzhuan MCP {name} returned no structured payload")
        return dict(payload)

    @staticmethod
    def _validate_image_urls(image_urls: Sequence[str] | None) -> list[str]:
        if image_urls is None:
            return []
        if isinstance(image_urls, (str, bytes)) or not isinstance(image_urls, Sequence):
            raise ValueError("image_urls must be a sequence of HTTP(S) URLs")
        if len(image_urls) > 35:
            raise ValueError("image_urls cannot contain more than 35 URLs")
        return [_safe_http_url(url, "image_url") for url in image_urls]

    @staticmethod
    def _validate_attributes(value: Mapping[str, str] | None) -> dict[str, str]:
        if value is None:
            return {}
        if not isinstance(value, Mapping) or len(value) > 50:
            raise ValueError("confirmed_attributes must be an object with at most 50 entries")
        result: dict[str, str] = {}
        for key, item in value.items():
            key_text = _non_empty_text(key, "confirmed_attributes key", maximum=200)
            result[key_text] = _non_empty_text(item, f"confirmed_attributes[{key_text}]", maximum=2000)
        return result

    def recycle_valuation(
        self,
        query: str = "",
        *,
        image_urls: Sequence[str] | None = None,
        confirmed_attributes: Mapping[str, str] | None = None,
        continuation_token: str | None = None,
    ) -> dict[str, Any]:
        """Identify a product and obtain an official CNY recycle estimate."""

        if not isinstance(query, str):
            raise ValueError("query must be a string")
        query = query.strip()
        if len(query) > 2000:
            raise ValueError("query exceeds the 2000-character limit")
        images = self._validate_image_urls(image_urls)
        if not query and not images:
            raise ValueError("query or image_urls must be provided")
        if continuation_token is not None:
            continuation_token = _non_empty_text(continuation_token, "continuation_token", maximum=2048)
        payload = self._call_tool(
            "recycle_valuation",
            {
                "query": query,
                "image_urls": images,
                "confirmed_attributes": self._validate_attributes(confirmed_attributes),
                "continuation_token": continuation_token,
            },
        )
        return self._normalize_valuation(payload)

    def open_recycle_entry(
        self,
        *,
        jump_url: str | None = None,
        model_id: int | str | None = None,
        product_id: int | str | None = None,
        cate_id: int | str | None = None,
        brand_id: int | str | None = None,
        query: str = "",
    ) -> dict[str, Any]:
        """Return a user-opened recycle handoff URL; never submits an order."""

        if jump_url is not None:
            jump_url = _safe_http_url(jump_url, "jump_url")
        if query is None or not isinstance(query, str):
            raise ValueError("query must be a string")
        query = query.strip()
        if len(query) > 200:
            raise ValueError("query exceeds the 200-character limit")
        payload = self._call_tool(
            "open_recycle_entry",
            {
                "jumpUrl": jump_url,
                "modelId": model_id,
                "productId": product_id,
                "cateId": cate_id,
                "brandId": brand_id,
                "query": query,
            },
        )
        return self._normalize_entry(payload)

    def _normalize_valuation(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        data = payload.get("data")
        data = data if isinstance(data, Mapping) else {}
        status = data.get("status") if data.get("status") in _VALUATION_STATUSES else "failed"
        product = data.get("product") if isinstance(data.get("product"), Mapping) else None
        price = data.get("price") if isinstance(data.get("price"), Mapping) else None
        handoff = data.get("handoff") if isinstance(data.get("handoff"), Mapping) else None
        warnings = data.get("warnings") if isinstance(data.get("warnings"), list) else []
        required_inputs = data.get("required_inputs") if isinstance(data.get("required_inputs"), list) else []
        return {
            "source_id": self.source_id,
            "capability": "recycle_valuation",
            "ok": payload.get("code", 0) == 0 and status != "failed",
            "code": payload.get("code"),
            "message": payload.get("message") or "unknown",
            "run_id": data.get("run_id"),
            "status": status,
            "product": dict(product) if product is not None else None,
            "price": dict(price) if price is not None else None,
            "required_inputs": list(required_inputs),
            "handoff": dict(handoff) if handoff is not None else None,
            "warnings": [str(item) for item in warnings],
            "trace_id": data.get("trace_id"),
            "observed_at": self._timestamp(),
            "currency": (price or {}).get("currency", "CNY") if isinstance(price or {}, Mapping) else "CNY",
            "read_only": True,
        }

    def _normalize_entry(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        data = payload.get("data")
        data = data if isinstance(data, Mapping) else {}
        jump_url = data.get("jumpUrl")
        if jump_url is not None:
            try:
                jump_url = _safe_http_url(jump_url, "data.jumpUrl")
            except ValueError:
                jump_url = None
        return {
            "source_id": self.source_id,
            "capability": "open_recycle_entry",
            "ok": payload.get("code", 0) == 0 and bool(jump_url),
            "code": payload.get("code"),
            "message": payload.get("message") or "unknown",
            "jump_url": jump_url,
            "entry_type": data.get("entryType"),
            "tips": data.get("tips"),
            "observed_at": self._timestamp(),
            "read_only": True,
        }

