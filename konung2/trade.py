# -*- coding: utf-8 -*-
"""
Торговля: экран обмена, деньги и цены.

Разобрано по коду, ничего не подобрано.

ОТКРЫТИЕ ЭКРАНА. Обработчик разговора 38 (VA 0x43346C) готовит обмен и
ставит номер экрана 7:

    деньги игрока      int по +0x26 записи ОТРЯДА (не юнита)
    монеты в мешке     считаются по 50 за штуку: предмет вида 0x0B
                       класса 0x24 (VA 0x433489)
    левая сторона      копия мешка игрока (unit+0x62, 42 слова)
    правая сторона     зависит от собеседника:
        должность 2…4  прилавок деревни: +0x3E0 (22 места), +0x40E (32),
                       +0x44E (39) — по должности торговца, деньги «без
                       предела» (999999)
        прочий юнит    его мешок и его же деньги (+0x26)
    режим              0x849624: должность торговца, со знаком минус, если
                       флаги деревни торговать не дают (обработчик 28), и 6
                       у обычного обмена

Тем же экраном 7 открывается куча на земле (VA 0x424128): правая сторона —
её предметы с +0x11 записи кучи, денег у кучи нет.

ЦЕНЫ. Обе стороны считаются от базовой цены предмета (поле класса +0x12) с
поправкой на разницу навыка ТОРГОВЛЯ (unit+0xE0, он же навык 14) между
игроком и торговцем:

    сколько дадут игроку   VA 0x41A6CC:
        база * 0.5 * (1 + (торговля игрока − торговля торговца) * 0.002)
        и ещё * 0.666667, если торговец деревенский

    сколько просят с него  VA 0x41AF3C:
        база * (1 − (торговля игрока − торговля торговца) * 0.002)
        и ещё * 1.5, если торговец деревенский

Числа лежат подряд: 0x45003C и 0x45009C — шаг за навык, 0x450044 — половина,
0x45004C и 0x4500A4 — деревенские множители.

СДЕЛКА. Экран сам подгоняет монеты: пока стороны неравны, монеты по одной
переезжают из кошелька на стол (VA 0x42C2AC), поэтому обмен всегда сходится
в ноль.

ЭКРАН (VA 0x42C2AC рисует, 0x43AEF0 ловит мышь). Он занимает окно мира
целиком и держит ЧЕТЫРЕ РЯДА по девять видимых ячеек:

    ряд 2  вверху    товар собеседника
    ряд 3            что он отдаёт
    ряд 1            что отдаю я
    ряд 0  внизу     мой мешок

В каждом ряду сорок два места, видно девять, по краям стрелки прокрутки —
те же спрайты, что у пояса. Ячейка 70x71, шаг 69 — тоже как у пояса.
Прямоугольники рядов лежат в exe (0x462DD0, по четыре числа), кнопки — в
0x462DA0, шесть чисел — в 0x462E20.

ЩЕЛЧОК по вещи перекладывает её в парный ряд: 0 <-> 1 у меня, 2 <-> 3 у
него, а исходный ряд уплотняется. Вещь с нулевой ценой из мешка не
берётся — квестовое не продаётся. Правая кнопка мыши показывает описание.

КНОПКИ две: «Ok» (спрайт 182, код 201) закрывает сделку, «Закрыть»
(спрайт 180, код 200) возвращает всё по местам. Обе зовут VA 0x41F638:

    отказ    ряды 0 и 1 возвращаются мне, ряды 2 и 3 — собеседнику
    сделка   ряд 3 уходит в мой мешок, ряд 1 — собеседнику; у деревенского
             торговца проданное просто пропадает, а купленное вычёркивается
             с прилавка: у него товар со склада и денег без счёта
    проверки не больше сорока двух вещей и тот же предел веса, что в
             мешке; иначе «Превышен вес» или «Под ногами у тебя нет места
             для вещей!»

НАВЫК. Удачная сделка учит торговать обоих: навык 14 растёт на СУММУ
СДЕЛКИ, делённую на 1024, и упирается в сотню (VA 0x41F638).
"""
from __future__ import annotations

import struct

from .paths import game_file

