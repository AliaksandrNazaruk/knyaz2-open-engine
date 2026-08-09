# -*- coding: utf-8 -*-
"""
INTERF.RES — картинки интерфейса: иконки предметов, панели, кнопки.

Формат снят с загрузчика VA 0x430295, который читает файл ровно так:

    +0x0000  u32       размер блока данных
    +0x0004  1000 x 8  каталог: (смещение в данных, смещение палитры)
    +0x1F44  данные    спрайты тем же кодеком, что GRAPH.RES

Каталог целиком уезжает в память по адресу 0x6B2618, и дальше движок берёт
спрайт как ``[0x6B2618 + номер*8]`` плюс база данных, а палитру — как
``[0x58E300] + [0x6B261C + номер*8]``, то есть вторым полем записи (VA
0x42B1D0). Палитра, как и у экипировки, задана байтовым смещением в блоке
палитр GRAPH.RES: индекс = смещение // 0x200.

Спрайт — ``u16 w; u16 h; u16 строки[h]; RLE`` (блиттер VA 0x43FFD1 читает
ширину и высоту, а данные начинает после таблицы строк). Иконки предметов
все 68x68.

Номер иконки предмета лежит в его классе полем +0x16 (konung2/items.py):
Меч 148, Топор 32, Двуручный меч 217, Составной лук 40, Щит круглый 136.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

from .paths import game_file
from .res import decode_rle, read_palettes

HEADER_SIZE = 4
DIRECTORY_ENTRIES = 1000
ENTRY_SIZE = 8
DATA_AT = HEADER_SIZE + DIRECTORY_ENTRIES * ENTRY_SIZE
PALETTE_STRIDE = 0x200

#: Раскладка окна снаряжения: таблица 0x460FB4, по 16 байт на слот —
#: (x1, y1, x2, y2). Цикл отрисовки VA 0x42B0E7 складывает первое поле с
#: третьим и вычитает ШИРИНУ спрайта, а второе с четвёртым и вычитает его
#: ВЫСОТУ, то есть по горизонтали идут поля +0x00 и +0x08, по вертикали
#: +0x04 и +0x0C, а иконка ставится по центру гнезда.
SLOT_RECTS_VA = 0x460FB4


@dataclass(frozen=True)
class InterfEntry:
    index: int
    offset: int
    palette_offset: int

    @property
    def palette(self) -> int:
        return self.palette_offset // PALETTE_STRIDE


class InterfRes:
    """Каталог INTERF.RES и распаковка его спрайтов."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.size = struct.unpack_from("<I", data)[0]
        if DATA_AT + self.size != len(data):
            raise ValueError(
                f"INTERF.RES: размер {len(data)} не сходится с заголовком {self.size}")
        self.entries = [
            InterfEntry(i, *struct.unpack_from("<II", data, HEADER_SIZE + i * ENTRY_SIZE))
            for i in range(DIRECTORY_ENTRIES)
        ]

    @classmethod
    def from_game(cls) -> "InterfRes":
        with open(game_file("INTERF.RES"), "rb") as stream:
            return cls(stream.read())

    def frame_size(self, index: int) -> tuple[int, int] | None:
        """Размер спрайта без распаковки."""
        entry = self.entries[index]
        start = DATA_AT + entry.offset
        if not 0 <= entry.offset < self.size:
            return None
        width, height = struct.unpack_from("<HH", self.data, start)
        if not (0 < width <= 1024 and 0 < height <= 1024):
            return None
        return width, height

    def sprite(self, index: int, palettes: list | None = None):
        """Спрайт по номеру каталога, в своей палитре."""
        entry = self.entries[index]
        if self.frame_size(index) is None:
            return None
        if palettes is None:
            palettes = read_palettes()
        palette = palettes[entry.palette % len(palettes)]
        return decode_rle(self.data, DATA_AT + entry.offset, palette=palette, mode=8)


