# -*- coding: utf-8 -*-
"""
Бой: точность удара и летящие снаряды.

ТОЧНОСТЬ. Расчёт удара (VA 0x41BF54) получает её отдельным числом, и это не
поле юнита: в записи юнита +0x1F почти у всех ноль. Считает её VA 0x41ADD8,
а сердце расчёта — VA 0x41B4CC, где наконец работают двадцать навыков:

    ближний бой (unit+0x58)
        пусто или у предмета нет слоя  ->  навык 0  Рукопашный бой
        слой < 0x0D (одноручное):
            вид на земле 166 (клинки)  ->  навык 3  Владение мечом
            154 (топоры)               ->  навык 4  Владение топором
            иначе                      ->  навык 5  Владение дубиной
        слой >= 0x0D (двуручное):
            166 -> навык 6, 154 -> навык 7, иначе -> навык 8

    метательное (unit+0x5A)
        слой 0x15 (самострел)          ->  навык 9  Стрельба из арбалета
        иначе                          ->  навык 10 Стрельба из лука

Дальше VA 0x41ADD8 правит это число. При стрельбе — и только когда юнит
в режиме стрельбы, метательное надето и цель не вплотную — оно ВЫЧИТАЕТ
небольшой штраф ``дальность_до_цели * 0.3 / дальность_оружия``
(VA 0x41AE7F…0x41AEAC, константа 0x450094 = 0.3), а не делит навык на долю
дальности. Потом прибавляет модификаторы (unit+0x4A и +0x46) и зажимает
итог между пятью и девяноста пятью (VA 0x41AF0D).

У зверей (``unit+0x1A & 0x40``) навыков нет, и точность считается прямо из
Ловкости: ``100 − (100 − Ловкость·0.5)·0.5``, то есть ``50 + Ловкость/4``
(VA 0x41ADED, константы 0x450084 = 0.5 и 0x45008C = 100). Эта ветка выходит
из функции сразу и под клемп не попадает.

СНАРЯДЫ. Летящие стрелы в движке есть — я их раньше не нашёл. Их массив
0x833AE8, до ста штук по 32 байта, создаёт VA 0x41BB10:

    +0x00  float  шаг по X за такт          +0x04  float шаг по Y
    +0x08  float  X снаряда                 +0x0C  float Y
    +0x14  u16    номер юнита-стрелка
    +0x16  u16    отрава из записи боеприпаса
    +0x18  i16    жребий разброса
    +0x1A  u8     кадр: направление юнита * 2 − 0x48
    +0x1B  u8     сторона стрелка
    +0x1C  u8     из класса метательного (+0x10)
    +0x1D  u8     вид боеприпаса            +0x1E  u8 его класс
    +0x1F  u8     ТОЧНОСТЬ этого выстрела

Точка вылета берётся от юнита (+0x36 и +0x3E) со смещением по направлению:
у лука таблица 0x45FACD, у самострела 0x45D40C. Шаг делится на длину пути,
поэтому снаряд летит по прямой. Каждый выстрел изнашивает оружие, и на
нуле прочности лук ломается (VA 0x41BB94).
"""
from __future__ import annotations

#: Блок навыков в юните и номера тех, что решают точность.
SKILLS_AT = 0xD2
SKILL_HAND, SKILL_SWORD, SKILL_AXE, SKILL_CLUB = 0, 3, 4, 5
SKILL_TWO_SWORD, SKILL_TWO_AXE, SKILL_TWO_CLUB = 6, 7, 8
SKILL_CROSSBOW, SKILL_BOW = 9, 10

