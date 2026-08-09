# -*- coding: utf-8 -*-
"""Процедурная земля: материал считается по высоте, а не рисуется по цвету.

Приём тот же, что в современных играх, только запечённый: у материала есть
карта высот, грязь затекает в низкие места, затенение берётся из градиента
высоты, а крупный шум гуляет по площади, чтобы не читался повтор.

Считаем сразу в МИРОВЫХ пикселях: сосед продолжает рисунок соседа, поэтому
швов между клетками не существует в принципе. Земля в игре — плоскость в
изометрии 2:1, поэтому по вертикали рисунок сжимается вдвое: круглый камень
на земле на экране выглядит эллипсом.

    python tools/groundgen.py --preview            # кусок 1024x512 в PNG
    python tools/groundgen.py --preview --wear 0.7 # он же, протоптанный
"""
from __future__ import annotations

import argparse
import numpy as np

#: Изометрия земли: ромб клетки 114 x 64, значит по вертикали рисунок сжат
#: в 114/64 раза. Круглый камень на земле выглядит эллипсом.
ISO_SQUASH = 114.0 / 64.0
#: Направление света в игре — то же, что у теней объектов (маски LIGHTS.RES).
LIGHT_DIR = (-0.95, 0.32)
#: Ромб клетки в экранных пикселях: половины его диагоналей и есть оси земли.
TILE_HALF_W, TILE_HALF_H = 57.0, 32.0


def to_ground(x, y):
    """Экранные пиксели -> координаты НА ЗЕМЛЕ (изометрический базис).

    Земля в изометрии — плоскость под углом, поэтому узор материала обязан
    идти по её осям, а не по осям экрана. Оси земли — это половины диагоналей
    ромба клетки: (57, 32) и (57, -32). Без этого перехода кладка ложится
    параллельно нижнему краю кадра и читается наклейкой поверх сцены.
    """
    u = (x / TILE_HALF_W + y / TILE_HALF_H) * 0.5
    v = (x / TILE_HALF_W - y / TILE_HALF_H) * 0.5
    return u * TILE_HALF_W, v * TILE_HALF_W


def _hash2(ix: np.ndarray, iy: np.ndarray, seed: int) -> np.ndarray:
    """Детерминированный хеш целочисленной решётки -> [0, 1)."""
    h = (ix * np.int64(374761393) + iy * np.int64(668265263) + seed * np.int64(1442695040888963407))
    h = (h ^ (h >> np.int64(13))) * np.int64(1274126177)
    return ((h ^ (h >> np.int64(16))) & np.int64(0xFFFFFF)).astype(np.float64) / float(0xFFFFFF)


def value_noise(x: np.ndarray, y: np.ndarray, cell: float, seed: int) -> np.ndarray:
    """Гладкий шум по решётке с шагом ``cell``."""
    gx, gy = x / cell, y / cell
    ix, iy = np.floor(gx).astype(np.int64), np.floor(gy).astype(np.int64)
    fx, fy = gx - ix, gy - iy
    sx, sy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    n00 = _hash2(ix, iy, seed)
    n10 = _hash2(ix + 1, iy, seed)
    n01 = _hash2(ix, iy + 1, seed)
    n11 = _hash2(ix + 1, iy + 1, seed)
    return (n00 * (1 - sx) + n10 * sx) * (1 - sy) + (n01 * (1 - sx) + n11 * sx) * sy


def fbm(x: np.ndarray, y: np.ndarray, cell: float, seed: int, octaves: int = 4) -> np.ndarray:
    """Несколько октав шума: крупные пятна плюс мелкое зерно."""
    total = np.zeros_like(x, dtype=np.float64)
    amplitude, norm = 1.0, 0.0
    for i in range(octaves):
        total += amplitude * value_noise(x, y, cell / (2 ** i), seed + i * 101)
        norm += amplitude
        amplitude *= 0.5
    return total / norm


