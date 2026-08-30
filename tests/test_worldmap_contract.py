# -*- coding: utf-8 -*-
"""Договор карты мира: канон против exe и расширение против канона.

Карту мира не проверял никто, и это вышло боком дважды. Во-первых, порт
читал канонные таблицы ПО НОМЕРУ КАРТЫ без границ: постоянный свет брался
из соседней таблицы указателей и красил сцену розовым, прибытия читались
из сетки мира. Во-вторых, расширенную карту 54x34 можно было собрать так,
что канонный кусок в ней поехал бы, и никакой тест бы не упал.

Здесь проверяется ровно это: границы таблиц, неизменность канона и то,
что вложенный в расширение канон совпадает с ним клетка в клетку.
"""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from konung2 import worldmap as canon
from konung2.graph import (FIXED_LIGHT_COUNT, fixed_light, fixed_light_word)
from konung2.interf import PANEL_WIDTH, InterfRes
from konung2.paths import game_file
from knyaz2.content import worldmap as pack

STATIC = Path(__file__).resolve().parent.parent / "knyaz2" / "web" / "static"

GAME_AVAILABLE = os.path.isfile(game_file("konung2.exe"))
needs_game = unittest.skipUnless(GAME_AVAILABLE, "игра недоступна: нет konung2.exe")

PROJECT = Path(__file__).resolve().parent.parent / "project"
DATASET = PROJECT / pack.DATASET
needs_dataset = unittest.skipUnless(
    DATASET.is_file(), f"расширенной карты нет: {DATASET}")


@needs_game
class TestCanonGeometry(unittest.TestCase):
    """Канон снят с движка и меняться не должен."""

    def test_grid_is_32_by_24(self):
        self.assertEqual((canon.COLS, canon.ROWS), (0x20, 0x18))

    def test_cell_is_26_by_28(self):
        self.assertEqual((canon.CELL_W, canon.CELL_H), (0x1A, 0x1C))

    def test_screen_origin(self):
        self.assertEqual((canon.ORIGIN_X, canon.ORIGIN_Y), (0xA7, 0x19))

    def test_pack_origin_is_inside_the_picture(self):
        # Пак публикует угол уже в координатах картинки: клиенту вычитать
        # ширину панели неоткуда, и правило должно жить в одном месте.
        self.assertEqual(pack.canon()["origin"],
                         [canon.ORIGIN_X - PANEL_WIDTH, canon.ORIGIN_Y])

    def test_canon_grid_fits_the_map_sprite(self):
        # СЕТКА ОБЯЗАНА УМЕЩАТЬСЯ В КАРТИНКУ. Это единственная проверка, по
        # которой видно, в каких координатах задан угол, и по ней же клиент
        # ловит пак, собранный до пересчёта. Размер берём у самого спрайта,
        # а не из константы.
        width, height = InterfRes.from_game().frame_size(canon.MAP_SPRITE)
        origin = pack.canon()["origin"]
        self.assertLessEqual(origin[0] + canon.COLS * canon.CELL_W, width)
        self.assertLessEqual(origin[1] + canon.ROWS * canon.CELL_H, height)

    def test_screen_origin_does_not_fit_the_picture(self):
        # Обратная сторона той же проверки: экранный угол НЕ умещается —
        # 167 + 32*26 = 999 при ширине картинки 884. Если однажды сойдётся и
        # он, отличать одно от другого станет нечем, и об этом надо узнать
        # здесь, а не по съехавшим значкам в игре.
        width, _ = InterfRes.from_game().frame_size(canon.MAP_SPRITE)
        self.assertGreater(canon.ORIGIN_X + canon.COLS * canon.CELL_W, width)


