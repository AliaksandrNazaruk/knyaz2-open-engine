# -*- coding: utf-8 -*-
"""Боевые данные юнитов против авторских исходников расстановок.

Первоисточник — GAME_0…5.TXT из посылки сообщества: характеристики,
навыки, броня и снаряжение каждого юнита открытым текстом. Полный
прогон и вердикт — docs/COMBAT_DATA_AUDIT.md; здесь сторож на мир 0,
чтобы разбор записей юнита (unit_stats) не уехал молча.

Два известных расхождения — артефакты АВТОРСКОГО конвейера и потому
ожидаются, а не чинятся: байтовое усечение NATIVEARMOUR=300 -> 44 и
дефолт «Управление деревней 80» при одиночном BARGAINSKILL.
"""
from __future__ import annotations

import importlib.util
import pathlib
import unittest

КОРЕНЬ = pathlib.Path(__file__).resolve().parents[1]
ИСХОДНИКИ = (КОРЕНЬ / "project" / "community" / "k2_tools" / "ucompiler" /
             "KONUNG2" / "RESOURCE" / "GAME")


def _средство():
    spec = importlib.util.spec_from_file_location(
        "game_txt_diff", КОРЕНЬ / "tools" / "game_txt_diff.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CombatDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (ИСХОДНИКИ / "GAME_0.TXT").is_file():
            raise unittest.SkipTest("исходники расстановок не распакованы")
        try:
            cls.вердикт = _средство().compare_world(0)
        except OSError as error:
            raise unittest.SkipTest(f"GAME.0 недоступен: {error}")

    def test_every_placed_unit_matches_binary(self) -> None:
        """Каждый юнит с клеткой находится в бинаре той же клеткой."""
        self.assertEqual(self.вердикт["placed"], 269)
        self.assertEqual(self.вердикт["matched"], 269)
        self.assertEqual(self.вердикт["failed"].get("—не найден—", 0), 0)

    def test_only_known_compiler_artifacts_diverge(self) -> None:
        """Расходятся ровно два авторских артефакта — и больше ничего."""
        плохие = dict(self.вердикт["failed"])
        плохие.pop("—не найден—", None)
        self.assertEqual(sorted(плохие),
                         ["NATIVEARMOUR", "скилл:Управление деревней"])
        self.assertEqual(плохие["NATIVEARMOUR"], 3)
        self.assertEqual(плохие["скилл:Управление деревней"], 3)
        # и это именно байтовое усечение 300 -> 44 и дефолт 80
        for мир, имя, карта, поле, надо, есть in self.вердикт["mismatch"]:
            if поле == "NATIVEARMOUR":
                self.assertEqual((надо, есть), (300, 300 & 0xFF))
            else:
                self.assertEqual((надо, есть), (0, 80))

    def test_field_coverage_is_wide(self) -> None:
        """Сверка покрывает все боевые входы, а не пару полей."""
        поля = self.вердикт["checked"]
        self.assertGreater(sum(поля.values()), 8000)
        for важное in ("PARAMETERS", "NATIVEARMOUR", "PLACES", "QUEST",
                       "скилл:Владение мечом", "скилл:Стрельба из лука",
                       "слот:ARM", "крепость:ARM", "direction",
                       "чары:ARM", "байт01:ARM"):
            self.assertIn(важное, поля)
            self.assertGreater(поля[важное], 0, важное)

    def test_bonus_word_layout(self) -> None:
        """BONUS -> (байт +0x01, слово чар): порядок групп от старших бит.

        Пары сняты с ожерелий класса 62 в кучах PCOMMON.TXT против
        бинарных записей GAME.N (карты 2, 6, 8, 47): шестое поле — биты
        0…2, пятое — 3…5, четвёртое — 6…8; 0x8000 первого поля — «не
        опознано». Формула отработала на всём снаряжении шести миров —
        9576 проверок без единого расхождения.
        """
        средство = _средство()
        пары = [
            ([0xFF, 6, 6, 6, 6, 6], (0xFF, 0x6DB6)),
            ([0x80FF, 0, 0, 0, 0, 6], (0xFF, 0x8006)),
            ([0x80FF, 0, 0, 0, 5, 0], (0xFF, 0x8028)),
            ([0x80FF, 0, 0, 5, 0, 0], (0xFF, 0x8140)),
            ([0xFF, 0, 0, 0, 0, 0], (0xFF, 0x0000)),
        ]
        for поля, ожидание in пары:
            self.assertEqual(средство.bonus_word(поля), ожидание, поля)


if __name__ == "__main__":
    unittest.main()
