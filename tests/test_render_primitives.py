# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest

from konung2.graph import LIGHT_MASK_SIZE, GraphRes, composite_sprites
from konung2.res import ObjectsRes, Sprite


class GroundCompositionTest(unittest.TestCase):
    def test_upper_sprite_overlays_only_opaque_pixels(self) -> None:
        lower = Sprite(2, 2, [
            (10, 20, 30, 255), (40, 50, 60, 255),
            (70, 80, 90, 255), (100, 110, 120, 255),
        ])
        upper = Sprite(2, 2, [
            (0, 0, 0, 0), (200, 201, 202, 255),
            (0, 0, 0, 0), (0, 0, 0, 0),
        ])

        result = composite_sprites(lower, upper)

        self.assertIsNotNone(result)
        self.assertEqual(result.pixels, [
            (10, 20, 30, 255), (200, 201, 202, 255),
            (70, 80, 90, 255), (100, 110, 120, 255),
        ])

    def test_empty_composition_has_no_sprite(self) -> None:
        self.assertIsNone(composite_sprites(None, None))

    @staticmethod
    def _two_tile_graph() -> GraphRes:
        graph = object.__new__(GraphRes)
        graph._tile_indices = lambda index: (
            ([0, 0], 0, 2, 1) if index == 0 else ([None, 0], 1, 2, 1)
        )
        graph.raw_palette = lambda index: ([0x001F] if index == 0 else [0x7C00])
        return graph

    def test_light_mask_modifies_composite_instead_of_blending_tiles(self) -> None:
        graph = self._two_tile_graph()
        mask = bytearray(LIGHT_MASK_SIZE)
        mask[0] = 31

        lit = graph.illuminate_cell(0, 1, mask)
        plain = graph.illuminate_cell(0, 1, bytearray(LIGHT_MASK_SIZE))

        # верхний тайл ЗАМЕЩАЕТ нижний, маска в этом не участвует
        self.assertEqual(lit.pixels[1], plain.pixels[1])
        self.assertEqual(lit.pixels[1][2], 0)
        # синий канал маска не трогает (VA 0x43FE9D: таблица одна и та же)
        self.assertEqual(lit.pixels[0][2], plain.pixels[0][2])
        # красный и зелёный светлеют — таблица уровня «уровень + маска»
        self.assertGreater(lit.pixels[0][0], plain.pixels[0][0])
        self.assertGreater(lit.pixels[0][1], plain.pixels[0][1])

    def test_light_delta_restores_engine_pixel_and_is_zero_without_mask(self) -> None:
        graph = self._two_tile_graph()
        mask = bytearray(LIGHT_MASK_SIZE)
        mask[0] = 31

        lit = graph.illuminate_cell(0, 1, mask)
        plain = graph.illuminate_cell(0, 1, bytearray(LIGHT_MASK_SIZE))
        delta = graph.light_delta_cell(0, 1, mask)

        # где маски нет, прибавки нет — отсюда у ауры не бывает края
        self.assertEqual(delta.pixels[1], (0, 0, 0, 0))
        # синий не прибавляется никогда
        self.assertEqual(delta.pixels[0][2], 0)
        # «обычная клетка + прибавка» даёт ровно тот пиксель, что и движок
        self.assertEqual(plain.pixels[0][0] + delta.pixels[0][0], lit.pixels[0][0])
        self.assertEqual(plain.pixels[0][1] + delta.pixels[0][1], lit.pixels[0][1])

    def test_animated_underlay_uses_original_wave_and_row_scroll(self) -> None:
        source = Sprite(256, 256, [
            (x, y, (x + y) & 0xFF, 255)
            for y in range(256)
            for x in range(256)
        ])
        graph = object.__new__(GraphRes)
        graph.decode_tile = lambda index: source

        fixed = graph.animate_underlay(
            160, wave_phase=1, scroll_phase=1, horizontal_scroll=False)
        scrolled = graph.animate_underlay(
            160, wave_phase=1, scroll_phase=1, horizontal_scroll=True)

        # High words of the executable's sine table are 8 at entry 1 and
        # 15 at entry 32.  VA 0x43F4D9 then rotates every row right by one.
        self.assertEqual(fixed.pixels[0], (8, 8, 16, 255))
        self.assertEqual(fixed.pixels[31 * 256 + 31], (46, 46, 92, 255))
        self.assertEqual(scrolled.pixels[0], (7, 7, 14, 255))


class StaticObjectCompositionTest(unittest.TestCase):
    def test_original_layers_share_top_left_anchor_and_order(self) -> None:
        transparent = (0, 0, 0, 0)
        red = (200, 10, 10, 255)
        blue = (10, 10, 200, 255)
        green = (10, 200, 10, 255)
        main = Sprite(2, 2, [red] * 4)
        walls = Sprite(2, 3, [blue, transparent] + [transparent] * 4)
        roof = Sprite(2, 1, [transparent, green])
        resource = object.__new__(ObjectsRes)
        resource.decode_building_layers = lambda *args, **kwargs: {
            "main": (main, -3, -4),
            "walls": (walls, -3, -4),
            "roof": (roof, -3, -4),
        }

        open_sprite, dx, dy = resource.decode_building(30, show_roof=False)
        closed_sprite, _, _ = resource.decode_building(30, show_roof=True)

        self.assertEqual((dx, dy), (-3, -4))
        self.assertEqual((open_sprite.width, open_sprite.height), (2, 3))
        self.assertEqual(open_sprite.pixels[:4], [blue, red, red, red])
        self.assertEqual(open_sprite.pixels[4:], [transparent, transparent])
        self.assertEqual(closed_sprite.pixels[:2], [blue, green])


if __name__ == "__main__":
    unittest.main()