#: Разложение экрана игры 1024x768, снятое с самих ресурсов и таблиц:
#:
#:     спрайт 3   1024x768  рамка интерфейса: левая панель и нижняя полоса
#:     спрайт 2    884x638  окно снаряжения (силуэт с гнёздами)
#:     спрайт 4    884x709  карта мира
#:
#: Проём окна мира замерен по самой рамке: строки 0..708 прозрачны от x=140
#: до x=1023, а с 709-й и до низа экрана рамка сплошная. Значит окно мира —
#: 884x709, и ровно столько же у карты (спрайт 4), а под окном лежит нижняя
#: полоса рамки высотой 59. Окно снаряжения на 638 короче ровно на высоту
#: пояса: оно кончается там, где начинается ряд ячеек.
SCREEN = (1024, 768)
FRAME_SPRITE = 3
PANEL_WIDTH = 140
VIEW_WIDTH = SCREEN[0] - PANEL_WIDTH
VIEW_HEIGHT = 709
FRAME_BOTTOM = VIEW_HEIGHT              # с этой строки идёт полоса рамки

#: Раскладка левой панели — таблица 0x460EB4, по 16 байт на прямоугольник
#: (x1, y1, x2, y2). Записей шестнадцать, и никаких «гнёзд под предметы»
#: среди них нет:
#:
#:     0…8    портреты: свой и до восьми спутников. Запись берётся по
#:            номеру юнита в отряде — VA 0x4305A4 делит (юнит − 0x84951C)
#:            на 256 и лезет в таблицу этим номером;
#:     9…15   семь кнопок. Рисует их VA 0x430794 по той же таблице со
#:            смещения 0x460F44 — это ровно запись 9.
#:
#: Попадание мышью возвращает «номер записи + 1» (VA 0x43AFE3), поэтому
#: портреты это коды 1…9, а кнопки 0x0A…0x10.
PANEL_RECTS_VA = 0x460EB4
BUTTON_RECTS_VA = 0x460F44
PANEL_LAYOUT = ("portrait", "party_1", "party_2", "party_3", "party_4",
                "party_5", "party_6", "party_7", "party_8",
                "button_1", "button_2", "button_3", "button_4",
                "button_5", "button_6", "button_7")

#: Что делает каждая кнопка — из разбора нажатия (VA 0x422943 — цепочка
#: сравнений кода наведения):
#:
#:     0x0A  лицо оружия      0x4228C6  сменить ближнее/метательное
#:     0x0B  кулак 10 / ладонь 15   0x421FA4  достать/убрать оружие
#:     0x0C  компас 14        0x4223B6  карта
#:     0x0D  звезда 11        0x420BFC  все ко мне (обход отряда)
#:     0x0E  стрелки 7        0x4202CC  атаковать (ставит лицо «кулак»)
#:     0x0F  книга 12         0x42300C  информация к размышлению
#:     0x10  мешок 13         0x423088  панель персонажа
#:
#: Названия и клавиши — подсказки самой игры (VA 0x4211EB и рядом).
BUTTON_ACTIONS = (
    {"id": "weapon_mode", "title": "Ближнее или метательное оружие", "key": ""},
    {"id": "toggle_weapon", "title": "Достать/Убрать оружие", "key": "Space"},
    {"id": "map", "title": "Карта", "key": "M"},
    {"id": "call_party", "title": "Все ко мне", "key": "F"},
    {"id": "attack", "title": "Атаковать", "key": "A"},
    {"id": "journal", "title": "Информация к размышлению", "key": "Q"},
    {"id": "character", "title": "Панель персонажа", "key": "I"},
)
#: Постоянные картинки кнопок; у первой её нет — лицо меняется по оружию,
#: у второй зависит от стойки. Массив лиц движок держит в 0x844288, и
#: рисовальщик берёт номер спрайта прямо оттуда (VA 0x43082D).
BUTTON_SPRITES = (None, None, 14, 11, 7, 12, 13)
#: Вторая кнопка: кулак, когда оружие достано (бит 0x04 байта unit+0x19),
#: и ладонь, когда убрано (VA 0x429407).
STANCE_SPRITES = {"combat": 10, "peace": 15}
#: Первая кнопка показывает, чем юнит бьётся (VA 0x4292DC). Если байт
#: unit+0xEE равен 1, в руках метательное: слой 0x15 — самострел, иначе лук.
#: Иначе смотрим предмет в руке: пусто или нет слоя — пустая рука, семейство
#: 166 (ножи и мечи) — клинок, 154 (топоры) — топор, остальное — дубина.
WEAPON_FACES = {"empty": 23, "blade": 16, "axe": 8, "other": 24,
                "bow": 9, "crossbow": 22}
