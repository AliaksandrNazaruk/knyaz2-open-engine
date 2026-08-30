"""Прогон генератора по всем экранам из каталога figrefs/screens.json.

Каждый кадр — отдельный вызов figgen; уже собранные пропускаются.
Итог: сколько собралось, что упало, и сводный отчёт по неразобранным
свойствам (чтобы чинить правила по частоте, а не наугад).

    python tools/figall.py                  # собрать всё, чего нет
    python tools/figall.py --force          # пересобрать
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'knyaz2/web/static/gen'
FIG = r'C:\Users\User\Downloads\Game UI Dark fantasy RPG (Community)3.fig'


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--fig', default=FIG)
    ap.add_argument('--force', action='store_true')
    args = ap.parse_args()

    plan = json.loads((ROOT / 'figrefs/screens.json').read_text('utf-8'))
    todo = [item for item in plan
            if args.force or not (OUT / f"{item['file']}.css").exists()]
    print(f'к сборке: {len(todo)} из {len(plan)}', flush=True)
    unknown: collections.Counter = collections.Counter()
    bad, start = [], time.time()
    for index, item in enumerate(todo, 1):
        done = subprocess.run(
            [sys.executable, str(ROOT / 'tools/figgen.py'), args.fig,
             '--node', item['id'], '--out', str(OUT),
             '--name', item['file'], '--report'],
            capture_output=True, text=True, encoding='utf-8', errors='replace')
        if done.returncode != 0:
            tail = (done.stderr or '').strip().splitlines()[-1:] or ['?']
            bad.append((item['file'], tail[0][:120]))
            print(f"[{index}/{len(todo)}] {item['file']}: ОШИБКА {tail[0][:80]}", flush=True)
            continue
        for line in (done.stdout or '').splitlines():
            hit = re.match(r'\s{3}(\S.*?)\s{2,}(\d+)$', line)
            if hit:
                unknown[hit.group(1)] += int(hit.group(2))
        print(f"[{index}/{len(todo)}] {item['file']}", flush=True)

    print(f'\nсобрано: {len(todo) - len(bad)}, ошибок: {len(bad)}, '
          f'за {time.time() - start:.0f}с')
    for name, err in bad[:10]:
        print('  ', name, '—', err)
    if unknown:
        print('\nНЕ РАЗЛОЖЕНО (по всем экранам, топ-15):')
        for key, count in unknown.most_common(15):
            print(f'   {key:38} {count}')


if __name__ == '__main__':
    main()
