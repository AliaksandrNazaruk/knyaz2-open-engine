# -*- coding: utf-8 -*-
"""
Проверка геометрии сетки в игре.

    python tools\\gridprobe.py 19

Отряд игрока ставится компактно рядом с жителями (как в testbuild_start_at),
а нескольких жителей переносим в клетки, которые по формуле соответствуют
точкам конкретных изб. Если формула верна, в игре эти жители окажутся
вплотную к своим избам.

Формула (таблица соседей 0x49CF68, VA 0x441344)::

    x = col * 58 + (row & 1) * 29
    y = row * 16
"""
from __future__ import annotations

import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from konung2.gamefile import GameWorld, T_PARTIES, T_UNITS   # noqa: E402
from konung2.grid import CELL_H, CELL_W                      # noqa: E402
from konung2.kn2 import KN2Map                               # noqa: E402
from konung2.names import LOCATIONS                          # noqa: E402
from konung2.paths import BUILD_DIR                          # noqa: E402
from konung2.res import ObjectsRes                           # noqa: E402

RIG = os.path.join(os.path.expanduser('~'), 'Documents', 'Knyaz2Test')
ODD_SHIFT = CELL_W // 2


def cell_of(pixel_x, pixel_y):
    row = round(pixel_y / CELL_H)
    col = round((pixel_x - (row & 1) * ODD_SHIFT) / CELL_W)
    return row, col


def pixels_of(row, col):
    return col * CELL_W + (row & 1) * ODD_SHIFT, row * CELL_H


def houses(map_number):
    """Избы карты: слот, точка объекта, расчётная клетка."""
    kn2 = KN2Map.from_game(map_number)
    res = ObjectsRes.from_game()
    out = []
    for obj in kn2.objects():
        if obj.get('kind', 0xFFFF) == 0xFFFF:
            continue
        slot = ObjectsRes.slot_of(obj)
        if not 0 <= slot < 1000 or res.entries[slot] is None or slot < 30:
            continue
        header = res.simple_header(slot)
        if not header or header['roof'] <= 0:
            continue
        row, col = cell_of(obj['pixel_x'], obj['pixel_y'])
        if 0 <= row < 250 and 0 <= col < 158:
            out.append({'slot': slot, 'px': obj['pixel_x'], 'py': obj['pixel_y'],
                        'row': row, 'col': col})
    return out


def main(map_number=19, probes=3):
    spots = houses(map_number)
    if not spots:
        sys.exit(f'на карте {map_number} не нашлось изб')
    spots.sort(key=lambda s: (s['row'], s['col']))
    step = max(1, len(spots) // probes)
    chosen = spots[::step][:probes]

    for index in range(6):
        src = os.path.join(BUILD_DIR, f'GAME.{index}')
        if not os.path.exists(src):
            continue
        with open(src, 'rb') as f:
            world = GameWorld(index, f.read())
        units = {r['slot']: r for r in T_UNITS.unpack(world.data)['records']}

        # жители карты, которых можно переставить
        locals_ = []
        for party in world.parties_on_map(map_number):
            for u in world.party_units(party):
                rec = units.get(u)
                if rec and (rec.get('x') or rec.get('y')):
                    locals_.append(u)
        if len(locals_) < len(chosen) + 1:
            print(f'GAME.{index}: жителей мало ({len(locals_)}) — пропуск')
            continue

        # отряд игрока — рядом с первым жителем, компактно
        anchor = units[locals_[0]]
        row, col = max(0, anchor['y'] - 3), anchor['x']
        off = T_PARTIES.offset
        party = bytearray(world.data[off:off + T_PARTIES.size])
        struct.pack_into('<H', party, 0x08, map_number)
        struct.pack_into('<H', party, 0x0C, row)
        party[0x14] = min(255, col)
        base = struct.unpack_from('<H', party, 0)[0]
        count = max(1, party[0x1C])
        world.data[off:off + T_PARTIES.size] = party
        for k in range(count):
            raw = bytearray(world.unit_raw(base + k))
            raw[0x12] = min(255, row)
            raw[0x14] = min(159, col + k)
            world.set_unit_raw(base + k, bytes(raw))

        # подопытные жители — в расчётные клетки изб
        for k, spot in enumerate(chosen):
            u = locals_[k + 1]
            raw = bytearray(world.unit_raw(u))
            raw[0x12] = min(255, spot['row'])
            raw[0x14] = min(159, spot['col'])
            world.set_unit_raw(u, bytes(raw))
            if index == 0:
                bx, by = pixels_of(spot['row'], spot['col'])
                print(f"  житель {u} -> клетка ({spot['row']}, {spot['col']}) "
                      f"= изба слот {spot['slot']} в ({spot['px']}, {spot['py']}); "
                      f"обратный счёт ({bx}, {by})")
        world.save(os.path.join(RIG, f'GAME.{index}'))

    print(f"\nотряд на карте {map_number} «{LOCATIONS.get(map_number, '?')}» "
          f"в клетке ({row}, {col}); записано в {RIG}")


if __name__ == '__main__':
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 19)