WEAPON_FACE_FAMILIES = {"blade": 166, "axe": 154}
CELL_SPRITE = 17
PORTRAIT_BASE = 261
HEALTH_BAR = {"height": 0x3E, "scale": 0x640}

#: Пояс — нижний ряд ячеек мешка. Рисует его VA 0x43096C, и всё оттуда:
#:
#:     ряд стоит на строке 639 и высотой 70 упирается в низ проёма (708),
#:     ячейка — спрайт 17 (70x70): движок берёт её как [0x6B26A0], а это
#:                 каталог 0x6B2618 плюс 0x88, то есть номер 17,
#:     первая ячейка с x=168, шаг 69, всего двенадцать,
#:     иконка предмета ставится по центру ячейки: x + (70 - ширина) / 2,
#:     слева стрелка (спрайт 18, нажатая 19, 28x70) на x=140,
#:     справа стрелка (спрайт 20, нажатая 21, 27x70) у кромки 1023,
#:     отсечка (140, 0, 1023, 708) — весь проём окна мира.
#:
#: 28 + 12*69 + 27 = 883, то есть ряд занимает всю ширину окна мира.
#:
#: Видно двенадцать ячеек из сорока двух: номер первой лежит в 0x849714,
#: стрелка влево уменьшает его и упирается в ноль (VA 0x4231E6), стрелка
#: вправо увеличивает, но только если следующая за окном ячейка занята
#: (VA 0x423C99 и предикат VA 0x420890: ``мешок[первая + 12] != 0``).
#: Тем же предикатом движок сам прокручивает пояс, когда предмет попадает
#: за его край (VA 0x43834C).
BELT = {
    "y": 639, "height": 70, "cell": 70, "pitch": 69,
    "first_x": 168, "cells": 12, "left_x": PANEL_WIDTH, "right_x": 1023,
}
BELT_ARROWS = {"left": 18, "left_pressed": 19,
               "right": 20, "right_pressed": 21}

#: Окно снаряжения: спрайт каталога 2 (884x638) — тот самый силуэт с
#: гнёздами под предметы, который показывает игра.
EQUIPMENT_WINDOW = 2
#: Порядок слотов в таблице 0x460FB4 — тот же, в котором движок перебирает
#: поля юнита в цикле отрисовки (VA 0x42B0E7): рука, метательное, доспех,
#: шлем, щит.
SLOT_ORDER = ("hand", "ranged", "body", "head", "off_hand")

#: Гнёзд в этой таблице на самом деле двенадцать, и рисует их VA 0x42A8F4:
#:
#:     0…4    рука, метательное, доспех, шлем, щит   unit+0x58…+0x60
#:     5      боеприпас                              unit+0x50
#:     6…10   украшения                              unit+0xB6…+0xBE
#:     11     ячейка предмета «в руке» курсора       0x849668
#:
#: Боеприпас в unit+0x50 подбирается перебором мешка: движок ищет в нём
#: предмет вида 0x0C того же класса (VA 0x41291C) — потому гнездо и стоит
#: вплотную к луку. Украшения читаются пятёркой с unit+0xB6, а их подсказки
#: — те самые строки «Место для ожерелья», «Место для браслета», «Место для
#: кольца» (таблица 0x45A090). Слоёв на теле у них нет, на персонаже они не
#: видны, поэтому в клиенте пока не показываются.
SLOT_RECTS_COUNT = 12
AMMO_SLOT_RECT, AMMO_FIELD = 5, 0x50
JEWELLERY_RECTS = (6, 7, 8, 9, 10)
JEWELLERY_FIELD = 0xB6
CURSOR_SLOT_RECT = 11

#: Подсказки гнёзд — строки самой игры. Наведение отдаёт код, а по коду
#: движок берёт строку из таблицы 0x45A090 (VA 0x421145); коды 17…21 идут
#: ровно в порядке слотов и читаются как «В правой руке воин может держать
#: меч, топор, дубину или кастет», «Место для лука или арбалета» и так далее.
SLOT_HINTS_VA = 0x45A090
SLOT_HINT_CODE = 17