#: Экран обмена.
TRADE_SCREEN = 7
#: Деньги отряда и монета в мешке.
PARTY_MONEY_AT = 0x26
COIN_KIND, COIN_CLASS, COIN_VALUE = 0x0B, 0x24, 50
#: Виды записи предмета, которые 0x41ABBC считает по-особому:
#: стопка идёт за количество, зелье — за крепость с восьмикратным
#: множителем, монета — просто по цене класса.
STACK_KIND, POTION_KIND = 0x0C, 0x09
#: Размер пачки боеприпаса в стартовых мирах (konung2/combat.py).
AMMO_STACK = 30
#: Навык «Торговля» — байт unit+0xE0 (он же четырнадцатый навык с +0xD2).
TRADE_SKILL_AT, TRADE_SKILL_INDEX = 0xE0, 14
#: Прилавки деревни: должность -> (смещение, сколько мест).
COUNTERS = {2: (0x3E0, 0x16), 3: (0x40E, 0x20), 4: (0x44E, 0x27)}
#: Экран: фон, кнопки и ряды ячеек.
SCREEN_SPRITE = 6
BUTTON_RECTS_VA, COLUMN_RECTS_VA, NUMBER_RECTS_VA = 0x462DA0, 0x462DD0, 0x462E20
#: Кнопки: (спрайт, спрайт нажатой, код, что делает).
BUTTONS = ((180, 181, 200, "refuse"), (182, 183, 201, "deal"))
#: Ряды: сколько их, сколько мест и сколько видно разом.
COLUMNS, COLUMN_SLOTS, COLUMN_VISIBLE = 4, 42, 9
#: Ячейка и шаг — те же, что у пояса.
CELL_WIDTH, CELL_HEIGHT, CELL_PITCH = 0x46, 0x47, 0x45
#: Стрелки прокрутки — те же спрайты, что у пояса.
ARROW_SPRITES = {"left": (18, 19), "right": (20, 21)}
#: Коды мыши: ячейка, левая и правая стрелки.
CODE_CELL, CODE_LEFT, CODE_RIGHT = 0x41, 0x1D, 0x1E
#: Ряды: что где и кто с кем в паре.
COLUMN_MY_BAG, COLUMN_MY_OFFER, COLUMN_HIS_STOCK, COLUMN_HIS_OFFER = 0, 1, 2, 3
COLUMN_PAIR = {0: 1, 1: 0, 2: 3, 3: 2}
#: Порядок сверху вниз — по их прямоугольникам.
COLUMN_ORDER = (COLUMN_HIS_STOCK, COLUMN_HIS_OFFER, COLUMN_MY_OFFER, COLUMN_MY_BAG)
#: Навык торговли растёт на сумму сделки, делённую на это, и не выше сотни.
SKILL_PER_DEAL, SKILL_CAP = 1024, 100
#: Сообщения движка при закрытии сделки (VA 0x41F638). Каждое стоит на
#: своей проверке, и путать их нельзя:
#:     weight     0x4502B3  вес не влезает в предел выносливости
#:     pile_full  0x4502C0  в куче под ногами больше 42 мест не бывает
#:     too_little 0x4502E7  моя сторона дешевле его — торговец не согласен
MESSAGES = {
    "weight": "Превышен вес",
    "pile_full": "Под ногами у тебя нет места для вещей!",
    "too_little": "Слишком мало даешь!",
}
MESSAGE_VA = {"weight": 0x4502B3, "pile_full": 0x4502C0, "too_little": 0x4502E7}

#: Кто торгует по НАСТОЯЩИМ ценам, а кто по базовым (VA 0x41A6CC, 0x41AF3C,
#: 0x41F638:74 — проверка одинаковая). Смысл гейта — «ПАРТНЁР ЖИВ»: бит
#: 0x80 в породе ``unit+0x1A`` ставит смерть зверя, а байт ``unit+0x17`` —
#: НАБОР АНИМАЦИИ, и 3/0x0B/0x0C — это его позы смерти. У ТРУПА ни навык
#: торговли, ни деревенские множители не применяются, а главное — за этим
#: же гейтом стоит и проверка «Слишком мало даешь!»: обыск убитого всегда
#: бесплатный, цена остаётся базовой, как у кучи на земле.
PRICE_GATE_FLAG_AT, PRICE_GATE_FLAG = 0x1A, 0x80
PRICE_GATE_TYPE_AT = 0x17
PRICE_GATE_TYPES = (3, 0x0B, 0x0C)
#: Режим торга (0x849624): должность деревенского торговца 2…4, со знаком
#: минус, если флаги деревни торговать не дают, и 6 у обычного обмена.
#: Деревенские множители применяются, только когда режим ПОЛОЖИТЕЛЕН.
TRADE_MODE_ORDINARY = 6
TRADE_MODE_AT = 0x849624

#: Множители цены (double в exe).
SKILL_STEP_VA, HALF_VA, VILLAGE_SELL_VA = 0x45003C, 0x450044, 0x45004C
SKILL_STEP_BUY_VA, VILLAGE_BUY_VA = 0x45009C, 0x4500A4


