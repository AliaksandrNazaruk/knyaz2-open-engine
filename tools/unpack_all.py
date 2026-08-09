# -*- coding: utf-8 -*-
"""
Распаковать игру в редактируемый проект:  python tools\\unpack_all.py

Читает файлы игры и раскладывает их в project/ как текст, JSON и PNG.
Ничего в папке игры не меняет.
"""
import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from konung2.kn2 import KN2Map
from konung2.gamefile import GameWorld
from konung2.quests import QuestsFile
from konung2.exetables import ExeTables
from konung2.names import MAP_NUMBERS, LOCATIONS, slug
from konung2.paths import GAME_DIR, PROJECT_DIR, game_file

t0 = time.time()
os.makedirs(PROJECT_DIR, exist_ok=True)
print(f"игра:   {GAME_DIR}")
print(f"проект: {PROJECT_DIR}\n")

print("== карты ==")
index = []
for n in MAP_NUMBERS:
    p = game_file(f'{n}.KN2')
    if not os.path.exists(p):
        continue
    m = KN2Map.from_game(n)
    d = os.path.join(PROJECT_DIR, 'maps', slug(n))
    m.unpack(d)
    index.append({'map': n, 'name': LOCATIONS.get(n, ''), 'dir': f'maps/{slug(n)}',
                  'used_cells': m.used_cells()})
    print(f"  {n:2d} {LOCATIONS.get(n,''):32s} -> maps/{slug(n)}")

print("\n== миры GAME.0-5 ==")
for i in range(6):
    if not os.path.exists(game_file(f'GAME.{i}')):
        continue
    out = os.path.join(PROJECT_DIR, 'world', f'game{i}.json')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    GameWorld.from_game(i).unpack(out)
    print(f"  GAME.{i} -> world/game{i}.json")

print("\n== тексты ==")
q = QuestsFile.from_game()
n = q.unpack(os.path.join(PROJECT_DIR, 'texts'))
print(f"  QUESTS.RES -> texts/quests.txt ({n} строк), quests_state.json, dialogs.bin")

print("\n== строковые таблицы exe ==")
e = ExeTables.from_game()
out = os.path.join(PROJECT_DIR, 'exe', 'strings.json')
os.makedirs(os.path.dirname(out), exist_ok=True)
doc = e.unpack(out, known={0x4D2D4: 'locations'})
print(f"  konung2.exe -> exe/strings.json ({len(doc['tables'])} таблиц, "
      f"{sum(t['count'] for t in doc['tables'])} строк)")
e.unpack_map_params(os.path.join(PROJECT_DIR, 'exe', 'map_params.json'))
print("  konung2.exe -> exe/map_params.json (44 записи параметров локаций)")

with open(os.path.join(PROJECT_DIR, 'index.json'), 'w', encoding='utf-8') as f:
    json.dump({'maps': index}, f, ensure_ascii=False, indent=1)

print(f"\nготово за {time.time()-t0:.1f} с")