def cobble_height(x: np.ndarray, y: np.ndarray, stone: float, seed: int):
    """Камни: высота-купол, номер камня и его оттенок.

    Вороной со ВЗВЕШЕННЫМ расстоянием: у каждой ячейки свой вес, поэтому одни
    камни вырастают, другие ужимаются — без этого решётка читается как сетка,
    сколько центр ни джитти. Разность до двух ближайших центров даёт купол;
    ширина шва тоже гуляет, иначе раствор выглядит расчерченным по линейке.
    """
    gx, gy = x / stone, y / stone
    ix, iy = np.floor(gx).astype(np.int64), np.floor(gy).astype(np.int64)
    best = np.full(x.shape, 1e9)
    second = np.full(x.shape, 1e9)
    owner = np.zeros(x.shape, dtype=np.int64)
    tint = np.zeros(x.shape)
    joint = np.zeros(x.shape)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            cx, cy = ix + dx, iy + dy
            jx = _hash2(cx, cy, seed)
            jy = _hash2(cx, cy, seed + 7)
            weight = 0.62 + 0.76 * _hash2(cx, cy, seed + 13)   # размер камня
            # центр камня внутри своей ячейки, но не в самом центре
            px = (cx + 0.12 + 0.76 * jx) * stone
            py = (cy + 0.12 + 0.76 * jy) * stone
            d = np.hypot(x - px, y - py) / weight
            closer = d < best
            second = np.where(closer, best, np.minimum(second, d))
            owner = np.where(closer, cx * 73856093 + cy * 19349663, owner)
            tint = np.where(closer, _hash2(cx, cy, seed + 19), tint)
            joint = np.where(closer, 0.16 + 0.30 * _hash2(cx, cy, seed + 23), joint)
            best = np.where(closer, d, best)
    gap = np.clip((second - best) / (stone * joint), 0, 1)
    # купол: широкая плоская макушка, быстрый спад к шву
    height = np.clip(gap * 1.7, 0, 1) ** 0.5
    return height, owner, tint


#: Высота солнца над горизонтом для затенения земли. Направление в плане
#: задаёт LIGHT_DIR — то же, что у теней объектов.
LIGHT_ELEVATION = 0.62
#: Блик на камне: степень сужает пятно, сила задаёт яркость.
GLOSS_POWER, GLOSS = 22.0, 0.30


def self_shadow(height: np.ndarray, steps: int = 7, step: float = 1.6,
                relief: float = 7.0, softness: float = 0.55):
    """Собственные тени рельефа: камень затеняет соседа.

    Тот самый эффект, ради которого обычно зовут пиксельный шейдер, — только
    посчитанный один раз. Из каждой точки шагаем навстречу солнцу и смотрим,
    поднимается ли рельеф выше луча. Именно эти короткие тени и заставляют
    камни лежать НА земле, а не быть узором: ламберт и блик их не заменяют,
    потому что все макушки у брусчатки на одной высоте.

    Массив высот должен идти С ЗАПАСОМ по краям, иначе на границе клетки
    луч упрётся в пустоту и появится шов.
    """
    lx, ly = LIGHT_DIR
    length = np.hypot(lx, ly)
    lx, ly = lx / length, ly / length
    rise = LIGHT_ELEVATION / max(length, 1e-3)
    shadow = np.zeros_like(height)
    for i in range(1, steps + 1):
        distance = i * step
        dx, dy = int(round(-lx * distance)), int(round(-ly * distance))
        sample = np.roll(np.roll(height, dy, axis=0), dx, axis=1)
        above = (sample - height) * relief - distance * rise
        shadow = np.maximum(shadow, np.clip(above * softness, 0, 1))
    return 1.0 - shadow


