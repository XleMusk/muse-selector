import json
import os
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen
from unittest.mock import patch

from muse_selector.web import capability_snapshot, make_handler, render_html, serve


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "ebay_hk_sample.json"


class WebTests(unittest.TestCase):
    def test_render_escapes_query_and_shows_read_only_fields(self):
        payload = {"ok": True, "search_spec": {"region": "HK", "currency": "HKD", "budget_max": "7000"}, "recommended": [], "rejected": [], "dropped": []}
        page = render_html(payload, "<script>alert(1)</script>")
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("只读结果页", page)
        self.assertNotIn("<script>alert(1)</script>", page)

    def test_render_shows_evidence_observed_at(self):
        payload = {
            "ok": True,
            "search_spec": {"region": "HK", "currency": "HKD", "budget_max": "7000"},
            "recommended": [{
                "title": "Mini PC",
                "landed_cost": "4999.00",
                "cost_status": "partial",
                "cost_basis": "item_price_plus_shipping",
                "shipping_cost": "0.00",
                "tax": None,
                "evidence_coverage": 1.0,
                "currency": "HKD",
                "source_id": "ebay.browse.hk.v1",
                "source_rank": 1,
                "fit_score": 100.0,
                "fit_breakdown": {"policy": "source_order_preserved"},
                "source_observed_at": "2026-10-24T04:00:00Z",
                "stock_status": "in_stock",
                "condition": "new",
                "specs": {},
                "risk_flags": [],
                "url": "https://www.ebay.com.hk/itm/live-1",
                "evidence": [{
                    "field": "price",
                    "value": "4999.00",
                    "status": "confirmed",
                    "observed_at": "2026-10-24T04:00:00Z",
                    "source_url": "https://www.ebay.com.hk/itm/live-1",
                }],
            }],
            "rejected": [],
            "dropped": [],
        }
        page = render_html(payload, "mini pc")
        self.assertIn("已知费用小计", page)
        self.assertIn("基准：item_price_plus_shipping", page)
        self.assertIn("来源标识：<code>ebay.browse.hk.v1</code>", page)
        self.assertIn("来源顺序：1", page)
        self.assertIn("source_order_preserved", page)
        self.assertIn("运费/税费：0.00 / unknown HKD", page)
        self.assertIn("关键字段证据覆盖率：100.0%", page)
        self.assertIn("观测时间：2026-10-24T04:00:00Z", page)
        self.assertIn("证据：4999.00", page)

    def test_render_replaces_untrusted_href(self):
        payload = {
            "ok": True,
            "search_spec": {"region": "HK", "currency": "HKD", "budget_max": "7000", "query": "mini pc"},
            "recommended": [{"title": "unsafe", "url": "javascript:alert(1)", "source_id": "x", "currency": "HKD", "landed_cost": "1", "evidence": [], "risk_flags": []}],
            "rejected": [],
            "dropped": [],
        }
        page = render_html(payload, "mini pc")
        self.assertNotIn("javascript:alert(1)", page)
        self.assertIn("href=' #'".replace(" ", ""), page)

    def test_render_shows_safe_link_only_entries(self):
        payload = {
            "ok": False,
            "status": "source_unavailable",
            "message": "官方挂牌搜索尚未接入",
            "link_only": [
                {
                    "source_id": "xianyu.partner.v1",
                    "display_name": "闲鱼",
                    "status": "link_only",
                    "entry_url": "https://www.goofish.com/",
                    "manual_query": "国内 RTX 4070",
                    "instruction": "请手动搜索",
                    "read_only": True,
                },
                {
                    "source_id": "bad",
                    "display_name": "bad",
                    "entry_url": "javascript:alert(1)",
                    "manual_query": "unsafe",
                },
            ],
        }
        page = render_html(payload, "国内 RTX 4070")
        self.assertIn("人工接管入口", page)
        self.assertIn("https://www.goofish.com/", page)
        self.assertIn("国内 RTX 4070", page)
        self.assertNotIn("javascript:alert(1)", page)

    def test_local_server_health_and_result_page(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(FIXTURE))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            with urlopen(base + "/healthz", timeout=2) as response:
                health = json.loads(response.read().decode("utf-8"))
            self.assertEqual(health, {"ok": True, "read_only": True})
            with urlopen(base + "/?q=%E9%A6%99%E6%B8%AF%E9%A2%84%E7%AE%97%20HKD%207000%20%E4%BB%A5%E5%86%85%E7%9A%84%E8%BF%B7%E4%BD%A0%E4%B8%BB%E6%9C%BA", timeout=2) as response:
                page = response.read().decode("utf-8")
            self.assertIn("Mini PC Ryzen 7", page)
            self.assertIn("证据", page)
            self.assertIn("没有登录、购买或写操作能力", page)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_capability_snapshot_is_local_and_reports_source_readiness(self):
        with patch.dict(
            os.environ,
            {"EBAY_ENVIRONMENT": "sandbox", "EBAY_CLIENT_ID": "", "EBAY_CLIENT_SECRET": ""},
            clear=False,
        ):
            snapshot = capability_snapshot()
        self.assertTrue(snapshot["ok"])
        self.assertTrue(snapshot["read_only"])
        self.assertEqual(snapshot["sources"]["ebay.browse.hk.v1"]["environment"], "sandbox")
        self.assertEqual(snapshot["sources"]["ebay.browse.hk.v1"]["credential_state"], "missing")
        self.assertEqual(snapshot["sources"]["xianyu.partner.v1"]["status"], "link_only")
        self.assertEqual(snapshot["sources"]["zhuanzhuan.recommerce.mcp.v1"]["status"], "auxiliary_only")

    def test_capability_endpoint_does_not_require_network_or_credentials(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(FIXTURE))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.dict(
                os.environ,
                {"EBAY_ENVIRONMENT": "sandbox", "EBAY_CLIENT_ID": "", "EBAY_CLIENT_SECRET": ""},
                clear=False,
            ):
                with urlopen(f"http://127.0.0.1:{server.server_port}/api/capabilities", timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    content_type = response.headers.get_content_type()
            self.assertEqual(content_type, "application/json")
            self.assertTrue(payload["read_only"])
            self.assertEqual(payload["sources"]["ebay.browse.hk.v1"]["status"], "credential_unavailable")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_local_server_json_search_endpoint_reuses_read_only_pipeline(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(FIXTURE))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = (
                f"http://127.0.0.1:{server.server_port}/api/search"
                "?q=%E9%A6%99%E6%B8%AF%E9%A2%84%E7%AE%97%20HKD%207000%20%E4%BB%A5%E5%86%85%E7%9A%84%E8%BF%B7%E4%BD%A0%E4%B8%BB%E6%9C%BA&limit=1"
            )
            with urlopen(url, timeout=2) as response:
                self.assertEqual(response.headers.get_content_type(), "application/json")
                payload = json.loads(response.read().decode("utf-8"))
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["read_only"])
            self.assertEqual(len(payload["recommended"]), 1)
            self.assertEqual(payload["recommended"][0]["source_id"], "ebay.browse.hk.v1")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_json_search_endpoint_reports_invalid_limit_without_side_effects(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(FIXTURE))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_port}/api/search?q=mini%20pc&limit=nope"
            with urlopen(url, timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["status"], "invalid_query")
            self.assertTrue(payload["read_only"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_live_handler_without_credentials_is_read_only_error(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(None))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urlopen(f"http://127.0.0.1:{server.server_port}/?q=%E9%A6%99%E6%B8%AF%E9%A2%84%E7%AE%97%20HKD%207000%20%E4%BB%A5%E5%86%85%E7%9A%84%E8%BF%B7%E4%BD%A0%E4%B8%BB%E6%9C%BA", timeout=2) as response:
                page = response.read().decode("utf-8")
            self.assertIn("source_unavailable", page)
            self.assertIn("只读结果页", page)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_local_server_rejects_non_loopback_bind_hosts(self):
        with self.assertRaises(ValueError):
            serve(FIXTURE, host="0.0.0.0", port=0)


if __name__ == "__main__":
    unittest.main()

