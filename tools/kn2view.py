#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kn2view.py — просмотрщик карт Князь 2 (.KN2)
Использование:
    python kn2view.py                # отрендерить все карты в ..\maps_png
    python kn2view.py 19             # только карту 19 (Черный Бор)
    python kn2view.py 19 --info      # + текстовая сводка секций
"""
import os, sys, struct

GAME_DIR = r"C:\Program Files (x86)\Князь - Коллекционное издание\02. Князь 2 - Кровь Титанов"
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'maps_png')

LOCATIONS = {
    1: "Дворец Повелителя", 2: "Лабиринт смерти", 3: "Застава Летающего острова",
    6: "Засада на старом капище", 7: "Сожженный лагерь", 8: "Капище у Темнолесья",
    9: "Могила героя Михаила", 10: "Берег озера", 11: "Переправа на остров",
    12: "Остров с рудником", 13: "Темнолесье", 14: "Жилище Верховного волхва",
    15: "Военный лагерь Повелителя", 16: "Вход в подземную тюрьму", 17: "Волхв у Борье",
    18: "Беглое", 19: "Черный Бор", 20: "Приволье", 21: "Поднебесье",
    22: "Лес у Поднебесья", 23: "Морской лагерь", 24: "Берег у Морского лагеря",
    25: "Торговый пост византийцев", 26: "Корабль в пути", 27: "Бой на корабле",
    28: "Местность на берегу реки", 29: "Скалистая местность", 30: "Местность у лесного капища",
    31: "Местность у лесного пруда", 32: "Местность у лесной просеки", 33: "Борье",
    34: "Волхв у Черного Бора", 35: "Поляна у Военного лагеря", 36: "Волхв у Беглое",
    37: "Нижний лагерь", 38: "Волхв у Нижнего лагеря", 39: "Лесной лагерь",
    40: "Волхв у Лесного лагеря", 41: "Стоянка разбойников", 42: "Болото у сожженного лагеря",
    43: "Засада разбойников", 44: "Река у Приволья", 45: "Пещера волхва-отшельника",
    46: "Заброшенный рудник", 47: "Подземное капище", 48: "Подземная тюрьма",
    49: "Пещера у Поднебесья", 50: "В пути", 51: "Берег", 52: "Берег", 53: "Берег", 54: "Берег",
}

# Секции .KN2 (см. FORMATS.md)
SEC_MINIMAP = (0x00000, 0x6400)    # 160x160 байт
SEC_LAYER2  = (0x06400, 0x3200)
SEC_GRID    = (0x09600, 0x28000)   # 256 строк x 160 клеток x 4 байта
SEC_DYN     = (0x31600, 0x2EE0)    # 1000 x 12
SEC_OBJ     = (0x344E0, 0x8CA0)    # 1000 x 36
SEC_FLAG    = (0x3D180, 4)
SEC_LIGHT   = (0x3D184, 0x200)     # 16 x 32
SEC_ZONES   = (0x3D384, 0x1680)    # 30 x 192 (16 подзаписей по 12)
EMPTY_CELL = 0x4FFF
GRID_W, GRID_H, ROW = 160, 256, 0x280


class KN2Map:
    def __init__(self, path):
        self.path = path
        self.data = bytearray(open(path, 'rb').read())
        assert len(self.data) == 256516, f"неверный размер {len(self.data)}"

    def cell(self, x, y):
        off = SEC_GRID[0] + y * ROW + x * 4
        return struct.unpack_from('<HH', self.data, off)

    def set_cell(self, x, y, lo, hi=None):
        off = SEC_GRID[0] + y * ROW + x * 4
        struct.pack_into('<H', self.data, off, lo)
        if hi is not None:
            struct.pack_into('<H', self.data, off + 2, hi)

    def objects(self):
        """Статические объекты: (index, id, next, type, px, py, raw)"""
        base = SEC_OBJ[0]
        out = []
        for i in range(1000):
            rec = self.data[base + i*36: base + (i+1)*36]
            if any(rec):
                oid, nxt, typ = struct.unpack_from('<HHH', rec, 0)
                px, py = struct.unpack_from('<HH', rec, 30)
                out.append((i, oid, nxt, typ, px, py, bytes(rec)))
        return out

    def zones(self):
        base = SEC_ZONES[0]
        out = []
        for i in range(30):
            rec = self.data[base + i*192: base + (i+1)*192]
            subs = []
            for j in range(16):
                sid, z1, typ, z2, px, py = struct.unpack_from('<6H', rec, j*12)
                if sid != 0xFFFF:
                    subs.append((sid, typ, px, py))
            if subs:
                out.append((i, subs))
        return out

    def save(self, path):
        open(path, 'wb').write(self.data)


def render(m, num, outdir):
    from PIL import Image
    img = Image.new('RGB', (GRID_W, GRID_H))
    px = img.load()
    for y in range(GRID_H):
        for x in range(GRID_W):
            lo, hi = m.cell(x, y)
            if lo == EMPTY_CELL:
                px[x, y] = (24, 24, 48)
            else:
                px[x, y] = ((lo*37) % 200 + 55, (lo*101) % 200 + 55, (lo*13) % 200 + 55)
    # объекты — красные точки (пиксельные координаты / 32 и /16 — эмпирика масштаба)
    for (_, oid, nxt, typ, opx, opy, _) in m.objects():
        gx, gy = min(GRID_W-1, opx // 32), min(GRID_H-1, opy // 16)
        px[gx, gy] = (255, 64, 64)
    img = img.resize((GRID_W*3, GRID_H*2), Image.NEAREST)
    name = LOCATIONS.get(num, '')
    p = os.path.join(outdir, f'map{num:02d}_{name.replace(" ", "_")}.png')
    img.save(p)
    return p


def info(m, num):
    used = sum(1 for y in range(GRID_H) for x in range(GRID_W) if m.cell(x, y)[0] != EMPTY_CELL and m.cell(x, y)[0] != 0)
    objs = m.objects()
    zones = m.zones()
    print(f"=== {num}.KN2 — {LOCATIONS.get(num, '?')} ===")
    print(f"  занятых клеток: {used} из {GRID_W*GRID_H}")
    print(f"  статических объектов: {len(objs)}")
    print(f"  зон/эмиттеров: {len(zones)}")
    for i, subs in zones[:6]:
        print(f"    зона[{i}]: {subs[:4]}")


if __name__ == '__main__':
    os.makedirs(OUT_DIR, exist_ok=True)
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    nums = [int(args[0])] if args else sorted(LOCATIONS.keys())
    for n in nums:
        p = os.path.join(GAME_DIR, f'{n}.KN2')
        if not os.path.exists(p):
            continue
        m = KN2Map(p)
        out = render(m, n, OUT_DIR)
        if '--info' in sys.argv or len(nums) == 1:
            info(m, n)
        print(f"  -> {out}")
