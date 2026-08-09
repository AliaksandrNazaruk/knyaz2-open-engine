# -*- coding: utf-8 -*-
"""Round-trip всех форматов: распаковать → собрать → сверить байты."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from konung2.kn2 import KN2Map
from konung2.gamefile import GameWorld
from konung2.quests import QuestsFile
from konung2.names import MAP_NUMBERS
from konung2.paths import game_file

tmp = tempfile.mkdtemp(prefix='k2rt_')
fails = 0


def check(label, orig, rebuilt):
    global fails
    if bytes(rebuilt) == bytes(orig):
        print(f"  OK   {label}")
        return True
    diff = [i for i in range(min(len(orig), len(rebuilt))) if orig[i] != rebuilt[i]]
    print(f"  FAIL {label}: len {len(orig)}->{len(rebuilt)}, разных байт {len(diff)}, "
          f"первые {[hex(d) for d in diff[:6]]}")
    fails += 1
    return False


print("== карты .KN2 ==")
ok = 0
for n in MAP_NUMBERS:
    p = game_file(f'{n}.KN2')
    if not os.path.exists(p):
        continue
    orig = open(p, 'rb').read()
    d = os.path.join(tmp, f'map{n}')
    KN2Map(n, orig).unpack(d)
    if bytes(KN2Map.pack(d).data) == orig:
        ok += 1
    else:
        check(f'{n}.KN2', orig, KN2Map.pack(d).data)
print(f"  OK   {ok} карт из {len(MAP_NUMBERS)}")

print("== миры GAME.0-5 ==")
for i in range(6):
    orig = open(game_file(f'GAME.{i}'), 'rb').read()
    j = os.path.join(tmp, f'game{i}.json')
    GameWorld(i, orig).unpack(j)
    check(f'GAME.{i}', orig, GameWorld.pack(j).data)

print("== QUESTS.RES ==")
orig = open(game_file('QUESTS.RES'), 'rb').read()
d = os.path.join(tmp, 'texts')
QuestsFile(orig).unpack(d)
check('QUESTS.RES', orig, QuestsFile.pack(d).to_bytes())

print(f"\nИтог: {'ВСЁ СОБИРАЕТСЯ БАЙТ-В-БАЙТ' if not fails else str(fails) + ' ошибок'}")
sys.exit(1 if fails else 0)