#: Слои: с 0x0D начинается двуручное, 0x15 — самострелы.
TWO_HAND_FROM_LAYER, CROSSBOW_LAYER = 0x0D, 0x15
#: Броню даёт только НАСТОЯЩИЙ щит. Одежда и доспех складываются без
#: проверок, а третий слот — лишь когда вид записи равен четырём
#: (VA 0x41A414: ``if ((iVar1 != 0) && (*(int *)(&DAT_006f9569 + iVar1 *
#: 0x10) >> 0x18 == 4))``; сдвиг на 0x18 от base-3 читает байт +0 записи,
#: то есть вид). Иначе одноручное оружие во второй руке, которое порт сам
#: разрешает при навыке «Бой двумя руками», давало бы броню по своей силе.
SHIELD_KIND = 4
#: «Вид на земле» решает семейство оружия (поле класса +0x18).
GROUND_BLADE, GROUND_AXE = 166, 154
#: Точность зажата между пятью и девяноста пятью (VA 0x41AF0D: ``> 0x5F``
#: заменяется на 0x5F, ``< 5`` — на 5).
ACCURACY_FLOOR, ACCURACY_CAP = 5, 0x5F
#: Штраф за дальность при стрельбе: ``дистанция * 0.3 / дальность оружия``
#: (VA 0x41AE85, константа 0x450094).
RANGE_PENALTY = 0.3
#: Точность зверя: ``100 − (100 − Ловкость·0.5)·0.5`` (VA 0x41ADFB,
#: константы 0x450084 = 0.5 и 0x45008C = 100).
BEAST_ACCURACY_FACTOR, BEAST_ACCURACY_BASE = 0.5, 100.0

#: ИЗНОС СНАРЯЖЕНИЯ при попадании. Оба резолвера после урона снимают
#: прочность (float +0x04 записи) с трёх гнёзд жертвы — тех же, что дают
#: броню: ``for (local_1c = 2; local_1c < 5; ...)`` читает u16 по +0x5C,
#: +0x5E, +0x60 (VA 0x41C194 ближний, 0x41BF54 стрелковый). Величина —
#: ``доля * сила_класса * 0.001``, где доля это ``min(1, сила_удара /
#: броня)`` (при нулевой броне единица, ``local_24``). На нуле прочности
#: запись метится пустой, а гнездо очищается — вещь уничтожается.
#:
#: Ближний резолвер вдобавок изнашивает ОРУЖИЕ атакующего на
#: ``сила_удара * 0.00025`` и убавляет на единицу заряд отравы (u16 +0x0C
#: записи), если он не нулевой. У стрелкового этого нет: лук стачивает сам
#: выстрел (VA 0x41BB94).
#:
#: Множители — восьмибайтовые константы exe: 0x450180 и 0x450158 равны
#: 0.001, 0x450188 равен 0.00025 (проверено чтением байт).
ARMOUR_WEAR_SCALE = 0.001
WEAPON_WEAR_SCALE = 0.00025
#: Гнёзда жертвы, которые изнашиваются, — те же три, что дают броню.
WEAR_SLOTS = ("body", "head", "off_hand")

#: «Смертельный удар» (навык 2, ``unit+0xD4``): ближний резолвер
#: (VA 0x41C194) после парирования бросает ``rand() % 100`` против
#: ``навык / 10`` атакующего — не больше порога значит мгновенная смерть,
#: минуя урон, броню, отраву и износ. Стрелковый резолвер (VA 0x41BF54)
#: этой проверки не имеет.
DEADLY_SKILL, DEADLY_DIVISOR = 2, 10

#: Парирование. Ближний удар отбивается только «в лицо»: пара направлений
#: должна стоять в таблице 0x459F94 (8×8 байт, строка — направление жертвы,
#: столбец — атакующего; в каждой строке три единицы напротив лица, удар со
#: спины не парируется вовсе), а порог — ``ROUND(Ловкость жертвы × 0.5)``
#: (double по 0x450160, округление сопроцессора к чётному) против
#: ``rand % 0x65`` (VA 0x41C1E8…0x41C230, снято дизасмом). Стрелковый
#: резолвер парирует с любой стороны порогом ``Ловкость × 0.1``
#: (0x450138) без округления (VA 0x41BF75).
PARRY_DIRECTIONS_VA = 0x459F94
PARRY_MELEE_SCALE, PARRY_RANGED_SCALE = 0.5, 0.1

