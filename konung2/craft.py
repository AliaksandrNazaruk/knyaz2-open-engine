# -*- coding: utf-8 -*-
"""
Зачарование камнями и варка снадобий.

Разобрано по коду, ничего не подобрано.

ГДЕ ЭТО ДЕЛАЮТ. Не у волхва и не в мастерской: в окне снаряжения есть
ДВЕНАДЦАТОЕ гнездо (код мыши 0x1C), и подсказка у него своя —

    «Здесь можно смешивать волшебные снадобья и вкладывать волшебные
     камни в оружие или доспехи»

Кладут туда вещь, а потом роняют на неё вторую: зелье на зелье варится,
камень в оружие вкладывается. Ту же самую пару обрабатывает и щелчок по
вещи в любом другом окне (VA 0x421690) — гнездо просто удобное место.

КАМНИ. Вид записи 0x0B, классы 52…56, и названия сходятся с полями один в
один (VA 0x436C48):

    52  Магический камень брони          биты 12-14, поле 7
    53  Магический камень выносливости   биты  0-2,  поле 6
    54  Магический камень ловкости       биты  6-8,  поле 2
    55  Магический камень силы           биты  3-5,  поле 5
    56  Магический камень удара          биты  9-11, поле 8

Правило одно на все пять:

    цель должна быть носимой вещью (вид записи не больше 8) и ОПОЗНАННОЙ
    её нынешний уровень в этой группе не больше пяти
    новый уровень = нынешний + навык 16 «Волхование» ДЕЛЁННЫЙ НА 16,
                    но не выше шести
    камень пропадает

То есть без волхования камень не даёт ничего: до навыка 16 прибавка
нулевая, а полные +6 за один камень выходят только на сотне.

ТОЧИЛЬНЫЙ КАМЕНЬ (класс 51) чинит оружие: цель должна быть видом 0.

СНАДОБЬЯ. Если уронить зелье на зелье, движок ищет пару в таблице
0x459FE4 — тридцать записей по шесть байт (VA 0x41B930, она же
W_SFLB_mixmagics):

    +0x00  класс цели        +0x01  класс того, что льют
    +0x02  чем станет цель   +0x03  что останется в руке (отрицательное —
                                    ничего, посуда пропадает)
    +0x04  прибавка к навыку 12 «Приготовление смесей»
    +0x05  как считать крепость

Пары не нашлось — выходит «Непонятная смесь» (класс 84), а она при
выпивании делит здоровье пополам. Крепость (поле +0x04 записи) считается
одним из пяти способов, и выше пятнадцати не поднимается:

    0  крепость = навык * 0.01
    1  крепость += навык * 0.01
    2  крепость = сумма обеих
    3  крепость = меньшая из двух
    4  крепость = чужая + навык * 0.01

Сама книга рецептов короткая и стройная: три сырья дают три простых
снадобья, а из них варятся остальные.
"""
from __future__ import annotations

import struct

#: Двенадцатое гнездо окна снаряжения — то самое место.
MIXING_CODE, MIXING_SLOT = 0x1C, 11
MIXING_HINT_VA = 0x45042D

#: Камни: класс -> сдвиг группы в слове прибавок.
STONE_GROUPS = {52: 12, 53: 0, 54: 6, 55: 3, 56: 9}
#: Точильный камень (класс 51, VA 0x432DE0, W?SFLB_repairweapon): работает
#: по всем ПЯТИ носимым видам записи (0…4, а не только оружию). Потолок
#: кузнеца = навык «Кузнечное дело» (+0xE3) × 2 (double 0x459198); максимум
#: прочности выше потолка деградирует к нему на 30 % разницы за одно
#: применение (× 0.7, double 0x4591A0); прочность чинится до максимума, и
#: удачная починка учит кузнеца: навык +1, пока рост был и навык меньше ста.
WHETSTONE_CLASS, WHETSTONE_TARGET_KINDS = 51, 5
WHETSTONE_CEILING_PER_SKILL, WHETSTONE_DECAY = 2.0, 0.7
WHETSTONE_SKILL, WHETSTONE_SKILL_AT = 17, 0xE3
#: Зачаровать можно только носимое (вид записи не больше этого).
WEARABLE_KIND_MAX = 8
#: Уровни: выше шестого не поднять, и с шестого камень уже не берётся.
LEVEL_MAX = 6
#: Навык 16 «Волхование» делится на это — вот и вся прибавка.
SORCERY_SKILL, SORCERY_SKILL_AT, SORCERY_DIVISOR = 16, 0xE2, 16

