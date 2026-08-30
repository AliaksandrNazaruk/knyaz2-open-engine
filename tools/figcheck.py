"""Численная сверка сгенерированных экранов с эталонами — без глаз.

Каждая проверка: страница рендерится headless-хромом, сравнивается с
эталонным PNG (родной экспорт Figma или рендер их REST API), и наружу
выходит ТЕКСТ: средняя дельта и прямоугольники горячих пятен в макетных
координатах. Смотреть картинки нужно только там, где числа закричали.

Эталоны лежат в figrefs/<имя>.png (1x или 2x — приводятся к 1920x1080).

ПРИМЕРЫ
    python tools/figcheck.py loadgame
    python tools/figcheck.py --all
    python tools/figcheck.py loadgame --keep   # оставить снимок для глаз
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
REFS = ROOT / 'figrefs'
CHROME = Path(r'C:\Program Files\Google\Chrome\Application\chrome.exe')
BASE = 'http://127.0.0.1:8765/gen'
#: имя экрана -> страница предпросмотра
SCREENS = json.loads((ROOT / 'knyaz2/web/static/gen/screens.json').read_text('utf-8')) \
    if (ROOT / 'knyaz2/web/static/gen/screens.json').exists() else {}

#: пятно считается горячим с этой средней дельты по блоку 32x32
HOT = 25.0
#: экран считается зелёным до этой средней дельты по кадру
PASS = 8.0


def shoot(url: str, out: Path, tries: int = 3) -> None:
    """Снимок страницы; серверные осечки картинок лечатся повтором."""
    last = None
    for attempt in range(tries):
        subprocess.run([str(CHROME), '--headless', '--disable-gpu',
                        f'--screenshot={out}', '--window-size=1920,1080',
                        '--hide-scrollbars', '--virtual-time-budget=15000',
                        url], capture_output=True)
        im = np.asarray(Image.open(out).convert('L'), float)
        # пустых чёрных дыр больше 1/3 кадра быть не должно
        dark = (im < 8).mean()
        if dark < 0.34:
            return
        last = dark
    print(f'  ! после {tries} попыток кадр всё ещё на {last:.0%} чёрный')


def clusters(diff: np.ndarray, block: int = 32) -> list[tuple[int, int, int, int, float]]:
    """Горячие блоки, слитые в прямоугольники (грубая склейка соседей)."""
    h, w = diff.shape
    gh, gw = h // block, w // block
    grid = diff[:gh * block, :gw * block].reshape(gh, block, gw, block).mean(axis=(1, 3))
    hot = grid > HOT
    out = []
    seen = np.zeros_like(hot)
    for y in range(gh):
        for x in range(gw):
            if not hot[y, x] or seen[y, x]:
                continue
            x0 = x1 = x
            y0 = y1 = y
            frontier = [(y, x)]
            seen[y, x] = True
            while frontier:
                cy, cx = frontier.pop()
                x0, x1 = min(x0, cx), max(x1, cx)
                y0, y1 = min(y0, cy), max(y1, cy)
                for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < gh and 0 <= nx < gw and hot[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        frontier.append((ny, nx))
            zone = diff[y0 * block:(y1 + 1) * block, x0 * block:(x1 + 1) * block]
            out.append((x0 * block, y0 * block,
                        (x1 + 1) * block, (y1 + 1) * block, float(zone.mean())))
    out.sort(key=lambda z: -z[4])
    return out


def check(name: str, keep: bool) -> bool:
    ref_path = REFS / f'{name}.png'
    if not ref_path.exists():
        print(f'{name}: НЕТ ЭТАЛОНА ({ref_path})')
        return False
    page = SCREENS.get(name, f'{BASE}/{name}_view.html' if name != 'loadgame'
                       else f'{BASE}/index.html')
    shot = Path(tempfile.gettempdir()) / f'figcheck_{name}.png'
    shoot(page, shot)
    ref = Image.open(ref_path).convert('RGB')
    if ref.size != (1920, 1080):
        ref = ref.resize((1920, 1080), Image.LANCZOS)
    mine = Image.open(shot).convert('RGB')
    diff = np.abs(np.asarray(ref, float) - np.asarray(mine, float)).mean(axis=2)
    mean = float(diff.mean())
    ok = mean <= PASS
    print(f'{name}: дельта {mean:.1f} — {"OK" if ok else "СМОТРЕТЬ"}')
    if not ok or mean > PASS * 0.6:
        for x0, y0, x1, y1, m in clusters(diff)[:6]:
            print(f'    пятно ({x0},{y0})..({x1},{y1}) дельта {m:.1f}')
    if keep:
        print(f'    снимок: {shot}')
    else:
        shot.unlink(missing_ok=True)
    return ok


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('names', nargs='*', help='имена экранов (пусто + --all = все)')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--keep', action='store_true', help='не удалять снимок')
    args = ap.parse_args()
    names = args.names
    if args.all or not names:
        names = sorted(p.stem for p in REFS.glob('*.png'))
    if not names:
        raise SystemExit('нет эталонов в figrefs/')
    bad = [n for n in names if not check(n, args.keep)]
    if bad:
        raise SystemExit(f'красных: {len(bad)} ({", ".join(bad)})')


if __name__ == '__main__':
    main()
