from __future__ import annotations

import json
import unittest
from urllib.parse import urlparse

from muse_selector.connectors.ebay import ConnectorUnavailable
from muse_selector.connectors.zhuanzhuan import ZhuanzhuanMcpConfig, ZhuanzhuanMcpConnector


class _Response:
    def __init__(self, payload, *, status=200, headers=None):
        self.status = status
        self.headers = headers or {}
        if isinstance(payload, bytes):
            self._body = payload
        elif payload is None:
            self._body = b""
        else:
            self._body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def read(self, amount=None):
        return self._body if amount is None else self._body[:amount]

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class _Opener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        return self.responses.pop(0)


class ZhuanzhuanConnectorTests(unittest.TestCase):
    def test_endpoint_is_fixed_to_official_gateway(self):
        with self.assertRaises(ValueError):
            ZhuanzhuanMcpConfig(endpoint="https://example.com/zai/zai-transfer")
        self.assertEqual(urlparse(ZhuanzhuanMcpConfig().endpoint).hostname, "mcp.zhuanzhuan.com")

    def test_missing_token_fails_before_network(self):
        opener = _Opener([])
        connector = ZhuanzhuanMcpConnector(token=None, opener=opener)
        with self.assertRaisesRegex(ConnectorUnavailable, "ZHUANZHUAN_MCP_TOKEN"):
            connector.recycle_valuation("iPhone 15 Pro")
        self.assertEqual(opener.requests, [])

    def test_valuation_uses_official_mcp_tools_call_and_normalizes_payload(self):
        opener = _Opener([
            _Response(
                {"jsonrpc": "2.0", "id": "muse-init", "result": {"protocolVersion": "2025-11-25"}},
                headers={"Mcp-Session-Id": "session-1"},
            ),
            _Response(None, status=202),
            _Response(
                {
                    "jsonrpc": "2.0",
                    "id": "muse-call",
                    "result": {
                        "structuredContent": {
                            "code": 0,
                            "message": "success",
                            "data": {
                                "run_id": "run-1",
                                "status": "valued",
                                "product": {"display_name": "ThinkPad X1", "confidence": 0.96},
                                "price": {"min_value": "2100", "max_value": "2600", "currency": "CNY"},
                                "warnings": [],
                            },
                        }
                    },
                }
            ),
        ])
        connector = ZhuanzhuanMcpConnector(token="token-value", opener=opener)
        result = connector.recycle_valuation("ThinkPad X1 Carbon，16GB，成色良好")
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "valued")
        self.assertEqual(result["price"]["currency"], "CNY")
        self.assertTrue(result["read_only"])
        call_payload = json.loads(opener.requests[2][0].data.decode("utf-8"))
        self.assertEqual(call_payload["method"], "tools/call")
        self.assertEqual(call_payload["params"]["name"], "recycle_valuation")
        self.assertEqual(opener.requests[2][0].headers["Mcp-session-id"], "session-1")

    def test_sse_text_payload_and_entry_url_are_supported(self):
        sse = b"event: message\ndata: {\"jsonrpc\":\"2.0\",\"id\":\"muse-call\",\"result\":{\"content\":[{\"type\":\"text\",\"text\":\"{\\\"code\\\":0,\\\"message\\\":\\\"success\\\",\\\"data\\\":{\\\"jumpUrl\\\":\\\"https://www.zhuanzhuan.com/recycle/1\\\",\\\"entryType\\\":\\\"h5\\\"}}\"}]}}\n\n"
        opener = _Opener([_Response({"jsonrpc": "2.0", "id": "muse-init", "result": {}}, headers={"Mcp-Session-Id": "session-1"}), _Response(None, status=202), _Response(sse)])
        connector = ZhuanzhuanMcpConnector(token="token-value", opener=opener)
        result = connector.open_recycle_entry(query="ThinkPad X1")
        self.assertTrue(result["ok"])
        self.assertEqual(result["jump_url"], "https://www.zhuanzhuan.com/recycle/1")

    def test_valuation_input_limits_are_enforced(self):
        connector = ZhuanzhuanMcpConnector(token="token-value", opener=_Opener([]))
        with self.assertRaises(ValueError):
            connector.recycle_valuation("")
        with self.assertRaises(ValueError):
            connector.recycle_valuation("x", image_urls=["ftp://invalid.example/image.jpg"])
        with self.assertRaises(ValueError):
            connector.open_recycle_entry(jump_url="https://example.com:8443/unsafe")

    def test_kill_switch_fails_closed(self):
        import os

        old = os.environ.get("MUSE_SOURCE_ZHUANZHUAN_RECOMMERCE_MCP_DISABLED")
        os.environ["MUSE_SOURCE_ZHUANZHUAN_RECOMMERCE_MCP_DISABLED"] = "1"
        try:
            connector = ZhuanzhuanMcpConnector(token="token-value", opener=_Opener([]))
            with self.assertRaisesRegex(ConnectorUnavailable, "kill switch"):
                connector.recycle_valuation("iPhone 15 Pro")
        finally:
            if old is None:
                os.environ.pop("MUSE_SOURCE_ZHUANZHUAN_RECOMMERCE_MCP_DISABLED", None)
            else:
                os.environ["MUSE_SOURCE_ZHUANZHUAN_RECOMMERCE_MCP_DISABLED"] = old


if __name__ == "__main__":
    unittest.main()

