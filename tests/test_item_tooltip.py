# -*- coding: utf-8 -*-
"""Подсказка предмета и краска ячейки — дословный канон (жалоба 23.08).

Печатник описания — VA 0x4315A0: свои строки на каждый ВИД записи, износ
двумя числами, вес «%4.2f», чары короткими именами полей (таблица
0x462D74), требование «, требует:  Сил:12», и НИКАКОЙ цены. Заколдованная
вещь (бит 0x8000 слова чар) печатается ОДНОЙ строкой «Заколдованное …» —
статов у неё не видно, пока не опознана.

Краска — не значка и не каймы: движок рисует ПОДЛОЖКУ ячейки перекрашенной
палитрой (0x42BFE8 обмен, 0x43096C пояс; выбор — 0x42FF20), а значок
кладёт родными цветами 1:1 по центру. Ряды краски строит 0x43C228 с шагом
0.01 (float 0x4593A8): ряд N тянет канал на N сотых остатка до максимума.
"""
from __future__ import annotations

import json
import pathlib
import unittest

КОРЕНЬ = pathlib.Path(__file__).resolve().parents[1]


def _строка_exe(va: int) -> str:
    from konung2.exetables import va_to_foff
    from konung2.profile import CANON
    data = CANON.exe_bytes()
    at = va_to_foff(va)
    return data[at:data.index(0, at)].decode("cp866")


class TooltipStringsTest(unittest.TestCase):
    """Строки печатника в клиенте — байт в байт из exe."""

    #: Литерал клиента -> адрес строки в exe (сняты дизасмом 0x4315A0).
    ЛИТЕРАЛЫ = {
        "Заколдованное оружие": 0x4525C6,
        "Заколдованное стрелковое оружие": 0x4525DB,
        "Заколдованный предмет": 0x4525FB,
        ", урон ": 0x452611,
        ", броня: ": 0x452619,
        ", износ ": 0x452623,
        ", вес ": 0x45262E,
        ", отравление: ": 0x452643,
        ", требует: ": 0x45266E,
        "Заколдованные стрелы: ": 0x45267C,
        " шт.": 0x452693,
        ", концентрация ": 0x45270B,
        ", недостаточная концентрация": 0x452729,
    }

    def test_client_literals_match_the_exe(self) -> None:
        ui = (КОРЕНЬ / "knyaz2" / "web" / "static" / "ui.js").read_text(
            encoding="utf-8")
        for литерал, адрес in self.ЛИТЕРАЛЫ.items():
            with self.subTest(литерал=литерал):
                self.assertEqual(литерал, _строка_exe(адрес),
                                 f"строка exe по {адрес:#x} разошлась")
                self.assertIn(литерал, ui, "клиент печатает не эту строку")

    def test_price_and_range_left_the_tooltip(self) -> None:
        """Цены и дальности в канонной подсказке нет — и у нас больше нет."""
        ui = (КОРЕНЬ / "knyaz2" / "web" / "static" / "ui.js").read_text(
            encoding="utf-8")
        self.assertNotIn("`цена ${", ui)
        self.assertNotIn("`дальность ${", ui)
        self.assertNotIn('parts.join(" · ")', ui, "самодельный разделитель")

    def test_short_stat_names_travel_in_the_pack(self) -> None:
        """Короткие имена полей и виды отравы — из exe, с ведущим пробелом."""
        from konung2.items import tooltip_strings
        табличка = tooltip_strings()
        self.assertEqual(табличка["stats"]["5"], " Сил")
        self.assertEqual(табличка["stats"]["6"], " Вын")
        self.assertEqual(табличка["stats"]["7"], " Брн")
        self.assertEqual(табличка["stats"]["10"], " Здр")
        self.assertEqual(len(табличка["poisons"]), 8)
        self.assertEqual(табличка["poisons"][0], ", зажигательные")
        self.assertEqual(табличка["poisons"][1], ", на кикимору")

    def test_shared_carries_the_tooltip(self) -> None:
        путь = КОРЕНЬ / "content_build" / "shared.json"
        if not путь.is_file():
            self.skipTest("пак не собран")
        документ = json.loads(путь.read_text(encoding="utf-8"))
        подсказка = (документ.get("hero", {}).get("rules", {})
                     .get("inventory", {}).get("tooltip"))
        self.assertIsNotNone(подсказка, "rules.inventory.tooltip не испечён")
        self.assertEqual(подсказка["stats"]["5"], " Сил")


