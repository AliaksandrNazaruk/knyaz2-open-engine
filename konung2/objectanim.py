# -*- coding: utf-8 -*-
"""
Огни на объектах карты: костры, факелы, горящие руины.

Разобрано 22.08.2026 по ассемблеру донора и живой памяти; у канона всё то
же самое, проверено его таблицей. Полная история раскопок — в
docs/REFACTOR_BACKLOG.md, здесь только итог.

КАК ЭТО УСТРОЕНО В ДВИЖКЕ. У заголовка объекта (256 байт в начале записи
слота OBJECTS.RES) есть счётчик огней и до восьми точек по пять байт:

    +0xFC  байт   сколько огней на объекте (0 или 0xFF — нет)
    +0x18 + i*5   байт id анимации, слово dx, слово dy (знаковые)

Смещения — от точки объекта на карте (pixel_x, pixel_y записи). Сам огонь
живёт в поле +8 записи объекта: загрузчик карты (VA 0x4423E1 донора)
кладёт туда СЛУЧАЙНЫЙ кадр из диапазона своей анимации, такт двигает его
на единицу за мировой такт, а отрисовка (VA 0x427E94) берёт спрайт по
таблице указателей и рисует в точке объекта плюс смещение. Анимируется
только объект в поле зрения — остальные стоят на своём кадре.

Диапазоны кадров лежат в exe парами (первый, последний):

    канон  VA 0x45FFF0        донор  VA 0x4618E8   (содержимое одинаковое)

    id 0  кадры  0…10   пожар 256x195      id 4  кадры 44…54  огонь чаши
    id 1  кадры 11…21   костёр 120x90      id 5  кадры 55…59  факел 38x31
    id 2  кадры 22…32   столб пламени      id 6  кадры 60…73  костёр 96x72
    id 3  кадры 33…43   пламя 93x130

САМИ КАДРЫ в файлах игры не нашлись: в памяти они лежат уже
конвертированными в 16-битный цвет (RLE со строчными длинами, наш
decode_rle с mode=16), и откуда движок их разворачивает — не разобрано.
Поэтому кадры сняты ИЗ ЖИВОЙ ПАМЯТИ оригинала (таблица указателей
0x873880, все 74) и лежат выверенным входом в project/fire_frames/
anim_00.png…anim_73.png. Пиксели канонные; провенанс записан здесь.
"""
from __future__ import annotations

import struct
from typing import Any

#: Таблица диапазонов: восемь байт на запись — (первый кадр, последний).
ANIM_TABLE_VA = {"canon": 0x0045FFF0, "legend": 0x004618E8}
ANIM_COUNT = 7

#: Заголовок объекта: счётчик огней и точки.
FIRE_COUNT_AT = 0xFC
FIRE_POINTS_AT = 0x18
FIRE_POINT_STRIDE = 5
FIRE_POINTS_MOST = 8

#: Таблица слотов OBJECTS.RES: 1000 пар (смещение, размер), смещения
#: считаются от конца таблицы (konung2/res.py).
_TABLE_BIAS = 0x1F40
_SIMPLE_FROM = 30
_HEADER_SIZE = 0x100


def anim_ranges(game: str = "canon") -> list[tuple[int, int]]:
    """Диапазоны кадров семи анимаций из exe игры."""
    from konung2.profile import CANON, LEGEND

    profile = LEGEND if game == "legend" else CANON
    data = profile.exe_bytes()
    at = profile.va_to_foff(ANIM_TABLE_VA[game])
    out = []
    for i in range(ANIM_COUNT):
        first, last = struct.unpack_from("<ii", data, at + i * 8)
        out.append((first, last))
    return out


def fire_points(game: str = "canon") -> dict[int, list[dict[str, int]]]:
    """Точки огня по слотам OBJECTS.RES: {слот: [{anim, dx, dy}, …]}.

    Читается прямо из файла ресурса, без движка: заголовок простого
    объекта лежит первой сотней шестнадцатеричных байт записи слота.
    """
    if game == "legend":
        from konung2.donor import donor_file
        path = donor_file("OBJECTS.RES")
    else:
        from konung2.paths import game_file
        path = game_file("OBJECTS.RES")
    data = open(path, "rb").read()
    out: dict[int, list[dict[str, int]]] = {}
    for slot in range(_SIMPLE_FROM, 1000):
        off, size = struct.unpack_from("<II", data, slot * 8)
        if size in (0, 0xFFFFFFFF) or off == 0xFFFFFFFF:
            continue
        header = data[off + _TABLE_BIAS: off + _TABLE_BIAS + _HEADER_SIZE]
        if len(header) < _HEADER_SIZE:
            continue
        count = header[FIRE_COUNT_AT]
        if not count or count == 0xFF:
            continue
        points = []
        for i in range(min(count, FIRE_POINTS_MOST)):
            base = FIRE_POINTS_AT + i * FIRE_POINT_STRIDE
            anim = header[base]
            dx, dy = struct.unpack_from("<hh", header, base + 1)
            if anim >= ANIM_COUNT:
                continue
            points.append({"anim": anim, "dx": dx, "dy": dy})
        if points:
            out[slot] = points
    return out


def export(frames_prefix: str = "assets/effects") -> dict[str, Any]:
    """Раздел `effects` для shared.json: кадры семи анимаций.

    Диапазоны у обеих игр одинаковые (сверено тестом), поэтому раздел
    один; движок двигает кадр на единицу за мировой такт.
    """
    ranges = anim_ranges("canon")
    return {
        "object_anims": [
            {"frames": [f"{frames_prefix}/anim_{n:02}.png"
                        for n in range(first, last + 1)]}
            for first, last in ranges
        ],
        # такт кадра: единица за мировой такт (VA 0x424BCB соседней
        # механики и живой замер — 13 смен в секунду при 12.8 тактах)
        "ticks_per_frame": 1,
    }
