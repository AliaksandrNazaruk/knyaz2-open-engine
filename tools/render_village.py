# -*- coding: utf-8 -*-
"""
Отрисовать локацию из файлов игры — без самой игры.

    python tools\\render_village.py 19          # Черный Бор
    python tools\\render_village.py 19 --pal 56

Сначала кладётся земля дневным проходом: два тайла на клетку. Идентификаторы
масок света слоя 2 считаются отдельно, но без runtime-состояния не запекаются.
Затем постройки идут по глубине, чтобы дальние оказались позади ближних. Слот
спрайта постройки — поле ``sprite`` записи объекта плюс 30, палитра — поле
``kind`` того же объекта либо палитра слота.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image                                        # noqa: E402

from konung2.graph import (GraphRes, TILE_STEP_X, TILE_STEP_Y,  # noqa: E402
                           cell_position, ground_cells)
from konung2.kn2 import KN2Map                               # noqa: E402
from konung2.names import LOCATIONS                          # noqa: E402
from konung2.paths import ROOT                               # noqa: E402
from konung2.res import ObjectsRes, read_palettes            # noqa: E402

EMPTY_KIND = 0xFFFF


def render(map_number: int, pal_index: int = 0, scale: int = 2) -> str:
    kn2 = KN2Map.from_game(map_number)
    objects = [o for o in kn2.objects() if o.get('kind', EMPTY_KIND) != EMPTY_KIND]
    res = ObjectsRes.from_game()
    palettes = read_palettes()
    palette = palettes[pal_index]

    placed = []
    for obj in objects:
        slot = ObjectsRes.slot_of(obj)
        if not 0 <= slot < 1000 or res.entries[slot] is None:
            continue
        if slot >= 30:
            # палитра объекта: своя из записи карты, иначе из заголовка слота
            index = obj['kind'] // 512 or res.simple_palette(slot)
            own = palettes[index] if index and index < len(palettes) else palette
            sprite, dx, dy = res.decode_building(
                slot, own, state=obj.get('state', 0),
                show_roof=obj['slot'] < 30)                    # VA 0x425AA8
        else:
            sprite = res.decode_frame(slot, 0, palette)       # анимированные объекты
            anchor = res.frame_anchor(slot, 0) or (0, 0, 0, 0)
            dx, dy = anchor[2], anchor[3]
        if sprite is None:
            continue
        x = obj['pixel_x'] + dx
        y = obj['pixel_y'] + dy
        # движок сортирует по низу спрайта: y + height (VA 0x426B5C)
        placed.append((y + sprite.height, x, y, sprite))

    if not placed:
        raise SystemExit(f'на карте {map_number} не нашлось объектов со спрайтами')

    # земля: два наложенных тайла на клетку, ромбы 116x32 со сдвигом рядов
    graph = GraphRes.from_game()
    cells = ground_cells(kn2)
    tiles = {}
    for _, _, lower, upper, light in cells:
        for index in (lower, upper):
            if index is not None and index not in tiles:
                tiles[index] = graph.decode_tile(index)

    left = min([x for _, x, _, _ in placed] + [cell_position(*c[:2])[0] for c in cells])
    top = min([y for _, _, y, _ in placed] + [cell_position(*c[:2])[1] for c in cells])
    right = max([x + s.width for _, x, _, s in placed] +
                [cell_position(*c[:2])[0] + TILE_STEP_X for c in cells])
    bottom = max([y + s.height for _, _, y, s in placed] +
                 [cell_position(*c[:2])[1] + TILE_STEP_Y for c in cells])
    canvas = Image.new('RGBA', (right - left, bottom - top), (22, 24, 30, 255))

    drawn = lit = 0
    for row, col, lower, upper, light in sorted(cells):
        x, y = cell_position(row, col)
        if light is not None:
            lit += 1
        for index in (lower, upper):
            sprite = tiles.get(index) if index is not None else None
            if sprite is not None:
                canvas.alpha_composite(sprite.to_image(), (x - left, y - top))
                drawn += 1

    placed.sort(key=lambda t: t[0])          # дальние объекты рисуются первыми
    for _, x, y, sprite in placed:
        canvas.alpha_composite(sprite.to_image(), (x - left, y - top))

    if scale > 1:
        canvas = canvas.resize((canvas.width // scale, canvas.height // scale),
                               Image.LANCZOS)
    out = os.path.join(ROOT, 'gfx', f'village{map_number}_pal{pal_index}.png')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    canvas.save(out)
    print(f'карта {map_number} «{LOCATIONS.get(map_number, "?")}»: '
          f'объектов {len(placed)} из {len(objects)}, '
          f'тайлов земли {drawn} в {len(cells)} клетках ({lit} с масками света), '
          f'холст {canvas.width}x{canvas.height} -> {out}')
    return out


if __name__ == '__main__':
    number = int(sys.argv[1]) if len(sys.argv) > 1 else 19
    pal = 0
    if '--pal' in sys.argv:
        pal = int(sys.argv[sys.argv.index('--pal') + 1])
    render(number, pal)


