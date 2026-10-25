import json
import os
import sys
import threading
import tempfile
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen
from unittest.mock import patch

from muse_selector.web import capability_snapshot, main, make_handler, render_html, serve
from muse_selector.contracts import RESULT_SCHEMA_VERSION
from muse_selector.persistence import SelectorStore


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "ebay_hk_sample.json"


class WebTests(unittest.TestCase):
    def test_cli_environment_is_temporary_and_restored(self):
        with patch.dict(os.environ, {"EBAY_ENVIRONMENT": "production"}, clear=False):
            with patch("muse_selector.web.serve", side_effect=KeyboardInterrupt):
                with patch.object(sys, "argv", ["muse-selector-web", "--environment", "sandbox"]):
                    with self.assertRaises(KeyboardInterrupt):
                        main()
            self.assertEqual(os.environ["EBAY_ENVIRONMENT"], "production")

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

    def test_render_shows_escaped_source_metadata(self):
        payload = {
            "ok": True,
            "source": "ebay.browse.hk.v1",
            "source_metadata": {
                "href": "https://api.ebay.com/buy/browse/v1/item_summary/search?q=mini%20pc",
                "total": 5,
                "next": None,
                "untrusted": "</pre><script>alert(1)</script>",
            },
            "search_spec": {"region": "HK", "currency": "HKD", "budget_max": "7000"},
            "recommended": [],
            "rejected": [],
            "dropped": [],
        }
        page = render_html(payload, "mini pc")
        self.assertIn("来源元数据", page)
        self.assertIn("https://api.ebay.com/buy/browse/v1/item_summary/search", page)
        self.assertIn("&quot;total&quot;: 5", page)
        self.assertNotIn("<script>alert(1)</script>", page)

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
            self.assertEqual(health["schema_version"], RESULT_SCHEMA_VERSION)
            self.assertTrue(health["ok"])
            self.assertTrue(health["read_only"])
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
        self.assertEqual(snapshot["schema_version"], RESULT_SCHEMA_VERSION)
        self.assertTrue(snapshot["read_only"])
        self.assertEqual(snapshot["sources"]["ebay.browse.hk.v1"]["environment"], "sandbox")
        self.assertEqual(snapshot["sources"]["ebay.browse.hk.v1"]["api_host"], "api.sandbox.ebay.com")
        self.assertEqual(snapshot["sources"]["ebay.browse.hk.v1"]["token_path"], "/identity/v1/oauth2/token")
        self.assertEqual(snapshot["sources"]["ebay.browse.hk.v1"]["credential_env"]["scoped"][0], "EBAY_SANDBOX_CLIENT_ID")
        self.assertEqual(snapshot["sources"]["ebay.browse.hk.v1"]["credential_state"], "missing")
        self.assertEqual(snapshot["sources"]["xianyu.partner.v1"]["status"], "link_only")
        self.assertEqual(snapshot["sources"]["zhuanzhuan.recommerce.mcp.v1"]["status"], "auxiliary_only")

    def test_capability_snapshot_reports_selected_environment_credentials(self):
        with patch.dict(
            os.environ,
            {
                "EBAY_ENVIRONMENT": "sandbox",
                "EBAY_CLIENT_ID": "",
                "EBAY_CLIENT_SECRET": "",
                "EBAY_SANDBOX_CLIENT_ID": "sandbox-id",
                "EBAY_SANDBOX_CLIENT_SECRET": "sandbox-secret",
            },
            clear=False,
        ):
            snapshot = capability_snapshot()
        self.assertEqual(snapshot["sources"]["ebay.browse.hk.v1"]["credential_state"], "present")
        self.assertEqual(snapshot["sources"]["ebay.browse.hk.v1"]["credential_env"]["scoped"][1], "EBAY_SANDBOX_CLIENT_SECRET")
        self.assertEqual(snapshot["sources"]["ebay.browse.hk.v1"]["status"], "ready")

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
            self.assertEqual(payload["sources"]["ebay.browse.hk.v1"]["api_host"], "api.sandbox.ebay.com")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_watch_endpoint_returns_saved_snapshot_without_refreshing(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SelectorStore(Path(directory) / "selector.sqlite3")
            watch_id = store.add_watch(
                "香港预算 HKD 7000 以内的迷你主机",
                FIXTURE,
                watch_id="watch_web",
            )
            refreshed = store.refresh_watch(watch_id)
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(FIXTURE, store))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with patch("muse_selector.web.run_search", side_effect=AssertionError("watch endpoint refreshed")):
                    with urlopen(
                        f"http://127.0.0.1:{server.server_port}/api/watch?watch_id={watch_id}",
                        timeout=2,
                    ) as response:
                        self.assertEqual(response.headers.get_content_type(), "application/json")
                        payload = json.loads(response.read().decode("utf-8"))
                self.assertTrue(payload["ok"])
                self.assertTrue(payload["read_only"])
                self.assertEqual(payload["schema_version"], RESULT_SCHEMA_VERSION)
                self.assertEqual(payload["status"], "watch_ready")
                self.assertEqual(payload["watch"]["last_run_id"], refreshed["run_id"])
                self.assertEqual(payload["watch"]["last_change_summary"], refreshed["change_summary"])
                self.assertEqual(payload["payload"], refreshed["payload"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_watches_endpoint_lists_saved_watches_without_refreshing(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SelectorStore(Path(directory) / "selector.sqlite3")
            store.add_watch(
                "香港预算 HKD 7000 以内的迷你主机",
                FIXTURE,
                watch_id="watch_one",
            )
            store.add_watch(
                "香港 RTX 4070 显卡，预算 HKD 9000",
                FIXTURE,
                watch_id="watch_two",
            )
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(FIXTURE, store))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with patch("muse_selector.web.run_search", side_effect=AssertionError("watches endpoint refreshed")):
                    with urlopen(f"http://127.0.0.1:{server.server_port}/api/watches", timeout=2) as response:
                        payload = json.loads(response.read().decode("utf-8"))
                self.assertTrue(payload["ok"])
                self.assertEqual(payload["schema_version"], RESULT_SCHEMA_VERSION)
                self.assertTrue(payload["read_only"])
                self.assertEqual(payload["status"], "watches_ready")
                self.assertEqual([item["watch_id"] for item in payload["watches"]], ["watch_one", "watch_two"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_watch_changes_endpoint_reads_history_and_replays_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SelectorStore(Path(directory) / "selector.sqlite3")
            watch_id = store.add_watch(
                "香港预算 HKD 7000 以内的迷你主机",
                FIXTURE,
                watch_id="watch_changes_web",
            )
            refreshed = store.refresh_watch(watch_id)
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(FIXTURE, store))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with patch("muse_selector.web.run_search", side_effect=AssertionError("changes endpoint refreshed")):
                    with urlopen(
                        f"http://127.0.0.1:{server.server_port}/api/watch/changes?watch_id={watch_id}&include_payload=1",
                        timeout=2,
                    ) as response:
                        payload = json.loads(response.read().decode("utf-8"))
                self.assertTrue(payload["ok"])
                self.assertEqual(payload["schema_version"], RESULT_SCHEMA_VERSION)
                self.assertEqual(payload["status"], "watch_changes_ready")
                self.assertEqual(payload["changes"][0]["run_id"], refreshed["run_id"])
                self.assertEqual(payload["changes"][0]["payload"], refreshed["payload"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_watch_changes_endpoint_reports_invalid_and_missing_watch(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SelectorStore(Path(directory) / "selector.sqlite3")
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(FIXTURE, store))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with self.assertRaises(HTTPError) as invalid_error:
                    urlopen(f"http://127.0.0.1:{server.server_port}/api/watch/changes?watch_id=missing&limit=0", timeout=2)
                self.assertEqual(invalid_error.exception.code, 400)
                self.assertEqual(json.loads(invalid_error.exception.read().decode("utf-8"))["status"], "invalid_query")
                with self.assertRaises(HTTPError) as missing_error:
                    urlopen(f"http://127.0.0.1:{server.server_port}/api/watch/changes?watch_id=missing", timeout=2)
                self.assertEqual(missing_error.exception.code, 404)
                self.assertEqual(json.loads(missing_error.exception.read().decode("utf-8"))["status"], "watch_not_found")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_watches_endpoint_without_db_is_structured_unavailable(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(FIXTURE))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with self.assertRaises(HTTPError) as error:
                urlopen(f"http://127.0.0.1:{server.server_port}/api/watches", timeout=2)
            self.assertEqual(error.exception.code, 503)
            payload = json.loads(error.exception.read().decode("utf-8"))
            self.assertEqual(payload["status"], "watch_unavailable")
            self.assertTrue(payload["read_only"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_watch_endpoint_reports_structured_unavailable_and_not_found(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(FIXTURE))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with self.assertRaises(HTTPError) as unavailable_error:
                urlopen(
                    f"http://127.0.0.1:{server.server_port}/api/watch?watch_id=missing",
                    timeout=2,
                )
            self.assertEqual(getattr(unavailable_error.exception, "code", None), 503)
            body = unavailable_error.exception.read().decode("utf-8")
            self.assertEqual(json.loads(body)["status"], "watch_unavailable")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        with tempfile.TemporaryDirectory() as directory:
            store = SelectorStore(Path(directory) / "selector.sqlite3")
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(FIXTURE, store))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with self.assertRaises(HTTPError) as not_found_error:
                    urlopen(
                        f"http://127.0.0.1:{server.server_port}/api/watch?watch_id=missing",
                        timeout=2,
                    )
                self.assertEqual(getattr(not_found_error.exception, "code", None), 404)
                body = not_found_error.exception.read().decode("utf-8")
                self.assertEqual(json.loads(body)["status"], "watch_not_found")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_watch_endpoint_reports_missing_checkpoint_without_traceback(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SelectorStore(Path(directory) / "selector.sqlite3")
            watch_id = store.add_watch(
                "香港预算 HKD 7000 以内的迷你主机",
                FIXTURE,
                watch_id="watch_missing_run_web",
            )
            with store._connection() as conn:
                conn.execute("UPDATE watches SET last_run_id = ? WHERE watch_id = ?", ("missing-run", watch_id))
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(FIXTURE, store))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with self.assertRaises(HTTPError) as error:
                    urlopen(
                        f"http://127.0.0.1:{server.server_port}/api/watch?watch_id={watch_id}",
                        timeout=2,
                    )
                self.assertEqual(error.exception.code, 409)
                payload = json.loads(error.exception.read().decode("utf-8"))
                self.assertFalse(payload["ok"])
                self.assertEqual(payload["status"], "watch_unavailable")
                self.assertEqual(payload["message"], "unknown run_id: missing-run")
                self.assertEqual(payload["schema_version"], RESULT_SCHEMA_VERSION)
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

    def test_json_search_endpoint_forwards_offset_to_pipeline(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(FIXTURE))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch(
                "muse_selector.web.run_search",
                return_value={"ok": True, "read_only": True, "recommended": []},
            ) as search:
                url = f"http://127.0.0.1:{server.server_port}/api/search?q=mini%20pc&limit=1&offset=40"
                with urlopen(url, timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            self.assertTrue(payload["ok"])
            search.assert_called_once_with("mini pc", str(FIXTURE), limit=1, offset=40)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_explicit_environment_is_forwarded_without_process_global_mutation(self):
        with patch.dict(os.environ, {"EBAY_ENVIRONMENT": "production"}, clear=False):
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(FIXTURE, environment="sandbox"))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with patch(
                    "muse_selector.web.run_search",
                    return_value={"ok": True, "read_only": True, "recommended": []},
                ) as search:
                    url = f"http://127.0.0.1:{server.server_port}/api/search?q=mini%20pc&limit=1"
                    with urlopen(url, timeout=2) as response:
                        payload = json.loads(response.read().decode("utf-8"))
                self.assertTrue(payload["ok"])
                search.assert_called_once_with("mini pc", str(FIXTURE), limit=1, offset=0, environment="sandbox")
                with urlopen(f"http://127.0.0.1:{server.server_port}/api/capabilities", timeout=2) as response:
                    capabilities = json.loads(response.read().decode("utf-8"))
                self.assertEqual(capabilities["sources"]["ebay.browse.hk.v1"]["environment"], "sandbox")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
            self.assertEqual(os.environ["EBAY_ENVIRONMENT"], "production")

    def test_json_search_endpoint_reports_invalid_offset_without_silent_zero(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(FIXTURE))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for raw_offset in ("nope", "-1"):
                url = (
                    f"http://127.0.0.1:{server.server_port}/api/search"
                    "?q=%E9%A6%99%E6%B8%AF%E9%A2%84%E7%AE%97%20HKD%207000%20%E4%BB%A5%E5%86%85%E7%9A%84%E8%BF%B7%E4%BD%A0%E4%B8%BB%E6%9C%BA"
                    f"&offset={raw_offset}"
                )
                with urlopen(url, timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                self.assertFalse(payload["ok"])
                self.assertEqual(payload["status"], "invalid_query")
                self.assertIn("offset must be a non-negative integer", payload["message"])
                self.assertEqual(payload["schema_version"], RESULT_SCHEMA_VERSION)
                self.assertTrue(payload["read_only"])
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
            self.assertEqual(payload["schema_version"], RESULT_SCHEMA_VERSION)
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