#: СИЛА УДАРА (0x41A7D0) — прибавка от ТЕКУЩЕЙ Силы (+0xD0) и здоровья:
#: с оружием и у зверя round(Сила · 0.04 · здоровье · 0.0625) поверх power
#: класса, голым кулаком сила = round(Сила · 0.02 · здоровье · 0.0625) —
#: вдвое слабее. Раненый бьёт слабее. Doubles 0x450054/5C (зверь),
#: 0x450064/6C (оружие), 0x450074/7C (кулак); у стрельбы (0x41A52C)
#: члена Силы НЕТ — там power снаряда × power метательного.
STRENGTH_TERM_WEAPON = 0.04
STRENGTH_TERM_FIST = 0.02
STRENGTH_TERM_HEALTH = 0.0625
STRENGTH_TERM_VA = (0x450064, 0x450074, 0x45006C)

#: УБИЙЦЫ ПОРОД (0x41A7D0: знаковый байт +2 ЗАПИСИ предмета — индекс в
#: таблице 0x4624F8/0x4624FC, шаг 0x20): если у оружия индекс ≥ 0 и порода
#: жертвы совпала — вместо power класса берётся особая сила. Механика
#: СПЯЩАЯ: аллокатор записей (0x43B6D8) кладёт в +2 минус единицу, ни один
#: разобранный код и ни один предмет шести стартовых миров индекса не
#: несёт (индекс 0 у стрел — метка МАСЛА, прицел и поджог читают его в
#: 0x428B88/0x421690, к силе он не применяется — стрельба идёт другим
#: расчётом). Таблица: (особая сила, порода жертвы).
SLAYER_TABLE_VA = 0x4624F8
SLAYER_TABLE = (
    (0, 0),        # 0 — пустая строка (её же занимает метка масла у стрел)
    (5000, 83),
    (500, 65),
    (3000, 70),
    (2000, 77),
    (3000, 78),
    (3500, 73),
    (4000, 75),
)


def parry_directions(data: bytes | None = None) -> list[list[int]]:
    """Таблица 0x459F94: можно ли жертве парировать удар с этой пары сторон."""
    from .exetables import va_to_foff
    from .paths import game_file
    if data is None:
        with open(game_file("konung2.exe"), "rb") as stream:
            data = stream.read()
    offset = va_to_foff(PARRY_DIRECTIONS_VA)
    return [[data[offset + row * 8 + col] for col in range(8)]
            for row in range(8)]
#: Удар двумя руками: в блоке анимации 9 ДВА ударных кадра — байт 0x45FE98
#: (0xF9) несёт кадр правой в старшем полубайте (7) и кадр левой в младшем
#: (9); левая бьёт слотом 4 (VA 0x412480), её точность — третий режим
#: 0x41B4CC: ``Бой двумя руками (+0xD3) × одноручный навык / 100``.
#: У остальных блоков ударный кадр один (таблица 0x45FE90).
DOUBLE_STRIKE_FRAMES_VA = 0x45FE98
DOUBLE_STRIKE_MAIN_FRAME, DOUBLE_STRIKE_OFF_FRAME = 7, 9

#: МОЖНО ЛИ ВЫСТРЕЛИТЬ (VA 0x414AF8). Три условия подряд:
#:
#:   1. до цели не меньше трёх клеток — в упор не стреляют (VA 0x414B22);
#:   2. дальше дальности оружия (класс +0x10) — тоже нет, у зверей вместо
#:      неё жёсткие сорок (VA 0x414B45);
#:   3. траектория чиста: движок шагает от стрелка к цели той же формулой
#:      «пиксель → клетка» и на первой же клетке с битом 0x4000 стрельбу
#:      отменяет (VA 0x414BA4) — это тот самый бит «стена или постройка»,
#:      по которому считается и попадание зажигательной стрелы.
RANGED_MIN_CELLS = 3
BEAST_RANGE_CELLS = 0x28
LINE_OF_FIRE_BLOCKER = 0x4000
#: Сколько подшагов делает трассировка на каждую клетку пути.
LINE_OF_FIRE_SUBSTEPS = 8

