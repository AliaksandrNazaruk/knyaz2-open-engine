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


class ScenarioCacheTest(unittest.TestCase):
    """Вклад карты в общие списки выпечки помнится и честно устаревает.

    Формы тел, палитры, пары и наборы тварей собираются обходом жителей
    КАЖДОЙ карты по всем мирам выбора, и обход этот стоил две трети
    времени сборки (замер: 468 с из 694 на карту 63). Кэш снимает его
    для карт, которых правка не касалась, — но обязан отпускать всё,
    как только меняются миры, и саму карту, как только меняются её файлы.
    """

    def подготовить(self, корень: Path) -> tuple[Path, Path]:
        проект = корень / "project"
        for номер, имя in ((19, "19_proba"), (20, "20_proba")):
            папка = проект / "maps" / имя
            папка.mkdir(parents=True)
            (папка / "map.json").write_text(
                json.dumps({"map_number": номер}), encoding="utf-8")
            (папка / "scenario.json").write_text("{}", encoding="utf-8")
        пак = корень / "pack"
        пак.mkdir()
        return проект, пак

    def test_cache_hits_and_invalidation(self) -> None:
        from unittest import mock
        from knyaz2.content import builder
        with tempfile.TemporaryDirectory() as raw:
            корень = Path(raw)
            проект, пак = self.подготовить(корень)
            счёт: list[int] = []

            def вклад(project, number):
                счёт.append(number)
                return {"shapes": [number], "palettes": [], "pairs": [],
                        "creatures": [], "equipment": [], "sourced": True}

            with mock.patch.object(builder, "_map_contribution", вклад), \
                    mock.patch.object(builder, "_shared_generation",
                                      lambda: "поколение-1"):
                builder._scenario_contributions(проект, (19, 20), пак)
                self.assertEqual(sorted(счёт), [19, 20])
                # второй заход не считает ничего: файлы карт целы
                счёт.clear()
                builder._scenario_contributions(проект, (19, 20), пак)
                self.assertEqual(счёт, [])
                # правка ОДНОЙ карты пересчитывает только её
                (проект / "maps" / "19_proba" / "scenario.json").write_text(
                    json.dumps({"units": [{"palette": 7}]}), encoding="utf-8")
                builder._scenario_contributions(проект, (19, 20), пак)
                self.assertEqual(счёт, [19])
                счёт.clear()
                # индекс живёт рядом с паком и читается человеком
                документ = json.loads(
                    (пак / builder.SCENARIO_INDEX).read_text(encoding="utf-8"))
                self.assertEqual(документ["generation"], "поколение-1")
                self.assertEqual(sorted(документ["maps"]), ["19", "20"])
            # СМЕНА МИРОВ ОБЕСЦЕНИВАЕТ ВСЁ: правка GAME.x меняет жителей
            # сразу всех карт, и вклад каждой обязан пересчитаться.
            with mock.patch.object(builder, "_map_contribution", вклад), \
                    mock.patch.object(builder, "_shared_generation",
                                      lambda: "поколение-2"):
                builder._scenario_contributions(проект, (19, 20), пак)
            self.assertEqual(sorted(счёт), [19, 20])

    def test_cached_and_fresh_inputs_match(self) -> None:
        """С кэшем и без него списки одинаковы — иначе кэш врёт."""
        from unittest import mock
        from knyaz2.content import builder
        with tempfile.TemporaryDirectory() as raw:
            корень = Path(raw)
            проект, пак = self.подготовить(корень)

            def вклад(project, number):
                return {"shapes": [number], "palettes": [number + 1],
                        "pairs": [["", number, number + 1]],
                        "creatures": [[number, 3]],
                        "equipment": [], "sourced": True}

            with mock.patch.object(builder, "_map_contribution", вклад), \
                    mock.patch.object(builder, "_shared_generation",
                                      lambda: "поколение"), \
                    mock.patch.object(builder, "_hero_extra_shapes", set), \
                    mock.patch.object(builder, "_hero_extra_palettes", set), \
                    mock.patch.object(builder, "_hero_extra_pairs", set), \
                    mock.patch.object(builder, "_hero_extra_equipment", list), \
                    mock.patch.object(builder, "_encounter_units", list), \
                    mock.patch.object(builder, "_layers_of",
                                      lambda names: {}):
                без_кэша = builder._shared_inputs(проект, (19, 20), (), None)
                первый = builder._shared_inputs(проект, (19, 20), (), пак)
                второй = builder._shared_inputs(проект, (19, 20), (), пак)
            self.assertEqual(без_кэша, первый)
            self.assertEqual(первый, второй)
            _, palettes, shapes, pairs, creatures = второй
            self.assertEqual(shapes, {19, 20})
            self.assertEqual(palettes, {20, 21})
            self.assertEqual(pairs, {("", 19, 20), ("", 20, 21)})
            self.assertEqual(creatures, {(19, 3), (20, 3)})


if __name__ == "__main__":
    unittest.main()