def shade_from_height(height: np.ndarray, relief: np.ndarray | float = 1.0,
                      steep: float = 11.0, gloss: float = GLOSS):
    """Освещение по нормали, посчитанное из карты высот.

    Это ровно то, что делал бы пиксельный шейдер, только один раз при
    генерации: нормаль из градиента высоты, рассеянный свет по Ламберту,
    блик по половинному вектору и окклюзия в углублениях. Объём кадру даёт
    именно блик — без него купол камня читается как пятно светлее фона.

    ``relief`` гасит рельеф там, где поверхность плоская: у земли в шве нет
    купола, ей достаточно лёгкой окклюзии, иначе шов выглядит обводкой.
    """
    gy, gx = np.gradient(height)
    nx, ny, nz = -gx * steep, -gy * steep, np.ones_like(height)
    inv = 1.0 / np.sqrt(nx * nx + ny * ny + 1.0)
    nx, ny, nz = nx * inv, ny * inv, nz * inv

    lx, ly, lz = LIGHT_DIR[0], LIGHT_DIR[1], LIGHT_ELEVATION
    inv_l = 1.0 / np.sqrt(lx * lx + ly * ly + lz * lz)
    lx, ly, lz = lx * inv_l, ly * inv_l, lz * inv_l

    lambert = np.clip(nx * lx + ny * ly + nz * lz, 0, 1)
    lit = 0.62 + 0.52 * lambert * relief + 0.24 * (1 - relief)

    # взгляд сверху: половинный вектор между солнцем и камерой
    hx, hy, hz = lx, ly, lz + 1.0
    inv_h = 1.0 / np.sqrt(hx * hx + hy * hy + hz * hz)
    spec = np.clip(nx * hx * inv_h + ny * hy * inv_h + nz * hz * inv_h, 0, 1) ** GLOSS_POWER
    ao = 1.0 - (0.40 - 0.18 * (1.0 - relief)) * (1.0 - height)
    return np.clip(lit * ao + spec * gloss * relief, 0.28, 1.55)


def cobblestone(x: np.ndarray, y: np.ndarray, *, seed: int = 1,
                stone: float = 17.0, wear: np.ndarray | float = 0.0,
                dirt_level: float = 0.34):
    """Брусчатка: камни, грязь в швах, затенение и крупная вариация.

    ``wear`` — карта протоптанности 0..1: камни утапливаются, грязи больше.
    """
    ys = y * ISO_SQUASH                              # изометрия земли
    height, owner, tint = cobble_height(x, ys, stone, seed)
    wear = np.asarray(wear, dtype=np.float64)

    # Цвет камня: у каждого свой тон и своя светлота. Широкий разброс важнее
    # точного оттенка — одинаковые камни и есть та самая «плитка».
    per_stone = (owner % 997) / 997.0
    grain = fbm(x, ys, stone * 0.22, seed + 31, octaves=3)
    warm = 0.5 + 0.5 * per_stone
    stone_rgb = np.stack([
        0.50 + 0.26 * tint + 0.05 * warm,
        0.49 + 0.24 * tint + 0.03 * warm,
        0.39 + 0.20 * tint,
    ])
    stone_rgb *= (0.80 + 0.34 * grain)

    # грязь между камнями и на протоптанном
    dirt = fbm(x, ys, stone * 1.6, seed + 57, octaves=4)
    dirt_rgb = np.stack([0.40 + 0.16 * dirt, 0.33 + 0.14 * dirt, 0.22 + 0.10 * dirt])

    # СМЕШИВАНИЕ ПО ВЫСОТЕ: грязь занимает всё, что ниже порога
    # грязи больше в низинах макро-шума: получаются целые запылённые участки
    patch = fbm(x, ys, stone * 9.0, seed + 71, octaves=3)
    level = dirt_level + 0.42 * wear + 0.26 * (patch - 0.45) + 0.10 * (dirt - 0.5)
    blend = np.clip((level - height) * 3.2, 0, 1)
    height = height * (1.0 - 0.65 * wear)            # протоптанные камни ниже
    rgb = stone_rgb * (1 - blend) + dirt_rgb * blend

    # рельеф есть у камня и почти нет у земли, залившей шов
    rgb = rgb * shade_from_height(height, relief=1.0 - 0.75 * blend)

    # Макро-вариация: крупные пятна яркости и запылённости во всю площадь.
    # Без неё повтор читается даже при уникальных камнях.
    macro = fbm(x, ys, stone * 18.0, seed + 91, octaves=3)
    rgb *= (0.80 + 0.42 * macro)
    # прозелень во влажных низинах — крупными пятнами, не по всей площади
    moss = np.clip((fbm(x, ys, stone * 12.0, seed + 137, octaves=3) - 0.56) * 3.4, 0, 1)
    rgb = rgb * (1 - 0.22 * moss) + np.stack([0.30, 0.36, 0.20])[:, None, None] * (0.22 * moss)
    return np.clip(rgb, 0, 1)