#: Экран персонажа (ветка отрисовки VA 0x42A8F4, параметр 2). Фон — спрайт 2
#: или 201, выбор по биту 1 байта unit+0xFC. Числа печатаются по таблице
#: 0x4612E4 (пары x, y подряд: уровень, опыт, свободный опыт, следующий
#: уровень, шесть характеристик, двадцать навыков, семь итоговых полей),
#: подписи — по таблице 0x46140C (указатель на строку и её x, y; строка
#: выравнивается ПРАВЫМ краем по этому x). Числа тоже правым краем: базовая
#: характеристика по своему x, текущая на 0x5A правее, знак «поднять» ещё на
#: 0x87 от базовой; у навыка значение по своему x, знак на 0x2D правее.
CHARACTER_SCREEN_SPRITE, CHARACTER_SCREEN_SPRITE_ALT = 2, 201
CHARACTER_FIELDS_VA = 0x4612E4
CHARACTER_LABELS_VA = 0x46140C
#: Записей 41, а не 34. Первые тридцать четыре — заголовки, характеристики и
#: навыки, а с 34-й по 40-ю идут подписи семи итоговых полей: «Здоровье»,
#: «Отравление», «Броня», «Удар», «Текущий вес», «Максимальный вес»,
#: «Золото» — все по x = 520, а y совпадает со строками их чисел (480…600).
#: Раньше здесь стояло 34, и панель показывала семь голых чисел без единой
#: подписи; комментарий ниже уверял, будто они «запечены в фоновом спрайте»,
#: но на них есть указатели прямо в этой таблице (0x46151C…0x46154C).
#: Сорок первая запись — «Максимальный отряд» с нулевыми координатами, её
#: печатает другой экран; дальше таблица кончается (в поле указателя лежат
#: числа вроде 0x166, не адреса).
CHARACTER_LABELS = 41
CHARACTER_CURRENT_DX, CHARACTER_RAISE_DX, CHARACTER_SKILL_RAISE_DX = 0x5A, 0x87, 0x2D
CHARACTER_FIELD_ORDER = (
    ("level", "уровень"), ("experience", "опыт"),
    ("free_xp", "свободный опыт"), ("next_level", "следующий уровень"),
)

#: После навыков таблица 0x4612E4 продолжается: ещё семь пар (x, y), итого
#: 37 — ровно до таблицы подписей (0x46140C − 0x4612E4 = 0x128 = 37·8).
#: Печатает их та же ветка VA 0x42A8F4, а подписи к ним лежат в той же
#: таблице подписей записями 34…40 (см. CHARACTER_LABELS):
#:
#:     health        здоровье = (i16 unit+0x4E) / 16 с усечением к нулю;
#:                   если вышло 0, а здоровье не ноль — печатается 1
#:     poison        отрава = i16 unit+0x52
#:     armour        броня = VA 0x41A414: своя (+0xF4) + доспех, шлем и
#:                   щит (вид 4) + чара брони (+0x42 по биту 1 байта +0xFA)
#:     strike        удар: стрелковый (VA 0x41A624), когда есть боеприпас
#:                   (+0x50), взведён режим (+0xEE == 1) и занято метательное
#:                   гнездо (+0x5A); иначе ближний (VA 0x41A7D0) плюс удар
#:                   второй руки, если в щитовом гнезде оружие (вид записи 0)
#:     weight        вес несомого (VA 0x41B218) в граммах; печать «%4.1f» от
#:                   граммов × 0.001 (формат 0x4524C6, double 0x4524D2);
#:                   при превышении предела — красной палитрой 0x60054C
#:     weight_limit  предел веса: Выносливость·1000/3 + 20000, тот же формат
#:     money         деньги = s32 unit+0x26
CHARACTER_EXTRA_FIELDS = ("health", "poison", "armour", "strike",
                          "weight", "weight_limit", "money")
#: Граммы → килограммы для двух весовых строк (double по VA 0x4524D2).
CHARACTER_WEIGHT_SCALE = 0.001
#: Здоровье печатается в шестнадцатых долях (шкала 0x640 → 0…100).
CHARACTER_HEALTH_DIVISOR = 16


def _string_at(data: bytes, va: int) -> str:
    """CP866-строка по виртуальному адресу."""
    from .exetables import va_to_foff
    offset = va_to_foff(va)
    if offset is None:
        return ""
    end = data.index(b"\0", offset)
    return data[offset:end].decode("cp866", "replace")


