from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import unittest
from unittest.mock import patch

from muse_selector.zhuanzhuan_smoke import main


class ZhuanzhuanSmokeTests(unittest.TestCase):
    def test_missing_token_returns_versioned_read_only_envelope(self):
        output = io.StringIO()
        with patch.dict(os.environ, {"ZHUANZHUAN_MCP_TOKEN": ""}, clear=False):
            with patch.object(sys, "argv", ["muse-zhuanzhuan-smoke", "--query", "RTX 4070"]):
                with contextlib.redirect_stdout(output):
                    self.assertEqual(main(), 2)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["schema_version"], "muse.zhuanzhuan.smoke.v1")
        self.assertTrue(payload["read_only"])
        self.assertEqual(payload["status"], "source_unavailable")


if __name__ == "__main__":
    unittest.main()
