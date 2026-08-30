# -*- coding: utf-8 -*-
"""Договор каталога объектов: канон и его продолжение.

Правило то же, что у карты мира: канон владеет началом номеров, проект —
продолжением. Здесь проверяется, что граница замерена, а не назначена, что
общие гнёзда берутся у нас (иначе лето сядет посреди осени) и что объект не
может пропасть с карты молча.
"""
from __future__ import annotations

import os
import unittest

from konung2 import donor
from konung2.kn2 import KN2Map
from konung2.paths import game_file
from konung2.res import ObjectsRes
from knyaz2.content.objects import MergedObjects, catalogue, missing_slots

GAME_AVAILABLE = os.path.isfile(game_file("konung2.exe"))
needs_game = unittest.skipUnless(GAME_AVAILABLE, "игра недоступна: нет konung2.exe")
needs_donor = unittest.skipUnless(
    donor.available(), f"донор недоступен: нет {donor.DONOR_EXE}")


@needs_game
class TestCanonCatalogue(unittest.TestCase):
    """Наш каталог — сам по себе."""

    @classmethod
    def setUpClass(cls):
        cls.ours = ObjectsRes.from_game()

    def test_canon_slots_run_without_holes(self):
        # Граница 509 не назначена: годные гнёзда идут подряд с 30, и на 509
        # ряд обрывается. Если каталог когда-нибудь дорастёт, тест упадёт.
        good = [slot for slot in range(len(self.ours.entries))
                if self.ours.frame_size(slot)]
        self.assertEqual(min(good), ObjectsRes.SIMPLE_SLOT_BASE)
        self.assertEqual(max(good), donor.CANON_LAST_SLOT)
        self.assertEqual(len(good), donor.CANON_LAST_SLOT
                         - ObjectsRes.SIMPLE_SLOT_BASE + 1, "в каноне есть дыра")

    def test_our_maps_lose_no_objects(self):
        # Ради этого и заводится громкая проверка в сборщике: на каноне
        # потерь нет ни одной, значит любая потеря — неисправность.
        from pathlib import Path

        from konung2.paths import GAME_DIR
        numbers = sorted(int(path.stem) for path in Path(GAME_DIR).glob("*.kn2")
                         if path.stem.isdigit())
        self.assertTrue(numbers)
        lost = {}
        for number in numbers:
            kn2 = KN2Map.from_game(number)
            wanted = {ObjectsRes.slot_of(record) for record in kn2.objects()
                      if record.get("kind", 0xFFFF) not in (0xFFFF, 0xFFFFFFFF)}
            gone = missing_slots(self.ours, wanted)
            if gone:
                lost[number] = gone
        self.assertEqual(lost, {})


@needs_game
@needs_donor
class TestExtendedCatalogue(unittest.TestCase):
    """Продолжение дозаписью, без перенумерации."""

    @classmethod
    def setUpClass(cls):
        cls.ours = ObjectsRes.from_game()
        cls.merged = catalogue()

    def test_catalogue_is_merged_when_donor_is_here(self):
        self.assertIsInstance(self.merged, MergedObjects)

    def test_extension_adds_exactly_seventy_eight_slots(self):
        good = [slot for slot in range(len(self.merged.entries))
                if self.merged.frame_size(slot)]
        self.assertEqual(max(good), donor.DONOR_LAST_SLOT)
        self.assertEqual(len(good), donor.DONOR_LAST_SLOT
                         - ObjectsRes.SIMPLE_SLOT_BASE + 1)
        added = donor.DONOR_LAST_SLOT - donor.CANON_LAST_SLOT
        self.assertEqual(added, 78)

    def test_shared_slots_come_from_us(self):
        # Донор перерисовал часть общих гнёзд в свой сезон. Берём наши —
        # сверяем по размеру записи, он у перерисованных отличается.
        theirs = donor.objects()
        redrawn = [slot for slot in range(ObjectsRes.SIMPLE_SLOT_BASE,
                                          donor.CANON_LAST_SLOT + 1)
                   if self.ours.simple_header(slot)["size"]
                   != theirs.simple_header(slot)["size"]]
        self.assertTrue(redrawn, "перерисованных гнёзд не нашлось — проверь замер")
        for slot in redrawn[:20]:
            with self.subTest(slot=slot):
                self.assertEqual(self.merged.simple_header(slot)["size"],
                                 self.ours.simple_header(slot)["size"])

    def test_creatures_share_their_slots(self):
        """Первые 30 записей каталога — твари, и номер породы общий.

        Двадцать две записи с 1-й по 22-ю совпадают по ДЛИНЕ побайтно, то
        есть это одни и те же существа в одних и тех же гнёздах. Значит
        переводить номера пород между играми не надо.
        """
        from konung2.creatures import CREATURE_ENTRIES, catalogue as breeds
        from konung2.paths import game_file
        ours = breeds(open(game_file("OBJECTS.RES"), "rb").read())
        theirs = breeds(open(donor.donor_file("OBJECTS.RES"), "rb").read())
        same = [slot for slot in range(1, CREATURE_ENTRIES)
                if ours[slot][1] == theirs[slot][1]]
        self.assertEqual(same, list(range(1, 23)))

    def test_donor_creatures_are_taken_from_the_donor(self):
        """Твари 23 и 24 есть только у донора — у нас там пусто.

        Пустое гнездо видно по длине: она равна длине служебного блока.
        """
        from konung2.creatures import catalogue as breeds
        from konung2.paths import game_file
        ours = breeds(open(game_file("OBJECTS.RES"), "rb").read())
        empty = ours[0][1]
        for slot in donor.DONOR_CREATURE_SLOTS:
            with self.subTest(slot=slot):
                self.assertEqual(ours[slot][1], empty, "у нас гнездо занято")
                self.assertNotEqual(self.merged.entries[slot],
                                    self.ours.entries[slot])

    def test_donor_maps_lose_nothing_with_the_extension(self):
        # Без продолжения объекты теряют 50 донорских карт из 90; с ним — ни одна.
        without, with_it = {}, {}
        for number in donor.map_numbers():
            data, _ = donor.map_data(number)
            wanted = {ObjectsRes.slot_of(record)
                      for record in KN2Map(number, data).objects()
                      if record.get("kind", 0xFFFF) not in (0xFFFF, 0xFFFFFFFF)}
            if missing_slots(self.ours, wanted):
                without[number] = True
            if missing_slots(self.merged, wanted):
                with_it[number] = missing_slots(self.merged, wanted)
        self.assertEqual(len(without), 50)
        self.assertEqual(with_it, {})


@needs_game
class TestNoSilentLoss(unittest.TestCase):
    """`missing_slots` должна ловить именно то, что пропадает молча."""

    def test_unknown_slot_is_reported(self):
        ours = ObjectsRes.from_game()
        self.assertEqual(missing_slots(ours, [donor.CANON_LAST_SLOT + 1]),
                         [donor.CANON_LAST_SLOT + 1])
        self.assertEqual(missing_slots(ours, [donor.CANON_LAST_SLOT]), [])

    def test_slot_beyond_the_table_is_reported(self):
        ours = ObjectsRes.from_game()
        self.assertEqual(missing_slots(ours, [len(ours.entries) + 5]),
                         [len(ours.entries) + 5])


if __name__ == "__main__":
    unittest.main()