@needs_game
class TestTableBounds(unittest.TestCase):
    """Таблицы, которые порт читает по номеру карты, имеют конец."""

    def test_fixed_light_stops_at_location_slots(self):
        self.assertEqual(FIXED_LIGHT_COUNT, canon.LOCATION_SLOTS)

    def test_fixed_light_beyond_the_table_is_zero(self):
        # За таблицей лежит чужая, из указателей: без границы карта 156
        # получала «постоянный свет» 0x00451F26 и заливалась розовым.
        for number in (FIXED_LIGHT_COUNT, 100, 156, 249):
            with self.subTest(number=number):
                self.assertEqual(fixed_light_word(number), 0)
                self.assertFalse(fixed_light(number)["frozen"])

    def test_fixed_light_inside_the_table_is_untouched(self):
        # Дворец Повелителя и Лабиринт смерти — вечная ночь с местным
        # светом; пещеры 45..49 — ровный дневной без него.
        self.assertEqual(fixed_light_word(1), 0x01CECEBA)
        self.assertEqual(fixed_light_word(2), 0x01CECEBA)
        for number in range(45, 50):
            with self.subTest(number=number):
                self.assertEqual(fixed_light_word(number), 0x00FFFFFF)

    def test_arrivals_fit_between_their_table_and_the_grid(self):
        gap = canon.GRID_VA - canon.ARRIVALS_VA
        self.assertEqual(canon.ARRIVAL_COUNT, gap // canon.ARRIVAL_STRIDE)
        self.assertLessEqual(max(canon.arrivals()), canon.ARRIVAL_COUNT)

    def test_arrivals_have_no_ghosts_from_the_grid(self):
        # Читали 64 записи и брали прибытия для карт 56, 58, 60 и 63 уже
        # из сетки мира.
        places = canon.arrivals()
        for number in (56, 58, 60, 63):
            with self.subTest(number=number):
                self.assertNotIn(number, places)

    def test_markers_stop_where_the_names_begin(self):
        NAMES_VA = 0x4616D4
        gap = NAMES_VA - canon.MARKERS_VA
        self.assertEqual(canon.MARKER_COUNT, gap // canon.MARKER_STRIDE)
        self.assertLess(max(canon.markers()), canon.MARKER_COUNT)


@needs_game
@needs_dataset
class TestExtendedMap(unittest.TestCase):
    """Расширение вкладывает канон в себя, ничего в нём не меняя."""

    @classmethod
    def setUpClass(cls):
        cls.rules = json.loads(DATASET.read_text(encoding="utf-8"))
        cls.canon_grid = canon.grid()
        cls.canon_walk = canon.rules()["walk"]

    def test_picture_divides_into_whole_cells(self):
        picture = self.rules["picture"]
        self.assertEqual(picture["width"], self.rules["cols"] * canon.CELL_W)
        self.assertEqual(picture["height"], self.rules["rows"] * canon.CELL_H)

    def test_grid_matches_declared_size(self):
        self.assertEqual(len(self.rules["grid"]), self.rules["rows"])
        for row in self.rules["grid"]:
            self.assertEqual(len(row), self.rules["cols"])

    def test_origin_is_the_picture_corner(self):
        self.assertEqual(self.rules["origin"], [0, 0])

    def test_grid_fits_the_picture(self):
        picture = self.rules["picture"]
        origin, cell = self.rules["origin"], self.rules["cell"]
        self.assertLessEqual(origin[0] + self.rules["cols"] * cell[0],
                             picture["width"])
        self.assertLessEqual(origin[1] + self.rules["rows"] * cell[1],
                             picture["height"])

    def test_canon_block_is_copied_cell_for_cell(self):
        row0, col0 = self.rules["canon_at"]
        grid = self.rules["grid"]
        for row in range(canon.ROWS):
            for col in range(canon.COLS):
                self.assertEqual(grid[row0 + row][col0 + col],
                                 self.canon_grid[row][col],
                                 f"клетка канона ({row},{col}) изменилась")

    def test_canon_walk_mask_is_copied_cell_for_cell(self):
        row0, col0 = self.rules["canon_at"]
        walk = self.rules["walk"]
        for row in range(canon.ROWS):
            for col in range(canon.COLS):
                self.assertEqual(walk[row0 + row][col0 + col],
                                 self.canon_walk[row][col],
                                 f"проходимость канона ({row},{col}) изменилась")

    def test_every_canon_location_stands_on_land(self):
        # Локация на нарисованном море была бы недостижима.
        row0, col0 = self.rules["canon_at"]
        walk = self.rules["walk"]
        for row in range(canon.ROWS):
            for col in range(canon.COLS):
                location = self.canon_grid[row][col] & 0xFF
                if not location:
                    continue
                with self.subTest(location=location):
                    self.assertTrue(walk[row0 + row][col0 + col] & canon.MASK_LAND)

    def test_new_cells_carry_a_terrain_kind(self):
        # Без вида местности клетка не даёт встреч и молча выпадает из игры.
        # Считаем разом, а не через subTest: клеток больше тысячи.
        row0, col0 = self.rules["canon_at"]
        empty = [(row, col)
                 for row, line in enumerate(self.rules["grid"])
                 for col, cell in enumerate(line)
                 if not (row0 <= row < row0 + canon.ROWS and
                         col0 <= col < col0 + canon.COLS)
                 and not (cell >> canon.CELL_TERRAIN) & 0xFF]
        self.assertFalse(empty, f"клетки без вида местности: {empty[:10]}")


@needs_game
@needs_dataset
class TestScreenOriginIsRejected(unittest.TestCase):
    """Пак с экранным углом не должен собираться вовсе.

    Так уже вышло: клиент перевели на угол в координатах картинки, а пак,
    которым играли, остался со старым, экранным. Ошибки не было ни одной —
    просто карта осталась канонной 884x709, а сетка, туман и все значки
    уехали вправо на ширину панели.
    """

    def test_screen_origin_raises(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "worldmap").mkdir()
            document = json.loads(DATASET.read_text(encoding="utf-8"))
            # Сдвигаем угол на ширину панели — ровно то, что даёт старый пак.
            document["origin"] = [document["origin"][0] + PANEL_WIDTH,
                                  document["origin"][1]]
            (root / pack.DATASET).write_text(json.dumps(document),
                                             encoding="utf-8")
            with self.assertRaises(ValueError):
                pack.rules(root)


class TestClientKeepsOneCoordinateSystem(unittest.TestCase):
    """В коде карты мира не должно остаться экранных пересчётов.

    Ширину панели знает РОВНО ОДНО место — `originInPicture` в worldmap.js,
    и знает ради старых паков. Всё остальное — и сетка, и туман, и значки,
    и место отряда, и щелчок — живёт в координатах картинки.

    Раньше их было три: щит отряда рисовался со сдвигом влево, а щелчок
    «войти» и цель похода — со сдвигом вправо. Пока угол приходил экранным,
    они друг друга гасили; как только угол стал картиночным, разъехались.
    """

    #: Кусок ui.js, где живёт карта мира.
    FIRST, LAST = "function mapGeometry", "export function worldMapBusy"

    def test_world_map_code_does_not_touch_panel_width(self):
        text = (STATIC / "ui.js").read_text(encoding="utf-8")
        start, end = text.index(self.FIRST), text.index(self.LAST)
        block = text[start:end]
        lines = [f"ui.js:{line}" for line in block.splitlines()
                 if "panel_width" in line and not line.lstrip().startswith("//")]
        self.assertEqual(lines, [], "карта мира снова считает по экрану")

    def test_panel_width_lives_in_one_place(self):
        text = (STATIC / "worldmap.js").read_text(encoding="utf-8")
        self.assertIn("function originInPicture", text)


@needs_game
class TestSwitch(unittest.TestCase):
    """Переключатель лежит в данных, а не в коде."""

    def test_missing_dataset_gives_canon(self):
        rules = pack.rules(Path(__file__).resolve().parent)   # тут набора нет
        self.assertEqual((rules["cols"], rules["rows"]), (canon.COLS, canon.ROWS))

    @needs_dataset
    def test_disabled_dataset_gives_canon(self):
        import tempfile
        import shutil
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "worldmap").mkdir()
            document = json.loads(DATASET.read_text(encoding="utf-8"))
            document["enabled"] = False
            (root / pack.DATASET).write_text(json.dumps(document),
                                             encoding="utf-8")
            rules = pack.rules(root)
        self.assertEqual((rules["cols"], rules["rows"]), (canon.COLS, canon.ROWS))


if __name__ == "__main__":
    unittest.main()


class CanonInsteadContractTest(unittest.TestCase):
    """Значок ведёт в карту СВОЕЙ игры, хотя байт в клетке один.

    Под локацию в клетке движка отведён один байт, поэтому две игры делят
    одно место мира: донорский Чёрный Бор объявил ``"replaces": 19`` и занял
    клетку канонного. Значок при этом канонный — клетка лежит на канонной
    части картинки карты мира.

    Пока выбора не было, канонный герой со значка приходил в донорскую
    деревню: ни Велиславны, ни её разговора, зато Ярополк. Тестер записал это
    как «не Кровь Титанов канон», и был прав.
    """

    def test_the_table_names_the_canon_map(self) -> None:
        from knyaz2.content import worldmap
        свод = worldmap.rules("project")
        подмена = свод.get("canon_instead") or {}
        self.assertEqual(подмена.get("169"), 19,
                         "донорский Чёрный Бор обязан назвать канонный 19")
        #: Вытеснять можно только канонную локацию, значит все значения
        #: таблицы лежат в канонном диапазоне.
        for донор, канон in подмена.items():
            self.assertGreater(int(донор), 150, "вытесняет только донорская")
            self.assertLessEqual(канон, 150, "вытесняется только канонная")

    def test_the_client_asks_the_table(self) -> None:
        import pathlib
        корень = pathlib.Path(__file__).resolve().parents[1]
        ui = (корень / "knyaz2" / "web" / "static" / "ui.js").read_text(encoding="utf-8")
        self.assertIn("canon_instead", ui)
        self.assertIn("ownGameLocation", ui)
        #: Вход идёт ЧЕРЕЗ подмену, а не мимо неё.
        self.assertIn("world.onTravel?.(ownGameLocation(number))", ui)
