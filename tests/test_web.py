import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

from muse_selector.web import make_handler, render_html


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "ebay_hk_sample.json"


class WebTests(unittest.TestCase):
    def test_render_escapes_query_and_shows_read_only_fields(self):
        payload = {"ok": True, "search_spec": {"region": "HK", "currency": "HKD", "budget_max": "7000"}, "recommended": [], "rejected": [], "dropped": []}
        page = render_html(payload, "<script>alert(1)</script>")
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("只读结果页", page)
        self.assertNotIn("<script>alert(1)</script>", page)

    def test_local_server_health_and_result_page(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(FIXTURE))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            with urlopen(base + "/healthz", timeout=2) as response:
                health = json.loads(response.read().decode("utf-8"))
            self.assertEqual(health, {"ok": True, "read_only": True})
            with urlopen(base + "/?q=mini%20pc", timeout=2) as response:
                page = response.read().decode("utf-8")
            self.assertIn("Mini PC Ryzen 7", page)
            self.assertIn("证据", page)
            self.assertIn("没有登录、购买或写操作能力", page)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_live_handler_without_credentials_is_read_only_error(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(None))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urlopen(f"http://127.0.0.1:{server.server_port}/?q=mini%20pc", timeout=2) as response:
                page = response.read().decode("utf-8")
            self.assertIn("source_unavailable", page)
            self.assertIn("只读结果页", page)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()

