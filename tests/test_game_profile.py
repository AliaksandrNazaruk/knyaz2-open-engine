# -*- coding: utf-8 -*-
"""Договор профиля игры: адрес — это данные, а не константа в коде.

Движок у двух игр один, а адреса не совпадают ни в одной таблице: перебор
всех 34 табличных констант ядра дал ноль совпадений. Поэтому профиль обязан
(1) повторять для канона ровно то, что было константами, иначе порт поедет,
и (2) ПАДАТЬ на ненайденном адресе, а не подставлять канонный: чужая сборка
по канонному адресу возвращает не ошибку, а правдоподобный мусор.
"""
from __future__ import annotations

import os
import unittest

from konung2 import profile as gp
from konung2.exetables import SECTIONS
from konung2.paths import game_file

GAME_AVAILABLE = os.path.isfile(game_file("konung2.exe"))
needs_game = unittest.skipUnless(GAME_AVAILABLE, "игра недоступна: нет konung2.exe")
needs_donor = unittest.skipUnless(gp.LEGEND.available(), "донор недоступен")


class TestUnknownAddressFails(unittest.TestCase):
    """Не найденное поле должно ронять, а не читаться по канону."""

    def test_missing_field_raises_with_its_name(self):
        with self.assertRaises(gp.UnknownAddress) as caught:
            gp.LEGEND.need("world_arrivals_va")
        self.assertIn("world_arrivals_va", str(caught.exception))

    def test_known_field_returns_value(self):
        self.assertEqual(gp.CANON.need("world_grid_va"), 0x460174)

    def test_unknown_list_matches_none_fields(self):
        # Перечень несделанного не должен расходиться с самими полями:
        # иначе работа выглядит закрытой, а адреса нет.
        for name in gp.LEGEND.unknown:
            if hasattr(gp.LEGEND, name):
                with self.subTest(field=name):
                    self.assertIsNone(getattr(gp.LEGEND, name))


@needs_game
class TestGameFileLayoutIsARunningSum(unittest.TestCase):
    """Таблицы GAME.<мир> лежат подряд, и их сумма равна размеру файла.

    Это и есть рычаг для чужой сборки: чтобы найти таблицу, достаточно знать
    длины предыдущих. Проверяется на каноне, где известно всё.
    """

    def test_canon_tables_sum_to_the_file(self):
        from konung2.gamefile import (T_ITEMS, T_PARTIES, T_GROUND, T_EXITS,
                                      T_UNITS, T_VILLAGES, T_EVENTS)
        tables = (T_ITEMS, T_PARTIES, T_GROUND, T_EXITS, T_UNITS, T_VILLAGES,
                  T_EVENTS)
        at = 0
        for table in tables:
            with self.subTest(table=table.name):
                self.assertEqual(table.offset, at)
            at += table.count * table.size
        self.assertEqual(at, os.path.getsize(game_file("GAME.0")))

    def test_canon_profile_repeats_those_lengths(self):
        from konung2.gamefile import T_EXITS, T_PARTIES, T_UNITS
        self.assertEqual(gp.CANON.game_parties, T_PARTIES.count)
        self.assertEqual(gp.CANON.game_exits_at, T_EXITS.offset)
        self.assertEqual(gp.CANON.game_units, T_UNITS.count)