#: ПОРОШКИ (ветки применения VA 0x436C48, случаи по классу; вещь после
#: съедается — группа записи становится −1). Навыковые: класс -> (номер
#: навыка, прибавка, строка движка); кап всегда 100. Характеристические
#: (0x2A и 0x2F, FUN_00436BA8):插 постоянный подъём БАЗЫ и спрятанной копии
#: (+0xC6, чтобы возврат временного зелья не съел прибавку), кламп 0…150.
#: Класс 0x31 — не навык, а опыт: «Волхование × 3» через общее начисление
#: 0x413110.
POWDER_SKILLS = {
    0x28: {"skill": 17, "gain": 5,
           "message": "Ты познал секреты кузнечного дела"},
    0x2C: {"skill": 14, "gain": 10,
           "message": "Ты узнал много нового об искусстве торговли"},
    0x2D: {"skill": 11, "gain": 10,
           "message": "Ты открыл для себя секреты древних целителей"},
    0x30: {"skill": 18, "gain": 10,
           "message": "Ты познал секреты строительного искусства"},
    0x32: {"skill": 15, "gain": 10,
           "message": "Ты узнал много интересного о неведомых вещах"},
}
POWDER_CHARACTERISTICS = {
    0x2A: {"characteristic": 4, "gain": 3},    # Сила
    0x2F: {"characteristic": 0, "gain": 10},   # Харизма
}
POWDER_XP_CLASS, POWDER_XP_SKILL, POWDER_XP_SCALE = 0x31, 16, 3
#: Навык 12 «Приготовление смесей».
BREW_SKILL, BREW_SKILL_AT, BREW_CAP = 12, 0xDE, 100
#: Таблица рецептов.
RECIPES_VA, RECIPES_STRIDE, RECIPES_COUNT = 0x459FE4, 6, 30
#: Не нашлось пары — выходит это.
FAILED_MIX_CLASS = 84
#: Крепость: множитель навыка и потолок.
BREW_STEP, BREW_MAX = 0.01, 15.0
#: Способы пересчёта крепости.
BREW_FROM_SKILL, BREW_ADD_SKILL, BREW_SUM, BREW_MIN, BREW_OTHER_PLUS_SKILL = range(5)


def stone_group(item_class: int) -> int | None:
    """Какую группу прибавок поднимает камень."""
    return STONE_GROUPS.get(item_class)


def stone_step(sorcery: int) -> int:
    """На сколько поднимет камень при таком волховании."""
    return sorcery // SORCERY_DIVISOR


def enchant_with_stone(word: int, item_class: int, sorcery: int) -> int | None:
    """Вложить камень в вещь. None — нельзя (VA 0x436C48)."""
    from .enchant import DORMANT, GROUP_MASK
    shift = stone_group(item_class)
    if shift is None or word & DORMANT:
        return None
    level = (word >> shift) & GROUP_MASK
    if level > LEVEL_MAX - 1:
        return None
    level = min(LEVEL_MAX, level + stone_step(sorcery))
    return (word & ~(GROUP_MASK << shift)) | (level << shift)


def recipes(data: bytes | None = None) -> list[dict]:
    """Книга рецептов как есть."""
    from .exetables import va_to_foff
    from .paths import game_file
    if data is None:
        with open(game_file("konung2.exe"), "rb") as stream:
            data = stream.read()
    start = va_to_foff(RECIPES_VA)
    rows = []
    for index in range(RECIPES_COUNT):
        target, poured, result, left, gain, how = struct.unpack_from(
            "<6b", data, start + index * RECIPES_STRIDE)
        rows.append({"target": target & 0xFF, "poured": poured & 0xFF,
                     "result": result & 0xFF,
                     "left": (left & 0xFF) if left >= 0 else None,
                     "skill": gain, "strength": how})
    return rows


def mix(target_class: int, poured_class: int,
        rows: list[dict] | None = None) -> dict | None:
    """Что выйдет из этой пары. None — «Непонятная смесь»."""
    rows = rows if rows is not None else recipes()
    for row in rows:
        if row["target"] == target_class and row["poured"] == poured_class:
            return row
    return None


def rules() -> dict:
    """Правила варки и зачарования одним куском — для content pack."""
    from .exetables import va_to_foff
    from .paths import game_file
    with open(game_file("konung2.exe"), "rb") as stream:
        blob = stream.read()
    at = va_to_foff(MIXING_HINT_VA)
    hint = blob[at:blob.index(b"\x00", at)].decode("cp866", "replace")
    return {
        "policy": "konung2_exe_0x436c48_0x41b930",
        "slot": {"code": MIXING_CODE, "index": MIXING_SLOT, "hint": hint},
        "stones": {
            "groups": {str(item): shift for item, shift in STONE_GROUPS.items()},
            "whetstone": WHETSTONE_CLASS,
            "wearable_kind_max": WEARABLE_KIND_MAX,
            "level_max": LEVEL_MAX,
            "skill": SORCERY_SKILL, "divisor": SORCERY_DIVISOR,
        },
        # точило: потолок кузнеца, деградация и навык (VA 0x432DE0)
        "whetstone": {
            "class": WHETSTONE_CLASS,
            "target_kinds": WHETSTONE_TARGET_KINDS,
            "ceiling_per_skill": WHETSTONE_CEILING_PER_SKILL,
            "decay": WHETSTONE_DECAY,
            "skill": WHETSTONE_SKILL,
        },
        # порошки навыков, характеристик и опыта (VA 0x436C48)
        "powders": {
            "skills": {str(item): dict(row)
                       for item, row in POWDER_SKILLS.items()},
            "characteristics": {str(item): dict(row)
                                for item, row in POWDER_CHARACTERISTICS.items()},
            "experience": {"class": POWDER_XP_CLASS,
                           "skill": POWDER_XP_SKILL,
                           "scale": POWDER_XP_SCALE},
        },
        "brew": {
            "skill": BREW_SKILL, "cap": BREW_CAP,
            "step": BREW_STEP, "max": BREW_MAX,
            "failed": FAILED_MIX_CLASS,
            "how": {"from_skill": BREW_FROM_SKILL, "add_skill": BREW_ADD_SKILL,
                    "sum": BREW_SUM, "min": BREW_MIN,
                    "other_plus_skill": BREW_OTHER_PLUS_SKILL},
            "recipes": recipes(blob),
        },
    }
