# -*- coding: utf-8 -*-
"""
Курсоры: девять картинок и правила, какая когда.

КАРТИНКИ лежат в GRAPH.RES сразу за блоком палитр — девять кусков подряд,
каждый «длина словом, потом данные» (VA 0x43C228 читает ровно девять и
раскладывает указатели в 0x840BB8). Каждый курсор 32x32, и рисуется он
остриём в точку мыши, то есть горячая точка — левый верхний угол.

Кусок устроен так:

    +0x00  u16   ширина
    +0x02  u16   высота
    +0x04  u16 * высота — длина каждой строки В БАЙТАХ
    дальше строки

Строка — это цепочка кодов (VA 0x44083F):

    0            строка кончилась, дальше прозрачно
    старший бит  пропустить ``код & 0x7F`` точек
    иначе        следом идут ``код`` точек по два байта, X1R5G5B5

ЗНАЧЕНИЯ выбирает VA 0x428B88 по тому, что под мышью. Проверено по самим
картинкам:

    0  скрещённые мечи   бить
    1  перечёркнутый круг  нельзя
    2  просто копьё      обычный, он же основной режим
    3  облачко речи      говорить
    4  пламя             поджечь
    5  рука              взять
    6  свиток карты      уйти на глобальную карту
    7  крест             перейти на другую карту
    8  просто копьё      режим переноса вещи; вместо копья движок рисует
                         иконку самой вещи (VA 0x42DDA0, поле класса +0x16)

ПОРЯДОК ПРОВЕРОК (VA 0x428B88, сверху вниз):

    мышь не в окне мира или идёт заставка   основной
    под мышью постройка деревни, а среди
      выбранных есть лучник с намасленными
      стрелами                              4  поджечь
    несём вещь                              1  нельзя
    под мышью юнит:
        свой                                основной, а при особом режиме 3
        чужой, и есть кому драться          0  бить
        чужой, разговора нет                1  нельзя
        чужой, разговор есть                3  говорить
        помеченный 0x80 (лежачий)           5  взять
    под мышью вещь на земле                 5  взять
    в клетке объект                         1  нельзя
    клетка помечена битом 0x10 (переход):
        цель −1                             6  на глобальную карту
        цель −2                             основной
        иначе                               7  на другую карту
    прочее                                  основной
"""
from __future__ import annotations

import struct

#: Сколько курсоров лежит в GRAPH.RES.
COUNT = 9
#: Что чем: имена по картинкам.
ATTACK, FORBIDDEN, NORMAL, TALK, BURN, TAKE, WORLD_MAP, TRAVEL, CARRY = range(9)
NAMES = {
    ATTACK: "бить", FORBIDDEN: "нельзя", NORMAL: "обычный", TALK: "говорить",
    BURN: "поджечь", TAKE: "взять", WORLD_MAP: "на глобальную карту",
    TRAVEL: "на другую карту", CARRY: "несём вещь",
}
#: Остриё курсора — левый верхний угол картинки.
HOTSPOT = (0, 0)
#: Клетка с этим битом — переход (VA 0x428B88 смотрит байт +1 клетки).
EXIT_CELL_BIT = 0x10
#: Цель выхода: −1 уйти на глобальную карту, −2 особый (курсор не меняется).
EXIT_LEAVE, EXIT_SPECIAL = -1, -2


def decode(index: int, data: bytes | None = None):
    """Курсор как список строк точек: None — прозрачно, иначе (r, g, b)."""
    from .graph import GraphRes
    graph = GraphRes(data) if data is not None else GraphRes.from_game()
    start, _ = graph.blocks[index]
    width, height = struct.unpack_from("<2H", graph.data, start)
    lengths = struct.unpack_from(f"<{height}H", graph.data, start + 4)
    at = start + 4 + 2 * height
    rows = []
    for length in lengths:
        end, row = at + length, []
        while at < end:
            code = graph.data[at]
            at += 1
            if code == 0:
                break
            if code & 0x80:
                row.extend([None] * (code & 0x7F))
                continue
            for _ in range(code):
                colour = struct.unpack_from("<H", graph.data, at)[0]
                at += 2
                row.append((((colour >> 10) & 0x1F) * 255 // 31,
                            ((colour >> 5) & 0x1F) * 255 // 31,
                            (colour & 0x1F) * 255 // 31))
        row.extend([None] * (width - len(row)))
        rows.append(row[:width])
        at = end
    return rows


def image(index: int, data: bytes | None = None):
    """Курсор картинкой PIL."""
    from PIL import Image
    rows = decode(index, data)
    height = len(rows)
    width = len(rows[0]) if rows else 0
    picture = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    pixels = picture.load()
    for y, row in enumerate(rows):
        for x, colour in enumerate(row):
            if colour is not None:
                pixels[x, y] = (*colour, 255)
    return picture


def exit_cursor(target: int) -> int | None:
    """Какой курсор над клеткой перехода. None — оставить основной."""
    if target == EXIT_SPECIAL:
        return None
    return WORLD_MAP if target == EXIT_LEAVE else TRAVEL


def rules() -> dict:
    """Правила курсоров одним куском — для content pack."""
    return {
        "policy": "konung2_exe_0x428b88_0x43c228",
        "count": COUNT,
        "hotspot": list(HOTSPOT),
        "names": {str(index): name for index, name in NAMES.items()},
        "kind": {
            "attack": ATTACK, "forbidden": FORBIDDEN, "normal": NORMAL,
            "talk": TALK, "burn": BURN, "take": TAKE,
            "world_map": WORLD_MAP, "travel": TRAVEL, "carry": CARRY,
        },
        "exit": {"cell_bit": EXIT_CELL_BIT,
                 "leave": EXIT_LEAVE, "special": EXIT_SPECIAL},
    }
