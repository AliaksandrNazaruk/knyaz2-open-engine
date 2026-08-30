# -*- coding: utf-8 -*-
"""Договор чтения донора — «Продолжения легенды».

Донор читается один раз, при подготовке данных проекта, и всё, что от него
нужно, снято замером по самим файлам. Здесь эти замеры закреплены: если
сдвинется таблица, изменится формат карты или разойдутся каталоги — тест
упадёт, а не выдаст правдоподобный мусор.

Особый случай — первый тест. Разбор секций PE применяется к ЧУЖОМУ файлу,
и доверять ему можно только доказав, что на своём он даёт ровно те
константы, которые сняты вручную и годами работают.
"""
from __future__ import annotations

import os
import unittest

from konung2 import donor
from konung2 import worldmap as canon
from konung2.exetables import SECTIONS
from konung2.kn2 import GRID_H, GRID_W, KN2Map, MAP_SIZE
from konung2.paths import game_file
from konung2.res import ObjectsRes

GAME_AVAILABLE = os.path.isfile(game_file("konung2.exe"))
needs_game = unittest.skipUnless(GAME_AVAILABLE, "игра недоступна: нет konung2.exe")
needs_donor = unittest.skipUnless(
    donor.available(), f"донор недоступен: нет {donor.DONOR_EXE}")


@needs_game
class TestSectionsParserAgreesWithCanon(unittest.TestCase):
    """Разбор заголовка PE обязан дать то же, что зашито вручную."""

    def test_parsed_sections_match_hard_coded(self):
        with open(game_file("konung2.exe"), "rb") as stream:
            blob = stream.read()
        parsed = {name: (rva, size, at)
                  for name, rva, size, at in donor.sections(blob)}
        for name, rva, size, at in SECTIONS:
            with self.subTest(section=name):
                self.assertIn(name, parsed)
                self.assertEqual(parsed[name], (rva, size, at))


