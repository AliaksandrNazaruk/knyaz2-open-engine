# -*- coding: utf-8 -*-
"""Человекочитаемый отчёт по стартовому миру: кто и где стоит.

    python tools\\world_report.py        # GAME.0
    python tools\\world_report.py 3 19   # мир героя 3, только карта 19
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from konung2.gamefile import GameWorld
from konung2.names import LOCATIONS, VILLAGES

idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0
only = int(sys.argv[2]) if len(sys.argv) > 2 else None

w = GameWorld.from_game(idx)
parties = w.parties()
units = {r['slot']: r for r in __import__('konung2.gamefile', fromlist=['T_UNITS'])
         .T_UNITS.unpack(w.data)['records']}

print(f"=== Мир GAME.{idx} ===")
print(f"отрядов: {len(parties)},  занятых юнитов: {len(units)} из 2000")
print(f"свободных слотов юнитов: {len(w.free_unit_slots())}, "
      f"свободных слотов отрядов: {200 - len(parties)}\n")

by_map = {}
for p in parties:
    by_map.setdefault(p.get('map'), []).append(p)

for m in sorted(by_map, key=lambda v: (v is None, v)):
    if only is not None and m != only:
        continue
    name = LOCATIONS.get(m, '') if m is not None and m < 55 else '(глобальный/в пути)'
    mark = ' [ДЕРЕВНЯ]' if m in VILLAGES else ''
    total = sum(p.get('count', 0) for p in by_map[m])
    print(f"карта {m:<4} {name:<32}{mark}  отрядов {len(by_map[m]):2d}, юнитов {total}")
    if only is not None:
        for p in by_map[m]:
            idxs = w.party_units(p)
            print(f"   отряд #{p['slot']:3d} база={p.get('base_unit')} кол-во={p.get('count')} "
                  f"поз=({p.get('x')},{p.get('y')})")
            for u in idxs:
                r = units.get(u)
                if r:
                    print(f"      юнит {u:4d} клетка=({r.get('x')},{r.get('y')}) "
                          f"тип={r.get('kind')} ур.={r.get('level')} hp={r.get('hp')} "
                          f"имя_id={r.get('name_id')}")