# ── фотоматериал как микродеталь ──────────────────────────────────────────
#
# Фотонабор (CC0, ambientCG) даёт зерно камня, сколы и настоящий цвет, но сам
# по себе он квадратный тайл: размноженный по площади, он читается повтором
# ровно так же, как нынешний тайл 44. Поэтому раскладку камней оставляем свою,
# а из фотографии КАЖДЫЙ КАМЕНЬ берёт собственный случайный кусок. Разрыв
# текстуры приходится ровно на шов между камнями, где его закрывает грязь.

class PhotoMaterial:
    """Цвет и высота из CC0-набора; выборка с заворотом по краям."""

    def __init__(self, color: np.ndarray, height: np.ndarray):
        self.color = color                    # линейный RGB, (H, W, 3)
        self.height = height                  # 0..1, (H, W)
        self._grain = None
        self._low = None

    @classmethod
    def load(cls, folder, name: str) -> "PhotoMaterial":
        from PIL import Image
        import os
        def read(suffix):
            path = os.path.join(folder, f"{name}_1K-JPG_{suffix}.jpg")
            return np.asarray(Image.open(path).convert("RGB"), dtype=np.float64) / 255.0
        color = read("Color") ** 2.2         # sRGB -> линейный
        height = read("Displacement")[..., 0]
        return cls(color, height)

    def low(self, sigma: float = 7.0):
        """Низкие частоты: собственный цвет камня без зерна и швов."""
        if self._low is None:
            from scipy.ndimage import gaussian_filter          # noqa: PLC0415
            self._low = gaussian_filter(self.color, (sigma, sigma, 0))
        return self._low

    def sample_low(self, x: np.ndarray, y: np.ndarray, scale: float):
        low = self.low()
        h, w = self.height.shape
        ix = np.mod((x / scale).astype(np.int64), w)
        iy = np.mod((y / scale).astype(np.int64), h)
        return low[iy, ix]

    def grain(self, sigma: float = 7.0):
        """Высокочастотная составляющая: зерно камня без его раскладки.

        Фотография мощения несёт две вещи: КАКИЕ камни (крупный узор, швы) и
        КАКОВ камень (зерно, сколы, крап). Первое нам мешает — раскладку
        считает Вороной, иначе выходит узор в узоре. Деление на размытие
        оставляет только второе. Там, где у источника шов (низкая высота),
        зерно гасится к единице, иначе его тёмные линии просочатся в наш
        камень чужой сеткой.
        """
        if self._grain is None:
            from scipy.ndimage import gaussian_filter          # noqa: PLC0415
            blur = gaussian_filter(self.color, (sigma, sigma, 0))
            grain = np.clip(self.color / np.maximum(blur, 1e-4), 0.55, 1.8)
            joint = np.clip((self.height - 0.35) * 3.0, 0, 1)[..., None]
            self._grain = 1.0 + (grain - 1.0) * joint
        return self._grain

    def sample_grain(self, x: np.ndarray, y: np.ndarray, scale: float):
        grain = self.grain()
        h, w = self.height.shape
        ix = np.mod((x / scale).astype(np.int64), w)
        iy = np.mod((y / scale).astype(np.int64), h)
        return grain[iy, ix]

    def sample(self, x: np.ndarray, y: np.ndarray, scale: float):
        """Выборка ближайшего пикселя с заворотом: аргументы в пикселях мира."""
        h, w = self.height.shape
        ix = np.mod((x / scale).astype(np.int64), w)
        iy = np.mod((y / scale).astype(np.int64), h)
        return self.color[iy, ix], self.height[iy, ix]


