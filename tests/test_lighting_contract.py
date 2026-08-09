# -*- coding: utf-8 -*-
"""Договор освещения: наши константы против самого konung2.exe.

Логика света трижды ломалась молча, потому что её никто не проверял: закон
маски подбирали вместо чтения кода, «дневной интерьер» держался на мёртвом
флаге, здание рисовали мимо фильтра и оно закрывало персонажа. Эти тесты
читают исходные байты игры и падают, если наши константы или флаги разойдутся
с движком.
"""
from __future__ import annotations

import os
import struct
import unittest

from konung2.exetables import va_to_foff
from konung2.graph import (LIGHT_FROM_TICK, LIGHT_MASK_SIZE, NIGHT_LEVEL_BLUE,
                           NIGHT_LEVEL_GREEN, NIGHT_LEVEL_RED, GraphRes,
                           fixed_light_map, read_light_masks)
from konung2.kn2 import KN2Map, T_OBJECTS
from konung2.paths import game_file
from konung2.res import ObjectsRes

GAME_AVAILABLE = os.path.isfile(game_file("konung2.exe"))
needs_game = unittest.skipUnless(GAME_AVAILABLE, "игра недоступна: нет konung2.exe")


def exe_bytes() -> bytes:
    with open(game_file("konung2.exe"), "rb") as stream:
        return stream.read()


@needs_game
class EngineConstantsTest(unittest.TestCase):
    """Числа, вокруг которых крутится весь ночной кадр."""

    def test_light_switches_on_at_the_engine_threshold(self) -> None:
        # Ветка «ночь» расписания суток (VA 0x429806) начинается там, где
        # время дошло до порога, читаемого как старшее слово по 0x45FC44.
        data = exe_bytes()
        threshold = struct.unpack_from("<h", data, va_to_foff(0x45FC46))[0]
        self.assertEqual(threshold, LIGHT_FROM_TICK)

    def test_night_levels_come_from_the_schedule_branch(self) -> None:
        # VA 0x429832: mov dword [ebp-8], 0x00CECEBA — байт 0 идёт в 0x58E2C8
        # (синий), байт 1 в 0x58E2C9 (зелёный), байт 2 в 0x58E2CA (красный).
        data = exe_bytes()
        offset = va_to_foff(0x429832)
        self.assertEqual(data[offset:offset + 3], bytes.fromhex("c745f8"))
        packed = struct.unpack_from("<I", data, offset + 3)[0]
        levels = [struct.unpack("<b", bytes([(packed >> shift) & 0xFF]))[0]
                  for shift in (0, 8, 16)]
        self.assertEqual(levels, [NIGHT_LEVEL_BLUE, NIGHT_LEVEL_GREEN, NIGHT_LEVEL_RED])

    def test_only_underground_maps_light_around_the_clock(self) -> None:
        # VA 0x4295E4: [0x8495CC] = таблица_0x4617B0[карта] & 0xFF000000.
        # Запись есть и у карт 45..49, но там старший байт нулевой (0x00FFFFFF),
        # то есть постоянный свет включён ровно у двух карт.
        always = [number for number in range(55) if fixed_light_map(number)]
        self.assertEqual(always, [1, 2])

        data = exe_bytes()
        for number in always:
            entry = struct.unpack_from("<I", data, va_to_foff(0x4617B0) + number * 4)[0]
            levels = [struct.unpack("<b", bytes([(entry >> shift) & 0xFF]))[0]
                      for shift in (0, 8, 16)]
            # младшие три байта записи — готовые уровни канала (VA 0x429605)
            self.assertEqual(levels, [NIGHT_LEVEL_BLUE, NIGHT_LEVEL_GREEN,
                                      NIGHT_LEVEL_RED])

    def test_light_masks_fill_the_tile_and_stay_in_range(self) -> None:
        masks = read_light_masks()
        self.assertEqual(len(masks), 19)
        for index, mask in enumerate(masks):
            self.assertEqual(len(mask), LIGHT_MASK_SIZE, f"маска {index}")
            self.assertLessEqual(max(mask), 0x1F, f"маска {index}")


@needs_game
class LightPassTest(unittest.TestCase):
    """Закон прохода VA 0x43FD70 на настоящих тайлах карты 19."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.graph = GraphRes.from_game()
        cls.masks = read_light_masks()

    def cases(self):
        # пары «тайл + маска», реально встречающиеся в Чёрном Бору
        return ((44, 9, 5), (45, None, 0), (7, 20, 1), (44, None, 8))

    def test_glow_restores_the_engine_pixel_exactly(self) -> None:
        for lower, upper, index in self.cases():
            mask = self.masks[index]
            lit = self.graph.illuminate_cell(lower, upper, mask)
            plain = self.graph.illuminate_cell(lower, upper, bytes(len(mask)))
            delta = self.graph.light_delta_cell(lower, upper, mask)
            with self.subTest(tile=(lower, upper), mask=index):
                for i, pixel in enumerate(lit.pixels):
                    if not pixel[3]:
                        continue
                    for channel in (0, 1):
                        self.assertEqual(
                            min(255, plain.pixels[i][channel] + delta.pixels[i][channel]),
                            pixel[channel])

    def test_glow_is_zero_without_mask_and_never_touches_blue(self) -> None:
        for lower, upper, index in self.cases():
            mask = self.masks[index]
            delta = self.graph.light_delta_cell(lower, upper, mask)
            width = delta.width
            with self.subTest(tile=(lower, upper), mask=index):
                for y in range(delta.height):
                    for x in range(width):
                        pixel = delta.pixels[y * width + x]
                        self.assertEqual(pixel[2], 0, "маска не трогает синий")
                        if not mask[y * 0x72 + x]:
                            self.assertEqual(pixel[:3], (0, 0, 0),
                                             "при нулевой маске прибавки нет")


@needs_game
class BuildingPaletteTest(unittest.TestCase):
    """Бит 0x04 байта hdr+0xFE: кадр main постройки не темнеет никогда."""

    def test_flag_belongs_to_buildings_with_walls_only(self) -> None:
        objects = ObjectsRes.from_game()
        static_with_walls = plain_with_walls = static_without_walls = 0
        for number in range(1, 55):
            try:
                kn2 = KN2Map.from_game(number)
            except OSError:
                continue
            for record in T_OBJECTS.unpack(kn2.data)["records"]:
                sprite = record.get("sprite")
                if sprite is None or not 0 <= sprite < 0xFFFF:
                    continue
                header = objects.simple_header(sprite + 30)
                if header is None:
                    continue
                static = bool(header["group"] & 0x04)
                if header["walls"] != -1:
                    static_with_walls += static
                    plain_with_walls += not static
                else:
                    static_without_walls += static
        self.assertEqual(static_without_walls, 0,
                         "исходную палитру получает только постройка")
        self.assertGreater(static_with_walls, plain_with_walls,
                           "большинство построек рисуется дневной палитрой")

    def test_exporter_publishes_the_flag(self) -> None:
        # Развилка VA 0x425AED читает тот же байт, что и сборщик пака.
        objects = ObjectsRes.from_game()
        kn2 = KN2Map.from_game(19)
        with_walls = []
        for record in T_OBJECTS.unpack(kn2.data)["records"]:
            sprite = record.get("sprite")
            if sprite is None or not 0 <= sprite < 0xFFFF:
                continue
            header = objects.simple_header(sprite + 30)
            if header is not None and header["walls"] != -1:
                with_walls.append(header["group"])
        self.assertTrue(with_walls, "на карте 19 есть постройки со стенами")
        for group in with_walls:
            self.assertTrue(group & 0x04)


if __name__ == "__main__":
    unittest.main()
