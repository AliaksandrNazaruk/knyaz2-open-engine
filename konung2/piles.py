# -*- coding: utf-8 -*-
"""
Кучи вещей на земле.

Куча в движке — это не предмет, а ЗАПИСЬ НА КЛЕТКУ: таблица 0x7AD7E4, до
двухсот записей по 101 байту (VA 0x423360 их заводит):

    +0x00 i16  x картинки, +0x02 i16 y — от клетки, минус половина спрайта
    +0x05 u8   строка,     +0x06 u8   столбец
    +0x08 u8   карта
    +0x0B u16  спрайт
    +0x0F u16  деньги
    +0x11      сорок два слова предметов

Кладут вещь так: если у клетки уже стоит бит 0x20, вещь падает в её кучу,
а нет — заводится новая и бит ставится. Мест в куче столько же, сколько в
мешке; когда все заняты, вещь на землю не ложится.

Спрайт выбирает VA 0x43BBC4: одна вещь и без денег — её собственная
картинка (поле класса +0x18), иначе мешочек 163.

Подойдя к куче (VA 0x4115AC), герой сам опознаёт её вещи броском против
навыка «Идентификация предметов», забирает деньги и открывает обмен
(VA 0x424128 кладёт мешок игрока в ряд 0, а кучу — в ряд 2).
"""
from __future__ import annotations

#: Таблица куч.
PILES_VA, PILE_STRIDE, PILE_LIMIT = 0x7AD7E4, 0x65, 200
#: Поля записи.
PILE_ROW_AT, PILE_COL_AT, PILE_MAP_AT = 0x05, 0x06, 0x08
PILE_SPRITE_AT, PILE_MONEY_AT, PILE_ITEMS_AT = 0x0B, 0x0F, 0x11
#: Мест в куче столько же, сколько в мешке.
PILE_SLOTS = 42
#: Бит клетки, которым помечена куча.
CELL_BIT = 0x20


def pile_sprite(items, money: int = 0, single_ground: int | None = None) -> int:
    """Картинка кучи (VA 0x43BBC4)."""
    from .items import GROUND_PILE_SPRITE
    if len(items) == 1 and not money and single_ground is not None:
        return single_ground
    return GROUND_PILE_SPRITE


def rules() -> dict:
    """Правила куч одним куском — для content pack."""
    return {
        "policy": "konung2_exe_0x423360_0x43bbc4_0x4115ac",
        "at": PILES_VA, "stride": PILE_STRIDE, "limit": PILE_LIMIT,
        "slots": PILE_SLOTS, "cell_bit": CELL_BIT,
        "fields": {"row": PILE_ROW_AT, "col": PILE_COL_AT, "map": PILE_MAP_AT,
                   "sprite": PILE_SPRITE_AT, "money": PILE_MONEY_AT,
                   "items": PILE_ITEMS_AT},
    }
