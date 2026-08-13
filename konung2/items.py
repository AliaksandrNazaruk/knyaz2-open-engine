# -*- coding: utf-8 -*-
"""
Предметы: таблица классов внутри konung2.exe.

Записей 211 по 32 байта начиная с VA 0x45DAF0. Разобрана по отрисовке
экипировки юнита (VA 0x4260A2 и 0x426166) и по выбору анимации удара
(VA 0x416B0E и 0x416BA5) — оба места читают одну и ту же запись:

    +0x00  u32  указатель на название (CP866)
    +0x04  u32  БОЕВАЯ СИЛА: урон у оружия, защита у брони и щита
    +0x08  u32  ПРОЧНОСТЬ: с неё начинается износ предмета
    +0x0C  u16  какая характеристика нужна (номер в таблице 0x462D74)
    +0x0E  u16  сколько её нужно
    +0x10  u16  ДАЛЬНОСТЬ в клетках: 1 у ближнего боя, 15…18 у луков
    +0x12  u16  ЦЕНА в монетах — база, к ней прибавляются чары предмета
    +0x14  u16  ВЕС в граммах
    +0x16  u16  ИКОНКА — номер спрайта в каталоге INTERF.RES
    +0x18  u16  ВИД НА ЗЕМЛЕ (низ), u16 СЛОЙ ЭКИПИРОВКИ (верх)
    +0x1C  u32  палитра слоя — байтовое смещение в блоке палитр GRAPH.RES

Поле +0x04 названо силой не по догадке: его читает и расчёт удара
(VA 0x41A59E — сила оружия), и расчёт брони цели (VA 0x41A460 и 0x41A48F —
одежда и доспех складываются). Дальность читает проверка цели перед
выстрелом (VA 0x414C01), поэтому лук бьёт на 15 клеток, а меч на одну.

Поле +0x18 я звал «семейством», но это номер спрайта, которым предмет лежит
НА ЗЕМЛЕ. Загрузчик кучи (VA 0x43BBC4) выбирает его так: если в куче ровно
один предмет — берётся это поле его класса, если несколько или куча пуста —
спрайт 163. Рисуется он из INTERF.RES (VA 0x43DF48 берёт каталог 0x6B2618)
по центру клетки: положение уменьшается на половину ширины и высоты спрайта.
Вот что это за номера: 153 колчан со стрелами, 154 топор, 155 лук, 158 и 159
доспехи, 161 шлем, 163 мешочек, 165 щит, 166 меч, 214 дубина. Поэтому лицо
кнопки оружия и вид на земле совпадают числами: и то и другое — «как этот
предмет выглядит со стороны».

Требование — не «вид предмета», как я считал раньше. Подсказка (VA 0x4315A0)
печатает «, требует: » плюс короткое имя из таблицы 0x462D74 по номеру из
+0x0C и следом число из +0x0E, а проверка перед надеванием (VA 0x418648)
сравнивает с ним характеристику юнита: меньше — предмет не наденется. Имена
там короткие: 1 Хар, 2 Лов, 3 Инт, 4 Обч, 5 Сил, 6 Вын, 7 Брн, 8 Удр,
9 Вер, 10 Здр. Сходится и с текстами игры: топор требует Вын 36 («требует
большой выносливости»), составной лук — Лов 55 («требует недюжинной
ловкости»), меч — Сил 36.

Вес и цену пришлось переставить: сборка подсказки предмета (VA 0x4315A0)
печатает «, вес » и следом ``%4.2f`` от поля +0x14, умноженного на 0.001, —
значит там граммы, а не монеты. Само число это подтверждает: у лопаты 1000,
у заячьего хвоста 100, у двуручной металлической палицы 4400. Цену же
считает VA 0x41ABBC — она берёт поле +0x12 и прибавляет надбавки за чары
(биты записи предмета +0x0E), а у стрел умножает на их количество. Поле
+0x08 оказалось прочностью: им инициализируется износ предмета, который
убывает при каждом полученном ударе (VA 0x41BF54) и печатается в подсказке
как «износ N/M».

Номер слоя — то же число, по которому движок выбирает анимацию удара, то
есть «класс оружия» и «слой в кадре» в этой игре одно и то же:

    1, 5, 9        одноручные: ножи и мечи, топоры и секиры, дубины
    13, 15, 17     двуручные: мечи, топоры, палицы
    19             луки            21   самострелы
    23…26 доспехи  27…32 щиты      39…48 шлемы
    0              не носится (грамоты, фиалы), 0xFFFF — стрелы и болты

Палитра берётся как ``[0x58E300] + значение`` (VA 0x426707), а блок палитр —
начало GRAPH.RES по 256 цветов rgb555, то есть 0x200 байт на палитру:
индекс палитры = значение // 0x200.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

from .exetables import va_to_foff
from .paths import game_file

TABLE_VA = 0x45DAF0
STRIDE = 32
PALETTE_STRIDE = 0x200          # 256 цветов rgb555
NO_LAYER = 0xFFFF               # стрелы и болты: слоя в кадре нет

#: Слои экипировки по смыслу. Числа — не наши, это поле +0x18 записи.
ONE_HAND_LAYERS = (1, 5, 9)
TWO_HAND_LAYERS = (13, 15, 17)
BOW_LAYER, CROSSBOW_LAYER = 19, 21
ARMOUR_LAYERS = range(23, 27)
SHIELD_LAYERS = range(27, 33)
HELMET_LAYERS = range(39, 49)

#: Инвентарь юнита в движке: пять слотов экипировки подряд по u16 и мешок
#: на 42 ячейки следом. Смещения и назначение сняты с кода:
#:
#:     unit+0x58  рука         вид 0   (VA 0x416B96 — им бьют)
#:     unit+0x5A  метательное  вид 1   (VA 0x416B08 — из него стреляют)
#:     unit+0x5C  доспех       вид 2   (VA 0x41A43D — складывается в броню)
#:     unit+0x5E  шлем         вид 3   (VA 0x41A46C — тоже броня)
#:     unit+0x60  щит          вид 4   (VA 0x41A49B и 0x426161)
#:     unit+0x62  мешок, 42 ячейки u16 (VA 0x4129AB, 0x41F948)
#:
#: «Вид» — байт +0 записи предмета, и это ровно номер слота: раздача
#: снаряжения VA 0x4394BA пишет вид 0 ножу и топору, 1 луку и самострелу,
#: 2 кольчуге, 3 шлемам. Класс предмета лежит в байте +3 той же записи,
#: количество в стопке — u16 по +0x0C (стрелы имеют отдельный вид 0x0C).
SLOT_FIELDS = {"hand": 0x58, "ranged": 0x5A, "body": 0x5C,
               "head": 0x5E, "off_hand": 0x60}
SLOT_BY_KIND = {0: "hand", 1: "ranged", 2: "body", 3: "head", 4: "off_hand"}
KIND_BY_SLOT = {name: kind for kind, name in SLOT_BY_KIND.items()}

#: Чем предмет требователен: номер из поля +0x0C — это индекс в таблице
#: коротких имён 0x462D74, которую игра печатает в подсказке. Первые шесть
#: — те же характеристики, что в панели персонажа (konung2/progress.py).
REQUIREMENT_STATS = {
    1: "Харизма", 2: "Ловкость", 3: "Интеллект", 4: "Обучаемость",
    5: "Сила", 6: "Выносливость", 7: "Броня", 8: "Удар",
    9: "Вера", 10: "Здоровье",
}
BAG_FIELD, BAG_SLOTS = 0x62, 42
#: Куча из нескольких предметов лежит мешочком (VA 0x43BBC4).
GROUND_PILE_SPRITE = 163
#: Цена зелья идёт по крепости и ещё ввосьмеро (VA 0x41ABBC).
POTION_PRICE_SCALE = 8
#: Виды записи, которые 0x41ABBC считает по-особому.
STACK_KIND, POTION_KIND, COIN_KIND = 0x0C, 0x09, 0x0B
#: Боеприпас: на земле это колчан, а вид записи предмета 0x0C — по нему
#: движок и ищет стрелы в мешке (VA 0x41291C).
AMMO_GROUND = 153
STACK_KIND = 0x0C

#: У ВСЕХ восьми слоёв оружия номер нечётный, а чётный сосед — то же оружие
#: «в покое»: у пояса, на плече, за спиной. Это видно по самим кадрам: блоки
#: мирной стойки (16, 17) несут только чётные слои 2…22, блоки удара — только
#: нечётные 1…17, а выстрел из лука — чётные плюс 19, то есть меч на поясе и
#: натянутый лук в руках одновременно.
#:
#: Отрисовка (VA 0x425DB4) объясняет и сам шаг номеров: у одноручного оружия
#: четыре слоя подряд — в правой руке (+0), убрано (+1), в левой руке (+2),
#: убрано в левой (+3), — потому меч 1, топор 5, дубина 9 идут через четыре.
#: У двуручного и луков левой руки нет, и шаг вдвое меньше: 13, 15, 17 и
#: 19, 21. У щита свой второй слой — за спиной, плюс шесть.
WEAPON_LAYERS = (*ONE_HAND_LAYERS, *TWO_HAND_LAYERS, BOW_LAYER, CROSSBOW_LAYER)
REST_LAYER_STEP = 1


@dataclass(frozen=True)
class ItemClass:
    """Класс предмета — одна запись таблицы."""

    index: int
    name: str
    power: int              # +0x04: урон у оружия, защита у брони и щита
    durability: int         # +0x08: прочность, с неё начинается износ
    requires: int           # +0x0C: какая характеристика нужна (0 — никакая)
    requirement: int        # +0x0E: сколько её нужно
    range_cells: int        # +0x10: дальность боя в клетках
    price: int              # +0x12: цена, ЗНАКОВАЯ (у зелий за крепость)
    weight: int             # +0x14: вес в граммах
    icon: int               # +0x16: номер иконки в INTERF.RES
    ground: int             # +0x18 низ: спрайт INTERF.RES на земле
    layer: int              # +0x18 верх: слой экипировки в кадре юнита
    palette_offset: int     # +0x1C: байтовое смещение палитры слоя

    @property
    def palette(self) -> int:
        """Индекс палитры в блоке GRAPH.RES."""
        return self.palette_offset // PALETTE_STRIDE

    def cost(self, count: int = 1, strength: float = 0.0,
             kind: int | None = None, enchant_word: int = 0) -> int:
        """Цена вещи так, как её считает движок (VA 0x41ABBC).

        Ветку выбирает ВИД ЗАПИСИ, а не знак цены:

            0x0C стопка   цена класса на количество
            0x09 зелье    ``round(−крепость * цена) << 3``; сдвиг стоит вне
                          проверки знака, поэтому ввосьмеро дорожает и
                          зелье с неотрицательной ценой
            0x0B монета   просто цена класса
            прочее        цена плюс надбавки чар, и не меньше единицы

        ``kind`` — вид записи предмета. В таблице классов его НЕТ (он
        известен только по вещам мира, см. ``gamefile.class_kinds``),
        поэтому без него приходится гадать по косвенным признакам:
        стопку выдаёт признак боеприпаса, зелье — отрицательная цена.
        Гадание совпадает с движком на всех данных стартовых миров, но
        честнее передавать вид явно.
        """
        from .enchant import price_bonus
        if kind == STACK_KIND or (kind is None and self.ammo):
            return self.price * count
        if kind == POTION_KIND or (kind is None and self.price < 0):
            # Сдвиг стоит ВНЕ проверки знака: зелье с неотрицательной ценой
            # тоже дорожает ввосьмеро (VA 0x41ABD9).
            value = int(round(-self.price * strength)) if self.price < 0 else self.price
            return value * POTION_PRICE_SCALE
        if kind == COIN_KIND:
            return self.price
        value = self.price + price_bonus(enchant_word)
        return max(1, value)

    @property
    def ammo(self) -> bool:
        """Стрелы и болты: слоя в кадре нет, а на земле лежат колчаном."""
        return self.layer == NO_LAYER and self.ground == AMMO_GROUND

    @property
    def wearable(self) -> bool:
        return self.layer not in (0, NO_LAYER)

    @property
    def two_handed(self) -> bool:
        return self.layer in TWO_HAND_LAYERS

    @property
    def ranged(self) -> bool:
        return self.layer in (BOW_LAYER, CROSSBOW_LAYER)

    @property
    def shield(self) -> bool:
        return self.layer in SHIELD_LAYERS

    @property
    def weapon(self) -> bool:
        return self.layer in WEAPON_LAYERS

    @property
    def rest_layer(self) -> int | None:
        """Слой «оружие в покое» — сосед сверху. У брони и щитов его нет."""
        return self.layer + REST_LAYER_STEP if self.weapon else None

    @property
    def kind_slot(self) -> int | None:
        """Вид предмета движка — он же номер слота (байт +0 записи)."""
        return KIND_BY_SLOT.get(self.slot)

    @property
    def slot(self) -> str:
        """Куда предмет надевается — по слою, как в движке."""
        if self.ranged:
            return "ranged"
        if self.layer in ONE_HAND_LAYERS or self.two_handed:
            return "hand"
        if self.shield:
            return "off_hand"
        if self.layer in ARMOUR_LAYERS:
            return "body"
        if self.layer in HELMET_LAYERS:
            return "head"
        return "bag"

    @property
    def attack_pose(self) -> str | None:
        """Какая анимация играет этим предметом — правила VA 0x416B50/0x416AC8."""
        if self.layer == CROSSBOW_LAYER:
            return "shoot_crossbow"
        if self.layer == BOW_LAYER:
            return "shoot_bow"
        if self.two_handed:
            return "attack_two_hand"
        if self.layer in ONE_HAND_LAYERS:
            return "attack_one_hand"
        return None


def read_items(data: bytes | None = None) -> list[ItemClass]:
    """Все классы предметов из konung2.exe.

    Конец таблицы виден по первой записи без названия: указатель +0x00
    перестаёт попадать в сегмент данных.
    """
    if data is None:
        with open(game_file("konung2.exe"), "rb") as handle:
            data = handle.read()
    offset = va_to_foff(TABLE_VA)
    items: list[ItemClass] = []
    while True:
        index = len(items)
        fields = struct.unpack_from("<8I", data, offset + index * STRIDE)
        text = va_to_foff(fields[0])
        if text is None or not 0x450000 <= fields[0] < 0x460000:
            break
        end = data.index(b"\0", text)
        items.append(ItemClass(
            index=index,
            name=data[text:end].decode("cp866", "replace").strip(),
            power=fields[1],
            durability=fields[2],
            requires=fields[3] & 0xFFFF,
            requirement=fields[3] >> 16,
            range_cells=fields[4] & 0xFFFF,
            # Цена читается со знаком: у зелий она отрицательная, и это
            # не ошибка, а «столько за единицу крепости» (VA 0x41ABBC).
            price=struct.unpack_from("<h", data, offset + index * STRIDE + 0x12)[0],
            # ВЕС ЧИТАЕТСЯ СО ЗНАКОМ, как и цена выше. Движок складывает
            # ноши арифметическим сдвигом — `*(int *)(...) >> 0x10`
            # (VA 0x41B218), то есть старшее слово знаковое. Беззнаковое
            # чтение делало «Сына Луны» (класс 43) грузом в 55.5 кг вместо
            # облегчения на 10: 55536 = 65536 − 10000. Такая вещь в таблице
            # одна, но она артефакт, и ошибка в ней заметна сразу.
            weight=struct.unpack_from("<h", data,
                                      offset + index * STRIDE + 0x14)[0],
            icon=fields[5] >> 16,
            ground=fields[6] & 0xFFFF,
            layer=fields[6] >> 16,
            palette_offset=fields[7],
        ))
    return items


def find(name: str, items: list[ItemClass] | None = None) -> ItemClass:
    """Первый предмет с таким названием — удобно для сборки контента."""
    for item in items if items is not None else read_items():
        if item.name.lower() == name.lower():
            return item
    raise KeyError(name)