@needs_donor
class TestLegendGameFile(unittest.TestCase):
    """Что установлено про GAME.<мир> донора."""

    def test_parties_explain_the_shift(self):
        # 255 отрядов вместо 200 — это ровно +14080 байт, и они объясняют
        # обе измеренные границы пустот: 0x2FF00 и 0x48988.
        from konung2.gamefile import T_GROUND, T_PARTIES
        shift = (gp.LEGEND.game_parties - gp.CANON.game_parties) * 256
        self.assertEqual(shift, 14080)
        self.assertEqual(T_GROUND.offset + shift, 0x2FF00)
        self.assertEqual(gp.LEGEND.game_exits_at,
                         T_GROUND.offset + shift + T_GROUND.count * T_GROUND.size)

    def test_tables_sum_to_the_file(self):
        """Найденные длины обязаны в сумме дать размер файла — до байта."""
        import os
        from konung2.gamefile import (T_EVENTS, T_GROUND, T_ITEMS, T_PARTIES,
                                      T_UNITS, T_VILLAGES)
        exits = ((gp.LEGEND.game_exits_at
                  - T_ITEMS.count * T_ITEMS.size
                  - gp.LEGEND.game_parties * T_PARTIES.size)
                 // T_GROUND.size)
        self.assertEqual(exits, T_GROUND.count, "земля должна остаться прежней")
        block = (T_ITEMS.count * T_ITEMS.size
                 + gp.LEGEND.game_parties * T_PARTIES.size
                 + T_GROUND.count * T_GROUND.size)
        self.assertEqual(block, gp.LEGEND.game_exits_at)
        total = (block
                 + gp.LEGEND.game_exits_bytes
                 + gp.LEGEND.game_units * T_UNITS.size
                 + gp.LEGEND.game_villages * T_VILLAGES.size
                 + gp.LEGEND.game_events * T_EVENTS.size)
        self.assertEqual(total, os.path.getsize(gp.LEGEND.file("GAME.0")))

    def test_units_start_where_worlds_begin_to_differ(self):
        """База таблицы юнитов видна сравнением МИРОВ, и признак общий.

        Всё до юнитов от мира не зависит, а первым различается поле +0x12
        нулевого юнита — строка его клетки. На каноне первое различие ровно
        на базе + 0x12, и у донора обязано быть так же. Этим и вскрылась
        прежняя ошибка: 2007 юнитов давали базу на семь записей раньше.
        """
        from konung2.gamefile import T_UNITS
        for profile, worlds, base in (
                (gp.CANON, 6, T_UNITS.offset),
                (gp.LEGEND, 4, gp.LEGEND.game_layout()["units"][0])):
            blobs = [open(profile.file(f"GAME.{n}"), "rb").read()
                     for n in range(worlds)]
            first = next(at for at in range(base - 0x400, base + 0x400)
                         if any(blob[at] != blobs[0][at] for blob in blobs[1:]))
            with self.subTest(game=profile.name):
                self.assertEqual(first - base, 0x12)

    def test_no_party_points_at_an_empty_unit(self):
        """Отряд не может состоять из пустых записей.

        Прежняя база (на семь записей раньше) давала 83 таких из 798 — и
        при этом читалась «связно», потому что сдвиг кратен размеру записи.
        Поэтому проверка не на вид записи, а на то, что отряд ссылается на
        занятую.
        """
        import struct

        from konung2.gamefile import T_PARTIES, T_UNITS
        blob = open(gp.LEGEND.file("GAME.0"), "rb").read()
        base = gp.LEGEND.game_layout()["units"][0]
        maps = {int(path.stem) for path in
                __import__("pathlib").Path(gp.LEGEND.directory).glob("*.kn2")
                if path.stem.isdigit()}
        checked = empty = 0
        for index in range(gp.LEGEND.game_parties):
            record = blob[T_PARTIES.offset + index * 256:][:256]
            number = struct.unpack_from("<H", record, 0x08)[0]
            if number not in maps or not record[0x1C]:
                continue
            first, count = struct.unpack_from("<H", record, 0x00)[0], record[0x1C]
            for step in range(count):
                at = base + (first + step) * T_UNITS.size
                checked += 1
                if not any(blob[at:at + T_UNITS.size]):
                    empty += 1
        self.assertGreater(checked, 700, "отрядов не нашлось — проверь замер")
        self.assertEqual(empty, 0)

    def test_villagers_are_slavic_where_the_village_is_slavic(self):
        """Проверка содержимым: в Дубках живут не византийцы.

        По прежней базе на карте 19 читались Константин, Евстафий, Нарсез и
        Королева Нежити — состав чужого отряда, а выглядел он связным.
        """
        from konung2.gamefile import map_units
        for number, wanted in ((19, "Добрыня"), (16, "Микула")):
            names = {unit["name"] for unit in map_units(number, 0,
                                                        profile=gp.LEGEND)}
            with self.subTest(map=number):
                self.assertIn(wanted, names)
                self.assertNotIn("Королева Нежити", names)

    def test_residents_carry_real_bodies_and_palettes(self):
        """Вид жителя читается из ТАБЛИЦЫ ЕГО СБОРКИ, а не по канонному месту.

        Отчёт с живой проверки: НПС в новых деревнях не рисовались.
        unit_stats брал юнита по канонному 0x46322 при донорских данных —
        имя и клетка (их map_units берёт по раскладке) выходили верными, а
        тело, палитра и здоровье читались из ЧУЖОГО места: у всех жителей
        Дубков выходило тело 0 и палитра −1 — юнит без листов кадров
        невидим, а по невидимому не кликнуть, и разговор не начать.
        """
        from konung2.gamefile import map_units
        residents = map_units(16, 0, profile=gp.LEGEND)
        self.assertTrue(residents)
        named = {unit["name"]: unit for unit in residents}
        self.assertIn("Позвизд", named)
        self.assertEqual(named["Позвизд"]["body"], 24)
        self.assertEqual(named["Позвизд"]["palette"], 178)
        palettes = {unit["palette"] for unit in residents}
        self.assertNotIn(-1, palettes, "палитра −1 — чтение мимо таблицы")
        self.assertGreater(len(palettes), 3, "у жителей должны быть свои масти")
        for unit in residents:
            with self.subTest(unit=unit["name"]):
                self.assertGreater(unit["health"], 0)

    def test_donor_ground_piles_are_readable(self):
        """Тайники его карт читаются его же раскладкой.

        У донора кучи лежат со сдвигом (отрядов 255, не 200), и канонное
        смещение 0x2C800 попадало в середину его таблицы отрядов.
        """
        from konung2.gamefile import ground_items
        piles = ground_items(4, 0, profile=gp.LEGEND)
        self.assertTrue(piles, "на Кирингхольме есть тайники")
        chest = [pile for pile in piles if pile.get("place") == 39]
        self.assertTrue(chest, "сундук в постройке 39 не прочитался")
        self.assertEqual(chest[0]["money"], 25)

    def test_the_shared_village_keeps_its_people(self):
        """Чёрный Бор в обеих играх населён во многом ОДНИМИ И ТЕМИ ЖЕ.

        Самая сильная из проверок базы: она связывает два разных exe (имена
        читаются каждое из своего) и два разных GAME.<мир> через одну
        деревню. По прежней базе общих имён не было ни одного.
        """
        from konung2.gamefile import map_units
        ours = {unit["name"] for unit in map_units(19, 0)}
        theirs = {unit["name"] for unit in map_units(19, 0, profile=gp.LEGEND)}
        self.assertGreaterEqual(len(ours & theirs), 5,
                                f"наши {sorted(ours)}, его {sorted(theirs)}")


@needs_game
class TestQuestsLayout(unittest.TestCase):
    """Семь секций QUESTS.RES в сумме дают размер файла — у обеих игр."""

    def test_canon_matches_the_module(self):
        from konung2 import quests
        layout = gp.CANON.quests_layout()
        for name, offset, size in quests.DIALOG_TABLES:
            with self.subTest(section=name):
                self.assertEqual(layout[name], (offset, size))
        self.assertEqual(layout["strings"], (quests.BLOB_OFF, quests.BLOB_SIZE))
        self.assertEqual(layout["quest_states"],
                         (quests.STATE_OFF, quests.STATE_SIZE))
        self.assertEqual(layout["__end__"][0], quests.TOTAL)

    @needs_donor
    def test_legend_sums_to_its_file(self):
        layout = gp.LEGEND.quests_layout()
        self.assertEqual(layout["__end__"][0],
                         os.path.getsize(gp.LEGEND.file("QUESTS.RES")))

    @needs_donor
    def test_legend_strings_start_with_text(self):
        # Проверка содержимым: блок строк обязан начинаться со строк, а не
        # с хвоста предыдущей таблицы. Сумма секций сама по себе ничего не
        # доказывает — она построена из тех же границ.
        at, size = gp.LEGEND.quests_layout()["strings"]
        blob = open(gp.LEGEND.file("QUESTS.RES"), "rb").read()
        end = blob.find(b"\0", at, at + 200)
        self.assertGreater(end, at)
        first = blob[at:end].decode("cp866", "replace")
        self.assertTrue(all(byte >= 0x20 for byte in blob[at:end]), first)
        after = blob.find(b"\0", end + 1, end + 300)
        self.assertIn("=", blob[end + 1:after].decode("cp866", "replace"))


@needs_game
@needs_donor
class TestDonorDialogsRead(unittest.TestCase):
    """Деревья разговоров донора читаются нашим же разбором.

    Раскладка секций сама по себе ничего не значит: чужие таблицы дают
    связный на вид, но не тот разговор. Проверяем текстом.
    """

    @classmethod
    def setUpClass(cls):
        from konung2.quests import Dialogs
        cls.theirs = Dialogs.from_game(gp.LEGEND)
        cls.lines = []
        for number in range(1, 150):
            try:
                line = cls.theirs.line(cls.theirs.root(number))
            except Exception:                                # noqa: BLE001
                continue
            if line and line.get("text") and not line["text"].startswith("Dummy"):
                cls.lines.append(line["text"])

    def test_most_dialogs_are_readable(self):
        self.assertGreater(len(self.lines), 120)

    def test_text_is_the_donors_own_story(self):
        joined = " ".join(self.lines)
        self.assertIn("Кирингхольм", joined)
        self.assertIn("пустын", joined)

    def test_no_control_bytes_in_text(self):
        for text in self.lines[:40]:
            with self.subTest(text=text[:30]):
                self.assertTrue(all(ord(ch) >= 0x20 or ch.isspace()
                                    for ch in text))

    def _calls(self, dialogs):
        """Вызовы обработчиков по СЫРЫМ секциям: номер -> сколько."""
        return {number: sum(seen.values())
                for number, seen in dialogs.handler_calls().items()}

    def test_counting_by_sections_not_by_walking_trees(self):
        """Обход деревьев считает малую часть — контроль на каноне.

        В секциях канона встречаются номера 0…75 и ни одного выше, то есть
        ровно наша таблица: мусор в счёт не попадает. А обход деревьев
        упирается в предел узлов и даёт вшестеро меньше.
        """
        from konung2.quests import Dialogs, HANDLERS
        ours = self._calls(Dialogs.from_game())
        self.assertEqual(sorted(ours), list(range(HANDLERS)))
        theirs = self._calls(self.theirs)
        self.assertEqual(max(theirs), gp.LEGEND.handlers_count - 1)
        self.assertGreater(sum(theirs.values()), 8000)

    def test_handlers_are_translated_into_our_numbering(self):
        """Номера обработчиков у донора СВОИ, и разбор обязан их перевести.

        Раньше здесь стояло «восемь обработчиков нам неизвестны» — неверно:
        семь из восьми оказались нашими же под другими номерами.
        """
        from konung2 import donor
        from konung2.quests import HANDLERS
        calls = self._calls(self.theirs)
        shared = {**donor.HANDLER_MAP, **donor.HANDLER_BY_HAND}
        ours = sum(count for number, count in calls.items() if number in shared)
        self.assertGreater(ours / sum(calls.values()), 0.9)
        # Общие уезжают в канонные номера, собственные — в проектный участок,
        # и перепутать их нельзя: между 76 и 128 пусто.
        for his, mine in self.theirs.handler_map.items():
            with self.subTest(handler=his):
                if his in shared:
                    self.assertLess(mine, HANDLERS)
                else:
                    self.assertGreaterEqual(mine, donor.PROJECT_HANDLER_BASE)

    def test_every_call_reaches_an_implemented_handler(self):
        """Ни один вызов не остаётся без обработчика — и это по КЛИЕНТУ.

        Проверяется не «номер отведён», а «обработчик написан»: номер без
        тела вёл бы себя как непереносенный, только тихо. Путь замера был
        такой: 1155 непокрытых вызовов, потом 275, теперь ноль.
        """
        import re
        from pathlib import Path
        from konung2 import donor
        source = (Path(__file__).resolve().parent.parent / "knyaz2" / "web"
                  / "static" / "dialog.js").read_text(encoding="utf-8")
        written = {int(number) for number
                   in re.findall(r"\[PROJECT_HANDLER_BASE \+ (\d+)\]", source)}
        self.assertTrue(written, "проектных обработчиков в клиенте нет вовсе")
        shared = {**donor.HANDLER_MAP, **donor.HANDLER_BY_HAND}
        calls = self._calls(self.theirs)
        lost = {number: count for number, count in calls.items()
                if number not in shared and number not in written}
        self.assertEqual(lost, {})
        # И сами доли: почти всё идёт через наши же обработчики.
        ours = sum(count for number, count in calls.items() if number in shared)
        self.assertGreater(ours / sum(calls.values()), 0.9)

    def test_reputation_is_the_second_biggest_hole(self):
        """Репутация донора — 461 вызов, и она перенесена под номерами проекта."""
        from konung2 import donor
        calls = self._calls(self.theirs)
        self.assertGreater(calls[donor.REPUTATION_ADD], 350)
        self.assertGreater(calls[donor.REPUTATION_ATLEAST], 90)
        for his in (donor.REPUTATION_ADD, donor.REPUTATION_ATLEAST):
            with self.subTest(handler=his):
                self.assertEqual(self.theirs.handler_map[his],
                                 donor.PROJECT_HANDLER_BASE + his)
        # Стартовых значений столько же, сколько у донора миров.
        worlds = len([1 for number in range(8)
                      if os.path.isfile(gp.LEGEND.file(f"GAME.{number}"))])
        self.assertEqual(len(donor.REPUTATION_STARTS), worlds)

    def test_tree_remembers_whose_game_it_is(self):
        """Дерево уезжает в пак и должно помнить свою игру.

        По этой пометке клиент выбирает граф переходов: номер записи у
        донора значит другой переход, его таблица на 350 записей.
        """
        from konung2.quests import Dialogs
        from konung2 import donor
        self.assertEqual(self.theirs.tree(9)["game"], donor.LEGEND_NAME)
        self.assertEqual(Dialogs.from_game().tree(9)["game"], gp.CANON.name)

    def test_the_same_dialog_number_means_different_words(self):
        """Ради чего всё это: номер разговора у него значит ДРУГОЕ.

        Пока дерево читалось из нашего файла, все 264 его жителя говорили
        нашими репликами — и ничего при этом не падало.
        """
        from konung2.quests import Dialogs
        ours = Dialogs.from_game()
        mine = ours.line(ours.root(9)) or {}
        yours = self.theirs.line(self.theirs.root(9)) or {}
        self.assertTrue(mine.get("text") and yours.get("text"))
        self.assertNotEqual(mine["text"], yours["text"])
        self.assertIn("мертв", yours["text"])

    def test_handler_35_now_goes_through_our_extended_28(self):
        """Его 35 переводится в наш 28 — обработчик расширен под его довод."""
        from konung2 import donor
        self.assertEqual(self.theirs.handler_map[35], 28)
        self.assertIn(35, donor.HANDLER_ARGUMENT_CHANGED)
        self.assertEqual(donor.HANDLER_BY_HAND[35], 28)

    def test_settlement_argument_of_handler_35_is_a_map_number(self):
        """У его 35 старший байт довода — НОМЕР КАРТЫ, и он вправду нужен.

        Поиск поселения (FUN_0043f670) идёт по 20 записям, сравнивая байт
        +0x03 записи — а это `map` в нашей же T_VILLAGES. Довод со старшим
        байтом встречается девять раз: карты 6, 8 и 15.
        """
        from konung2 import donor
        arguments = self.theirs.handler_calls()[35]
        high = {value >> 8: count for value, count in arguments.items()
                if value >> 8}
        self.assertEqual(sorted(high), [6, 8, 15])
        maps = set(donor.map_numbers())
        for number in high:
            with self.subTest(map=number):
                self.assertIn(number, maps)


@needs_game
class TestHandlerTables(unittest.TestCase):
    """Таблица обработчиков — массив адресов кода, и она найдена у обеих игр."""

    def _addresses(self, profile):
        import struct
        blob = profile.exe_bytes()
        at, count = profile.need("handlers_at"), profile.need("handlers_count")
        return [struct.unpack_from("<I", blob, at + i * 4)[0]
                for i in range(count)]

    def test_canon_table_matches_the_module(self):
        from konung2.quests import HANDLERS, HANDLERS_VA
        self.assertEqual(gp.CANON.handlers_at, gp.CANON.va_to_foff(HANDLERS_VA))
        self.assertEqual(gp.CANON.handlers_count, HANDLERS)

    def test_every_entry_points_into_code(self):
        for profile in (gp.CANON, gp.LEGEND):
            if not profile.available():
                continue
            with self.subTest(game=profile.name):
                outside = [value for value in self._addresses(profile)
                           if not 0x410000 <= value < 0x450000]
                self.assertEqual(outside, [])

    @needs_donor
    def test_donor_table_covers_the_handlers_its_dialogs_call(self):
        # Разговоры донора зовут обработчики до 90-го включительно, и
        # таблица на 93 записи их покрывает.
        self.assertGreater(gp.LEGEND.handlers_count, 90)
        self.assertGreater(gp.LEGEND.handlers_count, gp.CANON.handlers_count)


@needs_game
@needs_donor
class TestHandlerNumbering(unittest.TestCase):
    """Нумерация обработчиков у донора НЕ наша: та же с вставками.

    Сравнивается разобранный код с обезличенными операндами — побайтно
    нельзя, в командах сидят абсолютные адреса. Таблица в
    `konung2/donor.py: HANDLER_MAP` — замер, и тест его повторяет: разойдись
    она с самими exe, донорский разговор позовёт чужой обработчик.
    """

    @classmethod
    def setUpClass(cls):
        import sys
        from pathlib import Path
        tools = Path(__file__).resolve().parent.parent / "tools"
        sys.path.insert(0, str(tools))
        from handler_diff import resolved
        cls.mapping, cls.scores, cls.lost = resolved()

    def test_recorded_table_matches_the_binaries(self):
        from konung2 import donor
        back = {his: mine for mine, his in self.mapping.items()}
        self.assertEqual(back, donor.HANDLER_MAP)

    def test_reworked_and_own_lists_match(self):
        from konung2 import donor
        reworked = {self.mapping[mine] for mine in self.scores}
        self.assertEqual(reworked, set(donor.HANDLER_REWORKED))
        own = set(range(gp.LEGEND.handlers_count)) - set(self.mapping.values())
        self.assertEqual(own, set(donor.HANDLER_OWN))

    def test_order_is_never_broken(self):
        """Вставки сдвигают, но не переставляют — иначе замер неверен."""
        order = [self.mapping[number] for number in sorted(self.mapping)]
        self.assertEqual(order, sorted(order))
        self.assertEqual(len(set(order)), len(order), "два наших на один его")

    def test_numbering_is_not_shared(self):
        """Прямое опровержение прежнего довода «номера, похоже, общие»."""
        from konung2 import donor
        same = [his for his, mine in donor.HANDLER_MAP.items() if his == mine]
        self.assertEqual(same, list(range(1, 8)),
                         "совпадают только первые семь, дальше расходятся")
        self.assertEqual(donor.HANDLER_MAP[90], 74)

    def test_the_handlers_we_thought_unknown_are_mostly_ours(self):
        """Из восьми «неизвестных» семь оказались нашими же."""
        from konung2 import donor
        called = (78, 80, 81, 82, 83, 85, 88, 90)
        ours = {his: donor.HANDLER_MAP.get(his) for his in called}
        self.assertEqual(ours, {78: 63, 80: None, 81: 65, 82: 66, 83: 67,
                                85: 69, 88: 72, 90: 74})
        self.assertIn(80, donor.HANDLER_OWN)

    def test_our_handler_bodies_are_distinctive(self):
        """Мера имела бы грош цену, будь обработчики похожи друг на друга."""
        import sys
        from handler_diff import bodies
        ours = [body for body in bodies(gp.CANON) if body]
        self.assertGreaterEqual(len(set(ours)), len(ours) - 2)


#: Диапазоны сетки карты: строк 256, столбцов 160.
GRID_H, GRID_W = 256, 160


def _sane_exit(record, known_maps):
    """Похожа ли запись на настоящий выход. Порознь от разбора — нарочно."""
    if record["from_map"] != 127 and record["from_map"] not in known_maps:
        return False
    target = record["to_map"]
    if target not in (-1, -2) and abs(target) not in known_maps:
        return False
    if record["entry_row"] >= GRID_H or record["entry_col"] >= GRID_W:
        return False
    if record["row2"] >= GRID_H or record["col2"] >= GRID_W:
        return False
    return record["row1"] <= record["row2"] and record["col1"] <= record["col2"]


@needs_game
class TestExitRecord(unittest.TestCase):
    """Запись выхода: у канона 250 по 17, у донора 350 по 16 со сдвигом.

    Сдвиг не догадка: разбор одного и того же блока тремя раскладками
    оставляет ровно одну, при которой нет НИ ОДНОЙ бракованной записи. И
    сама проверка не поддавки — на каноне она так же уверенно отвергает
    ложную раскладку.
    """

    def _maps(self, profile):
        from pathlib import Path
        return {int(path.stem)
                for path in Path(profile.directory).glob("*.[kK][nN]2")
                if path.stem.isdigit()}

    def _score(self, profile, stride, shift, count):
        import struct

        from konung2.gamefile import _exit_record
        blob = open(profile.file("GAME.0"), "rb").read()
        at = profile.game_exits_at
        known = self._maps(profile)
        good = bad = blank = 0
        for index in range(count):
            raw = blob[at + index * stride:][:max(stride, 17)]
            if not any(raw[:stride]):
                blank += 1
                continue
            good += 1 if _sane_exit(_exit_record(raw, shift), known) else 0
            bad += 0 if _sane_exit(_exit_record(raw, shift), known) else 1
        return good, bad, blank

    def test_canon_layout_beats_the_shifted_one(self):
        # Проверка обязана РАЗЛИЧАТЬ, иначе ей грош цена.
        good, bad, _ = self._score(gp.CANON, 17, 0, 250)
        self.assertEqual(bad, 0)
        self.assertGreater(good, 150)
        wrong_good, wrong_bad, _ = self._score(gp.CANON, 16, 1, 265)
        self.assertGreater(wrong_bad, wrong_good * 10)

    @needs_donor
    def test_donor_layout_is_sixteen_bytes_shifted_by_one(self):
        good, bad, blank = self._score(gp.LEGEND, 16, 1, 350)
        self.assertEqual((good, bad, blank), (300, 0, 50))
        for stride, shift, count in ((17, 0, 224), (16, 0, 350), (272, 0, 14)):
            with self.subTest(stride=stride, shift=shift):
                other_good, other_bad, _ = self._score(gp.LEGEND, stride,
                                                       shift, count)
                self.assertGreater(other_bad, other_good)

    @needs_donor
    def test_block_divides_into_whole_records(self):
        layout = gp.LEGEND.game_layout()
        at, count, size = layout["exits"]
        self.assertEqual((at, count, size), (0x48988, 350, 16))
        self.assertEqual(count * size, gp.LEGEND.game_exits_bytes)
        self.assertEqual(at + count * size, layout["units"][0])

    def test_exits_do_not_depend_on_the_world(self):
        """Выходы у обеих игр одни на все миры — и это держит границу блока."""
        for profile, worlds in ((gp.CANON, 6), (gp.LEGEND, 4)):
            if not profile.available():
                continue
            at, count, size = profile.game_layout()["exits"]
            blobs = [open(profile.file(f"GAME.{n}"), "rb").read()
                     for n in range(worlds)]
            block = blobs[0][at:at + count * size]
            with self.subTest(game=profile.name):
                for index, blob in enumerate(blobs[1:], start=1):
                    self.assertEqual(blob[at:at + count * size], block,
                                     f"мир {index} расходится")

    @needs_donor
    def test_entry_cell_is_walkable_on_the_destination(self):
        """Клетка прибытия обязана быть проходимой — связь двух разных файлов.

        Раскладка записи взята из GAME.<мир>, а проверяется по .kn2: если
        поля разобраны неверно, совпасть тут нечему.
        """
        import struct

        from konung2 import donor
        from konung2.gamefile import all_exits
        from konung2.kn2 import GRID_ROW, SEC_GRID
        maps, cache, good, bad = set(donor.map_numbers()), {}, 0, 0
        for door in all_exits(0, profile=gp.LEGEND):
            number = door["to_map"]
            if number <= 0 or number not in maps:
                continue
            if number not in cache:
                cache[number] = donor.map_data(number, translate=False)[0]
            at = (SEC_GRID[0] + door["entry_row"] * GRID_ROW
                  + door["entry_col"] * 4)
            cell = struct.unpack_from("<H", cache[number], at)[0]
            if cell & donor.DONOR_BLOCKED:
                bad += 1
            else:
                good += 1
        self.assertGreater(good, 80)
        self.assertLessEqual(bad, 1, "разобранные поля не ложатся на карты")

    @needs_donor
    def test_donor_maps_have_doors_the_edge_strips_never_had(self):
        """Настоящие выходы дают то, чего сочинённые кромки дать не могли."""
        from konung2.gamefile import map_exits
        doors = map_exits(16, 0, profile=gp.LEGEND)
        inner = [door for door in doors if door["to_map"] > 0]
        self.assertEqual([door["to_map"] for door in inner], [37])
        self.assertEqual(inner[0]["to_name"], "Пещера у Дубков")
        # и кромки у настоящих выходов подогнаны под карту, а не по всей ширине
        self.assertTrue(any(door["col2"] < GRID_W - 1 for door in doors))

    def test_numbering_is_listed_as_unproven(self):
        # Совпадение нумерации с нашей НЕ доказано: побайтное сравнение кода
        # не годится (в инструкциях абсолютные адреса), а сравнение размеров
        # функций дало 8 совпадений из 76 при 8 и 10 у сдвигов — шум.
        self.assertIn("handler_numbering_shared", gp.LEGEND.unknown)


@needs_game
class TestCanonProfileMatchesTheCode(unittest.TestCase):
    """Профиль канона обязан повторять прежние константы до числа."""

    def test_world_map_addresses(self):
        from konung2 import worldmap
        self.assertEqual(gp.CANON.world_grid_va, worldmap.GRID_VA)
        self.assertEqual(gp.CANON.world_markers_va, worldmap.MARKERS_VA)
        self.assertEqual(gp.CANON.world_arrivals_va, worldmap.ARRIVALS_VA)

    def test_sections_parser_matches_hard_coded(self):
        parsed = {name: (rva, size, at)
                  for name, rva, size, at in gp.sections(gp.CANON.exe_bytes())}
        for name, rva, size, at in SECTIONS:
            with self.subTest(section=name):
                self.assertEqual(parsed[name], (rva, size, at))

    def test_string_tables_read_the_same_as_before(self):
        from konung2.worldmap import location_names
        self.assertEqual(gp.strings(gp.CANON, gp.CANON.location_names),
                         location_names())


@needs_game
@needs_donor
class TestBothProfilesRead(unittest.TestCase):
    """Одна и та же функция читает обе игры."""

    def test_location_names(self):
        ours = gp.strings(gp.CANON, gp.CANON.location_names)
        theirs = gp.strings(gp.LEGEND, gp.LEGEND.location_names)
        self.assertEqual(ours[19], "Черный Бор")
        self.assertEqual(theirs[19], "Черный Бор")
        self.assertEqual(ours[33], "Борье")
        self.assertIn("Оазис", theirs)

    def test_npc_names(self):
        theirs = gp.strings(gp.LEGEND, gp.LEGEND.npc_names)
        self.assertEqual(len(theirs), 214)
        self.assertEqual(theirs[0], "", "нулевой номер — «без имени»")
        self.assertIn("Яман", theirs)

    def test_map_units_carry_facing(self):
        """Поворот жителя (+0x18) — из расстановки, а не умолчание клиента.

        Пока поля не было, клиент ставил всем шестёрку, и деревня встречала
        игрока лицом вниз. Проверяем три вещи разом: поворот в диапазоне
        восьми сторон, на карте он РАЗНЫЙ, и это не сплошная шестёрка —
        иначе правка молча вернулась бы к прежнему поведению.
        """
        from konung2.gamefile import map_units
        for number in (33, 19, 37):
            with self.subTest(map=number):
                units = map_units(number, 0)
                self.assertTrue(units, "жители карты не прочитались")
                facings = [unit["direction"] for unit in units]
                for facing in facings:
                    self.assertIn(facing, range(8))
                self.assertGreater(len(set(facings)), 1,
                                   "на карте все смотрят в одну сторону")
                self.assertNotEqual(set(facings), {6},
                                    "это прежнее умолчание клиента, а не данные")

    def test_canon_and_legend_share_no_address(self):
        # Ровно то, ради чего заведён профиль: ни одна таблица не совпала.
        pairs = [(gp.CANON.npc_names.at, gp.LEGEND.npc_names.at),
                 (gp.CANON.location_names.at, gp.LEGEND.location_names.at),
                 (gp.CANON.world_grid_va, gp.LEGEND.world_grid_va)]
        for ours, theirs in pairs:
            with self.subTest(ours=hex(ours)):
                self.assertNotEqual(ours, theirs)


if __name__ == "__main__":
    unittest.main()
