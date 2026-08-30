# -*- coding: utf-8 -*-
"""Договор реестра локаций: канон владеет началом, проект продолжением.

Опора всего — НОМЕР ЛОКАЦИИ РАВЕН НОМЕРУ КАРТЫ. Это видно прямо на каноне,
и на этом же держится нумерация переносимых карт, поэтому проверяется
первым. Дальше — что проектная локация действительно достижима: стоит на
суше, не поверх канонной, попала в сетку карты мира и получила имя, значок
и место прибытия.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from konung2 import worldmap as canon
from konung2.paths import game_file
from knyaz2.content import locations
from knyaz2.content import worldmap as pack

GAME_AVAILABLE = os.path.isfile(game_file("konung2.exe"))
needs_game = unittest.skipUnless(GAME_AVAILABLE, "игра недоступна: нет konung2.exe")

PROJECT = Path(__file__).resolve().parent.parent / "project"
needs_registry = unittest.skipUnless(
    (PROJECT / locations.REGISTRY).is_file(), "реестра локаций нет")


@needs_game
class TestLocationIsMapNumber(unittest.TestCase):
    """Номер локации и номер карты — одно число."""

    def test_canon_names_sit_at_their_map_numbers(self):
        names = canon.location_names()
        self.assertEqual(names[19], "Черный Бор")
        self.assertEqual(names[33], "Борье")
        self.assertEqual(names[26], "Корабль в пути")

    def test_canon_owns_up_to_forty_three(self):
        # Столько записей в таблицах имён и значков; проект начинается с 44.
        self.assertEqual(locations.CANON_LAST, canon.MARKER_COUNT - 1)
        self.assertEqual(locations.CANON_LAST, 43)

    def test_number_fits_one_byte(self):
        # Под локацию в клетке карты мира отведён байт, и правило
        # «150 + номер донора» укладывает все 90 карт в 151…249.
        self.assertEqual(locations.MAX_NUMBER, 0xFF)
        self.assertLessEqual(150 + 99, locations.MAX_NUMBER)


class TestRegistryValidation(unittest.TestCase):
    """Кривая запись должна падать при сборке, а не в игре."""

    def _write(self, entry):
        root = Path(self.temporary.name)
        (root / locations.REGISTRY).write_text(
            json.dumps({"locations": [entry]}, ensure_ascii=False),
            encoding="utf-8")
        return root

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.good = {"number": 156, "name": "Холмогорье", "cell": [8, 18],
                     "marker": {"sprite": 256, "dx": 0, "dy": 0},
                     "arrival": {"row": 50, "col": 22}}

    def test_missing_registry_is_legal(self):
        self.assertEqual(locations.registry(self.temporary.name), [])

    def test_good_entry_passes(self):
        self.assertEqual(len(locations.registry(self._write(self.good))), 1)

    def test_canon_number_is_refused(self):
        # Иначе проект молча переименовал бы канонную локацию.
        with self.assertRaises(ValueError):
            locations.registry(self._write({**self.good, "number": 33}))

    def test_number_beyond_a_byte_is_refused(self):
        with self.assertRaises(ValueError):
            locations.registry(self._write({**self.good, "number": 300}))

    def test_takeover_of_a_project_location_is_refused(self):
        """Вытеснять можно только канонную: у проектных клетки не спорят."""
        with self.assertRaises(ValueError):
            locations.registry(self._write({**self.good, "replaces": 156}))

    def test_incomplete_entry_is_refused(self):
        for key in locations.REQUIRED:
            with self.subTest(key=key):
                broken = {k: v for k, v in self.good.items() if k != key}
                with self.assertRaises(ValueError):
                    locations.registry(self._write(broken))


class TestStamp(unittest.TestCase):
    """Клетка на карте мира: локация обязана быть достижимой."""

    LAND, SEA = 1, 2

    def setUp(self):
        self.grid = [[0] * 4 for _ in range(3)]
        self.walk = [[self.LAND] * 4 for _ in range(3)]
        self.entry = {"number": 156, "name": "Х", "cell": [1, 2],
                      "marker": {}, "arrival": {"row": 0, "col": 0}}

    def test_number_lands_in_the_cell(self):
        out = locations.stamp(self.grid, self.walk, [self.entry], self.LAND)
        self.assertEqual(out[1][2] & 0xFF, 156)
        self.assertEqual(self.grid[1][2], 0, "исходную сетку портить нельзя")

    def test_other_fields_of_the_cell_survive(self):
        self.grid[1][2] = 4 << canon.CELL_TERRAIN
        out = locations.stamp(self.grid, self.walk, [self.entry], self.LAND)
        self.assertEqual((out[1][2] >> canon.CELL_TERRAIN) & 0xFF, 4)

    def test_sea_cell_is_refused(self):
        self.walk[1][2] = self.SEA
        with self.assertRaises(ValueError):
            locations.stamp(self.grid, self.walk, [self.entry], self.LAND)

    def test_cell_outside_the_grid_is_refused(self):
        with self.assertRaises(ValueError):
            locations.stamp(self.grid, self.walk,
                            [{**self.entry, "cell": [9, 9]}], self.LAND)

    def test_busy_cell_is_refused(self):
        self.grid[1][2] = 33
        with self.assertRaises(ValueError):
            locations.stamp(self.grid, self.walk, [self.entry], self.LAND)

    def test_declared_takeover_is_allowed(self):
        """Заявленный захват канонной клетки проходит, и номер меняется.

        Одно место мира, две игры: донорский Чёрный Бор приходится ровно на
        канонный. Занять клетку может лишь одна карта, и запись обязана
        назвать вытесняемую — тогда это решение, а не случайность.
        """
        self.grid[1][2] = (7 << canon.CELL_TERRAIN) | 19
        out = locations.stamp(self.grid, self.walk,
                              [{**self.entry, "replaces": 19}], self.LAND)
        self.assertEqual(out[1][2] & 0xFF, 156)
        self.assertEqual((out[1][2] >> canon.CELL_TERRAIN) & 0xFF, 7,
                         "остальные поля клетки захват не трогает")

    def test_takeover_of_another_location_is_refused(self):
        """Заявлен захват одной локации, а в клетке стоит другая."""
        self.grid[1][2] = 33
        with self.assertRaises(ValueError):
            locations.stamp(self.grid, self.walk,
                            [{**self.entry, "replaces": 19}], self.LAND)

    HIDDEN = 0x80

    def test_revealed_clears_the_hidden_flag(self):
        """Снятие флага «скрыта»: значок появляется на общих правах.

        Шесть канонных локаций и две засады лежат в сетке с 0x80, и их
        значка нет, пока сюжет не откроет локацию. Проектная карта, занявшая
        такую клетку, наследует флаг — и остаётся невидимой навсегда, если
        открывающего разговора у героя нет.
        """
        self.grid[1][2] = self.HIDDEN << 24
        out = locations.stamp(self.grid, self.walk,
                              [{**self.entry, "revealed": True}], self.LAND,
                              hidden_bit=self.HIDDEN)
        self.assertEqual((out[1][2] >> 24) & 0xFF, 0)
        self.assertEqual(out[1][2] & 0xFF, 156)

    def test_other_knowledge_flags_survive_revealing(self):
        """Снимается ровно «скрыта», туман остаётся своим."""
        self.grid[1][2] = (self.HIDDEN | 0x20) << 24
        out = locations.stamp(self.grid, self.walk,
                              [{**self.entry, "revealed": True}], self.LAND,
                              hidden_bit=self.HIDDEN)
        self.assertEqual((out[1][2] >> 24) & 0xFF, 0x20)

    def test_revealing_without_the_flag_value_is_refused(self):
        """Без самого флага правка ничего бы не сделала — это надо знать."""
        self.grid[1][2] = self.HIDDEN << 24
        with self.assertRaises(ValueError):
            locations.stamp(self.grid, self.walk,
                            [{**self.entry, "revealed": True}], self.LAND)

    def test_takeover_of_an_empty_cell_is_refused(self):
        """Заявка, которая никого не вытесняет, — след прошлой раскладки.

        Клетку могли передвинуть; молча приняв заявку, мы бы развели две
        локации по карте мира и узнали об этом только от игрока.
        """
        with self.assertRaises(ValueError):
            locations.stamp(self.grid, self.walk,
                            [{**self.entry, "replaces": 19}], self.LAND)


@needs_game
@needs_registry
class TestRegistryInTheRules(unittest.TestCase):
    """Проектная локация доезжает до правил пака целиком."""

    @classmethod
    def setUpClass(cls):
        cls.entries = locations.registry(PROJECT)
        cls.rules = pack.rules(PROJECT)

    def test_every_entry_is_on_the_grid(self):
        for entry in self.entries:
            number = int(entry["number"])
            row, col = entry["cell"]
            with self.subTest(number=number):
                self.assertEqual(self.rules["grid"][row][col] & 0xFF, number)

    def test_every_entry_has_name_marker_and_arrival(self):
        for entry in self.entries:
            number = int(entry["number"])
            with self.subTest(number=number):
                self.assertEqual(self.rules["names"][number], entry["name"])
                # ЗНАЧОК МОЖЕТ БЫТЬ ПУСТЫМ — это решение, а не забытое поле:
                # локация без значка стоит в сетке, но на карте не рисуется
                # (канонные морские 26/27, его «Лес у Кирингхольма»). Пустой
                # значок в словарь не попадает — клиент рисует только то,
                # что в словаре.
                if entry["marker"] is None:
                    self.assertNotIn(str(number), self.rules["markers"])
                else:
                    self.assertIn(str(number), self.rules["markers"])
                self.assertIn(str(number), self.rules["arrivals"])

    def test_markerless_entries_mirror_the_donor(self):
        """Пустой значок не выдуман: у донора этой локации значка нет.

        И наоборот: всем, у кого значок есть, он взят из его данных, а не
        назначен. Раньше «Лес у Кирингхольма» и три морских боя ехали со
        спрайтом 256 «от фонаря» — в его игре такого значка у них нет.

        Исключение одно и оно тоже сверяется с данными: запись с захватом
        канонной клетки (``replaces``) стоит на КАНОННОЙ части картинки, и
        значок ей положен канонный — тот самый, что канон рисует в этой
        клетке. Проверяется это ниже, отдельным правилом, а не поблажкой.
        """
        from konung2 import donor
        if not donor.available():
            self.skipTest("донор недоступен")
        checked = 0
        for entry in self.entries:
            native = int(entry["number"]) - 150
            if not 0 < native < 100 or locations.REPLACES in entry:
                continue
            real = donor.world_marker(native)
            checked += 1
            with self.subTest(number=entry["number"]):
                if entry["marker"] is None:
                    self.assertEqual(real, 0, "значок есть в данных, а у нас пусто")
                else:
                    self.assertEqual(entry["marker"]["sprite"], real)
        self.assertGreater(checked, 20)

    def test_replacing_entries_wear_the_canon_marker(self):
        """Захватившая канонную клетку носит значок вытесненной локации.

        Клетка донорского Чёрного Бора пришлась ровно на канонную: это одно
        место мира в двух играх. Картинка карты мира там канонная, деревня
        на ней нарисована канонной — значит и значок канонный (0x4615CC),
        со своим сдвигом. Значок донора (у его записи это 256) сюда ставить
        нельзя: он от его картинки, и на канонной карте это подмена вида.
        """
        canon_markers = canon.markers()
        checked = 0
        for entry in self.entries:
            replaced = entry.get(locations.REPLACES)
            if replaced is None:
                continue
            checked += 1
            with self.subTest(number=entry["number"]):
                self.assertIsNotNone(entry["marker"],
                                     "вытесняя канонную локацию, значок нельзя "
                                     "убирать: место останется без метки")
                self.assertEqual(entry["marker"], dict(canon_markers[replaced]))
        self.assertGreater(checked, 0, "записей с захватом нет — правило мертво")

    def test_replaced_canon_location_leaves_the_grid(self):
        """Вытесненная локация уходит с карты мира совсем.

        Байт клетки один, и войти можно только в одну карту. Если после
        захвата номер вытесненной остался ещё где-то в сетке, значит клетку
        задвоили, и игрок попадёт не туда, куда показывает значок.
        """
        grid = self.rules["grid"]
        for entry in self.entries:
            replaced = entry.get(locations.REPLACES)
            if replaced is None:
                continue
            left = [(row, col) for row, line in enumerate(grid)
                    for col, value in enumerate(line) if value & 0xFF == replaced]
            with self.subTest(number=entry["number"]):
                self.assertEqual(left, [], f"локация {replaced} вытеснена, "
                                           f"но осталась в клетках {left}")

    def test_revealed_entries_are_visible_in_the_pack(self):
        """Заявившая ``revealed`` доехала до сетки без флага «скрыта».

        Проверка сквозная, от реестра до правил пака: правило легко сделать
        и не подключить — тогда значка на карте мира так и не будет, а тест
        на самой `stamp` останется зелёным.
        """
        hidden = self.rules["flags"]["hidden"]
        checked = 0
        for entry in self.entries:
            if not entry.get(locations.REVEALED):
                continue
            checked += 1
            row, col = entry["cell"]
            with self.subTest(number=entry["number"]):
                self.assertFalse((self.rules["grid"][row][col] >> 24) & hidden,
                                 "флаг «скрыта» остался: значок не появится")
        self.assertGreater(checked, 0, "записей со снятием флага нет")

    def test_canon_names_are_untouched(self):
        canon_names = canon.location_names()
        self.assertEqual(self.rules["names"][:len(canon_names)], canon_names)

    def test_arrival_cell_is_passable(self):
        """Отряд не должен появляться в стене.

        Прибытие замеряется по самой карте, и замер уже был неверным: он
        сравнивал пустую клетку с 0xFFFF, хотя у нас она 0x4FFF, и считал
        проходимой любую занятую. На донорских картах, у которых до перевода
        не было ни одной стены, это давало прибытие посреди дома.
        """
        import glob

        from konung2.kn2 import KN2Map
        for entry in self.entries:
            number = int(entry["number"])
            found = glob.glob(str(PROJECT / "maps" / f"{number}_*"))
            if not found:
                continue
            with self.subTest(number=number):
                kn2 = KN2Map.pack(found[0])
                place = entry["arrival"]
                low = kn2.cell(int(place["col"]), int(place["row"]))[0]
                self.assertFalse(low & 0x0FFF,
                                 f"прибытие {entry['name']} в непроходимой клетке")

    def test_every_map_has_walls(self):
        """Карта без единой непроходимой клетки — это карта, где ходят сквозь дома."""
        import glob

        from konung2.kn2 import GRID_H, GRID_W, KN2Map
        for entry in self.entries:
            number = int(entry["number"])
            found = glob.glob(str(PROJECT / "maps" / f"{number}_*"))
            if not found:
                continue
            with self.subTest(number=number):
                kn2 = KN2Map.pack(found[0])
                walls = sum(1 for row in range(GRID_H) for col in range(GRID_W)
                            if kn2.cell(col, row)[0] & 0x0FFF)
                self.assertGreater(walls, 100, f"{entry['name']}: стен нет")

    def test_donor_maps_declare_their_origin(self):
        """Перенесённая карта обязана помнить, из чьей игры она и под каким номером.

        По этой записи сборщик разворачивает чтение жителей на GAME.<мир>
        донора. Нет её — деревня приезжает пустой, и заметить это можно
        только зайдя в неё.
        """
        import glob

        from konung2 import donor
        for entry in self.entries:
            number = int(entry["number"])
            found = glob.glob(str(PROJECT / "maps" / f"{number}_*" / "map.json"))
            if not found:
                continue
            with self.subTest(number=number):
                origin = json.loads(Path(found[0]).read_text(
                    encoding="utf-8")).get("origin")
                self.assertIsNotNone(origin, f"{entry['name']}: нет origin")
                self.assertEqual(origin["game"], donor.LEGEND_NAME)
                self.assertEqual(origin["map"], number - 150)

    def test_entry_stands_where_it_can_be_reached(self):
        """До локации должно быть чем добраться — ногами или по воде.

        Морская локация законна: у «Продолжения легенды» три «Боя с
        морскими разбойниками» стоят на воде, и это правильно — туда
        приплывают. Но такая запись обязана СКАЗАТЬ о себе: иначе на воду
        попадёт промах вроде его Капища Вотана, и мы этого не заметим.
        """
        for entry in self.entries:
            row, col = entry["cell"]
            walk = self.rules["walk"][row][col]
            with self.subTest(number=entry["number"]):
                if entry.get("sea"):
                    self.assertTrue(walk & canon.MASK_SEA)
                else:
                    self.assertTrue(walk & canon.MASK_LAND)

    def test_sea_locations_are_only_the_sea_ones(self):
        """Заявленных морских ровно три, и все три — морские бои."""
        by_sea = [entry for entry in self.entries if entry.get("sea")]
        self.assertEqual(len(by_sea), 3)
        for entry in by_sea:
            with self.subTest(number=entry["number"]):
                self.assertIn("морскими разбойниками", entry["name"])
                walk = self.rules["walk"][entry["cell"][0]][entry["cell"][1]]
                self.assertFalse(walk & canon.MASK_LAND, "это не море вовсе")


if __name__ == "__main__":
    unittest.main()
