# -*- coding: utf-8 -*-
"""
Перенос вещей: взять в руку, положить, бросить.

Разобрано по коду, ничего не подобрано.

ВЗЯТЬ (VA 0x41DFE0). Движок запоминает три вещи — у кого взяли, ОТКУДА и
что, — и переключает режим курсора на 8, в котором вместо курсора рисуется
иконка самой вещи (VA 0x42DDA0). Откуда — это код места:

     1   боеприпас, одно гнездо unit+0x50
     5   снаряжение, пять гнёзд с unit+0x58
    -5   второй набор, пять гнёзд с unit+0xB6
    42   мешок, сорок два гнезда с unit+0x62

Вынимая, движок сохраняет копию всего списка (снаряжение и второй набор по
десять байт, мешок целиком) — по ней вещь потом возвращается, если перенос
отменили. Мешок при этом УПЛОТНЯЕТСЯ: хвост сдвигается влево, дырок в нём
не бывает.

ОТМЕНИТЬ (VA 0x42944C и 0x41EAB8) — вернуть сохранённую копию на место.

ПОЛОЖИТЬ В ГНЕЗДО (VA 0x41E280). Гнездо называется своим номером: 0 рука,
1 метательное, 2 доспех, 3 шлем, 4 щит, 12 боеприпас. Проверки идут в
таком порядке:

    характеристика     VA 0x418648; не хватает — «Предмет не доступен
                       для использования»
    вид предмета       байт +0 записи должен совпасть с номером гнезда
    рука               двуручное (слой больше 12) сгоняет щит
    щит                кроме вида 4 туда ложится и одноручное оружие, но
                       только если у юнита есть навык unit+0xD3
    метательное
    и боеприпас        самострелу (слой 0x15) нужны БОЛТЫ, луку — СТРЕЛЫ;
                       различаются они номером класса: больше 0xCD болты
    занятое гнездо     старое уходит в мешок, а если мешок полон — на
                       землю; не вышло ни то, ни другое — отказ

ПОЛОЖИТЬ В МЕШОК (VA 0x423218):

    цена ноль          такую вещь можно отдать только своему герою: у
                       квестовых вещей цена нулевая
    вес                ПРЕДЕЛ = текущая Выносливость * 1000 / 3 + 20000
                       граммов; больше — «Превышен вес»
    место              нет свободного гнезда — «Мешок у тебя не резиновый!»

Сколько юнит несёт, считает VA 0x41B218: пять гнёзд снаряжения, пять
второго набора, сорок два мешка и боеприпас, причём у стопок вес берётся
за штуку и умножается на количество.

БРОСИТЬ (VA 0x421690 -> 0x423360). Вещь ложится в клетку САМОГО ЮНИТА, а
не туда, куда показывает мышь, и опять же только если цена не ноль. Куч на
земле не больше двухсот (0x7AD7E4, по 0x65 байт).

УРОНИТЬ НА ДРУГУЮ ВЕЩЬ (VA 0x421690):

    несём зелье (вид 9)      оно применяется К ТОЙ ВЕЩИ — так яд и масло
                             попадают на стрелы
    несём вид 0x0B           то же самое через VA 0x436C48
    обе стопки боеприпаса    складываются, но только если СОВПАЛИ и класс,
                             и отрава; в пачке не больше тридцати, а
                             остаток движок кладёт в мешок и на этом
                             перенос заканчивает — в руке не остаётся
                             ничего (VA 0x421690)

УРОНИТЬ НА ЮНИТА (VA 0x41F55C) — то же самое, но применяется к юниту:
зелье выпивается, вид 0x0B уходит в VA 0x436C48.
"""
from __future__ import annotations

#: Режим курсора «несём вещь» — в нём рисуется иконка вещи.
CARRY_MODE = 8
#: Коды мест, откуда берут.
FROM_AMMO, FROM_EQUIPMENT, FROM_SECOND, FROM_BAG = 1, 5, -5, 42
PLACE_AT = {FROM_AMMO: 0x50, FROM_EQUIPMENT: 0x58, FROM_SECOND: 0xB6, FROM_BAG: 0x62}
#: Гнёзда экипировки по номерам и особое гнездо боеприпаса.
SLOT_HAND, SLOT_RANGED, SLOT_BODY, SLOT_HEAD, SLOT_OFF_HAND = 0, 1, 2, 3, 4
SLOT_AMMO = 12
#: Мешок и второй набор.
BAG_SLOTS, SECOND_SLOTS = 42, 5
#: Вид записи боеприпаса и размер пачки — те же, что в бою.
STACK_KIND = 0x0C
AMMO_STACK = 30