class CellPaintTest(unittest.TestCase):
    """Краска подложки ячейки — по формуле строителя рядов 0x43C228."""

    def test_painted_cells_repeat_the_row_formula(self) -> None:
        """Красная — ряд 0x18 красного канала, зелёная — 0x0C зелёного.

        Формула строителя: new = v + round(N/100 * (max - v)), каналы
        5-6-5. Сверяется каждый пиксель испечённых подложек с пересчётом
        из базовой ячейки.
        """
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("нет PIL")
        основа = КОРЕНЬ / "content_build" / "assets" / "icons" / "ui_17.png"
        красная = КОРЕНЬ / "content_build" / "assets" / "icons" / "ui_17_unusable.png"
        зелёная = КОРЕНЬ / "content_build" / "assets" / "icons" / "ui_17_special.png"
        if not (основа.is_file() and красная.is_file() and зелёная.is_file()):
            self.skipTest("крашеные подложки не испечены")
        base = list(Image.open(основа).convert("RGBA").getdata())

        def пересчёт(пиксель, ряд_красного, ряд_зелёного):
            r, g, b, a = пиксель
            r5, g6 = r >> 3, g >> 2
            r5 += round(ряд_красного * 0.01 * (31 - r5))
            g6 += round(ряд_зелёного * 0.01 * (63 - g6))
            return ((r5 << 3) | (r5 >> 2), (g6 << 2) | (g6 >> 4), b, a)

        for путь, ряды in ((красная, (0x18, 0)), (зелёная, (0, 0x0C))):
            with self.subTest(файл=путь.name):
                краска = list(Image.open(путь).convert("RGBA").getdata())
                self.assertEqual(len(краска), len(base))
                for точка, (было, стало) in enumerate(zip(base, краска)):
                    self.assertEqual(пересчёт(было, *ряды), стало,
                                     f"пиксель {точка}")

    def test_client_paints_the_cell_not_the_icon(self) -> None:
        ui = (КОРЕНЬ / "knyaz2" / "web" / "static" / "ui.js").read_text(
            encoding="utf-8")
        self.assertIn("cell_unusable", ui)
        self.assertIn("cell_special", ui)
        self.assertIn("iconScale", ui)
        self.assertNotIn("classList.add(`item-${tint}`)", ui)
        стили = (КОРЕНЬ / "knyaz2" / "web" / "static" / "styles.css").read_text(
            encoding="utf-8")
        self.assertNotIn("item-unusable", стили)
        self.assertNotIn("drop-shadow(0 0 1px", стили)


class GlowHighlightsLootTest(unittest.TestCase):
    """Свечение Факела подсвечивает КУЧИ, а не круг выделения (23.08).

    Оба прохода отрисовки лута (VA 0x424514:146 и 0x424FD8:220) при флаге
    0x849610 кладут маску-осветление 64×43 под каждую кучу и рисуют её
    спрайт базовой палитрой, мимо суточного пересчёта 0x441393. Прежняя
    дымка вокруг круга выделения была неверным чтением этих адресов — и
    «подсветить лут факелом» не работало. Живой замер 23.08 на карте 33,
    ночь: включение флага меняет 4411 пикселей кадра, прибавка до +323.
    """

    def client(self, name: str) -> str:
        return (КОРЕНЬ / "knyaz2" / "web" / "static" / name).read_text(
            encoding="utf-8")

    def test_glow_lives_in_the_pile_draw(self) -> None:
        loot = self.client("loot.js")
        self.assertIn("world.glow", loot)
        self.assertIn("0x424514:146", loot)
        self.assertIn("0x424FD8:220", loot)
        self.assertIn("drawBrightImage(image, x, y)", loot)
        self.assertIn('context.globalCompositeOperation = "lighter"', loot)

    def test_glow_left_the_selection_circle(self) -> None:
        hero = self.client("hero.js")
        начало = hero.index("function drawSelectionCircle")
        конец = hero.index("export function renderHero")
        self.assertNotIn("world.glow", hero[начало:конец],
                         "дымка вернулась к кругу выделения")

    def test_torch_use_sets_the_flag(self) -> None:
        квест = self.client("questitems.js")
        self.assertIn("world.glow = true", квест)


if __name__ == "__main__":
    unittest.main()
