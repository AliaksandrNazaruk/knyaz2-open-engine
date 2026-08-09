# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from knyaz2.web.server import resolve_request


class WebRoutingTest(unittest.TestCase):
    def test_routes_app_and_content_without_crossing_roots(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            web = root / "web"
            content = root / "content"
            web.mkdir()
            content.mkdir()
            (web / "index.html").write_text("app", encoding="utf-8")
            (content / "manifest.json").write_text("{}", encoding="utf-8")

            self.assertEqual(resolve_request("/", web, content), web / "index.html")
            self.assertEqual(resolve_request("/content/manifest.json", web, content),
                             content / "manifest.json")
            self.assertIsNone(resolve_request("/content/../web/index.html", web, content))
            self.assertIsNone(resolve_request("/%2e%2e/content/manifest.json", web, content))


if __name__ == "__main__":
    unittest.main()