@needs_donor
class TestDonorTables(unittest.TestCase):
    """Таблицы донора: границы посчитаны, а не назначены."""

    @classmethod
    def setUpClass(cls):
        cls.exe = donor.DonorExe.load()

    def test_location_stride_is_not_four(self):
        # Наши локации — простой массив указателей с шагом 4, донорские —
        # записи по 46 байт. Шаг на четыре не делится, и выровненный поиск
        # теряет каждую вторую запись: так пропали «Черный Бор» и «Тиграт».
        self.assertEqual(donor.DONOR_LOCATION_STRIDE % 4, 2)

    def test_location_table_ends_where_names_begin(self):
        gap = donor.DONOR_NPC_NAMES_AT - donor.DONOR_LOCATIONS_AT
        self.assertEqual(donor.DONOR_LOCATION_COUNT,
                         gap // donor.DONOR_LOCATION_STRIDE)
        self.assertLess(gap % donor.DONOR_LOCATION_STRIDE,
                        donor.DONOR_LOCATION_STRIDE)

    def test_location_names_are_readable(self):
        # Пустые записи есть и у нас (номера 0, 4, 5), поэтому пустая строка
        # это не поломка. Проверяем, что читается подавляющее большинство:
        # мусорный шаг или неверное начало обрушили бы долю сразу.
        names = self.exe.location_names()
        self.assertEqual(len(names), donor.DONOR_LOCATION_COUNT)
        self.assertGreater(sum(1 for name in names if name), 90)

    def test_location_number_equals_map_number(self):
        # ГЛАВНАЯ ОПОРА ВСЕЙ НУМЕРАЦИИ, и в ней же было ошиблись на две
        # записи. Донорская карта 19 доказана геометрически как «Черный
        # Бор»; если имя встаёт на 19 — начало таблицы найдено верно.
        names = self.exe.location_names()
        self.assertEqual(names[19], "Черный Бор")
        # Корабли сходятся и по имени, и по геометрии: наши карты 26 и 27 —
        # двойники донорских 1 и 2.
        self.assertEqual(names[1], "Корабль в пути")
        self.assertEqual(names[2], "Бой на корабле")

    def test_desert_content_is_named(self):
        names = self.exe.location_names()
        self.assertIn("Оазис", names)
        self.assertIn("Деревушка в песках", names)
        self.assertIn("Кирингхольм", names)

    def test_npc_names_start_with_the_empty_slot(self):
        """Нулевой номер имени обязан быть пустым — это «без имени».

        Сначала таблица была взята на запись позже, и каждый безымянный
        житель выходил «Белуном». Распределение номеров у донорских юнитов
        совпадает с нашим (чаще всего ноль, дальше 173, 177, 168, 174), и
        значит ноль пустой у обоих.
        """
        names = self.exe.npc_names()
        self.assertEqual(len(names), donor.DONOR_NPC_NAME_COUNT)
        self.assertEqual(names[0], "")
        self.assertEqual(names[1], "Белун")
        self.assertIn("Яман", names)

    def test_location_table_ends_exactly_at_the_names(self):
        # При верном начале таблицы имён локации кончаются ровно на нём,
        # без остатка. Это независимая проверка обеих границ разом.
        gap = donor.DONOR_NPC_NAMES_AT - donor.DONOR_LOCATIONS_AT
        self.assertEqual(gap % donor.DONOR_LOCATION_STRIDE, 0)
        self.assertEqual(gap // donor.DONOR_LOCATION_STRIDE,
                         donor.DONOR_LOCATION_COUNT)


@needs_game
@needs_donor
class TestDonorWorldGrid(unittest.TestCase):
    """Сетка карты мира донора и то, как она ложится на нашу.

    Адрес найден по геометрии, а не перебором: две игры описывают одну
    страну с наложением, и наш Чёрный Бор обязан оказаться в той же клетке,
    что донорский. Здесь это и проверяется — иначе сдвиг подобран, а не
    измерен, и все донорские локации встанут не туда.
    """

    @classmethod
    def setUpClass(cls):
        cls.places = donor.world_locations()

    def test_grid_is_clean(self):
        # 28 локаций, каждая по одному разу, и у каждой есть свой .kn2.
        # Ложные таблицы, на которые поиск натыкался, этого не давали:
        # там локации повторялись десятками.
        self.assertEqual(len(self.places), 28)
        have = set(donor.map_numbers())
        self.assertEqual(sorted(set(self.places) - have), [])

    def test_black_bor_lands_on_our_black_bor(self):
        # Единственная клетка, за которую две игры спорят, — и это ровно та
        # деревня, которая есть в обеих.
        grid = canon.grid()
        ours = [(row, col) for row in range(canon.ROWS) for col in range(canon.COLS)
                if grid[row][col] & 0xFF == 19][0]
        row0, col0 = 0, 22                      # где сидит канон на общей карте
        self.assertEqual(self.places[19], (ours[0] + row0, ours[1] + col0))

    def test_only_black_bor_collides(self):
        grid = canon.grid()
        row0, col0 = 0, 22
        mine = {(row + row0, col + col0): grid[row][col] & 0xFF
                for row in range(canon.ROWS) for col in range(canon.COLS)
                if grid[row][col] & 0xFF}
        clash = {place: (mine[place], location)
                 for location, place in self.places.items() if place in mine}
        self.assertEqual(clash, {self.places[19]: (19, 19)})


@needs_donor
class TestDonorMaps(unittest.TestCase):
    """Формат карт донора и что теряется при обрезке."""

    @classmethod
    def setUpClass(cls):
        cls.numbers = donor.map_numbers()

    def test_ninety_maps(self):
        self.assertEqual(len(self.numbers), 90)
        self.assertEqual(max(self.numbers), 99)

    def test_only_three_maps_use_the_extra_zones(self):
        # Хвост — 32 записи обстановки сверх нашего формата, пустая залита
        # 0xFF. Заняты они лишь у трёх карт, и эти три крупнее наших.
        heavy = {}
        for number in self.numbers:
            _, beyond = donor.map_data(number)
            if beyond:
                heavy[number] = beyond
        self.assertEqual(heavy, {4: 26, 5: 15, 26: 2})

    def test_map_arrives_whole(self):
        """Карта приезжает ЦЕЛИКОМ, вместе с хвостом обстановки.

        Раньше здесь стояло `len(data) == MAP_SIZE` — хвост резался, и с ним
        пропадала обстановка построек с тридцатой.
        """
        from konung2.kn2 import zone_count
        data, beyond = donor.map_data(19)
        self.assertEqual(len(data), 262660)
        self.assertEqual(zone_count(data), 62)
        self.assertEqual(beyond, 0, "у 19-й лишние записи пусты")
        self.assertGreater(KN2Map(19, data).used_cells(), 0)


@needs_game
@needs_donor
class TestPassabilityTranslation(unittest.TestCase):
    """Непроходимость донора переводится в наш формат.

    Без перевода донорская карта приезжает БЕЗ ЕДИНОЙ СТЕНЫ: у нас
    непроходимость это младшие 12 бит младшего слова, а донор перенёс её в
    бит 0x1000 и младшие обнулил. Герой ходил сквозь дома, а «ближайшая
    проходимая клетка» оказывалась любой занятой — отсюда и прибытие
    посреди постройки.
    """

    def test_donor_maps_have_no_low_bits_of_their_own(self):
        # Причина: во всех 90 картах донора нет ни одной клетки с нашими
        # младшими битами. Если это когда-нибудь перестанет быть правдой,
        # перевод станет опасен и об этом надо узнать здесь.
        for number in (6, 16, 19):
            with self.subTest(number=number):
                raw, _ = donor.map_data(number, translate=False)
                kn2 = KN2Map(number, raw)
                low = 0
                for row in range(GRID_H):
                    for col in range(GRID_W):
                        low |= kn2.cell(col, row)[0]
                self.assertFalse(low & donor.CANON_BLOCKED)
                self.assertTrue(low & donor.DONOR_BLOCKED)

    def test_translation_maps_onto_our_four_values(self):
        raw, _ = donor.map_data(19)
        kn2 = KN2Map(19, raw)
        values = {kn2.cell(col, row)[0]
                  for row in range(GRID_H) for col in range(GRID_W)}
        # ровно те же значения, что в нашей карте: земля, стена, край, пол
        self.assertLessEqual(values, {0x0000, 0x0FFF, 0x4FFF, 0x8000, 0x4000})

    def test_translated_walls_match_the_twin(self):
        # Карта 19 — Чёрный Бор в обеих играх, стены те же. Расхождение
        # объясняется достроенной у донора хижиной знахаря.
        theirs = KN2Map(19, donor.map_data(19)[0])
        ours = KN2Map.from_game(19)
        same = sum(1 for row in range(GRID_H) for col in range(GRID_W)
                   if bool(theirs.cell(col, row)[0] & donor.CANON_BLOCKED)
                   == bool(ours.cell(col, row)[0] & donor.CANON_BLOCKED))
        self.assertGreater(same / (GRID_W * GRID_H), 0.95)

    def test_his_flags_stand_one_bit_higher_because_the_number_is_wider(self):
        """Флаги у донора выше на бит — потому что поле номера шире на бит.

        Это одно свойство, а не два. У канона номер постройки пятибитный, и
        больше 31 постройки на карте быть не может; у донора шестибитный, и
        в его Кирингхольме их 58. Читается его карта СВОЕЙ раскладкой, а не
        переводится: шестибитный номер в наши пять бит не влезает.
        """
        from konung2.world.model import CANON_CELLS, LEGEND_CELLS
        theirs = KN2Map(19, donor.map_data(19)[0])
        ours = KN2Map.from_game(19)

        def flagged(kn2, mask):
            return {(row, col) for row in range(GRID_H) for col in range(GRID_W)
                    if kn2.cell(col, row)[1] & mask}

        # Чёрный Бор — общее место: дневные клетки совпадают все до одной,
        # маршрутные донора — подмножество наших (у канона на 27 больше:
        # хижина знахаря у нас не достроена).
        with self.subTest(flag="routed"):
            his = flagged(theirs, LEGEND_CELLS.routed)
            mine = flagged(ours, CANON_CELLS.routed)
            self.assertTrue(his)
            self.assertGreaterEqual(len(his & mine) / len(his), 0.99)
        with self.subTest(flag="bright"):
            self.assertEqual(flagged(theirs, LEGEND_CELLS.bright),
                             flagged(ours, CANON_CELLS.bright))

        # А ширина поля видна на его больших картах: по пяти битам номеров
        # находится вдвое меньше, чем построек на самом деле.
        big = KN2Map(4, donor.map_data(4)[0])
        def numbers(mask):
            found = {big.cell(col, row)[1] & mask
                     for row in range(GRID_H) for col in range(GRID_W)}
            found.discard(0)
            return found
        with self.subTest(width="шесть бит против пяти"):
            self.assertGreater(len(numbers(LEGEND_CELLS.building)),
                               len(numbers(CANON_CELLS.building)) + 20)
            self.assertGreater(max(numbers(LEGEND_CELLS.building)), 31)

    def test_translation_leaves_the_high_word_alone(self):
        """Перевод трогает ТОЛЬКО проходимость.

        Прежняя запись резала номер по пяти битам и сдвигала флаги вниз:
        постройка 38 (0xE6) становилась постройкой 6 (0x66), и на
        Кирингхольме клетки теряли 29 построек из 58 — крыша не пряталась,
        юнит рисовался поверх дома.
        """
        for number in (4, 16):
            with self.subTest(number=number):
                source = KN2Map(number, donor.map_data(number, translate=False)[0])
                cooked = KN2Map(number, donor.map_data(number)[0])
                for row in range(GRID_H):
                    for col in range(GRID_W):
                        low, high = source.cell(col, row)
                        low2, high2 = cooked.cell(col, row)
                        self.assertEqual(high2, high)
                        self.assertEqual(low2 & 0x8000, low & 0x8000)


@needs_game
@needs_donor
class TestItemClasses(unittest.TestCase):
    """Классы предметов донора: таблица найдена, поля сдвинуты на байт.

    Запись 32 байта, в начале указатель на название — по этому признаку
    таблица и находится. Байты +0x04..+0x10 совпадают с нашими у всех
    предметов с одинаковым именем, а с +0x12 идут НА БАЙТ РАНЬШЕ: без
    поправки цена и вес выходят мусором (11264, 22273).
    """

    @classmethod
    def setUpClass(cls):
        from konung2.items import read_items
        from konung2.profile import LEGEND
        cls.ours = read_items()
        cls.theirs = read_items(profile=LEGEND)
        cls.pairs = [(a, b) for a, b in zip(cls.ours, cls.theirs)
                     if a.name == b.name]

    def test_table_is_found(self):
        self.assertEqual(len(self.ours), 211)
        self.assertEqual(len(self.theirs), 212)
        self.assertEqual(self.theirs[0].name, "Береста")

    def test_most_items_share_their_number(self):
        # 193 из 211: остальные донор заменил своими.
        self.assertGreaterEqual(len(self.pairs), 190)

    def test_shifted_fields_read_the_same_values(self):
        # Байт вставлен перед +0x12 и к концу записи отыгрывается обратно:
        # цена, вес, значок и ground читаются со сдвигом, а палитра — без.
        for field, least in (("price", 190), ("weight", 193),
                             ("icon", 190), ("ground", 193),
                             ("palette_offset", 170)):
            with self.subTest(field=field):
                same = sum(1 for a, b in self.pairs
                           if getattr(a, field) == getattr(b, field))
                self.assertGreaterEqual(same, least)

    def test_layer_is_honestly_unverified(self):
        """Слой снаряжения для чужой сборки НЕ найден, и это записано.

        Перебор всех смещений записи не дал победителя: лучшее 89 из 193
        при уровне шума 85. Тест сторожит, чтобы «не нашли» со временем не
        превратилось в «нашли» молча: если поле вдруг начнёт сходиться,
        значит его место установлено и комментарий пора менять.
        """
        same = sum(1 for a, b in self.pairs if a.layer == b.layer)
        self.assertLess(same, len(self.pairs) * 0.9)

    def test_donor_has_its_own_items(self):
        ours = {item.name for item in self.ours}
        fresh = [item.name for item in self.theirs if item.name not in ours]
        self.assertIn("Ключ Воды", fresh)
        self.assertIn("Книга Мудрых", fresh)


@needs_game
@needs_donor
class TestCatalogues(unittest.TestCase):
    """Что придётся ввозить, а что нет."""

    def test_donor_objects_go_beyond_our_catalogue(self):
        # 73 спрайта донора (480..557) у нас отсутствуют — их гнёзда
        # 510..587, и ввоз получается дозаписью в конец без перенумерации.
        with open(game_file("OBJECTS.RES"), "rb") as stream:
            catalogue = ObjectsRes(stream.read())
        missing = set()
        for number in donor.map_numbers():
            data, _ = donor.map_data(number)
            for entry in KN2Map(number, data).objects():
                sprite = entry.get("sprite", -1)
                if sprite <= 0 or entry["pixel_x"] == 0xFFFF:
                    continue
                if not catalogue.frame_size(ObjectsRes.slot_of(entry)):
                    missing.add(sprite)
        self.assertEqual((min(missing), max(missing), len(missing)),
                         (480, 557, 73))


@needs_game
@needs_donor
class TestTwinMaps(unittest.TestCase):
    """Двойник — это ТО ЖЕ МЕСТО, а не та же земля.

    Различие не буквоедство: по двойникам переводятся выходы. Ошибись — и
    дверь из донорской пещеры откроется в нашу, чужую ей.
    """

    #: Насколько объект может сдвинуться и всё ещё считаться тем же, точек.
    NEAR = 32

    def _objects(self, kn2):
        """Постройки карты: гнездо и место в точках."""
        out = []
        for record in kn2.objects():
            if record.get("kind", 0xFFFF) in (0xFFFF, 0xFFFFFFFF):
                continue
            x, y = record.get("pixel_x"), record.get("pixel_y")
            if x is None or x == 0xFFFF:
                continue
            out.append((ObjectsRes.slot_of(record), x, y))
        return out

    def _covered(self, first, second):
        """Доля объектов first, у которых в second есть такой же рядом.

        Мера ОДНОСТОРОННЯЯ, и в этом всё дело: на густой карте «такой же
        рядом» находится сам собой. Считать надо в обе стороны.
        """
        if not first:
            return 0.0
        hits = 0
        for slot, x, y in first:
            if any(other == slot and abs(x2 - x) <= self.NEAR
                   and abs(y2 - y) <= self.NEAR for other, x2, y2 in second):
                hits += 1
        return hits / len(first)

    def _pair(self, native, mine):
        data, _ = donor.map_data(native)
        return (self._objects(KN2Map.from_game(mine)),
                self._objects(KN2Map(mine, data)))

    def _named(self):
        """Имена карт обеих игр по номеру.

        У нас таблица мест короткая — 44 записи, только то, что видно на
        глобальной, — поэтому подлокации вроде 45-й берутся из общего
        списка карт.
        """
        from konung2.gamefile import location_names
        from konung2.names import LOCATIONS
        from konung2.profile import LEGEND
        places = location_names()

        def ours(number):
            if 0 <= number < len(places) and places[number]:
                return places[number]
            return LOCATIONS.get(number, "")

        theirs = location_names(profile=LEGEND)
        return ours, (lambda number: theirs[number])

    def test_twins_share_the_name(self):
        ours, theirs = self._named()
        for native, mine in donor.TWIN_MAPS.items():
            with self.subTest(donor_map=native):
                self.assertEqual(ours(mine), theirs(native))

    def test_twins_match_both_ways(self):
        """У двойника застройка сходится в ОБЕ стороны, а не в одну."""
        for native, mine in donor.TWIN_MAPS.items():
            a, b = self._pair(native, mine)
            with self.subTest(donor_map=native):
                self.assertGreater(self._covered(a, b), 0.9)
                self.assertGreater(self._covered(b, a), 0.9)

    def test_one_sided_match_is_not_a_twin(self):
        """Донорское «Ловье» стоит на нашем «Поднебесье», но это не оно.

        Пара считалась двойником по односторонней мере: 0.885. Обратный
        счёт даёт 0.359 — у донора 463 объекта против наших 183, и на
        густой карте похожий сосед находится сам собой.
        """
        ours, theirs = self._named()
        a, b = self._pair(11, 21)
        self.assertNotIn(11, donor.TWIN_MAPS)
        self.assertNotEqual(ours(21), theirs(11))
        self.assertGreater(len(b), 2 * len(a))
        self.assertGreater(self._covered(a, b), 0.8)
        self.assertLess(self._covered(b, a), 0.5)

    def test_reused_level_with_another_name_is_not_a_twin(self):
        """Донорская 23 — наш уровень 45 под чужим именем.

        Здесь застройка сходится и в обе стороны, и всё же это не общее
        место: у него «Пещера Вотана», у нас «Пещера волхва-отшельника».
        Переиспользованный уровень — не то же место: жители, разговоры и
        роль в сюжете там свои. Признак «имя» тут единственный работающий.
        """
        ours, theirs = self._named()
        self.assertNotIn(23, donor.TWIN_MAPS)
        self.assertNotEqual(ours(45), theirs(23))
        a, b = self._pair(23, 45)
        self.assertGreater(self._covered(a, b), 0.7)
        # А густотой это не объясняется: прочие его пещеры дают почти ноль.
        for other in (37, 46):
            data, _ = donor.map_data(other)
            with self.subTest(other=other):
                self.assertLess(
                    self._covered(a, self._objects(KN2Map(45, data))), 0.1)


@needs_game
@needs_donor
class TestForeignNumbering(unittest.TestCase):
    """Перевод номеров карт собирается из проекта, а не из правила в коде."""

    def setUp(self):
        from pathlib import Path
        from knyaz2.content.builder import _foreign_numbering
        self.table = _foreign_numbering(Path("project"), donor.LEGEND_NAME)

    def test_twins_keep_our_numbers(self):
        for native, mine in donor.TWIN_MAPS.items():
            with self.subTest(donor_map=native):
                self.assertEqual(self.table[native], mine)

    def test_imported_maps_use_their_declared_number(self):
        import json
        from pathlib import Path
        found = 0
        for path in sorted(Path("project/maps").glob("*/map.json")):
            document = json.loads(path.read_text(encoding="utf-8"))
            origin = document.get("origin") or {}
            if origin.get("game") != donor.LEGEND_NAME:
                continue
            found += 1
            with self.subTest(map=path.parent.name):
                self.assertEqual(self.table[int(origin["map"])],
                                 int(document["map_number"]))
        self.assertGreater(found, 10)

    def test_no_number_is_claimed_twice(self):
        # Иначе две карты приедут под одним номером и одна потеряется.
        values = list(self.table.values())
        self.assertEqual(len(values), len(set(values)))

    def test_imported_donor_maps_declare_no_handmade_exits(self):
        """Сочинённые кромки убраны: выходы у этих карт настоящие."""
        import json
        from pathlib import Path
        for path in sorted(Path("project/maps").glob("*/map.json")):
            document = json.loads(path.read_text(encoding="utf-8"))
            if (document.get("origin") or {}).get("game") != donor.LEGEND_NAME:
                continue
            with self.subTest(map=path.parent.name):
                self.assertNotIn("exits", document)


@needs_game
@needs_donor
class TestInteriorsSurviveTheImport(unittest.TestCase):
    """Обстановка построек больше не режется по нашему формату.

    «Зоны» — историческое имя: это то, что стоит ВНУТРИ дома. У нас таких
    записей 30, у донора 62, и его большие города лишние занимают. Обрезка
    делала эти дома пустыми внутри, а сундуки в них теряли гнездо.
    """

    #: Сколько записей занято сверх наших тридцати — замерено по файлам.
    BEYOND = {4: 26, 5: 15, 26: 2}

    def test_count_comes_from_the_file_length(self):
        from konung2.kn2 import KN2Map, zone_count
        self.assertEqual(zone_count(KN2Map.from_game(19).data), 30)
        for number in self.BEYOND:
            with self.subTest(map=number):
                data, _ = donor.map_data(number)
                self.assertEqual(zone_count(data), 62)

    def test_extra_interiors_arrive(self):
        from konung2.kn2 import KN2Map, interior_slots
        for number, records in self.BEYOND.items():
            data, extra = donor.map_data(number)
            slots = interior_slots(KN2Map(150 + number, data))
            deep = {key for key in slots if key[0] >= 30}
            with self.subTest(map=number):
                self.assertEqual(extra, records)
                self.assertEqual(len({obj for obj, _ in deep}), records)
                self.assertTrue(deep)

    def test_the_one_container_beyond_thirty_arrives(self):
        """Сундук привязан к постройке байтом +0x09 записи кучи.

        Разбор снят с загрузчика (VA 0x43DF48): при +0x09 не равном 0xFF он
        пишет «номер контейнера плюс один» по адресу
        ``0x6AE45C + гнездо*12 + запись*192``, то есть +0x09 это НОМЕР
        ЗАПИСИ обстановки, а +0x0A — гнездо в ней.

        ПУСТЫЕ ЗАПИСИ В СЧЁТ НЕ ИДУТ. У донора четырнадцать куч ссылаются на
        записи за тридцатой, и я сперва счёл их сундуками — но у всех у них
        гнездо 0xFF, спрайта нет, денег нет, вещей нет: это свободные места
        таблицы с мусором в байтах. ЖИВАЯ среди них ровно одна — на
        Кирингхольме, запись 39, гнездо 0, 25 монет и одна вещь. Вот её
        обрезка и теряла.
        """
        import struct
        from konung2.gamefile import (GROUND_MAP_AT, GROUND_MONEY_AT,
                                      GROUND_PLACE_AT, GROUND_SLOTS,
                                      GROUND_SLOTS_AT, GROUND_SPRITE_AT,
                                      _game_bytes)
        from konung2.kn2 import zone_count
        from konung2.profile import LEGEND
        data, layout = _game_bytes(0, LEGEND)
        at, count, size = layout["ground_items"]
        live, empty = [], 0
        for index in range(count):
            record = data[at + index * size:][:size]
            place = record[GROUND_PLACE_AT]
            if place == 0xFF or place < 30:
                continue
            things = [struct.unpack_from("<H", record, GROUND_SLOTS_AT + k * 2)[0]
                      for k in range(GROUND_SLOTS)]
            has = (struct.unpack_from("<h", record, GROUND_SPRITE_AT)[0]
                   or struct.unpack_from("<h", record, GROUND_MONEY_AT)[0]
                   or [x for x in things if x not in (0, 0xFFFF)])
            if has:
                live.append((record[GROUND_MAP_AT], place, record[0x0A]))
            else:
                empty += 1
        self.assertEqual(live, [(4, 39, 0)])
        self.assertGreater(empty, 10, "пустые записи должны быть отсеяны")
        body, _ = donor.map_data(4)
        self.assertLess(39, zone_count(body), "постройка 39 не доехала")

    def test_round_trip_keeps_the_long_tail(self):
        """Разбор и сборка карты не теряют лишние записи."""
        import tempfile
        from pathlib import Path
        from konung2.kn2 import KN2Map, interior_slots
        data, _ = donor.map_data(4)
        source = KN2Map(154, data)
        with tempfile.TemporaryDirectory() as folder:
            source.unpack(folder)
            back = KN2Map.pack(folder, 154)
        self.assertEqual(len(back.data), len(source.data))
        self.assertEqual(interior_slots(back), interior_slots(source))


@needs_game
class TestSettlementsIndex(unittest.TestCase):
    """Состояние ВСЕХ поселений, а не только тех, где игрок побывал.

    Движок держит блок записей целиком и читает его один раз, поэтому
    разговор вправе спросить про дальнюю деревню. У нас запись приезжала
    вместе со своей картой, и ответить было нечем.
    """

    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        from knyaz2.content.builder import _settlements_index
        cls.index = _settlements_index(Path("project"))

    def test_every_world_has_its_own_row(self):
        # Ключей столько же, сколько слотов на экране выбора: у героя должен
        # быть СВОЙ мир, а не общий нулевой.
        from knyaz2.content.builder import _hero_worlds
        self.assertEqual(sorted(self.index),
                         [str(n) for n in range(_hero_worlds())])

    def test_canon_settlements_are_all_there(self):
        from konung2.gamefile import villages
        from konung2.profile import CANON
        from knyaz2.content.builder import _hero_worlds, _world_of
        for slot in range(_hero_worlds()):
            with self.subTest(slot=slot):
                ours = {record["map"]
                        for record in villages(_world_of(CANON, slot))}
                listed = {entry["map"] for entry in self.index[str(slot)]
                          if "game" not in entry}
                self.assertEqual(listed, ours)

    def test_index_is_scalar_state_only(self):
        # Постройки и жители сюда не идут: девять с половиной килобайт на
        # запись, а спрашивают их только на своей карте.
        for entry in self.index["0"]:
            with self.subTest(map=entry["map"]):
                self.assertNotIn("buildings", entry)
                self.assertNotIn("people", entry)
                self.assertIn("flags", entry)

    @needs_donor
    def test_donor_settlements_come_under_our_numbers(self):
        """Поселение перенесённой карты названо НАШИМ номером.

        Иначе обработчик будет искать поселение по донорскому номеру и
        найдёт чужое: его 16 «Дубки» — это наша 166.
        """
        from pathlib import Path
        theirs = {entry["map"]: entry for entry in self.index["0"]
                  if entry.get("game") == donor.LEGEND_NAME}
        self.assertTrue(theirs)
        for number in theirs:
            with self.subTest(map=number):
                self.assertGreater(number, 150)
                folder = next(Path("project/maps").glob(f"{number}_*"), None)
                self.assertIsNotNone(folder)

    @needs_donor
    def test_maps_handler_35_asks_about_are_listed(self):
        """Те самые дальние деревни, про которые спрашивает его 35.

        Он спрашивает про донорские карты 6, 8 и 15 — у нас это 156, 158 и
        165, и без указателя ответить было бы нечем.
        """
        listed = {entry["map"] for entry in self.index["0"]}
        for number in (156, 158, 165):
            with self.subTest(map=number):
                self.assertIn(number, listed)


@needs_game
@needs_donor
class TestVoiceNumbering(unittest.TestCase):
    """У донора свой voices.res и своя нумерация реплик.

    Под общим номером у него лежит ДРУГАЯ реплика, и все наши номера
    попадают в его диапазон. Без разведения его персонаж заговорил бы нашим
    голосом и чужими словами — а половина реплик просто молчала бы.
    """

    @classmethod
    def setUpClass(cls):
        from konung2.quests import Dialogs
        from konung2.profile import LEGEND
        cls.ours = Dialogs.from_game()
        cls.theirs = Dialogs.from_game(LEGEND)

    def _voices(self, dialogs):
        out = set()
        for index in range(dialogs.node_count):
            node = dialogs.node(index)
            if node["phrase"] == -1:
                continue
            try:
                voice = dialogs.phrase(node["phrase"])["voice"]
            except (IndexError, ValueError):
                continue
            if voice > 0:
                out.add(voice)
        return out

    def test_numbers_no_longer_collide(self):
        mine, theirs = self._voices(self.ours), self._voices(self.theirs)
        self.assertEqual(mine & theirs, set())
        self.assertLess(max(mine), donor.PROJECT_VOICE_BASE)
        self.assertGreater(min(theirs), donor.PROJECT_VOICE_BASE)

    def test_without_the_shift_they_would_collide_completely(self):
        """Замер того, что чинится: пересекались ВСЕ наши номера."""
        from konung2.voices import VoicesRes
        from konung2.profile import LEGEND
        mine = self._voices(self.ours)
        raw = {voice - donor.PROJECT_VOICE_BASE
               for voice in self._voices(self.theirs)}
        self.assertEqual(len(mine & raw), len(mine))
        # И у донора реплик вдвое больше — остальные молчали бы.
        self.assertGreater(len(raw - mine), 1000)
        self.assertEqual(len(VoicesRes.from_game(LEGEND).used()), 2318)

    def test_every_referenced_line_has_a_record(self):
        """Ссылка без записи — это молчащий персонаж."""
        from konung2.voices import VoicesRes
        from konung2.profile import CANON, LEGEND
        have = set(VoicesRes.from_game(CANON).used())
        have |= {index + donor.PROJECT_VOICE_BASE
                 for index in VoicesRes.from_game(LEGEND).used()}
        for dialogs in (self.ours, self.theirs):
            with self.subTest(game=dialogs.profile.name):
                self.assertEqual(self._voices(dialogs) - have, set())

    def test_the_two_files_are_different(self):
        """Не один и тот же файл под двумя именами."""
        from konung2.voices import VoicesRes
        from konung2.profile import CANON, LEGEND
        mine = VoicesRes.from_game(CANON)
        theirs = VoicesRes.from_game(LEGEND)
        self.assertNotEqual(len(mine.data), len(theirs.data))
        self.assertNotEqual(mine.pcm(1), theirs.pcm(1))


@needs_game
@needs_donor
class TestQuestNumbering(unittest.TestCase):
    """Квесты обеих игр в одной таблице на 300 мест — номера разведены.

    Обе игры считают с нуля: канон занимает 0…102, донор 0…161. Без сдвига
    «отметить квест N» из донорского разговора взводило бы наш квест N, а
    его Мунд-однофамилец под номером 8 получал бы канонный авто-подход.
    """

    @classmethod
    def setUpClass(cls):
        from konung2.quests import Dialogs
        from konung2.profile import LEGEND
        cls.ours = Dialogs.from_game()
        cls.theirs = Dialogs.from_game(LEGEND)

    def test_tree_number_and_quests_are_shifted_together(self):
        # Номер дерева и номера квестов — ОДНО пространство (таблица
        # состояний индексируется номером диалога), сдвигаются вместе.
        self.assertEqual(self.theirs.tree(9)["number"],
                         donor.PROJECT_QUEST_BASE + 9)
        self.assertEqual(self.ours.tree(9)["number"], 9)

    def test_quest_commands_carry_shifted_numbers(self):
        import struct
        from konung2.quests import CMD_KIND_MASK, CMD_QUEST
        found = []
        for name in ("phrase_a", "phrase_b"):
            at, size = self.theirs.profile.quests_layout()[name]
            for offset in range(at, at + size, 4):
                word = struct.unpack_from("<I", self.theirs.data, offset)[0]
                if word & CMD_KIND_MASK == CMD_QUEST:
                    found.append(word & 0xFFFF)
        self.assertTrue(found, "у донора нет квестовых команд — замер сбился")
        highest = max(found)
        # ТАБЛИЦА РАСТЁТ, А НЕ ДОНОР РЕЖЕТСЯ. У движка мест 300, и обе
        # игры в них не влезают: 152 + 161 = 313. База считается по
        # номерам РАЗГОВОРОВ (у канона их 151), иначе донорская заявка
        # ложится на канонного жителя — так Фёдора с Торгового поста
        # сама заговаривала с игроком.
        self.assertLessEqual(donor.PROJECT_QUEST_BASE + highest,
                             donor.QUEST_SLOTS,
                             "сдвиг не влезает в отведённую таблицу")
        # И разбор действительно сдвигает: возьмём любой узел с квестом.
        for number in range(1, 60):
            tree = self.theirs.tree(number)
            for node in tree["nodes"]:
                pools = [node.get("actions") or []]
                pools += [option.get("actions") or []
                          for option in node.get("options") or []]
                for pool in pools:
                    for command in pool:
                        if command.get("kind") != "quest":
                            continue
                        self.assertGreaterEqual(
                            command["quest"], donor.PROJECT_QUEST_BASE)
                        self.assertEqual(command["quest"],
                                         command["native_quest"]
                                         + donor.PROJECT_QUEST_BASE)
                        return
        self.fail("ни одной квестовой команды в деревьях")

    def test_initial_states_merge_without_collisions(self):
        from knyaz2.content.builder import _quest_state
        state = _quest_state()
        self.assertEqual(len(state["flags"]), donor.QUEST_SLOTS)
        # Канонные разговоры доходят до 151 — участок донора начинается
        # ЗА ними, иначе его квест индексируется канонным разговором.
        self.assertGreater(donor.PROJECT_QUEST_BASE, 151)
        lit = [index for index, flag in enumerate(state["flags"]) if flag]
        # Шесть канонных «подойди и заговори» — как были.
        self.assertEqual([n for n in lit if n < donor.PROJECT_QUEST_BASE],
                         [8, 16, 26, 36, 50, 60])
        # И донорские появились в своём участке.
        self.assertTrue([n for n in lit if n >= donor.PROJECT_QUEST_BASE])

    def test_journal_texts_come_from_their_own_game(self):
        from knyaz2.content.builder import _quest_state
        state = _quest_state()
        theirs = {int(key): value for key, value in state["text"].items()
                  if int(key) >= donor.PROJECT_QUEST_BASE}
        self.assertGreater(len(theirs), 60)
        joined = " ".join(theirs.values())
        self.assertIn("Желтых собак", joined, "тексты не донорские")
        for value in state["text"].values():
            self.assertFalse(value.startswith(("MAP=", "OBJECT=",
                                               "LANDSCAPE=")),
                             "скрипт-команда пролезла в журнал")

    def test_map_arguments_are_translated_in_trees(self):
        from pathlib import Path
        from knyaz2.content.builder import (_foreign_numbering,
                                            _translate_tree_arguments)
        numbering = _foreign_numbering(Path("project"), donor.LEGEND_NAME)
        translated, lost = 0, []
        for number in range(1, 150):
            try:
                tree = _translate_tree_arguments(self.theirs.tree(number),
                                                 numbering)
            except (IndexError, ValueError):
                continue
            for node in tree["nodes"]:
                pools = [node.get("actions") or []]
                pools += [option.get("actions") or []
                          for option in node.get("options") or []]
                pools += [option.get("condition") or []
                          for option in node.get("options") or []]
                pools += [branch.get("condition") or []
                          for branch in node.get("branches") or []]
                for pool in pools:
                    for command in pool:
                        if "native_argument" in command:
                            translated += 1
                        if command.get("foreign_map"):
                            lost.append(command)
        self.assertGreater(translated, 1000)
        self.assertEqual(lost, [], "довод-карта остался непереводимым")


@needs_game
class TestQuestScripts(unittest.TestCase):
    """Скрипты квестов: «взвести квест» = бит 0x80 + исполнить строку фразы.

    Механика ОБЩАЯ (его 0x4399C8 зовёт 0x439864; канонный квест 96 тем же
    путём открывает клетку карты 14), и порт не исполнял её никогда.
    """

    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        from knyaz2.content.builder import _quest_state
        cls.state = _quest_state(Path("project"))

    def test_scripts_are_exported_parsed(self):
        scripts = self.state["scripts"]
        self.assertGreater(len(scripts), 0)
        kinds = {entry["kind"] for entry in scripts.values()}
        self.assertIn("map", kinds)
        for entry in scripts.values():
            with self.subTest(entry=entry):
                self.assertEqual(len(entry["args"]), 4)

    def test_canon_quest_96_opens_a_cell_of_map_14(self):
        entry = self.state["scripts"].get("96")
        self.assertIsNotNone(entry, "канонный скрипт пропал из выпечки")
        self.assertEqual(entry["kind"], "map")
        self.assertEqual(entry["args"], [14, 34, 54, 0x4FFF])

    @needs_donor
    def test_every_map_argument_is_translated(self):
        # Первый довод ЛЮБОЙ из трёх команд — номер карты; его 0x439864
        # сверяет его с текущей у всех, не только у MAP=.
        for number, entry in self.state["scripts"].items():
            with self.subTest(quest=number):
                self.assertNotIn("foreign_map", entry)
                if int(number) >= donor.PROJECT_QUEST_BASE:
                    self.assertIn("native_map", entry)

    @needs_donor
    def test_the_crossing_quests_move_its_bridge(self):
        """Квесты Переправы бьют в неё же: двигают оверлей, прячут объекты.

        Это и есть механика моста, о которой говорил пользователь: локация
        стоит на воде, и сюжет переставляет её объекты.
        """
        ours = {number: entry for number, entry in self.state["scripts"].items()
                if entry.get("native_map") == 36}
        self.assertGreaterEqual(len(ours), 4)
        for entry in ours.values():
            self.assertEqual(entry["args"][0], 186)
        kinds = sorted(entry["kind"] for entry in ours.values())
        self.assertIn("landscape", kinds)
        self.assertIn("object", kinds)

    def test_client_runs_scripts_on_quest_set(self):
        """Проводка клиента: исполнение на взводе и канонный повтор на входе.

        Повтор — по СОСТОЯНИЯМ КВЕСТОВ, как в загрузчике движка (донорский
        0x4417E0 прокручивает все триста записей): квест, взведённый не на
        своей карте, применяется при первом же входе на неё. Отдельная
        память правок (mapstate) удваивала бы применение и теряла чужие
        взводы — её больше нет.
        """
        from pathlib import Path
        static = Path("knyaz2/web/static")
        dialog = (static / "dialog.js").read_text(encoding="utf-8")
        self.assertIn("if (command.set) questScriptRun(command.quest)", dialog)
        self.assertIn("dialog.quests.get(Number(key)) !== true", dialog)
        self.assertNotIn("mapStateQuestEdit", dialog)
        app = (static / "app.js").read_text(encoding="utf-8")
        self.assertEqual(app.count("questEditsReplay(map?.legacy?.map_number)"),
                         2, "повтор правок должен стоять на ОБОИХ входах")
        hero = (static / "hero.js").read_text(encoding="utf-8")
        self.assertIn("export function heroCellToggle", hero)

    def test_client_talks_to_piles(self):
        """Проводка разговорных куч: чан открывает диалог, а не обмен.

        Донорский разборщик прибытия (0x411BC6) смотрит байт диалога
        записи РАНЬШЕ ветки обыска; собеседника у такого разговора нет.
        """
        from pathlib import Path
        static = Path("knyaz2/web/static")
        loot = (static / "loot.js").read_text(encoding="utf-8")
        self.assertIn("entry.dialog_tree", loot)
        self.assertIn("export function lootSpeaker", loot)
        # щелчок обязан видеть кучу без вещей, если у неё есть разговор
        self.assertIn("!pile.items.length && !pile.dialog", loot)
        # дерево — данные пака: после восстановления подшивается заново
        self.assertIn("export function lootReattachTalk", loot)
        save = (static / "save.js").read_text(encoding="utf-8")
        self.assertIn("lootReattachTalk(world.map)", save)
        combat = (static / "combat.js").read_text(encoding="utf-8")
        self.assertIn("talkPileAtCell", combat)
        self.assertIn("dialogStart(lootSpeaker(spoken))", combat)
        # ветка разговора стоит ДО поиска обычной кучи
        self.assertLess(combat.index("talkPileAtCell(at.row, at.col)"),
                        combat.index("pileAtCell(at.row, at.col)"))
        agent = (static / "agent.js").read_text(encoding="utf-8")
        self.assertIn("pile.items?.length || pile.dialog", agent)

    def test_hero_game_never_sticks_to_previous_choice(self):
        """Игра героя не залипает от предыдущего выбора на экране создания.

        У канонных шаблонов поля `game` нет, и «?? hero.game» оставлял
        «legend» после просмотра донорского героя: за Ратибора панель
        показывала Иззарка (`legend:0`), Путяту — legend_ui_271 (у донора
        под этим номером предметная иконка, его база портретов 274), Тура
        — legend_ui_275, то есть донорскую Велиславну. Жалоба 23.08.
        """
        from pathlib import Path
        progress = (Path("knyaz2/web/static") / "progress.js").read_text(
            encoding="utf-8")
        self.assertIn(
            "hero.game = template ? template.game ?? null : hero.game ?? null",
            progress)
        self.assertNotIn("hero.game = template?.game ?? hero.game", progress)
        # ...и сейв её ни пишет, ни читает: игра — производное от шаблона
        # мира и пака карты, а чтение отсюда воскрешало залипший «legend»
        # из сохранений, записанных до правки («потом обратно палатка»).
        save = (Path("knyaz2/web/static") / "save.js").read_text(
            encoding="utf-8")
        self.assertNotIn("game: actor.game", save)
        self.assertNotIn("saved.game", save)
        # записи отряда при этом игру НЕСУТ — по ним поднимается нанятый
        # донорский спутник на чужой карте
        units_js = (Path("knyaz2/web/static") / "units.js").read_text(
            encoding="utf-8")
        self.assertIn("game: unit.game ?? null", units_js)
        # опора правила — данные пака: у канонных шаблонов игры нет,
        # у донорских она названа
        import json
        shared = json.loads(Path("content_build/shared.json").read_text(
            encoding="utf-8"))
        for start in shared["hero"]["starts"]:
            template = start.get("template") or {}
            if start.get("game") == "legend":
                self.assertEqual(template.get("game"), "legend", start["name"])
            else:
                self.assertNotIn("game", template, start["name"])


@needs_game
@needs_donor
class TestTransitionGraphs(unittest.TestCase):
    """У каждой игры свой граф переходов: номер записи значит разное.

    Действие разговора «перенести отряд игрока по переходу» адресует запись
    НОМЕРОМ. Наша таблица на 250 записей, донорская на 350 — один общий граф
    уносил бы героя из донорского разговора в случайное место, и молча.
    """

    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        from knyaz2.content.builder import _transitions, _transitions_by_game
        cls.canon = _transitions()
        cls.by_game = _transitions_by_game(Path("project"))

    def test_each_game_keeps_its_own_length(self):
        from konung2.profile import CANON
        self.assertEqual(len(self.by_game[CANON.name]), 250)
        self.assertEqual(len(self.by_game[donor.LEGEND_NAME]), 350)

    def test_canon_graph_is_untouched(self):
        from konung2.profile import CANON
        self.assertEqual(self.by_game[CANON.name], self.canon)

    def test_donor_targets_are_translated(self):
        """Цель донорской записи названа НАШИМ номером карты."""
        from knyaz2.content.builder import _foreign_numbering
        from pathlib import Path
        numbering = _foreign_numbering(Path("project"), donor.LEGEND_NAME)
        translated = [door for door in self.by_game[donor.LEGEND_NAME]
                      if door.get("from_foreign_map")]
        self.assertTrue(translated)
        for door in translated:
            with self.subTest(index=door["index"]):
                native = abs(int(door["from_foreign_map"]))
                self.assertEqual(abs(int(door["to_map"])), numbering[native])

    def test_the_same_index_leads_elsewhere(self):
        """Ради чего это: под одним номером у игр разные переходы."""
        from konung2.profile import CANON
        mine = self.by_game[CANON.name]
        theirs = self.by_game[donor.LEGEND_NAME]
        differ = sum(1 for index in range(len(mine))
                     if (mine[index]["from_map"], mine[index]["to_map"])
                     != (theirs[index]["from_map"], theirs[index]["to_map"]))
        self.assertGreater(differ, 200, "графы обязаны расходиться")


@needs_game
@needs_donor
class TestProjectHandlerNumbers(unittest.TestCase):
    """Свои обработчики донора живут в проектном участке номеров."""

    def test_project_numbers_do_not_touch_canon(self):
        from konung2.quests import HANDLERS
        self.assertGreater(donor.PROJECT_HANDLER_BASE, HANDLERS)

    def test_every_donor_handler_gets_a_number(self):
        numbers = donor.handler_numbers()
        self.assertEqual(sorted(numbers), list(range(93)))
        self.assertEqual(len(set(numbers.values())), len(numbers))

    def test_reputation_starts_match_his_worlds(self):
        # Четыре значения на четыре его файла мира — сходится.
        from pathlib import Path
        worlds = len(list(Path(donor.DONOR_DIR).glob("[Gg][Aa][Mm][Ee].[0-9]")))
        self.assertEqual(len(donor.REPUTATION_STARTS), worlds)
        self.assertIn(donor.REPUTATION_CANON_START, donor.REPUTATION_STARTS)

    def test_reputation_starts_are_read_from_the_exe(self):
        """Значения не выдуманы: лежат таблицей по замеренному адресу."""
        import struct
        blob = donor.DonorExe.load()
        at = blob.va_to_foff(donor.REPUTATION_STARTS_VA)
        found = struct.unpack_from(f"<{len(donor.REPUTATION_STARTS)}i",
                                   blob.blob, at)
        self.assertEqual(found, donor.REPUTATION_STARTS)


@needs_game
@needs_donor
class TestGraphicsAreNotShared(unittest.TestCase):
    """Гнёзда, палитры и плитки одного номера у двух игр — РАЗНЫЕ картинки.

    Прежний ввоз считал каталоги «слот в слот»: сверка мерила заголовки
    записей (вид, число кадров, группа) и совпадений хватало. Побайтная
    сверка это опровергает, и цена ошибки видна в игре: кусок канонного
    Дворца Повелителя в порту Тиграта (гнездо 314), чёрные навесы и пятна
    земли, дома без крыш, цветная рябь на частоколе и печи.

    Поэтому карта рисуется графикой СВОЕЙ игры, а картинки донора уезжают
    в пак с приставкой — перенумеровать нельзя: номер плитки лежит в карте
    байтом, палитра — смещением в блоке из 256 записей.
    """

    def test_most_nests_differ(self):
        shared = donor.shared_nests()
        total = donor.CANON_LAST_SLOT - 29
        self.assertLess(len(shared), total // 2,
                        "каталоги объектов вдруг стали общими — проверить замер")
        # гнездо 314: у нас Дворец Повелителя, у него портовые своды
        self.assertNotIn(314, shared)

    def test_palettes_and_tiles_differ_too(self):
        self.assertLess(len(donor.shared_palettes()), donor.PALETTE_SLOTS)
        self.assertLess(len(donor.shared_tiles()), donor.CANON_LAST_TILE)

    def test_legend_heroes_res_needs_both_corrections(self):
        """Его HEROES.RES читается только с ДВУМЯ поправками.

        Формат общий, и таблицы анимации побайтно одинаковы — оттого и
        соблазн читать его файл как свой. Но по канонному адресу таблицы
        смещений (0x33E0) у него нули до 146-го индекса, а слои сдвинуты
        на два: без поправок запись отдаёт либо пусто, либо обрывок 15x13
        вместо тела 44x79. С поправками габариты сходятся кадр в кадр.
        """
        from konung2.heroes import HeroesRes, LegendHeroesRes
        from konung2.res import read_palettes
        ours = HeroesRes.from_game()
        fixed = LegendHeroesRes.from_game()
        raw = HeroesRes(fixed.data)          # его файл нашими правилами
        palette = read_palettes()[28]

        matched = compared = naive = 0
        for record in (8, 9, 40, 120, 300, 700):
            for layer in range(54):
                a = ours.decode_layer(record, layer=layer, palette=palette)
                b = fixed.decode_layer(record, layer=layer, palette=palette)
                if a[0] is None and b[0] is None:
                    continue
                compared += 1
                if a[0] and b[0] and (a[0].width, a[0].height) == \
                        (b[0].width, b[0].height):
                    matched += 1
                c = raw.decode_layer(record, layer=layer, palette=palette)
                if a[0] and c[0] and (a[0].width, a[0].height) == \
                        (c[0].width, c[0].height):
                    naive += 1
        self.assertGreater(compared, 200, "нечего сравнивать — замер сбился")
        self.assertEqual(matched, compared, "поправки перестали сходиться")
        self.assertLess(naive, compared // 10,
                        "его файл вдруг читается нашими правилами — "
                        "проверить заново, поправки могли стать лишними")

    def test_legend_has_its_own_sixth_body(self):
        """Тело 6 (Иззарк) есть только у него, и оно читается."""
        from knyaz2.content.builder import BODY_LAYER_BASE
        from konung2.heroes import HeroesRes, LegendHeroesRes
        from konung2.res import read_palettes
        palette = read_palettes(donor.graph_palette_block())[247]
        theirs = LegendHeroesRes.from_game()
        ours = HeroesRes.from_game()
        frames = 0
        for record in (8, 9, 10, 11, 12, 13):
            sprite, _, _ = theirs.decode_layer(
                record, layer=BODY_LAYER_BASE + 6, palette=palette)
            if sprite is not None and sprite.width > 20 and sprite.height > 40:
                frames += 1
        self.assertEqual(frames, 6, "шаг Иззарка на запад не читается")
        self.assertIsNone(ours.decode_layer(8, layer=BODY_LAYER_BASE + 6,
                                            palette=palette)[0],
                          "у канона вдруг появилось шестое тело")

    def test_exporter_switches_source_and_prefix(self):
        import tempfile
        from pathlib import Path as _Path
        from knyaz2.content.builder import _AssetExporter
        assets = _AssetExporter(_Path(tempfile.mkdtemp()))
        assets.select(None)
        self.assertFalse(assets.legend)
        self.assertEqual(assets.prefix, "")
        canon_objects = assets.objects
        assets.select(donor.LEGEND_NAME)
        self.assertTrue(assets.legend)
        self.assertEqual(assets.prefix, assets.LEGEND_PREFIX)
        self.assertIsNot(assets.objects, canon_objects)
        # У гнезда 314 (у нас Дворец Повелителя, у него портовые своды)
        # ПИКСЕЛИ разные — значит источник действительно сменился, а не
        # подписался другим именем. Габариты при этом совпадают, и на
        # них проверку строить нельзя.
        theirs = assets.object(314, 91, 0)
        assets.select(None)
        ours = assets.object(314, 91, 0)
        self.assertIsNotNone(theirs)
        self.assertIsNotNone(ours)
        self.assertTrue(theirs["path"].split("/")[-1].startswith(
            assets.LEGEND_PREFIX))
        self.assertFalse(ours["path"].split("/")[-1].startswith(
            assets.LEGEND_PREFIX))
        self.assertNotEqual((assets.root / theirs["path"]).read_bytes(),
                            (assets.root / ours["path"]).read_bytes())


@needs_game
@needs_donor
class TestNineHeroes(unittest.TestCase):
    """Девять героев экрана «Новая игра»: правило слотов и его данные.

    У донора четыре мира — четыре героя. Наш слот 1 (Велиславна) живёт
    его миром 1: та же героиня (тело 1, палитра 70) на той же карте 19,
    «Продолжение легенды» рассказывает её историю дальше. Его трое встают
    слотами 6…8.
    """

    def test_slots_follow_the_rule(self):
        self.assertEqual(len(donor.HERO_SLOTS), 9)
        # канон владеет началом: слоты 0 и 2…5 — наши миры под своим номером
        for slot in (0, 2, 3, 4, 5):
            self.assertEqual(donor.HERO_SLOTS[slot], ("canon", slot))
        # проект продолжением: его миры входят по одному разу
        legend = [world for game, world in donor.HERO_SLOTS if game == "legend"]
        self.assertEqual(sorted(legend), [0, 1, 2, 3])
        self.assertEqual(donor.HERO_SLOTS[1], ("legend", 1))

    def setUp(self):
        # ПРАВИЛО СЛОТОВ ПРОВЕРЯЕМ ПРИ СНЯТОМ РЕЖИМЕ НЕЙТРАЛЬНОГО МИРА.
        # Пока сюжетов нет, `_world_of` отдаёт всем один мир, и без этой
        # подмены три теста ниже мерили бы заглушку, а не правило, которое
        # включится вместе с сюжетными линиями.
        from knyaz2.content import builder
        self._story_free = builder.STORY_FREE_WORLD
        builder.STORY_FREE_WORLD = False
        self.addCleanup(setattr, builder, "STORY_FREE_WORLD", self._story_free)

    def test_every_slot_reads_its_own_world_at_home(self):
        """На картах СВОЕЙ игры слот читает родной мир героя.

        Прежнее правило (канону — слот как есть, донору — всегда ноль)
        отдавало Драгомиру на его же Военном лагере мир Иззарка: там все
        тринадцать жителей немые (разговор 127), а сам Драгомир стоит
        чужим NPC.
        """
        from konung2.profile import CANON, LEGEND
        from knyaz2.content.builder import _hero_worlds, _world_of
        self.assertEqual(_hero_worlds(), len(donor.HERO_SLOTS))
        for slot, (owner, native) in enumerate(donor.HERO_SLOTS):
            home = LEGEND if owner == "legend" else CANON
            away = CANON if owner == "legend" else LEGEND
            with self.subTest(slot=slot):
                self.assertEqual(_world_of(home, slot), native)
                # на чужих картах — общий мир, и он существует в той игре
                other = _world_of(away, slot)
                limit = 4 if away is LEGEND else 6
                self.assertLess(other, limit)

    @needs_donor
    def test_his_portraits_start_at_their_own_number(self):
        """Полоса портретов у донора своя, и найдена она размером.

        По канонной формуле «лицо + 261» за Иззарка панель брала спрайт 261
        его INTERF.RES, а там иконка ключа 68x68.
        """
        from pathlib import Path
        from konung2.interf import InterfRes, PORTRAIT_BASE
        from konung2.paths import game_file
        ours = InterfRes(Path(game_file("INTERF.RES")).read_bytes())
        his = InterfRes(Path(donor.donor_file("interf.res")).read_bytes())
        size = ours.frame_size(PORTRAIT_BASE)
        self.assertEqual(size, (62, 62))

        def runs(res):
            found, start = [], None
            for index in range(len(res.entries)):
                if res.frame_size(index) == size:
                    if start is None:
                        start = index
                elif start is not None:
                    found.append((start, index - start))
                    start = None
            return [row for row in found if row[1] >= 4]

        self.assertEqual(runs(ours), [(PORTRAIT_BASE, 43)])
        self.assertEqual(runs(his), [(donor.PORTRAIT_BASE, 49)])
        # у донора 261 — не портрет вовсе, и это видно по размеру
        self.assertNotEqual(his.frame_size(PORTRAIT_BASE), size)

    def test_the_common_world_is_never_an_empty_map(self):
        """Общий мир на чужих картах не должен оказаться безлюдным.

        У донора мир Велиславны не держит на его карте 14 (наш 164, Военный
        лагерь) НИ ОДНОГО юнита — единственный такой случай на 49 его карт
        с жителями и на 40 наших. Возьми мы общий мир не глядя, все шесть
        наших героев пришли бы в пустой лагерь.
        """
        from konung2.gamefile import map_units
        from konung2.profile import LEGEND
        from knyaz2.content.builder import NEUTRAL_WORLD, _world_of
        self.assertEqual(map_units(14, NEUTRAL_WORLD, profile=LEGEND), [])
        for slot in (0, 2, 3, 4, 5):
            with self.subTest(slot=slot):
                world = _world_of(LEGEND, slot, 14)
                self.assertNotEqual(world, NEUTRAL_WORLD)
                self.assertTrue(map_units(14, world, profile=LEGEND))
        # там, где мир населён, подмены не происходит
        self.assertEqual(_world_of(LEGEND, 0, 4), NEUTRAL_WORLD)

    def test_dragomir_at_home_meets_talkers_not_himself(self):
        """Замер, ради которого правило и менялось: его карта 14."""
        from konung2.gamefile import map_units
        from konung2.profile import LEGEND
        from knyaz2.content.builder import _in_player_party, _world_of
        his = {}
        for slot in (6, 7):
            world = _world_of(LEGEND, slot)
            # отряд игрока — не житель, в паке он тоже отфильтрован
            his[slot] = [unit for unit in map_units(14, world, profile=LEGEND)
                         if not _in_player_party(unit.get("index"), world,
                                                 LEGEND)]
        # У Иззарка (слот 6) лагерь немой: разговор есть ровно у одного, и
        # это сам Драгомир — он там сюжетное лицо, а не хозяин.
        speaks = [unit["name"] for unit in his[6]
                  if int(unit.get("dialog", 0xFF)) < 127]
        self.assertEqual(speaks, ["Драгомир"])
        # у самого Драгомира (слот 7) лагерь говорит, и себя он не встречает
        talkers = [unit for unit in his[7]
                   if int(unit.get("dialog", 0xFF)) < 127]
        self.assertGreaterEqual(len(talkers), 12)
        self.assertNotIn("Драгомир", {unit["name"] for unit in his[7]})

    def test_the_neutral_world_holds_no_playable_hero(self):
        """Дома — свой мир, в гостях — общий и без чужих завязок.

        ПРАВИЛО ИЗМЕНИЛОСЬ 19.08.2026. Прежде все девять слотов читали ОДИН
        мир, и разница между героями была только в точке старта. Но общий мир
        берётся нулевым, а нулевой у донора — Иззарков: Драгомир на СВОЁМ
        Военном лагере оказывался среди чужой расстановки. В его мире лагерь
        это два отряда (116 на двенадцать человек и 117 на одного), а сам он
        стоит отрядом игрока прямо на карте; в нулевом лагерь слит в один
        отряд из тринадцати, и места герою нет. Оттого ссора с одним
        поднимала весь лагерь, и «свои» его не признавали.

        Теперь на картах СВОЕЙ игры слот читает свой мир, а общий остаётся
        для чужих карт — там же и вычистка сюжетных лиц.
        """
        from konung2 import donor
        from konung2.gamefile import map_units
        from konung2.profile import CANON, LEGEND
        from knyaz2.content import builder
        builder.STORY_FREE_WORLD = True  # setUp снял, здесь он и проверяется

        # В ГОСТЯХ — ОДИН МИР НА ВСЕХ.
        canon_slots = [slot for slot in range(9)
                       if donor.HERO_SLOTS[slot][0] == "canon"]
        legend_slots = [slot for slot in range(9)
                        if donor.HERO_SLOTS[slot][0] == "legend"]
        self.assertEqual({builder._world_of(LEGEND, slot, 14)
                          for slot in canon_slots}, {builder.BASE_WORLD})
        self.assertEqual({builder._world_of(CANON, slot, 33)
                          for slot in legend_slots}, {builder.BASE_WORLD})

        # ДОМА — СВОЙ, И ЭТО РОВНО ТО, ЧТО ЗАПИСАНО В ТАБЛИЦЕ СЛОТОВ.
        for slot in legend_slots:
            with self.subTest(слот=slot, дома="донор"):
                self.assertEqual(builder._world_of(LEGEND, slot, 14),
                                 donor.HERO_SLOTS[slot][1])
        for slot in canon_slots:
            with self.subTest(слот=slot, дома="канон"):
                self.assertEqual(builder._world_of(CANON, slot, 33),
                                 donor.HERO_SLOTS[slot][1])

        # У ДРАГОМИРА ДОМА ЕСТЬ СВОЁ МЕСТО В РАССТАНОВКЕ, а лагерь — два
        # мирных отряда, и нападает только третий. Это и есть канон.
        from konung2.gamefile import map_parties
        bands = map_parties(14, builder._world_of(LEGEND, 7, 14), profile=LEGEND)
        by_side = {band["side"]: band for band in bands}
        self.assertIn(0, by_side, "герой обязан стоять отрядом игрока")
        self.assertEqual(sorted(by_side), [0, 116, 117, 118])
        self.assertFalse(by_side[116]["on_player"], "лагерь мирный")
        self.assertFalse(by_side[117]["on_player"])
        self.assertTrue(by_side[118]["on_player"], "нападает третий отряд")

        names = builder._hero_unit_names()
        self.assertEqual(len(names), 9, sorted(names))
        for name in ("Ратибор", "Велиславна", "Драгомир", "Хельга"):
            self.assertIn(name, names)

        # ДВА ПРАВИЛА, И ОБА НУЖНЫ.
        # Первое, ядро, снимает того, кого нет хотя бы в одном мире: в своём
        # мире герой — игрок, а не житель, поэтому Велиславна и Хельга
        # выпадают сами.
        for game, native, name in ((CANON, 19, "Велиславна"),
                                   (CANON, 37, "Хельга"),
                                   (LEGEND, 14, "Драгомир")):
            with self.subTest(правило="ядро", name=name):
                core = builder._neutral_core(game, native) or ()
                self.assertTrue(all(key[0] != name for key in core))

        # Второе, список имён. Ратибор, Александр и Анастасия стоят у донора
        # во ВСЕХ четырёх его мирах — ядром их не поймать.
        for native, name in ((10, "Ратибор"), (6, "Александр"),
                             (30, "Анастасия")):
            with self.subTest(правило="имена", name=name):
                core = builder._neutral_core(LEGEND, native)
                self.assertTrue(any(key[0] == name for key in core),
                                "иначе пример устарел и правило имён не нужно")
                self.assertIn(name, names)
        self.assertTrue(map_units(14, 0, profile=LEGEND))

    def test_both_velislavnas_share_body_and_start(self):
        import struct
        from konung2.gamefile import hero_stats, _game_bytes
        from konung2.profile import LEGEND
        ours = hero_stats(1)
        hers = hero_stats(1, profile=LEGEND)
        self.assertEqual((ours["body"], ours["palette"]),
                         (hers["body"], hers["palette"]))
        data, layout = _game_bytes(1, LEGEND)
        at, _, size = layout["parties"]
        map_number = struct.unpack_from("<H", data, at + 0x08)[0]
        self.assertEqual(map_number, 19, "её старт — Чёрный Бор обеих игр")

    def test_stories_match_their_heroes(self):
        # Таблица указателей в его exe: индекс — мир. Биографии открывают
        # имена, и они обязаны совпадать с миром (сверено с портретами).
        for world, name in ((0, "Иззарк"), (1, "Велиславна"),
                            (2, "Драгомир"), (3, "Гильдис")):
            with self.subTest(world=world):
                self.assertIn(name, donor.hero_story(world)[:80])

    def test_item_class_map_is_injective_and_fits_a_byte(self):
        mapping = donor.item_class_map()
        self.assertEqual(len(set(mapping.values())), len(mapping),
                         "два его класса легли в один наш")
        self.assertLessEqual(max(mapping.values()), 0xFF,
                             "хвост не влезает в байт класса записи")
        # пары одноимённых спарены по цене, а не по случайному порядку
        from konung2.items import read_items
        from konung2.profile import LEGEND
        ours = {item.index: item for item in read_items()}
        for record in read_items(profile=LEGEND):
            mine = mapping[record.index]
            if mine >= donor.PROJECT_ITEM_BASE:
                continue
            with self.subTest(his=record.index):
                self.assertEqual(record.name.lower(), ours[mine].name.lower())

    def test_unique_donor_items_go_to_the_tail(self):
        mapping = donor.item_class_map()
        from konung2.items import read_items
        from konung2.profile import LEGEND
        his = {item.index: item.name for item in read_items(profile=LEGEND)}
        tail = {his[h] for h, m in mapping.items()
                if m >= donor.PROJECT_ITEM_BASE}
        # сюжетные вещи «Продолжения легенды» живут своими классами
        for name in ("Браслет Владыка", "Амулет Дракона", "Доспех Дракона"):
            self.assertIn(name, tail)

    def test_builder_offers_nine_heroes(self):
        from knyaz2.content.builder import _hero_choices
        choices = _hero_choices()
        self.assertEqual(len(choices), 9)
        by_slot = {entry["slot"]: entry for entry in choices}
        # Слот 1 — Велиславна «Продолжения легенды», и стартует она в ЕГО
        # Чёрном Бору, карта 169, а не в канонном 19.
        #
        # Деревня есть в обеих играх под одним номером, и раньше донорская
        # не ввозилась вовсе — её переходы приходили в нашу. Но в прошлом
        # это другое место: своя застройка, свои жители. Теперь у каждой
        # игры свой Чёрный Бор, и героиня прошлого начинает в своём.
        #
        # Экземпляры её мешка живут в legend-пространстве, не в канонном game.
        her = by_slot[1]
        self.assertEqual((her["game"], her["map"], her["name"]),
                         ("legend", 169, "Велиславна"))
        self.assertTrue(any("legend:1:" in str(ref)
                            for ref in her["template"]["bag"] if ref))
        # новые трое стартуют на перенесённых картах
        for slot, name, map_number in ((6, "Иззарк", 155),
                                       (7, "Драгомир", 164),
                                       (8, "Гильдис", 154)):
            entry = by_slot[slot]
            self.assertEqual((entry["name"], entry["map"]), (name, map_number))
        # Амулет Дракона Драгомира разыменован в наш хвостовой класс
        mapping = donor.item_class_map()
        amulet = mapping[19]
        self.assertTrue(any(f"instance:{amulet}:legend:2:" in str(ref)
                            for ref in by_slot[7]["template"]["bag"] if ref))
        # мир каждого слота — сам слот: клиент выбирает мир номером
        for entry in choices:
            self.assertEqual(entry["world"], entry["slot"])


@needs_game
@needs_donor
class TestDonorEncounters(unittest.TestCase):
    """Засады на земле донора — его: его местности, отряды и места боя.

    Правило снято с его же кода: FUN_0042A450 зовёт жребий как
    ``FUN_00439B38(&DAT_00461690 + ((клетка & 0xff00) >> 8) * 0x40)``, то есть
    вид местности — байт 1 клетки, таблица 0x461690 с шагом 0x40. В записи
    спокойствие (u16 на +0) и двадцать номеров отрядов (u16 с +0x18); класса
    опасности по телу героя, как у канона, у него НЕТ, а место боя берётся из
    байта 2 самой клетки, а не из пятнадцати сцен записи.
    """

    def test_table_has_nine_records(self):
        """Девять — и это видно с двух сторон, а не выбрано на глаз."""
        table = donor.terrain_table()
        self.assertEqual(len(table), donor.DONOR_TERRAIN_COUNT)
        self.assertEqual(len(table), 9)
        # Записи похожи друг на друга: спокойствие в разумных пределах.
        for kind, record in enumerate(table):
            with self.subTest(kind=kind):
                self.assertLessEqual(record["calm"], 1000)
                self.assertEqual(len(record["parties"]),
                                 donor.DONOR_TERRAIN_CHOICES)
        # А десятая — уже не запись: её спокойствие вылезает за тысячу.
        exe = donor.DonorExe.load()
        at = exe.va_to_foff(donor.DONOR_TERRAIN_VA)
        import struct
        tenth = struct.unpack_from(
            "<H", exe.blob, at + 9 * donor.DONOR_TERRAIN_STRIDE)[0]
        self.assertGreater(tenth, 1000,
                           "десятая запись выглядит настоящей — граница не там")

    def test_his_grid_uses_exactly_these_kinds(self):
        """Вторая сторона того же довода: сетка знает виды 0…8 и только их."""
        kinds = {kind for line in donor.world_terrain() for kind, _ in line}
        self.assertEqual(kinds, set(range(donor.DONOR_TERRAIN_COUNT)))

    def test_base_matches_the_canon_table_length(self):
        """Сдвиг видов равен числу канонных местностей — иначе они съедут."""
        self.assertEqual(donor.DONOR_TERRAIN_BASE, len(canon.terrain_table()))

    def test_every_party_number_has_a_squad(self):
        """Все номера из таблицы находятся отрядами в его GAME.<мир>.

        Это и есть перевод «номер местности -> кого встретим»: у канона
        отряды-шаблоны приписаны к несуществующим картам 100…140, у него —
        1000…1717, и ищутся тем же полем +0x08 записи отряда.
        """
        wanted = {number for record in donor.terrain_table()
                  for number in record["parties"] if number}
        self.assertGreater(len(wanted), 50)
        templates = donor.encounter_templates()
        self.assertEqual(sorted(templates), sorted(wanted))
        self.assertTrue(all(template["units"] for template in templates.values()))

    def test_his_scenes_are_his_maps(self):
        """Байт 2 клетки — номер ЕГО карты, и она у нас есть.

        Перевод через `our_map_number`, а не сдвигом: у карт 1 и 2 есть наши
        двойники (26 и 27), и сдвиг увёл бы 221 клетку его моря на карту 151,
        которой в паке нет вовсе.
        """
        import json
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        index = json.loads((root / "project" / "index.json").read_text("utf-8"))
        imported = {int(record["map"]) for record in index["maps"]}
        scenes = {scene for line in donor.world_terrain()
                  for _, scene in line if scene}
        self.assertGreater(len(scenes), 30)
        twins, missing = [], []
        for scene in sorted(scenes):
            ours = donor.our_map_number(scene)
            if scene in donor.TWIN_MAPS:
                twins.append((scene, ours))       # наша карта, она есть всегда
            elif ours not in imported:
                missing.append((scene, ours))
        self.assertEqual(missing, [], "его сцены указывают на карты, "
                                      "которых мы не ввозили")
        self.assertTrue(twins, "ни одна сцена не пришлась на двойника — "
                               "перевод номеров проверять не на чем")


if __name__ == "__main__":
    unittest.main()