#: Массив снарядов.
PROJECTILES_VA, PROJECTILE_STRIDE, PROJECTILE_LIMIT = 0x833AE8, 0x20, 100
#: Картинка снаряда — спрайт INTERF.RES с номером ``направление * 2 − 0x48``
#: как БЕЗЗНАКОВОГО байта, плюс 0 или 1 по кадру мигания (VA 0x424454).
#: Получаются 184…199: по два кадра на каждое из восьми направлений.
PROJECTILE_SPRITE_BASE, PROJECTILE_FRAMES = 0x48, 2
#: Скорость: шаг делится на |смещение| * 0.25, то есть примерно четыре
#: пикселя за ПОДШАГ (VA 0x41BB94, константа 0x450128), а за такт движок
#: делает восемь подшагов (VA 0x41FE30) — выходит около клетки за такт.
PROJECTILE_SPEED = 4.0
PROJECTILE_SUBSTEPS = 8
#: Каждый выстрел изнашивает оружие на 0.1 (константа 0x450124), и на нуле
#: прочности лук ломается: его запись помечается 0xFF, а слот очищается.
PROJECTILE_WEAR = 0.1
#: РАСХОД СТРЕЛ. Он лежит не в самом выстреле, а в такте анимации
#: (VA 0x413894, ветки блоков 4 и 10 — лук и самострел): на кадре выстрела
#: движок зовёт создание снаряда и, если оно удалось, уменьшает счётчик
#: пачки на единицу. Счётчик — поле +0x04 ЗАПИСИ ПРЕДМЕТА (у носимых вещей
#: там прочность, у стопок — количество; цена стрел тоже считается по нему,
#: VA 0x41ABBC). Когда пачка кончилась, движок ищет в мешке следующую
#: (VA 0x41291C). Кадр выстрела — шестой с конца анимации.
AMMO_COUNT_AT = 0x04
AMMO_SHOT_FRAME_FROM_END = 6
#: Ближний удар приходит на ПРЕДПОСЛЕДНЕМ кадре анимации (VA 0x413894,
#: строка `кадр == число_кадров − 2`), а не в её середине. Выстрел, для
#: сравнения, срывается на шестом с конца — оттого замах и виден дольше.
MELEE_HIT_FRAME_FROM_END = 2
#: В стартовых мирах все пачки по тридцать штук (проверено по GAME.0: 342
#: записи вида 0x0C, у всех тридцать).
AMMO_STACK = 30
#: Снаряд живёт столько тактов, какова ДАЛЬНОСТЬ оружия в клетках: движок
#: кладёт её в запись (+0x1C = класс метательного +0x10) и уменьшает каждый
#: такт, а на нуле снаряд пропадает (VA 0x41FE03) — это и есть промах мимо.


def projectile_sprite(direction: int, frame: int = 0) -> int:
    """Номер спрайта INTERF.RES для летящего снаряда."""
    return ((direction * 2 - PROJECTILE_SPRITE_BASE) & 0xFF) + (frame & 1)


def weapon_skill(layer: int | None, ground: int | None, ranged: bool = False) -> int:
    """Какой навык отвечает за этот предмет (VA 0x41B4CC)."""
    if ranged:
        return SKILL_CROSSBOW if layer == CROSSBOW_LAYER else SKILL_BOW
    if not layer:
        return SKILL_HAND
    if layer < TWO_HAND_FROM_LAYER:
        if ground == GROUND_BLADE:
            return SKILL_SWORD
        if ground == GROUND_AXE:
            return SKILL_AXE
        return SKILL_CLUB
    if ground == GROUND_BLADE:
        return SKILL_TWO_SWORD
    if ground == GROUND_AXE:
        return SKILL_TWO_AXE
    return SKILL_TWO_CLUB


def beast_accuracy(dexterity: int) -> int:
    """Точность зверя — только из Ловкости, без клемпа (VA 0x41ADED)."""
    value = BEAST_ACCURACY_BASE - (BEAST_ACCURACY_BASE -
                                   dexterity * BEAST_ACCURACY_FACTOR) * BEAST_ACCURACY_FACTOR
    return int(round(value))


