#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gametool.py — инспектор GAME.N (стартовые состояния мира Князь 2)
Использование:
    python gametool.py 0 units          # юниты из GAME.0 (группировка по картам)
    python gametool.py 0 units 19       # юниты на карте 19 (Черный Бор)
    python gametool.py 0 items          # занятые слоты пула предметов
"""
import os, sys, struct

GAME_DIR = r"C:\Program Files (x86)\Князь - Коллекционное издание\02. Князь 2 - Кровь Титанов"

OFF_ITEMS  = 0x00000   # 8192 x 16
OFF_TAB2   = 0x20000   # 0xC800
OFF_GROUND = 0x2C800   # 1000 x 101
OFF_GROUPS = 0x45288   # 0x109A
OFF_UNITS  = 0x46322   # 2000 x 256
OFF_QLINKS = 0xC3322   # 0x378C
OFF_EVENTS = 0xC6AAE   # 10 x 16

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


class Unit:
    SIZE = 0x100
    def __init__(self, idx, raw):
        self.idx = idx
        self.raw = raw
        self.map = struct.unpack_from('<h', raw, 0x08)[0]
        self.y = raw[0x12]
        self.x = raw[0x14]
        self.type = raw[0x17]
        self.flags = raw[0x1A]
        self.hp = struct.unpack_from('<h', raw, 0x4E)[0]
        self.name_id = raw[0xF0]
        self.nick_id = raw[0xF1]
        self.level = raw[0xF3]

    @property
    def empty(self):
        return not any(self.raw)

    def __str__(self):
        return (f"unit[{self.idx:4d}] map={self.map:3d} pos=({self.x:3d},{self.y:3d}) "
                f"type=0x{self.type:02X} flags=0x{self.flags:02X} hp={self.hp:5d} "
                f"lvl={self.level:3d} name_id={self.name_id:3d}")


class GameFile:
    def __init__(self, n):
        self.path = os.path.join(GAME_DIR, f'GAME.{n}')
        self.data = bytearray(open(self.path, 'rb').read())
        assert len(self.data) == 813902

    def units(self):
        out = []
        for i in range(2000):
            raw = bytes(self.data[OFF_UNITS + i*0x100: OFF_UNITS + (i+1)*0x100])
            u = Unit(i, raw)
            if not u.empty:
                out.append(u)
        return out

    def items(self):
        out = []
        for i in range(8192):
            rec = self.data[OFF_ITEMS + i*16: OFF_ITEMS + (i+1)*16]
            if rec != b'\xff'*16 and any(b not in (0, 0xFF) for b in rec):
                t, iid = rec[0], rec[3]
                dur, mx = struct.unpack_from('<ff', rec, 4)
                out.append((i, t, iid, dur, mx))
        return out


if __name__ == '__main__':
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    cmd = sys.argv[2] if len(sys.argv) > 2 else 'units'
    g = GameFile(n)
    if cmd == 'units':
        us = g.units()
        print(f"GAME.{n}: непустых юнитов {len(us)} из 2000")
        if len(sys.argv) > 3:
            target = int(sys.argv[3])
            for u in us:
                if u.map == target:
                    print(' ', u)
        else:
            from collections import Counter
            c = Counter(u.map for u in us)
            for mapn, cnt in sorted(c.items()):
                print(f"  карта {mapn:3d} ({LOCATIONS.get(mapn, '?'):35s}): {cnt:3d} юнитов")
    elif cmd == 'items':
        its = g.items()
        print(f"GAME.{n}: занятых слотов предметов {len(its)}")
        for i, t, iid, dur, mx in its[:60]:
            print(f"  [{i:4d}] type={t:3d} id={iid:3d} dur={dur:8.1f}/{mx:8.1f}")
