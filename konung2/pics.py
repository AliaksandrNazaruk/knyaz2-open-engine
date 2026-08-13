# -*- coding: utf-8 -*-
"""Экраны загрузки из каталога ``PICS``.

КТО ИХ ПОКАЗЫВАЕТ. ``FUN_00422CCC(номер)`` собирает имя файла как ``M`` +
номер карты + ``.RES`` (строки 0x4504DB и 0x4504DD) и отдаёт его в
``FUN_004304D4``, а тот дописывает каталог ``PICS\\`` (0x45259F), читает
dword размера и заливает остаток прямо в экранную поверхность. Файла нет —
загрузчик возвращает ноль, и экран просто не показывается.

Ноль вместо номера значит «не карта»:

    в море (0x84960C == -1)  -> SEA.RES,      номер сцены 0x1A
    иначе                    -> RANDOM.RES,   номер = вид местности клетки
                                              (ноль заменяется на 0x32)

Встречи в пути идут своим путём (VA 0x4277F4): обычная — ENCOUNTS.RES,
сцена 0x1B — SBUTTLE.RES. При запуске игры показывается INTRO.RES.

ФОРМАТ снят с ``FUN_004276EC`` — она правит цвета прямо в распакованном
буфере и потому обходит всю раскладку:

    u32              размер полезной части (всё, что ниже)
    u16              ширина, у всех 1024
    u16              строк, у всех 768
    u16 x строк      длина каждой строки в байтах
    далее            строки одна за другой

Строка — цепочка кусков со знаковым управляющим байтом:

    c < 0    пропуск |c| точек, своих байтов у куска нет
    c >= 0   c точек подряд, по два байта на точку

Счётчик строки начинается с ``длина - 1`` и убывает на 1 у пропуска и на
``c * 2 + 1`` у литерала; последний байт строки — хвост, его пропускают.

ЦВЕТ — RGB555. В шестнадцатибитном режиме движок раздвигает его до 565 на
месте: ``*p = *p * 2 & 0xFFC0 | *p & 0x1F`` (VA 0x4276EC). Нам это не нужно:
мы разворачиваем 555 сразу в восемь бит на канал.
"""
from __future__ import annotations

import struct
from pathlib import Path

#: Каталог с экранами внутри установки игры.
PICS_DIR = "PICS"

#: Приставка и хвост имени карты (VA 0x4504DB, 0x4504DD).
MAP_PREFIX, MAP_SUFFIX = "M", ".RES"

#: Экраны, не привязанные к номеру карты.
SEA_PIC = "SEA.RES"            # отряд в море (VA 0x422CCC)
RANDOM_PIC = "RANDOM.RES"      # остановка в пути по виду местности
ENCOUNTER_PIC = "ENCOUNTS.RES"  # встреча в пути (VA 0x4277F4)
BATTLE_PIC = "SBUTTLE.RES"     # сцена 0x1B, бой на корабле
INTRO_PIC = "INTRO.RES"        # заставка при запуске

#: Номера сцен, которые движок подставляет вместо карты (VA 0x422CCC).
SEA_SCENE, RANDOM_SCENE = 0x1A, 0x32
#: Сцена, которой отвечает «Готовьтесь к бою» (VA 0x4277F4).
BATTLE_SCENE = 0x1B


def map_pic_name(number: int) -> str:
    """Имя файла экрана для карты, как его собирает движок."""
    return f"{MAP_PREFIX}{number}{MAP_SUFFIX}"


def decode(data: bytes) -> tuple[int, int, bytearray]:
    """Развернуть экран в RGB888. Возвращает ширину, высоту и байты."""
    if len(data) < 8:
        raise ValueError("экран короче заголовка")
    size = struct.unpack_from("<I", data, 0)[0]
    if size + 4 > len(data):
        raise ValueError(f"заявлено {size} байт, а в файле {len(data) - 4}")
    width, height = struct.unpack_from("<HH", data, 4)
    if not (0 < width <= 4096 and 0 < height <= 4096):
        raise ValueError(f"нелепый размер {width}x{height}")
    rows = struct.unpack_from(f"<{height}H", data, 8)
    at = 8 + height * 2
    out = bytearray(width * height * 3)
    for y, length in enumerate(rows):
        end = at + length
        left = length - 1
        x = 0
        while left > 0 and at < end:
            control = struct.unpack_from("<b", data, at)[0]
            at += 1
            if control < 0:
                left -= 1
                x += -control
                continue
            left -= control * 2 + 1
            for _ in range(control):
                value = struct.unpack_from("<H", data, at)[0]
                at += 2
                if x < width:
                    base = (y * width + x) * 3
                    out[base] = ((value >> 10) & 31) * 255 // 31
                    out[base + 1] = ((value >> 5) & 31) * 255 // 31
                    out[base + 2] = (value & 31) * 255 // 31
                x += 1
        at = end
    return width, height, out


def read(path: str | Path) -> tuple[int, int, bytearray]:
    """Прочитать и развернуть экран."""
    return decode(Path(path).read_bytes())


def catalogue(root: str | Path) -> dict[str, str]:
    """Что вообще лежит в ``PICS`` этой установки: имя в нижнем регистре -> путь.

    Имена файлов на диске в разном регистре (``M3.res`` рядом с ``m10.res``),
    поэтому ключом берём нижний регистр — движку на Windows это было
    безразлично, а нам искать.
    """
    folder = Path(root) / PICS_DIR
    if not folder.is_dir():
        return {}
    return {item.name.lower(): str(item) for item in folder.iterdir()
            if item.is_file()}