#: Все двенадцать гнёзд по порядку таблицы. Пять надетых и пятёрка
#: украшений — живые гнёзда: раздачу украшений по видам делает VA 0x41E8D8
#: (вид 6 — ожерелье, 7 — браслет в любое из двух, 8 — кольцо в любое из
#: двух), лежат они в юните с +0xB6. Слоёв на теле у украшений нет — на
#: спрайт они не влияют, только на слова прибавок.
#: Двенадцатое гнездо — не «курсор», как я думал по картинке, а МЕСТО
#: СМЕШИВАНИЯ: движок даёт ему свой код мыши 0x1C и свою подсказку про
#: снадобья и волшебные камни (VA 0x421690, konung2/craft.py).
SLOT_LAYOUT = (*SLOT_ORDER, "ammo", "necklace", "bracelet_1", "bracelet_2",
               "ring_1", "ring_2", "mixing")
#: Подсказки украшений идут кодами 7…11 той же таблицы 0x45A090.
JEWELLERY_HINT_CODE = 7


def slot_rects(data: bytes | None = None) -> list[dict]:
    """Гнёзда окна снаряжения из konung2.exe вместе с подсказками игры."""
    from .exetables import va_to_foff
    if data is None:
        with open(game_file("konung2.exe"), "rb") as stream:
            data = stream.read()
    offset = va_to_foff(SLOT_RECTS_VA)
    hints = va_to_foff(SLOT_HINTS_VA)

    def hint(code: int) -> str:
        pointer = struct.unpack_from("<I", data, hints + code * 4)[0]
        return _string_at(data, pointer) if 0x440000 < pointer < 0x470000 else ""

    rects = []
    for index, name in enumerate(SLOT_LAYOUT):
        x1, y1, x2, y2 = struct.unpack_from("<4i", data, offset + index * 16)
        if index < len(SLOT_ORDER):
            text = hint(SLOT_HINT_CODE + index)
        elif index in JEWELLERY_RECTS:
            text = hint(JEWELLERY_HINT_CODE + index - JEWELLERY_RECTS[0])
        elif index == AMMO_SLOT_RECT:
            text = "Место для стрел или болтов"
        else:
            text = ""
        rects.append({"slot": name, "x": x1, "y": y1,
                      "width": x2 - x1, "height": y2 - y1, "hint": text,
                      # боеприпас движок кладёт сам, но показывает как слот;
                      # украшения — живые гнёзда второго набора (+0xB6)
                      "wearable": index < len(SLOT_ORDER) or name == "ammo"
                      or index in JEWELLERY_RECTS})
    return rects


def character_screen(data: bytes | None = None) -> dict:
    """Раскладка экрана персонажа: числа, подписи и колонки."""
    from .exetables import va_to_foff
    from .progress import CHARACTERISTICS, SKILLS
    if data is None:
        with open(game_file("konung2.exe"), "rb") as stream:
            data = stream.read()

    offset = va_to_foff(CHARACTER_FIELDS_VA)
    numbers: list[dict] = []
    for index, (key, _) in enumerate(CHARACTER_FIELD_ORDER):
        x, y = struct.unpack_from("<2i", data, offset + index * 8)
        numbers.append({"field": key, "x": x, "y": y})
    base = len(CHARACTER_FIELD_ORDER)
    for index, name in enumerate(CHARACTERISTICS):
        x, y = struct.unpack_from("<2i", data, offset + (base + index) * 8)
        numbers.append({"field": "characteristic", "index": index, "name": name,
                        "x": x, "y": y,
                        "current_x": x + CHARACTER_CURRENT_DX,
                        "raise_x": x + CHARACTER_RAISE_DX})
    base += len(CHARACTERISTICS)
    for index, name in enumerate(SKILLS):
        x, y = struct.unpack_from("<2i", data, offset + (base + index) * 8)
        numbers.append({"field": "skill", "index": index, "name": name,
                        "x": x, "y": y,
                        "raise_x": x + CHARACTER_SKILL_RAISE_DX})
    base += len(SKILLS)
    for index, key in enumerate(CHARACTER_EXTRA_FIELDS):
        x, y = struct.unpack_from("<2i", data, offset + (base + index) * 8)
        numbers.append({"field": key, "x": x, "y": y})

    labels = []
    offset = va_to_foff(CHARACTER_LABELS_VA)
    for index in range(CHARACTER_LABELS):
        pointer, x, y = struct.unpack_from("<Ihh", data, offset + index * 8)
        text = _string_at(data, pointer) if 0x440000 < pointer < 0x470000 else ""
        if text:
            labels.append({"text": text, "x": x, "y": y})
    return {"sprite": CHARACTER_SCREEN_SPRITE,
            "sprite_alt": CHARACTER_SCREEN_SPRITE_ALT,
            "numbers": numbers, "labels": labels,
            "weight_scale": CHARACTER_WEIGHT_SCALE,
            "health_divisor": CHARACTER_HEALTH_DIVISOR}