#: Предел веса: текущая Выносливость (unit+0xD1) в этой мере.
WEIGHT_BASE, WEIGHT_PER_STAMINA, WEIGHT_DIVISOR = 20000, 1000, 3
#: Текущие характеристики лежат с +0xCC, шестая из них — Выносливость.
CURRENT_AT, STAMINA_AT = 0xCC, 0xD1

#: Навык, по которому в левую руку ложится оружие (unit+0xD3).
OFF_HAND_SKILL_AT = 0xD3
#: Слои: с 0x0D двуручное, 0x15 самострел.
TWO_HAND_FROM_LAYER, CROSSBOW_LAYER = 0x0D, 0x15
#: Боеприпас: классы выше этого — болты, остальные стрелы.
BOLT_CLASS_FROM = 0xCD
#: В пачке не больше тридцати — движок сам режет по этому числу.
STACK_MAX = 30
#: Куч на земле не больше двухсот.
GROUND_PILES = 200
#: Цена ноль — вещь квестовая: её нельзя ни бросить, ни отдать чужому.
QUEST_PRICE = 0

#: Сообщения движка.
MESSAGES = {
    "requirement": "Предмет не доступен для использования",
    "weight": "Превышен вес",
    "bag_full": "Мешок у тебя не резиновый!",
}


def weight_limit(stamina: int) -> int:
    """Сколько граммов юнит унесёт (VA 0x423218)."""
    return stamina * WEIGHT_PER_STAMINA // WEIGHT_DIVISOR + WEIGHT_BASE


def is_bolt(item_class: int) -> bool:
    """Болт это или стрела — решает номер класса."""
    return item_class > BOLT_CLASS_FROM


def ammo_fits(weapon_layer: int | None, ammo_class: int | None) -> bool:
    """Подходит ли боеприпас метательному (VA 0x41E280)."""
    if weapon_layer is None or ammo_class is None:
        return True
    return is_bolt(ammo_class) == (weapon_layer == CROSSBOW_LAYER)


def merge_stacks(target: int, carried: int) -> tuple[int, int]:
    """Сложить две пачки: (сколько стало в целевой, сколько осталось в руке)."""
    total = target + carried
    if total < STACK_MAX + 1:
        return total, 0
    return STACK_MAX, total - STACK_MAX


def rules() -> dict:
    """Правила переноса одним куском — для content pack."""
    return {
        "policy": "konung2_exe_0x41dfe0_0x41e280_0x423218_0x421690",
        "cursor_mode": CARRY_MODE,
        "from": {"ammo": FROM_AMMO, "equipment": FROM_EQUIPMENT,
                 "second": FROM_SECOND, "bag": FROM_BAG},
        "slots": {"hand": SLOT_HAND, "ranged": SLOT_RANGED, "body": SLOT_BODY,
                  "head": SLOT_HEAD, "off_hand": SLOT_OFF_HAND, "ammo": SLOT_AMMO},
        "bag_slots": BAG_SLOTS, "second_slots": SECOND_SLOTS,
        # вид записи стопки: её вес умножается на количество
        # (VA 0x41B218 в мешке и 0x41AA78 у несомой вещи)
        "item_kinds": {"stack": STACK_KIND},
        "ammo_stack": AMMO_STACK,
        "weight": {"base": WEIGHT_BASE, "per_stamina": WEIGHT_PER_STAMINA,
                   "divisor": WEIGHT_DIVISOR, "stamina_at": STAMINA_AT},
        "off_hand_skill_at": OFF_HAND_SKILL_AT,
        "two_hand_from_layer": TWO_HAND_FROM_LAYER,
        "crossbow_layer": CROSSBOW_LAYER,
        "bolt_class_from": BOLT_CLASS_FROM,
        "stack_max": STACK_MAX,
        "quest_price": QUEST_PRICE,
        "ground_piles": GROUND_PILES,
        "messages": dict(MESSAGES),
    }
