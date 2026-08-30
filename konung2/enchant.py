# -*- coding: utf-8 -*-
"""
Зачарование вещей.

Разобрано по коду, ничего не подобрано.

ГДЕ ОНО ЛЕЖИТ. В записи предмета есть слово +0x0E, и это не число, а пять
уровней по три бита. Уровень от одного до шести, ноль — прибавки нет:

    биты 12-14  ->  поле 7   броня        (unit+0x42)
    биты  9-11  ->  поле 8   сила удара   (unit+0x44)
    биты  6-8   ->  поле 2   Ловкость
    биты  3-5   ->  поле 5   Сила
    биты  0-2   ->  поле 6   Выносливость

Величины лежат в таблице 0x45D530 по шестнадцать байт на запись: цена
прибавки, номер поля, маска и сама величина. Характеристикам достаётся от
+1 до +6, броне и силе удара — от +4 до +48.

Поля нумеруются с единицы: 1…6 — шесть характеристик по порядку, 7, 8 и 9
— три поля юнита, куда прибавки складываются отдельно от характеристик.

СТАРШИЙ БИТ слова (0x8000) — «магия не опознана». Пока он стоит, прибавок
нет вовсе (VA 0x41C494 такую вещь пропускает) и цена у неё обычная.

КАК ЭТО РАБОТАЕТ. Пересчёт идёт после любой смены снаряжения (VA
0x41C494): движок обнуляет общий счёт, проходит по пяти гнёздам и пяти
украшениям и складывает всё, что нашёл. Дальше:

    характеристики   текущие (+0xCC) = база (+0xC0) плюс прибавка, а если
                     маска обнулила флажок — прибавка ВМЕСТО базы
    три поля юнита   +0x42 броня, +0x44 сила удара, +0x46 точность

Читают их те же расчёты, что и всё остальное: броню VA 0x41A414, силу
удара VA 0x41A7D0 и 0x41A624, точность VA 0x41ADD8. У каждого своя
проверка: если поле не ноль, то бит байта +0xFA решает, ПРИБАВИТЬ его к
своему числу или ЗАМЕНИТЬ им своё, — бит 1 у брони, 2 у силы, 4 у
точности. В таблице все маски единичные, так что в игре прибавки
складываются.

ЦЕНА. Зачарование дорого стоит: VA 0x41ABBC берёт базовую цену класса и
прибавляет к ней цену каждой прибавки — но только у ОПОЗНАННОЙ вещи.
Неопознанная магия продаётся как простая железка.

ОПОЗНАНИЕ. Отдельного действия нет, оно случается само:

    у кучи на земле   подходя к ней (VA 0x4115AC), герой бросает по
                      каждой неопознанной вещи: удача, если бросок % 100
                      меньше навыка 15 «Идентификация предметов»
                      (unit+0xE1); удача снимает бит и поднимает навык на
                      единицу, но не выше сотни
    разом             VA 0x41B7C0 открывает всё, что при юните — гнёзда,
                      боеприпас, мешок и украшения, — и растит навык за
                      каждую вещь; зовут её из обработчика вещей вида 0x0B

ЧЕГО НЕТ. В записи есть ещё байт +0x01 со своей таблицей прибавок
(VA 0x41844C, таблица 0x45D430, до трёх прибавок в записи и своя цена), но
во всех четырёх стартовых мирах он у всех вещей 0xFF, то есть выключен.
Зачарование в игре раздано заранее, но НЕ навсегда: слово +0x0E пишут
пять веток обработчика камней (VA 0x436C48, классы 52…56) — каждая
поднимает свою группу прибавок. Правила этого разбора живут в
``konung2/craft.py``; здесь только чтение готового слова.
"""
from __future__ import annotations

import struct

#: Слово прибавок в записи предмета.
ENCHANT_AT = 0x0E
#: Старший бит: магия не опознана.
DORMANT = 0x8000
#: (сдвиг, номер раздела таблицы) — по порядку, как их читает движок.
GROUPS = ((12, 0), (9, 6), (6, 12), (3, 18), (0, 24))
GROUP_MASK, GROUP_LEVELS = 0x7, 6
#: Таблица прибавок.
TABLE_VA, TABLE_STRIDE = 0x45D530, 0x10
#: Вторая таблица — по байту +0x01 записи предмета И ПО ФЛАГАМ ЮНИТА.
#:
#: Прежняя пометка «в стартовых мирах не работает» неверна и снята 19.08.2026:
#: предметы с ненулевым байтом +0x01 там и правда не встречаются, но по этой
#: же таблице считаются КВЕСТОВЫЕ ФЛАГИ. Пересчёт характеристик 0x41C494:72-74
#: перед каждым расчётом делает `if (юнит[+0xF9] != 0) FUN_0041844C(+0xF9)` —
#: то есть скармливает разборщику флаговый байт наравне с номером прибавки
#: предмета. Отсюда и берётся благословение волхва, которого тестеры не
#: дождались: разговор поднимает флаг 1 (обработчик 34), а прибавку даёт
#: таблица.
#:
#: Разборщик 0x41844C: значение 1…15 — это МАСКА, и он проходит по битам
#: 8, 4, 2, 1, беря строку по САМОМУ БИТУ (строка = база + бит * 16). Значение
#: 0 или больше 15 — номер прибавки предмета, тогда строка берётся по нему
#: целиком. Поэтому строки 3, 5…7, 9…15 не читает никто: до них не доводит ни
#: один путь, и лежит там мусор от соседей.
SECOND_TABLE_VA, SECOND_BYTE_AT = 0x45D430, 0x01