def photo_cobblestone(x, y, photo: PhotoMaterial, *, seed: int = 1,
                      stone: float = 18.0, wear=0.0, dirt: PhotoMaterial | None = None,
                      scale: float = 0.28, tone=(0.46, 0.45, 0.35)):
    """Брусчатка: раскладка НАША, зерно камня — с фотографии.

    Раскладку считает Вороной, поэтому у материала нет периода и нет рядов
    европейской кладки. С фотографии берётся только зерно (высокие частоты),
    и каждый камень читает его со своего смещения — два соседних камня не
    выглядят отлитыми в одной форме.
    """
    gx, gy = to_ground(x, y)                   # узор лежит по осям земли
    height, owner, tint = cobble_height(gx, gy, stone, seed)
    wear = np.asarray(wear, dtype=np.float64)

    # каждый камень читает зерно со своего смещения
    off_x = (owner % 733) * 37.0
    off_y = ((owner // 733) % 733) * 53.0
    grain = np.moveaxis(photo.sample_grain(gx + off_x, gy + off_y, scale), -1, 0)

    # Свой ЦВЕТ каждому камню: низкие частоты фотографии с того же смещения.
    # Зерно даёт фактуру, но не цвет; без этого все камни выходят одного тона,
    # и материал снова читается заливкой.
    low = np.moveaxis(photo.sample_low(gx + off_x, gy + off_y, scale), -1, 0)
    low = np.clip(low / np.maximum(low.mean(axis=(1, 2), keepdims=True), 1e-4), 0.62, 1.5)

    base = np.array(tone, dtype=np.float64)[:, None, None] ** 2.2
    # разброс светлоты между камнями — главное, что отличает булыжник от
    # серой заливки; узкий разброс и есть та самая «плитка»
    stone_rgb = base * grain * low * (0.72 + 0.52 * tint)

    relief = np.clip(height, 0, 1)

    if dirt is not None:
        dirt_rgb, dirt_h = dirt.sample(gx * 1.7, gy * 1.7, scale)
        dirt_rgb = np.moveaxis(dirt_rgb, -1, 0)
        dm = dirt_rgb.mean(axis=(1, 2), keepdims=True)
        dirt_rgb = dirt_rgb * (np.array([0.34, 0.28, 0.19])[:, None, None] ** 2.2 / np.maximum(dm, 1e-4))
    else:
        dirt_rgb = np.stack([np.full(x.shape, 0.34 ** 2.2), np.full(x.shape, 0.28 ** 2.2),
                             np.full(x.shape, 0.19 ** 2.2)])

    # грязь в швах: без неё камни висят в пустоте и материал бледнеет
    patch = fbm(gx, gy, stone * 9.0, seed + 71, octaves=3)
    level = 0.46 + 0.44 * wear + 0.26 * (patch - 0.45)
    blend = np.clip((level - height) * 3.4, 0, 1)
    rgb = stone_rgb * (1 - blend) + dirt_rgb * blend

    rgb = rgb * shade_from_height(relief * (1.0 - 0.55 * wear), relief=1.0 - 0.6 * blend)

    macro = fbm(gx, gy, stone * 18.0, seed + 91, octaves=3)
    rgb *= (0.84 + 0.34 * macro)
    return np.clip(rgb, 0, 1) ** (1 / 2.2)     # обратно в sRGB


def render(width: int, height: int, origin=(0, 0), **kwargs) -> np.ndarray:
    """Кусок мира в RGB uint8."""
    y, x = np.mgrid[0:height, 0:width].astype(np.float64)
    rgb = cobblestone(x + origin[0], y + origin[1], **kwargs)
    return (np.moveaxis(rgb, 0, -1) * 255).astype(np.uint8)


def main() -> int:
    parser = argparse.ArgumentParser(description="Процедурная земля")
    parser.add_argument("--preview", action="store_true", help="сохранить пробный кусок")
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=512)
    parser.add_argument("--stone", type=float, default=17.0, help="размер камня в пикселях")
    parser.add_argument("--wear", type=float, default=0.0, help="протоптанность 0..1")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--out", default="ground_preview.png")
    args = parser.parse_args()

    from PIL import Image
    image = render(args.width, args.height, stone=args.stone, wear=args.wear, seed=args.seed)
    Image.fromarray(image).save(args.out)
    print(f"{args.out}: {args.width}x{args.height}, камень {args.stone}px, износ {args.wear}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
