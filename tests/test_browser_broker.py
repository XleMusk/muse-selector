import unittest

from muse_selector.browser_broker import BROWSER_SCHEMA_VERSION, ReadOnlyBrowserBroker


class _Adapter:
    def __init__(self):
        self.urls = []

    def read_accessibility_tree(self, url):
        self.urls.append(url)
        return {
            "role": "document",
            "name": "eBay HK search",
            "token": "secret-token",
            "children": [{"role": "link", "name": "Mini PC", "password": "secret"}],
            "headers": {"cookie": "session=secret"},
        }


class BrowserBrokerTests(unittest.TestCase):
    def test_feature_is_disabled_by_default_and_does_not_call_adapter(self):
        adapter = _Adapter()
        result = ReadOnlyBrowserBroker(adapter).snapshot("https://www.ebay.com.hk/sch/i.html?_nkw=mini+pc")
        self.assertEqual(result["schema_version"], BROWSER_SCHEMA_VERSION)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "feature_disabled")
        self.assertTrue(result["read_only"])
        self.assertEqual(adapter.urls, [])
        self.assertEqual(result["manual_handoff"]["action"], "user_open")

    def test_enabled_snapshot_sanitizes_sensitive_tree_fields(self):
        adapter = _Adapter()
        result = ReadOnlyBrowserBroker(adapter, enabled=True).snapshot("https://www.ebay.com.hk/itm/123")
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "tree_ready")
        self.assertEqual(result["redacted_field_count"], 3)
        serialized = str(result["tree"])
        self.assertNotIn("secret-token", serialized)
        self.assertNotIn("session=secret", serialized)
        self.assertEqual(adapter.urls, ["https://www.ebay.com.hk/itm/123"])

    def test_url_allowlist_rejects_network_and_credential_variants(self):
        broker = ReadOnlyBrowserBroker(enabled=True)
        for url in (
            "http://www.ebay.com.hk/itm/123",
            "https://evil.example/itm/123",
            "https://user:secret@www.ebay.com.hk/itm/123",
            "https://www.ebay.com.hk:8443/itm/123",
            "https://www.ebay.com.hk/itm/123#fragment",
            "https://www.ebay.com.hk/itm/123?access_token=secret",
        ):
            with self.subTest(url=url):
                result = broker.snapshot(url)
                self.assertFalse(result["ok"])
                self.assertEqual(result["status"], "invalid_url")

    def test_manual_handoff_is_read_only(self):
        handoff = ReadOnlyBrowserBroker.manual_handoff("https://www.ebay.com.hk/sch/i.html?_nkw=mini+pc")
        self.assertEqual(handoff, {
            "action": "user_open",
            "url": "https://www.ebay.com.hk/sch/i.html?_nkw=mini+pc",
            "read_only": True,
        })


if __name__ == "__main__":
    unittest.main()