def accuracy(skills, layer=None, ground=None, ranged=False,
             distance: float = 0.0, reach: float = 0.0) -> int:
    """Точность удара (VA 0x41ADD8).

    Навык оружия, а при стрельбе — минус штраф за дальность. Штраф работает
    только когда цель не вплотную (``distance != 0``) и у оружия задана
    дальность; итог зажат между пятью и девяноста пятью.
    """
    index = weapon_skill(layer, ground, ranged)
    value = skills[index] if index < len(skills) else 0
    if ranged and distance and reach:
        value = int(round(value - distance * RANGE_PENALTY / reach))
    return min(ACCURACY_CAP, max(ACCURACY_FLOOR, value))


def rules() -> dict:
    """Правила точности одним куском — для content pack."""
    return {
        "policy": "konung2_exe_0x41B4CC_0x41ADD8",
        "skills_at": SKILLS_AT,
        "floor": ACCURACY_FLOOR,
        "cap": ACCURACY_CAP,
        "range_penalty": RANGE_PENALTY,
        "ranged_min_cells": RANGED_MIN_CELLS,
        "beast_range_cells": BEAST_RANGE_CELLS,
        "line_of_fire": {"blocker": LINE_OF_FIRE_BLOCKER,
                         "substeps": LINE_OF_FIRE_SUBSTEPS},
        "beast_accuracy": {"factor": BEAST_ACCURACY_FACTOR,
                           "base": BEAST_ACCURACY_BASE},
        # мгновенное убийство ближнего удара (VA 0x41C194)
        "deadly": {"skill": DEADLY_SKILL, "divisor": DEADLY_DIVISOR},
        # парирование: ближнее — по таблице направлений, стрелковое — всегда
        "parry": {"melee_scale": PARRY_MELEE_SCALE,
                  "ranged_scale": PARRY_RANGED_SCALE,
                  "directions": parry_directions()},
        # прибавка силы удара от текущей Силы и здоровья (0x41A7D0)
        "strength_term": {"weapon": STRENGTH_TERM_WEAPON,
                          "fist": STRENGTH_TERM_FIST,
                          "health": STRENGTH_TERM_HEALTH},
        # спящая таблица «убийц пород» — для полноты канона
        "slayers": [list(row) for row in SLAYER_TABLE],
        "two_hand_from_layer": TWO_HAND_FROM_LAYER,
        "crossbow_layer": CROSSBOW_LAYER,
        "shield_kind": SHIELD_KIND,
        # износ снаряжения при попадании (0x41C194, 0x41BF54)
        "wear": {"armour": ARMOUR_WEAR_SCALE, "weapon": WEAPON_WEAR_SCALE,
                 "slots": list(WEAR_SLOTS)},
        "ground": {"blade": GROUND_BLADE, "axe": GROUND_AXE},
        "skill": {
            "hand": SKILL_HAND, "sword": SKILL_SWORD, "axe": SKILL_AXE,
            "club": SKILL_CLUB, "two_sword": SKILL_TWO_SWORD,
            "two_axe": SKILL_TWO_AXE, "two_club": SKILL_TWO_CLUB,
            "crossbow": SKILL_CROSSBOW, "bow": SKILL_BOW,
        },
        "projectiles": {
            "at": PROJECTILES_VA, "stride": PROJECTILE_STRIDE,
            "limit": PROJECTILE_LIMIT, "speed": PROJECTILE_SPEED,
            "substeps": PROJECTILE_SUBSTEPS, "wear": PROJECTILE_WEAR,
            "ammo_stack": AMMO_STACK,
            "shot_frame_from_end": AMMO_SHOT_FRAME_FROM_END,
            "melee_hit_frame_from_end": MELEE_HIT_FRAME_FROM_END,
            "sprites": [[projectile_sprite(direction, frame)
                         for frame in range(PROJECTILE_FRAMES)]
                        for direction in range(8)],
        },
    }
