# -*- coding: utf-8 -*-
"""
Собрать файлы игры из проекта:  python tools\\build_all.py [--verify]

Собирает в build/. Ничего не устанавливает — для установки см. install.py.
С ключом --verify дополнительно сверяет результат с оригиналами игры и
сообщает, какие файлы отличаются (то есть что именно изменит ваш мод).
"""
import os, sys, time, filecmp
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from konung2.kn2 import KN2Map
from konung2.gamefile import GameWorld
from konung2.quests import QuestsFile
from konung2.exetables import ExeTables
from konung2.names import MAP_NUMBERS, slug
from konung2.paths import PROJECT_DIR, BUILD_DIR, game_file

verify = '--verify' in sys.argv
t0 = time.time()
os.makedirs(BUILD_DIR, exist_ok=True)
changed, built = [], []


def emit(name, data):
    path = os.path.join(BUILD_DIR, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data)
    built.append(name)
    orig = game_file(name)
    if os.path.exists(orig):
        with open(orig, 'rb') as f:
            if f.read() != data:
                changed.append(name)
    else:
        changed.append(name + '  (НОВЫЙ ФАЙЛ)')


print("== карты ==")
mapdir = os.path.join(PROJECT_DIR, 'maps')
for d in sorted(os.listdir(mapdir)) if os.path.isdir(mapdir) else []:
    src = os.path.join(mapdir, d)
    if not os.path.exists(os.path.join(src, 'map.json')):
        continue
    m = KN2Map.pack(src)
    emit(f'{m.number}.KN2', bytes(m.data))

print("== миры ==")
wdir = os.path.join(PROJECT_DIR, 'world')
for i in range(6):
    p = os.path.join(wdir, f'game{i}.json')
    if os.path.exists(p):
        emit(f'GAME.{i}', bytes(GameWorld.pack(p).data))

print("== тексты ==")
td = os.path.join(PROJECT_DIR, 'texts')
if os.path.exists(os.path.join(td, 'quests.txt')):
    emit('QUESTS.RES', QuestsFile.pack(td).to_bytes())

print("== exe ==")
se = os.path.join(PROJECT_DIR, 'exe', 'strings.json')
sp = os.path.join(PROJECT_DIR, 'exe', 'map_params.json')
if os.path.exists(se) or os.path.exists(sp):
    e = ExeTables.from_game()
    n = e.apply(se) if os.path.exists(se) else 0
    m = e.apply_map_params(sp) if os.path.exists(sp) else 0
    if n or m:
        emit('konung2.exe', bytes(e.data))
    print(f"  изменённых строк: {n}, параметров локаций: {m}")

print(f"\nсобрано файлов: {len(built)}, за {time.time()-t0:.1f} с -> {BUILD_DIR}")
if changed:
    print(f"\nОТЛИЧАЮТСЯ ОТ ОРИГИНАЛА ({len(changed)}) — это и есть ваш мод:")
    for c in changed:
        print(f"  {c}")
else:
    print("\nОтличий от оригинала нет: проект собирается байт-в-байт.")