def constants(data: bytes | None = None) -> dict[str, float]:
    """Множители цены прямо из exe."""
    from .exetables import va_to_foff
    if data is None:
        with open(game_file("konung2.exe"), "rb") as stream:
            data = stream.read()
    read = lambda va: struct.unpack_from("<d", data, va_to_foff(va))[0]
    return {
        "skill_step_sell": read(SKILL_STEP_VA),
        "half": read(HALF_VA),
        "village_sell": read(VILLAGE_SELL_VA),
        "skill_step_buy": read(SKILL_STEP_BUY_VA),
        "village_buy": read(VILLAGE_BUY_VA),
    }


def item_price(base: int, enchant_word: int = 0) -> int:
    """Цена вещи с её зачарованием (VA 0x41ABBC).

    Прибавки стоят денег, но только у ОПОЗНАННОЙ вещи: неопознанная магия
    продаётся как простая железка.
    """
    from .enchant import price_bonus
    return base + price_bonus(enchant_word)


def sell_price(base: int, hero_trade: int, merchant_trade: int,
               village: bool = True, numbers: dict[str, float] | None = None) -> int:
    """Сколько дадут игроку за предмет (VA 0x41A6CC)."""
    numbers = numbers or constants()
    price = base * numbers["half"] * (
        1.0 + (hero_trade - merchant_trade) * numbers["skill_step_sell"])
    if village:
        price *= numbers["village_sell"]
    return int(round(price))


def buy_price(base: int, hero_trade: int, merchant_trade: int,
              village: bool = True, numbers: dict[str, float] | None = None) -> int:
    """Сколько просят с игрока за предмет (VA 0x41AF3C)."""
    numbers = numbers or constants()
    price = base * (1.0 - (hero_trade - merchant_trade) * numbers["skill_step_buy"])
    if village:
        price *= numbers["village_buy"]
    return int(round(price))


def screen(data: bytes | None = None) -> dict:
    """Раскладка торгового экрана прямо из exe."""
    from .exetables import va_to_foff
    if data is None:
        with open(game_file("konung2.exe"), "rb") as stream:
            data = stream.read()

    def rects(va: int, count: int) -> list[dict]:
        out = []
        for index in range(count):
            x1, y1, x2, y2 = struct.unpack_from("<4i", data, va_to_foff(va) + index * 16)
            out.append({"x": x1, "y": y1, "width": x2 - x1, "height": y2 - y1})
        return out

    return {
        "sprite": SCREEN_SPRITE,
        "columns": [{**rect, "column": column}
                    for rect, column in zip(rects(COLUMN_RECTS_VA, COLUMNS), range(COLUMNS))],
        "order": list(COLUMN_ORDER),
        "pair": {str(one): two for one, two in COLUMN_PAIR.items()},
        "slots": COLUMN_SLOTS, "visible": COLUMN_VISIBLE,
        "cell": {"width": CELL_WIDTH, "height": CELL_HEIGHT, "pitch": CELL_PITCH},
        "arrows": {name: list(pair) for name, pair in ARROW_SPRITES.items()},
        "buttons": [{**rect, "sprite": sprite, "pressed": pressed,
                     "code": code, "action": action}
                    for rect, (sprite, pressed, code, action)
                    in zip(rects(BUTTON_RECTS_VA, len(BUTTONS)), BUTTONS)],
        "numbers": rects(NUMBER_RECTS_VA, 6),
        "codes": {"cell": CODE_CELL, "left": CODE_LEFT, "right": CODE_RIGHT},
        "skill": {"per_deal": SKILL_PER_DEAL, "cap": SKILL_CAP},
        "messages": dict(MESSAGES),
    }


def rules() -> dict:
    """Правила торговли одним куском — для content pack."""
    numbers = constants()
    return {
        "screen_layout": screen(),
        "policy": "konung2_exe_0x43346C_0x41A6CC_0x41AF3C",
        "screen": TRADE_SCREEN,
        "money_at": PARTY_MONEY_AT,
        "coin": {"kind": COIN_KIND, "class": COIN_CLASS, "value": COIN_VALUE},
        "skill": {"at": TRADE_SKILL_AT, "index": TRADE_SKILL_INDEX},
        "counters": {str(role): {"offset": offset, "slots": slots}
                     for role, (offset, slots) in COUNTERS.items()},
        # виды записи предмета, по которым 0x41ABBC считает полную цену,
        # а 0x41B218 и 0x41AA78 — вес
        "item_kinds": {"stack": STACK_KIND, "potion": POTION_KIND,
                       "coin": COIN_KIND},
        "ammo_stack": AMMO_STACK,
        "price_gate": {"flag_at": PRICE_GATE_FLAG_AT, "flag": PRICE_GATE_FLAG,
                       "type_at": PRICE_GATE_TYPE_AT,
                       "types": list(PRICE_GATE_TYPES)},
        "mode": {"ordinary": TRADE_MODE_ORDINARY, "at": TRADE_MODE_AT},
        "price": numbers,
    }
