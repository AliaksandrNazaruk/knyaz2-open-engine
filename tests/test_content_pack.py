# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from knyaz2.content import (CONTENT_SCHEMA_VERSION, ContentManifest, ContentMap,
                            PackedFile, verify_content_pack)


class ContentSchemaTest(unittest.TestCase):
    def test_manifest_round_trip(self) -> None:
        manifest = ContentManifest(
            content_id="test",
            maps=(ContentMap("legacy:19", 19, "Черный Бор", "maps/19/map.json"),),
            files=(PackedFile("maps/19/map.json", 2, "a" * 64),),
        )
        restored = ContentManifest.from_dict(manifest.to_dict())
        self.assertEqual(restored, manifest)
        self.assertEqual(restored.schema_version, CONTENT_SCHEMA_VERSION)

    def test_unknown_schema_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ContentManifest.from_dict({
                "schema_version": "999",
                "content_id": "future",
                "maps": [],
                "files": [],
            })


class ContentVerificationTest(unittest.TestCase):
    def make_pack(self, root: Path) -> Path:
        target = root / "maps" / "19" / "map.json"
        target.parent.mkdir(parents=True)
        target.write_text("{}", encoding="utf-8")
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        manifest = ContentManifest(
            content_id="test",
            maps=(ContentMap("legacy:19", 19, "Черный Бор", "maps/19/map.json"),),
            files=(PackedFile("maps/19/map.json", target.stat().st_size, digest),),
        )
        (root / "manifest.json").write_text(
            json.dumps(manifest.to_dict()), encoding="utf-8")
        return target

    def test_valid_pack_passes_and_tampering_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = self.make_pack(root)
            self.assertEqual(verify_content_pack(root), [])
            target.write_text("tampered", encoding="utf-8")
            errors = verify_content_pack(root)
            self.assertTrue(any("размер" in error or "sha256" in error for error in errors))

    def test_path_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = ContentManifest(
                content_id="test", maps=(),
                files=(PackedFile("../outside", 0, "0" * 64),),
            )
            (root / "manifest.json").write_text(
                json.dumps(manifest.to_dict()), encoding="utf-8")
            self.assertTrue(any("опасный путь" in error
                                for error in verify_content_pack(root)))


if __name__ == "__main__":
    unittest.main()

