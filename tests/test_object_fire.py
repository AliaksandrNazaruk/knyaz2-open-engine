# -*- coding: utf-8 -*-
"""Огни на объектах: костры, факелы, маяк, горящие руины.

Механика снята с ассемблера и живой памяти оригинала (разбор — в
`konung2/objectanim.py`): у заголовка объекта до восьми точек «анимация +
смещение», кадр живёт в записи объекта и двигается раз в мировой такт,
стартуя со случайного. Кадры вытащены из памяти живой игры — в файлах они
не нашлись, движок держит их уже конвертированными в 16-битный цвет.

Тест сторожит три вещи: таблицы читаются из exe и совпадают между играми,
точки огня читаются из OBJECTS.RES, и пак всё это несёт.
"""
from __future__ import annotations

import json
import pathlib
import unittest

КОРЕНЬ = pathlib.Path(__file__).resolve().parents[1]

#: Диапазоны кадров семи анимаций — то, что лежит в exe по 0x45FFF0 (канон)
#: и 0x4618E8 (донор). Проверено живым замером: кадр чана бежал по 44…53.
ДИАПАЗОНЫ = [(0, 10), (11, 21), (22, 32), (33, 43), (44, 54), (55, 59),
             (60, 73)]


class AnimTablesTest(unittest.TestCase):
    """Таблицы анимаций читаются из exe, а не выдуманы."""

    def test_canon_ranges(self) -> None:
        from konung2 import objectanim
        self.assertEqual(objectanim.anim_ranges("canon"), ДИАПАЗОНЫ)

    def test_donor_ranges_match_canon(self) -> None:
        from konung2 import donor, objectanim
        if not donor.available():
            self.skipTest("exe «Продолжения легенды» недоступен")
        self.assertEqual(objectanim.anim_ranges("legend"),
                         objectanim.anim_ranges("canon"))

    def test_fire_points_known_objects(self) -> None:
        """Точки сверены с живой памятью оригинала.

        Слот 317 донора — чан ущелья: одна точка, анимация 4, смещение
        (−89, −116); ровно эти числа стояли в заголовке 0x79A4BC живой
        игры. Слот 67 канона — факел: анимация 5.
        """
        from konung2 import donor, objectanim
        canon = objectanim.fire_points("canon")
        self.assertEqual(canon.get(67), [{"anim": 5, "dx": -7, "dy": 0}])
        self.assertGreater(len(canon), 80, "у канона под сотню слотов с огнём")
        if donor.available():
            legend = objectanim.fire_points("legend")
            self.assertEqual(legend.get(317),
                             [{"anim": 4, "dx": -89, "dy": -116}])


class FirePackTest(unittest.TestCase):
    """Пак несёт кадры и точки: без них клиент молчит."""

    def setUp(self) -> None:
        self.корень = КОРЕНЬ / "content_build"
        if not (self.корень / "shared.json").is_file():
            self.skipTest("пак не собран")

    def test_shared_has_seven_anims_and_frames_exist(self) -> None:
        shared = json.loads((self.корень / "shared.json")
                            .read_text(encoding="utf-8"))
        anims = (shared.get("effects") or {}).get("object_anims") or []
        self.assertEqual(len(anims), 7)
        for i, (первый, последний) in enumerate(ДИАПАЗОНЫ):
            кадры = anims[i]["frames"]
            self.assertEqual(len(кадры), последний - первый + 1, f"анимация {i}")
            for путь in кадры:
                self.assertTrue((self.корень / путь).is_file(), путь)

    def test_gorge_has_seven_burning_bowls(self) -> None:
        """Ущелье возле Угорья — семь чанов квеста дракона.

        В оригинале эти семь объектов до квеста запаркованы у скалы, а на
        точках стоят оверлеи незажжённых чанов; поджиг меняет их местами
        токенами-командами (tests/test_dragon_nest.py, IgnitionChainTest).
        Пока механика токенов не перенесена, пак несёт чаны горящими —
        тест сторожит сам огонь, а не канонность старта.
        """
        карта = json.loads((self.корень / "maps" / "188" / "map.json")
                           .read_text(encoding="utf-8"))
        огни = [o for g in ("props", "buildings")
                for o in (карта.get(g) or []) if o.get("fire")]
        self.assertEqual(len(огни), 7)
        for o in огни:
            self.assertEqual(o["fire"], [{"anim": 4, "dx": -89, "dy": -116}])

    def test_sea_camp_lighthouse_burns(self) -> None:
        """Морской лагерь — горящая чаша-маяк со скриншота тестера."""
        карта = json.loads((self.корень / "maps" / "23" / "map.json")
                           .read_text(encoding="utf-8"))
        огни = [o for g in ("props", "buildings")
                for o in (карта.get(g) or []) if o.get("fire")]
        self.assertEqual(len(огни), 1)

    def test_manifest_lists_the_frames(self) -> None:
        манифест = json.loads((self.корень / "manifest.json")
                              .read_text(encoding="utf-8"))
        пути = {f["path"] for f in манифест["files"]}
        for n in range(74):
            self.assertIn(f"assets/effects/anim_{n:02}.png", пути)


if __name__ == "__main__":
    unittest.main()