#: ПРОЗВИЩЕ ИГРОКА (VA 0x42FDC0). Подсказка о своём герое начинается не с
#: имени, а с прозвища по двум сильнейшим характеристикам:
#:
#:     v = базовые характеристики +0xC0, +0xC1, +0xC2, +0xC4, +0xC5
#:         — ПЯТЬ из шести, Обучаемость (+0xC3) не участвует;
#:     отсортировать по убыванию, запомнив их номера;
#:     если номер первой меньше номера второй, номер второй уменьшить на 1;
#:     строка = таблица[(значение_второй − 1) // 30
#:                      + номер_первой * 20 + номер_второй * 5]
#:
#: Существительное задаёт первая характеристика, прилагательное — вторая, а
#: ступень внутри пятёрки — величина второй. Записей ровно сто.
EPITHETS_VA, EPITHETS_COUNT = 0x462B4C, 100
#: Номера характеристик в блоке +0xC0, которые участвуют в прозвище.
EPITHET_CHARACTERISTICS = (0, 1, 2, 4, 5)
#: На сколько делится значение второй характеристики, выбирая ступень.
EPITHET_STEP = 30


def epithets(data: bytes | None = None) -> list[str]:
    """Сто строк прозвищ из таблицы 0x462B4C."""
    from .exetables import va_to_foff
    if data is None:
        with open(game_file("konung2.exe"), "rb") as stream:
            data = stream.read()
    offset = va_to_foff(EPITHETS_VA)
    out = []
    for index in range(EPITHETS_COUNT):
        pointer = struct.unpack_from("<I", data, offset + index * 4)[0]
        out.append(_string_at(data, pointer))
    return out


def epithet_index(characteristics) -> int | None:
    """Номер прозвища для базовых характеристик (VA 0x42FDC0).

    ``characteristics`` — весь блок +0xC0 по порядку; отбор нужных пяти
    делается здесь, чтобы вызывающему не пришлось помнить про пропуск
    Обучаемости.
    """
    try:
        values = [(int(characteristics[at]), place)
                  for place, at in enumerate(EPITHET_CHARACTERISTICS)]
    except (IndexError, TypeError, ValueError):
        return None
    # Сортировка устойчивая и по УБЫВАНИЮ значения — как пузырёк движка,
    # который меняет местами только при строгом «меньше».
    values.sort(key=lambda pair: -pair[0])
    (_, first), (second_value, second) = values[0], values[1]
    if first < second:
        second -= 1
    # Деление С УСЕЧЕНИЕМ К НУЛЮ, как в C: у питоновского `//` округление
    # вниз, и на нулевой характеристике (−1 // 30) оно дало бы −1 там, где
    # движок даёт ноль.
    index = int((second_value - 1) / EPITHET_STEP) + first * 20 + second * 5
    return index if 0 <= index < EPITHETS_COUNT else None


def panel_rects(data: bytes | None = None) -> list[dict]:
    """Раскладка левой панели игры: портрет, отряд, оружие, кнопки."""
    from .exetables import va_to_foff
    if data is None:
        with open(game_file("konung2.exe"), "rb") as stream:
            data = stream.read()
    offset = va_to_foff(PANEL_RECTS_VA)
    rects = []
    for index, name in enumerate(PANEL_LAYOUT):
        x1, y1, x2, y2 = struct.unpack_from("<4i", data, offset + index * 16)
        rects.append({"name": name, "x": x1, "y": y1,
                      "width": x2 - x1, "height": y2 - y1})
    return rects
