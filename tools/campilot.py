# -*- coding: utf-8 -*-
"""Автопилот камеры в запущенной игре: навести экран на клетку или пиксель.

    python tools\\campilot.py 19 --cell 98 58        # клетка сетки
    python tools\\campilot.py 19 --px 3366 1562      # мировой пиксель
    python tools\\campilot.py 19 --cell 98 58 --shot изба217

Требует готового рендера gfx/village<N>_pal0.png (tools/render_village.py)
и запущенной игры на этой карте. Каждый шаг: кадр экрана матчится с рендером
(FFT-корреляция), вычисляется невязка, камера докручивается курсором у края;
скорость прокрутки оси уточняется по фактическому сдвигу. Сходится за 3-6
итераций, точность ~40 пикселей.

Особенности, добытые опытом:
- курсор к краю двигаем в ФИЗИЧЕСКИХ координатах экрана (GetSystemMetrics),
  игра может работать и в 1024x768, и в 1280x960 с DPI-масштабом;
- восстановление свёрнутого окна иногда сбрасывает камеру к отряду игрока —
  автопилоту это не мешает, а вот слепому счислению — фатально;
- жители поселений при старте новой игры расставляются движком по зданиям,
  их координаты в GAME.x бесполезны для стендов — цельтесь по объектам карты.
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np
from PIL import Image, ImageGrab

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from konung2.grid import CELL_H, CELL_W                      # noqa: E402
from konung2.paths import ROOT                               # noqa: E402
import playtest as pt                                        # noqa: E402

# видимая игровая область экрана 1024x768 (без панелей HUD)
VIEW = (150, 10, 1020, 630)
SCALE = 2                     # рендер сохранён 1:2
VEL = {'right': 640.0, 'left': 640.0, 'down': 470.0, 'up': 440.0}


def canvas_origin(map_number: int, pal_index: int = 0):
    """Мировой пиксель угла холста рендера — та же логика, что в render_village."""
    from konung2.graph import cell_position, ground_cells
    from konung2.kn2 import KN2Map
    from konung2.res import ObjectsRes, read_palettes

    kn2 = KN2Map.from_game(map_number)
    res = ObjectsRes.from_game()
    palettes = read_palettes()
    xs, ys = [], []
    for obj in kn2.objects():
        if obj.get('kind', 0xFFFF) == 0xFFFF:
            continue
        slot = ObjectsRes.slot_of(obj)
        if not 0 <= slot < 1000 or res.entries[slot] is None:
            continue
        if slot >= 30:
            index = obj['kind'] // 512 or res.simple_palette(slot)
            own = palettes[index] if index and index < len(palettes) else palettes[pal_index]
            sprite, dx, dy = res.decode_building(
                slot, own, state=obj.get('state', 0),
                show_roof=obj['slot'] < 30)
        else:
            sprite = res.decode_frame(slot, 0, palettes[pal_index])
            anchor = res.frame_anchor(slot, 0) or (0, 0, 0, 0)
            dx, dy = anchor[2], anchor[3]
        if sprite is None:
            continue
        xs.append(obj['pixel_x'] + dx)
        ys.append(obj['pixel_y'] + dy)
    cells = ground_cells(kn2)
    xs += [cell_position(*c[:2])[0] for c in cells]
    ys += [cell_position(*c[:2])[1] for c in cells]
    return min(xs), min(ys)


class Camera:
    def __init__(self, map_number: int):
        path = os.path.join(ROOT, 'gfx', f'village{map_number}_pal0.png')
        if not os.path.exists(path):
            sys.exit(f'нет {path} — сначала tools\\render_village.py {map_number}')
        self.map = np.asarray(Image.open(path).convert('L'), dtype=np.float64)
        self.left, self.top = canvas_origin(map_number)
        print(f'рендер {self.map.shape[1]}x{self.map.shape[0]}, '
              f'угол холста ({self.left}, {self.top})')

    def origin(self):
        """Мировой пиксель левого-верхнего угла экрана (матчинг кадра)."""
        img = ImageGrab.grab(all_screens=False).convert('L').crop(VIEW)
        img = img.resize((img.width // SCALE, img.height // SCALE), Image.LANCZOS)
        patch = np.asarray(img, dtype=np.float64)
        H, W = self.map.shape
        h, w = patch.shape
        a = self.map - self.map.mean()
        b = np.zeros_like(a)
        b[:h, :w] = patch - patch.mean()
        corr = np.fft.irfft2(np.fft.rfft2(a) * np.conj(np.fft.rfft2(b)), s=a.shape)
        corr[H - h + 1:, :] = -1e18
        corr[:, W - w + 1:] = -1e18
        my, mx = divmod(int(corr.argmax()), W)
        return mx * SCALE + self.left - VIEW[0], my * SCALE + self.top - VIEW[1]

    @staticmethod
    def _hold(direction: str, seconds: float):
        user32 = pt.user32
        w, h = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        edges = {'down': (w // 2, h - 1), 'up': (w // 2, 0),
                 'left': (0, h // 2), 'right': (w - 1, h // 2)}
        user32.SetCursorPos(*edges[direction])
        time.sleep(seconds)
        user32.SetCursorPos(w // 2, h // 2)
        time.sleep(0.35)

    def goto(self, wx: int, wy: int, tol: int = 40, iters: int = 10):
        """Привести мировой пиксель (wx, wy) в центр игровой области."""
        tx = wx - (VIEW[0] + VIEW[2]) // 2
        ty = wy - (VIEW[1] + VIEW[3]) // 2
        ox, oy = self.origin()
        print(f'старт origin=({ox}, {oy}), цель origin=({tx}, {ty})')
        for _ in range(iters):
            dx, dy = tx - ox, ty - oy
            if abs(dx) <= tol and abs(dy) <= tol:
                print(f'попадание: ({ox}, {oy}), ошибка ({dx}, {dy})')
                return ox, oy
            if abs(dx) >= abs(dy):
                d, need = ('right' if dx > 0 else 'left'), abs(dx)
            else:
                d, need = ('down' if dy > 0 else 'up'), abs(dy)
            t = max(0.12, min(2.5, need / VEL[d]))
            self._hold(d, t)
            nx, ny = self.origin()
            moved = abs((nx - ox) if d in ('left', 'right') else (ny - oy))
            if t > 0.15 and moved > 30:
                VEL[d] = max(150, min(1500, 0.5 * VEL[d] + 0.5 * moved / t))
            print(f'  {d} {t:.2f}s -> ({nx}, {ny}); v[{d}]={VEL[d]:.0f}')
            ox, oy = nx, ny
        print(f'не сошлось за {iters} итераций: ({ox}, {oy})')
        return ox, oy


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return
    map_number = int(args[0])
    if '--cell' in args:
        i = args.index('--cell')
        row, col = int(args[i + 1]), int(args[i + 2])
        wx = col * CELL_W + (row & 1) * (CELL_W // 2)
        wy = row * CELL_H
    elif '--px' in args:
        i = args.index('--px')
        wx, wy = int(args[i + 1]), int(args[i + 2])
    else:
        sys.exit('нужно --cell ROW COL или --px X Y')

    cam = Camera(map_number)
    if pt.focus_game() is None:
        sys.exit('окно игры не найдено')
    time.sleep(1.0)
    cam.goto(wx, wy)
    if '--shot' in args:
        pt.shot(args[args.index('--shot') + 1])


if __name__ == '__main__':
    main()
