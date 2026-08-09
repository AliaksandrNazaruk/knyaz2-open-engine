# -*- coding: utf-8 -*-
"""
Тестовая сборка: посадить героя сразу на нужную карту.

    python tools\\testbuild_start_at.py 32

Берёт файлы из build\\, переставляет отряд игрока на указанную карту рядом
с местными жителями и кладёт результат в тестовое зеркало Knyaz2Test.
Проект и сам мод при этом не меняются — это только для проверки в игре.
"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from konung2.gamefile import GameWorld, T_PARTIES, T_UNITS
from konung2.paths import BUILD_DIR
from konung2.names import LOCATIONS

RIG = os.path.join(os.path.expanduser('~'), 'Documents', 'Knyaz2Test')
target = int(sys.argv[1]) if len(sys.argv) > 1 else 32

for i in range(6):
    src = os.path.join(BUILD_DIR, f'GAME.{i}')
    if not os.path.exists(src):
        continue
    with open(src, 'rb') as f:
        w = GameWorld(i, f.read())

    # куда ставить: рядом с первым жителем целевой карты
    spot = None
    units = {r['slot']: r for r in T_UNITS.unpack(w.data)['records']}
    for p in w.parties_on_map(target):
        for u in w.party_units(p):
            r = units.get(u)
            if r and r.get('x') and r.get('y'):
                spot = (r['y'], r['x'])       # (строка, столбец)
                break
        if spot:
            break
    if spot is None:
        print(f"GAME.{i}: на карте {target} нет жителей — пропуск")
        continue
    row, col = spot
    row = max(0, row - 3)

    # отряд игрока — запись 0
    off = T_PARTIES.offset
    party = bytearray(w.data[off:off + T_PARTIES.size])
    struct.pack_into('<H', party, 0x08, target)     # карта
    struct.pack_into('<H', party, 0x0C, row)        # строка (как пишет переход)
    party[0x14] = min(255, col)                     # столбец
    base = struct.unpack_from('<H', party, 0)[0]
    count = party[0x1C]
    w.data[off:off + T_PARTIES.size] = party

    # сам герой и спутники
    for k in range(max(1, count)):
        u = base + k
        raw = bytearray(w.unit_raw(u))
        raw[0x12] = min(255, row)
        raw[0x14] = min(159, col + k)
        w.set_unit_raw(u, bytes(raw))

    w.save(os.path.join(RIG, f'GAME.{i}'))
    print(f"GAME.{i}: герой (юниты {base}..{base+count-1}) -> карта {target} "
          f"«{LOCATIONS.get(target,'?')}», клетка (строка {row}, столбец {col})")

print(f"\nзаписано в {RIG}")
