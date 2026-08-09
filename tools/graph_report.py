# -*- coding: utf-8 -*-
"""
Граф переходов между локациями.

    python tools\\graph_report.py            # весь граф
    python tools\\graph_report.py 19         # переходы конкретной локации
    python tools\\graph_report.py --dot      # вывод в формате Graphviz
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from konung2.gamefile import GameWorld, EXIT_LEAVE, EXIT_SPECIAL
from konung2.names import LOCATIONS, VILLAGES

w = GameWorld.from_game(0)
exits = w.exits()
args = [a for a in sys.argv[1:] if not a.startswith('--')]
only = int(args[0]) if args else None

links, leaves, unbound = {}, {}, []
for e in exits:
    src, dst = e.get('from_map'), e.get('to_map')
    if src == 127:
        unbound.append(e)
    elif dst == EXIT_LEAVE:
        leaves.setdefault(src, []).append(e)
    elif dst == EXIT_SPECIAL:
        leaves.setdefault(src, []).append(e)
    elif dst and dst > 0:
        links.setdefault(src, []).append(e)

if '--dot' in sys.argv:
    print('graph world {')
    print('  node [shape=box];')
    done = set()
    for s, es in links.items():
        for e in es:
            d = e['to_map']
            k = tuple(sorted((s, d)))
            if k in done:
                continue
            done.add(k)
            print(f'  "{LOCATIONS.get(s,s)}" -- "{LOCATIONS.get(d,d)}";')
    print('}')
    sys.exit()


def show(m):
    name = LOCATIONS.get(m, '?')
    mark = ' [ДЕРЕВНЯ]' if m in VILLAGES else ''
    print(f"\n{m:3d} {name}{mark}")
    for e in links.get(m, []):
        d = e['to_map']
        print(f"     -> {d:3d} {LOCATIONS.get(d,'?'):30s} "
              f"вход (строка {e['entry_row']}, столбец {e['entry_col']}), "
              f"зона строки {e['row1']}..{e['row2']}, столбцы {e['col1']}..{e['col2']}")
    n = len(leaves.get(m, []))
    if n:
        print(f"     -- краевых зон ухода с локации: {n}")


if only is not None:
    show(only)
else:
    print(f"переходов всего: {len(exits)}; связей между картами: "
          f"{sum(len(v) for v in links.values())}; "
          f"краевых зон ухода: {sum(len(v) for v in leaves.values())}; "
          f"без привязки к карте (127): {len(unbound)}")
    for m in sorted(set(links) | set(leaves)):
        show(m)
