import unittest
from pathlib import Path

from muse_selector.watch import default_watch_id


class WatchTests(unittest.TestCase):
    def test_implicit_watch_id_is_stable_and_fixture_scoped(self):
        query = "香港预算 HKD 7000 以内的迷你主机"
        first = default_watch_id(query, Path("tests/fixtures/ebay_hk_sample.json"))
        second = default_watch_id(query, Path("tests/fixtures/ebay_hk_sample.json"))
        other_fixture = default_watch_id(query, Path("tests/fixtures/other.json"))
        self.assertEqual(first, second)
        self.assertNotEqual(first, other_fixture)
        self.assertRegex(first, r"^watch_[0-9a-f]{16}$")


if __name__ == "__main__":
    unittest.main()
