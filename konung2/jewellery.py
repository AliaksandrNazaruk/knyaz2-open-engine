# -*- coding: utf-8 -*-
"""
Второй набор гнёзд: украшения и то, зачем они нужны.

ЧТО ЭТО. Пять слов подряд в юните с +0xB6, сразу за мешком. Кладут туда
через VA 0x41E8D8, и гнёзда там свои, с номерами 0x17…0x1B, а годится в
них только по виду записи предмета:

    вид 6  ожерелье   гнездо 0x17          — одно
    вид 7  браслет    гнёзда 0x18 и 0x19   — два запястья
    вид 8  кольцо     гнёзда 0x1A и 0x1B   — два пальца

Ровно так же они и подписаны в окне снаряжения. Проверка характеристики
та же, что у обычной экипировки (VA 0x418648), занятое гнездо уходит в
мешок, и в вес украшения тоже считаются (VA 0x41B218).

ЗАЧЕМ. Украшение носят не для вида, а ради прибавок: они лежат в слове
+0x0E записи предмета, и разбор этого слова — в konung2/enchant.py. Там же
и то, что зачарование бывает не только на украшениях: в стартовом мире
121 такая вещь, и большинство из них — доспехи, шлемы, щиты и метательное.
"""
from __future__ import annotations

#: Зачарование разбирается отдельно — здесь только гнёзда.
from .enchant import bonuses, table  # noqa: F401

#: Пять гнёзд второго набора и их номера в обработчике.
SECOND_SET_AT, SECOND_SLOTS = 0xB6, 5
SLOT_FIRST = 0x17
SLOT_NECKLACE, SLOT_BRACELET_1, SLOT_BRACELET_2, SLOT_RING_1, SLOT_RING_2 = range(0x17, 0x1C)
#: Какой вид записи куда ложится.
KIND_NECKLACE, KIND_BRACELET, KIND_RING = 6, 7, 8
KIND_SLOTS = {
    KIND_NECKLACE: (SLOT_NECKLACE,),
    KIND_BRACELET: (SLOT_BRACELET_1, SLOT_BRACELET_2),
    KIND_RING: (SLOT_RING_1, SLOT_RING_2),
}
NAMES = {SLOT_NECKLACE: "necklace", SLOT_BRACELET_1: "bracelet_1",
         SLOT_BRACELET_2: "bracelet_2", SLOT_RING_1: "ring_1", SLOT_RING_2: "ring_2"}

def slots_for(kind: int) -> tuple[int, ...]:
    """В какие гнёзда ложится вид записи."""
    return KIND_SLOTS.get(kind, ())


def rules() -> dict:
    """Правила второго набора одним куском — для content pack."""
    from .enchant import rules as enchant_rules
    return {
        "policy": "konung2_exe_0x41e8d8_0x41c494_0x41b7c0",
        "at": SECOND_SET_AT,
        "slots": [{"code": code, "name": NAMES[code]} for code in sorted(NAMES)],
        "kinds": {str(kind): [NAMES[code] for code in codes]
                  for kind, codes in KIND_SLOTS.items()},
        # зачарование общее для всех вещей, не только для украшений
        "enchant": enchant_rules(),
    }