#: Поля: 1…6 характеристики, дальше три поля юнита.
FIELD_ARMOUR, FIELD_STRIKE, FIELD_ACCURACY = 7, 8, 9
FIELD_UNIT_AT = {FIELD_ARMOUR: 0x42, FIELD_STRIKE: 0x44, FIELD_ACCURACY: 0x46}
#: Бит байта +0xFA: стоит — прибавить, снят — заменить.
MODE_AT = 0xFA
MODE_BIT = {FIELD_ARMOUR: 1, FIELD_STRIKE: 2, FIELD_ACCURACY: 4}
#: Характеристики: база и текущие.
BASE_AT, CURRENT_AT = 0xC0, 0xCC
#: Квестовые флаги юнита: байт +0xF9 (обработчик 34 ставит, 42 снимает).
FLAGS_AT = 0xF9
#: Опознание: навык 15, бросок против него, потолок сотня.
IDENTIFY_SKILL, IDENTIFY_SKILL_AT, IDENTIFY_CAP = 15, 0xE1, 100


def table(data: bytes | None = None) -> list[dict]:
    """Записи таблицы прибавок как есть."""
    from .exetables import va_to_foff
    from .paths import game_file
    if data is None:
        with open(game_file("konung2.exe"), "rb") as stream:
            data = stream.read()
    start = va_to_foff(TABLE_VA)
    rows = []
    for index in range(len(GROUPS) * GROUP_LEVELS):
        price, field, mask, value = struct.unpack_from(
            "<IBBH", data, start + index * TABLE_STRIDE)
        rows.append({"index": index, "price": price, "field": field,
                     "mask": mask, "value": value})
    return rows


#: Сколько строк второй таблицы печём. Флагам хватает первых шестнадцати:
#: маска байта +0xF9 больше 15 быть не может, а номера прибавок предметов —
#: отдельная работа, их в стартовых мирах нет.
BONUS_ROWS = 16
#: Тройки в строке: три штуки, по четыре байта — стат, режим, величина.
BONUS_TRIPLES, BONUS_TRIPLE_AT = 3, 4


def bonus_table(data: bytes | None = None) -> list[list[dict]]:
    """Строки второй таблицы: строка -> список прибавок «стат, режим, величина».

    Пустые тройки (стат 0) выброшены: разборщик их пропускает первой же
    проверкой `if (стат != 0)`.
    """
    from .exetables import va_to_foff
    from .paths import game_file
    if data is None:
        with open(game_file("konung2.exe"), "rb") as stream:
            data = stream.read()
    start = va_to_foff(SECOND_TABLE_VA)
    rows = []
    for index in range(BONUS_ROWS):
        at = start + index * TABLE_STRIDE
        triples = []
        for k in range(BONUS_TRIPLES):
            field, mode, value = struct.unpack_from(
                "<BBh", data, at + BONUS_TRIPLE_AT + k * 4)
            if field:
                triples.append({"field": field, "mode": mode, "value": value})
        rows.append(triples)
    return rows


def levels(word: int) -> dict[int, int]:
    """Уровни прибавок в слове: сдвиг -> уровень. Неопознанное молчит.

    Верхней границы движок НЕ проверяет: единственное условие — уровень не
    ноль (VA 0x41C4xx и 0x41ABBC, во всех пяти группах одинаково). Значение
    7 он честно индексирует таблицей и читает строку соседнего раздела;
    прежний отсев «больше шести — пропустить» был нашей выдумкой.
    """
    if word & DORMANT:
        return {}
    out = {}
    for shift, _ in GROUPS:
        level = (word >> shift) & GROUP_MASK
        if level:
            out[shift] = level
    return out


def bonuses(word: int, rows: list[dict] | None = None) -> dict[int, int]:
    """Что даёт слово: поле -> величина."""
    if word & DORMANT:
        return {}
    rows = rows if rows is not None else table()
    out: dict[int, int] = {}
    for shift, section in GROUPS:
        level = (word >> shift) & GROUP_MASK
        if not level:
            continue
        row = rows[section + level - 1]        # уровень 7 читает соседний раздел
        out[row["field"]] = out.get(row["field"], 0) + row["value"]
    return out


def price_bonus(word: int, rows: list[dict] | None = None) -> int:
    """Насколько зачарование дороже пустой вещи (VA 0x41ABBC)."""
    if word & DORMANT:
        return 0
    rows = rows if rows is not None else table()
    total = 0
    for shift, section in GROUPS:
        level = (word >> shift) & GROUP_MASK
        if level:
            total += rows[section + level - 1]["price"]
    return total


def identified(word: int) -> bool:
    """Опознана ли магия вещи."""
    return not word & DORMANT


def identify(word: int) -> int:
    """Снять признак «не опознано»."""
    return word & ~DORMANT


def rules() -> dict:
    """Правила зачарования одним куском — для content pack."""
    rows = table()
    return {
        "policy": "konung2_exe_0x41c494_0x41abbc_0x4115ac",
        "at": ENCHANT_AT, "dormant": DORMANT, "levels": GROUP_LEVELS,
        "groups": [{"shift": shift, "section": section} for shift, section in GROUPS],
        "table": rows,
        # Флаги юнита (+0xF9) считаются ПО ЭТОЙ ЖЕ таблице, что и номер
        # прибавки предмета: разборщик у них один (0x41844C).
        "flags_at": FLAGS_AT,
        "bonus_table": bonus_table(),
        "bonus_by_bit": True,
        "fields": {"armour": FIELD_ARMOUR, "strike": FIELD_STRIKE,
                   "accuracy": FIELD_ACCURACY,
                   "unit_at": FIELD_UNIT_AT,
                   "mode_at": MODE_AT, "mode_bit": MODE_BIT},
        "characteristics": {"base_at": BASE_AT, "current_at": CURRENT_AT},
        "identify": {"skill": IDENTIFY_SKILL, "at": IDENTIFY_SKILL_AT,
                     "cap": IDENTIFY_CAP},
    }
