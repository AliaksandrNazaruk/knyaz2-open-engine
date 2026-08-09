# -*- coding: utf-8 -*-
"""Тест round-trip для KN2: распаковать и собрать все карты, сверить байты."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from konung2.kn2 import KN2Map
from konung2.names import MAP_NUMBERS
from konung2.paths import game_file

ok = bad = 0
tmp = tempfile.mkdtemp(prefix='kn2rt_')
for n in MAP_NUMBERS:
    p = game_file(f'{n}.KN2')
    if not os.path.exists(p):
        continue
    orig = open(p, 'rb').read()
    m = KN2Map(n, orig)
    d = os.path.join(tmp, str(n))
    m.unpack(d)
    rebuilt = KN2Map.pack(d).data
    if bytes(rebuilt) == orig:
        ok += 1
    else:
        bad += 1
        diff = [i for i in range(len(orig)) if orig[i] != rebuilt[i]]
        print(f"  РАСХОЖДЕНИЕ карта {n}: {len(diff)} байт, первые {diff[:8]}")
print(f"KN2 round-trip: OK {ok}, ошибок {bad}")
sys.exit(1 if bad else 0)
