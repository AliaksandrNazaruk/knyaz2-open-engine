"""Дорисовка узлов-заглушек: растр через мост вместо пустых дыр.

Компоненты из подключённой библиотеки Figma не выгружает в .fig — в файле
остаётся только заглушка символа (размер есть, содержимого нет). Именно
поэтому фоны экранов и логотипы приезжали пустыми div'ами. Генератор
складывает такие узлы в <экран>.blanks.json, а этот инструмент снимает
каждый прямо из открытого файла через мост DesignAgent и дописывает в CSS
правило с картинкой.

    python tools/figfill.py credits-credits
    python tools/figfill.py --all
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / 'knyaz2/web/static/gen'
MARK = '/* дорисовано figfill.py — растр заглушек внешней библиотеки */'


def shoot(node_id: str, target: Path, tries: int = 2) -> bool:
    for _ in range(tries):
        done = subprocess.run(
            [sys.executable, str(ROOT / 'tools/figbridge.py'), 'take_screenshot',
             f'nodeId={node_id}', 'scale=1', '--save', str(target),
             '--timeout', '90'],
            capture_output=True, text=True, encoding='utf-8', errors='replace')
        if '"saved"' in (done.stdout or '') and target.exists() \
                and target.stat().st_size > 2000:
            return True
    return False


def fill(name: str) -> tuple[int, int]:
    spec = GEN / f'{name}.blanks.json'
    css = GEN / f'{name}.css'
    if not spec.exists() or not css.exists():
        return 0, 0
    blanks = json.loads(spec.read_text('utf-8'))
    text = css.read_text('utf-8')
    if MARK in text:                       # прошлую дорисовку сносим целиком
        text = text.split(MARK)[0].rstrip() + '\n'
    lines, good = [], 0
    for item in blanks:
        if item.get('scene'):
            # фон, которого нет в выгрузке: берём извлечённую сцену
            lines.append(f".{item['class']} {{ background: "
                         f"url(\"assets/bg_cloud.png\") center / cover "
                         f"no-repeat; }}")
            good += 1
            continue
        rel = f"assets/blank_{item['node'].replace(':', '_')}.png"
        target = GEN / rel
        if target.exists() and target.stat().st_size > 2000:
            ok = True
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            ok = shoot(item['node'], target)
        if not ok:
            print(f"    ! не снялся {item['node']} ({item['name']})")
            continue
        lines.append(f".{item['class']} {{ background: url(\"{rel}\") "
                     f"center / cover no-repeat; }}")
        good += 1
    if lines:
        # Пишем атомарно: браузер, снимающий страницу ровно в этот момент,
        # иначе успевает прочитать полуготовый файл — так титры однажды
        # показали 48 вместо 5.2. Замена файла целиком неделима.
        spare = css.with_suffix('.css.tmp')
        spare.write_text(text + MARK + '\n' + '\n'.join(lines) + '\n', 'utf-8')
        spare.replace(css)
    return good, len(blanks)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('names', nargs='*')
    ap.add_argument('--all', action='store_true')
    args = ap.parse_args()
    names = args.names
    if args.all or not names:
        names = sorted(p.name[:-len('.blanks.json')]
                       for p in GEN.glob('*.blanks.json'))
    total_good = total_all = 0
    for name in names:
        good, count = fill(name)
        total_good += good
        total_all += count
        if count:
            print(f'{name}: {good}/{count}', flush=True)
    print(f'итого дорисовано: {total_good} из {total_all}')


if __name__ == '__main__':
    main()
