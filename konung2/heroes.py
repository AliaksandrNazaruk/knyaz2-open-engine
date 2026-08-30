# -*- coding: utf-8 -*-
"""
`HEROES.RES` — анимации юнитов.

Раскладка снята с загрузчика (VA 0x43D487), выбора кадра (VA 0x416240) и
отрисовки слоёв юнита (VA 0x426698 картинка, 0x42674C тень, блиттер 0x43F3FC):

* заголовок 0x49C0 байт читается в память целиком (0x844B4C);
* внутри — анимационные блоки: ``u16 таблица[kind * 0x180 + dir * 0x30]``,
  строка направления: ``[число_кадров, номер_записи…]`` (24 u16);
* на +0x33E0 — 1400 u32-смещений записей; запись ``i`` занимает
  ``[offs[i], offs[i+1])``, последний конец равен размеру файла байт в байт.

Запись — один кадр одного направления на холсте **256×150** (движок ставит
размер кадра юниту: ``[unit+0x54]=0x100, [unit+0x56]=0x96``, VA 0x416547).
Точка юнита (ноги) — **(127, 144)** холста: экранная позиция кадра считается
как ``x - 0x7F, y - 0x90`` (VA 0x4162E1, 0x416559).

Внутри записи ДВЕ таблицы по 54 слоя экипировки (слой 0 — тело):

    +0x000  54 × { u16 off; i16 y }   тени слоёв   (проход VA 0x42674C)
    +0x0D8  54 × { u16 off; i16 y }   картинки     (проход VA 0x426698)
    +0x1B0  данные слоёв

``off`` — смещение данных от начала записи, 0 — слоя нет. ``y`` — строка
холста, с которой рисуется слой (блиттер 0x43F3FC начинает с неё и идёт
вниз). Палитра слоя не хранится в записи: её задаёт юнит ([0x8A7318]).

Картинка слоя — обычный спрайт ``u16 w; u16 h; u16 line_len[h]; RLE``
(тот же кодек, что GRAPH.RES; w всегда 256). Тень слоя — спановая маска
``u16 w; u16 h; u16 rows[h]``, затем по строкам знаковые байты: 0 — конец
строки, n<0 — пропуск (n & 0x7F), n>0 — n непрозрачных точек (данных нет);
формат общий с масками построек (читатель VA 0x43F260).

Проверено контрольными суммами line_len на всех слоях записей 0…119:
границы слоёв и записей сходятся байт-в-байт.
"""
from __future__ import annotations

import struct

from .paths import game_file
from .res import Sprite, decode_rle, read_palettes

HEADER_SIZE = 0x49C0
OFFSETS_AT = 0x33E0
OFFSET_COUNT = 1400
KIND_STRIDE, DIR_STRIDE, DIRECTIONS = 0x180, 0x30, 8

LAYER_COUNT = 54
SHADOW_TABLE_AT, IMAGE_TABLE_AT = 0x000, 0x0D8
CANVAS_W, CANVAS_H = 256, 150      # [unit+0x54], [unit+0x56]
ANCHOR_X, ANCHOR_Y = 127, 144      # sub eax,0x7F / sub eax,0x90

#: Блоки анимации юнита. Стойку держит бит 0x04 байта ``unit+0x19``, выбор
#: блока — VA 0x4166A5 (шаг и бег), 0x416DCD и 0x416DF6 (стойка и простой):
#:
#:     бит стоит -> 0 стойка, 1 шаг, 6 простой, 7 бег
#:     бит снят  -> 16,       17,    18,        19
#:
#: Какой набор боевой, видно по тому, кто бит трогает. Ставят его переход в
#: бой (VA 0x4103D6, 0x411423 — обе после проверки, что бита ещё нет) и любая
#: атака (VA 0x416AF7, 0x416B85). СНИМАЮТ В ЧЕТЫРЁХ, а не в одном: `and 0xFB`
#: по 0x410DCA (приказ 0x0C «стой, с тобой говорят») и `xor 4` по 0x41145F
#: (рассудок: дел не осталось — снять и встать в блок 16), 0x420577 и
#: 0x420D0F (перевод блока). Здесь стояло «ровно в одном месте — при мирном
#: приказе идти»: искали ОДНУ форму записи, и три `xor` не увидели, а подпись
#: единственной находки додумали. Отсюда же и жалоба «житель уходит из
#: казармы с мечом»: снимает оружие именно рассудок, перед новым делом.
#: При включении бита текущий блок переводится
#: таблицей 0x45A0C0: 16->0, 17->1, 18->6, 19->7 (VA 0x420402 и 0x420552),
#: обратная таблица 0x45A098 переводит 0->16, 1->17, 6->18, 7->19. Значит
#: боевой набор — 0, 1, 6, 7, мирный — 16…19.
#:
#: То же подтверждают слои: у блоков 0, 1, 6, 7 заняты все 54 слоя, включая
#: 19 и 21 (натянутый лук и заряженный самострел), — с оружием наготове
#: ходить можно только в них; у 16…19 этих слоёв нет.
POSES = ("stand", "walk", "idle", "run")
STANCE_BLOCKS = {"peace": {"stand": 16, "walk": 17, "idle": 18, "run": 19},
                 "combat": {"stand": 0, "walk": 1, "idle": 6, "run": 7}}
#: Действия — блоки без пары в таблицах 0x45A098/0x45A0C0, общие для обеих
#: стоек. Само оружие в кадре живёт ОТДЕЛЬНЫМ СЛОЕМ экипировки (до 54 слоёв
#: на запись), поэтому у тела нет анимаций «меч», «топор», «лук»: есть пять
#: анимаций удара и выстрела, а какая играет — решает группа предмета.
#:
#: Группа предмета: ``[ITEM_CLASS_TABLE + тип * 32] >> 16``, где тип берётся
#: из записи предмета ``[0x6F956F + предмет * 16]`` (записи предметов живут
#: в памяти, таблица классов — в exe). Группы: 0x01…0x0B одноручное оружие,
#: 0x0D…0x13 двуручное и луки, 0x15 боевые самострелы, дальше броня и шлемы.
#:
#: Ближний бой — предмет основной руки ``unit+0x58`` (VA 0x416B50):
#:     группа >= 0x0D -> 8   двуручные мечи, топоры, секиры, палицы
#:     иначе смотрится навык «Бой двумя руками» (unit+0xD3):
#:         навык 0                            -> 5   всегда, даже с пустой
#:                                                   второй рукой
#:         навык есть, вторая рука (unit+0x60)
#:             пуста или в ней вид записи 0   -> 9   второе оружие
#:             иначе (щит)                    -> 5
#: Стрельба — метательное ``unit+0x5A`` (VA 0x416AC8), вызывается
#: только после проверки цели 0x414AF8:
#:     группа == 0x15 -> 10  боевой самострел
#:     иначе -> 4            лук
#:
#: Разделение подтверждается слоями экипировки: у блока 9 заняты нечётные
#: слои 1…11, у блоков 4 и 10 — чётные 2…18, то есть это разные руки; слой 19
#: есть только в блоке 4, слой 21 — только в блоке 10, и больше нигде: это
#: натянутый лук и заряженный самострел. Слои 20 и 22 (оружие в руке) стоят
#: в блоках 5, 8, 9 и в боевой стойке 16…19.
#:
#: Блок 2 — НЕ защита, а реакция на полученный урон: оба вызова (VA 0x41418B
#: и 0x42022F) стоят сразу после списания здоровья. Отдельной анимации блока
#: щитом в движке нет — все 20 блоков заняты, защита считается числами.
#: Блоки 3, 11, 12 — смерть, ровно три варианта по rand() % 3 (VA 0x416A5D),
#: перед этим юнит вычищается из клетки (VA 0x416A52); 13, 14, 15 — позы
#: трупа, по одному кадру.
ACTION_BLOCKS = {
    "attack_one_hand": 9, "attack_shield": 5, "attack_two_hand": 8,
    "shoot_bow": 4, "shoot_crossbow": 10,
    "hit": 2,
    "death_1": 3, "death_2": 11, "death_3": 12,
    "corpse_1": 13, "corpse_2": 14, "corpse_3": 15,
}
#: Таблица классов предметов: 32 байта на запись, первое слово старшей
#: половины — группа, dword +8 — указатель на название (CP866).
ITEM_CLASS_TABLE = 0x45DB08
ITEM_CLASS_STRIDE = 32
#: Пороги выбора анимации из ветвей 0x416BC2 и 0x416B28.
TWO_HAND_GROUP, CROSSBOW_GROUP = 0x0D, 0x15
#: Смерть выбирается жребием ровно из трёх вариантов (VA 0x416A64).
DEATH_VARIANTS = 3

#: Бит бега (unit+0x19 & 0x80) ставится режимом движения 1 (VA 0x416641),
#: если скорость юнита неотрицательна и не стоит флаг 0x40 в unit+0x1A.
RUN_BIT, STANCE_BIT = 0x80, 0x04

#: Отрисовка юнита со снаряжением — VA 0x425DB4. Сначала, до всякого
#: сценария, движок кладёт два слоя:
#:
#:     тело     байт unit+0xFC: ноль — слой 0, иначе 48 + это число
#:     доспех   предмет unit+0x5C своим слоем (u16 класса +0x1A)
#:
#: Дальше идёт сценарий из ПЯТИ БАЙТ на направление (таблица 0x4627D0,
#: направление — байт unit+0x18), и каждый байт это шаг отрисовки:
#:
#:     100  щит в руке      unit+0x60, вид 4, слой как есть
#:     101  оружие в руке   unit+0x58 слой; второе оружие unit+0x60 слой+2;
#:                          в метательном режиме вместо них лук unit+0x5A
#:     3    шлем            unit+0x5E слоем как есть
#:     111  убранное        оружие слой+1, лук слой+1, второе оружие слой+3
#:     110  щит за спиной   unit+0x60 слой+6
#:
#: Отсюда и шаг слоёв у оружия: у каждого по четыре (в руке, убрано, во
#: второй руке, убрано во второй) — потому меч 1, топор 5, дубина 9, а у
#: двуручных и луков левой руки нет и шаг вдвое меньше.
#:
#: Что рисуется, а что нет, решают бит стойки (unit+0x19 & 0x04) и режим
#: оружия (байт unit+0xEE): «в руках» — только с достанным оружием и в своём
#: режиме, «убрано» — во всех остальных случаях.
DRAW_SCRIPT_VA = 0x4627D0
DRAW_SCRIPT_LEN = 5
BODY_LAYER_FIELD = 0xFC
BODY_COSTUME_BASE = 0x30
#: Смещения слоя от базового у предмета одной руки.
LAYER_IN_HAND, LAYER_AT_REST = 0, 1
LAYER_OFF_HAND, LAYER_OFF_REST = 2, 3
#: Щит за спиной — тот же слой плюс шесть.
LAYER_SHIELD_BACK = 6
SHIELD_KIND = 4


def draw_script(data: bytes | None = None) -> list[list[int]]:
    """Сценарий отрисовки снаряжения: 8 направлений по 5 шагов (0x4627D0)."""
    from .exetables import va_to_foff
    from .paths import game_file
    if data is None:
        with open(game_file("konung2.exe"), "rb") as stream:
            data = stream.read()
    offset = va_to_foff(DRAW_SCRIPT_VA)
    return [list(data[offset + d * DRAW_SCRIPT_LEN:
                      offset + (d + 1) * DRAW_SCRIPT_LEN]) for d in range(8)]

#: Простой запускается ЖРЕБИЕМ, а не таймером бездействия (VA 0x416D92):
#: пока текущий блок — стойка, движок бросает rand() % 10 и при нуле
#: включает блок простоя. Тот доигрывает свои кадры (у героя 23 кадра, из них
#: 6 разных — остальное задержки) и по таблице 0x45A0C0 возвращается в стойку.
IDLE_CHANCE = 10

#: СКОЛЬКО ТАКТОВ ЗАНИМАЕТ КЛЕТКА — таблица 0x45FE90, байт на блок анимации.
#: Ставит её FUN_00429B2C (VA 0x429B3E) в байт юнита +0xFD:
#:
#:     *(char *)(юнит + 0xFD) = DAT_0045FE90[блок] - *(char *)(юнит + 0x1D);
#:
#: а такт шага (FUN_0041611C, VA 0x41612B) прибавляет единицу к счётчику
#: +0xFB, и по достижении +0xFD юнит переходит в следующую клетку
#: (FUN_00413894, VA 0x4143xx: ``if (юнит[0xFD] <= юнит[0xFB])``).
#:
#: Отсюда: КЛЕТКА = база_блока − скорость(+0x1D) тактов. Число кадров блока
#: (+0xFE) на скорость не влияет вовсе — оно только крутит спрайты.
MOVE_BLOCK_TICKS_VA = 0x0045FE90

#: Четыре блока хода — их выбирает FUN_00416C84 по битам байта +0x19:
#: 0x80 бег, 0x04 боевая стойка.
MOVE_BLOCKS = {"combat_walk": 0x01, "combat_run": 0x07,
               "walk": 0x11, "run": 0x13}

#: Смещения подшагов: X с 0x459AD4, Y с 0x459D14, по восемь float на походку
#: в порядке направлений W, NW, N, NE, E, SE, S, SW; всего 18 походок
#: (0x459D14 − 0x459AD4 = 0x240 = 18 × 32). Индекс — САМА походка +0xFD
#: (VA 0x416157: ``shl eax, 5`` по байту +0xFD плюс направление × 4).
#:
#: Походка N даёт ровно «клетка / N»: смещение × N — это (±58, 0), (±29, ±16)
#: или (0, ±32), то есть переход в соседнюю клетку. Это независимая проверка
#: того, что +0xFD и есть число тактов на клетку.
#:
#: Прежние 0x459AF4 / 0x459D34 — та же таблица, но с походки 1, поэтому
#: индексы уезжали на единицу; и обрывалась она на пяти походках из
#: восемнадцати.
GAIT_X_VA, GAIT_Y_VA, GAIT_COUNT = 0x00459AD4, 0x00459D14, 18


def _exe_blob() -> bytes:
    from .paths import game_file
    with open(game_file("konung2.exe"), "rb") as stream:
        return stream.read()


def move_block_ticks() -> dict[str, int]:
    """База длительности клетки по блокам хода: имя блока -> такты."""
    from .exetables import va_to_foff
    blob = _exe_blob()
    at = va_to_foff(MOVE_BLOCK_TICKS_VA)
    return {name: blob[at + block] for name, block in MOVE_BLOCKS.items()}


#: База клетки ТВАРИ — своя таблица по ТЕЛУ (+0xFC), а не четыре блока хода:
#: FUN_00429B2C, VA 0x429B93: ``mov dl, [тело*4 + 0x462734]; sub dl, [+0x1D];
#: mov [+0xFD], dl``. У большинства тел 12 тактов на клетку, у тела 17 — 7,
#: нули у неходячих. Бег твари не положен вовсе (0x416574 требует не-тварь).
BEAST_MOVE_TICKS_VA, BEAST_BODIES = 0x00462734, 32


def beast_move_ticks() -> list[int]:
    """Такты на клетку для тварей: индекс — тело (+0xFC)."""
    from .exetables import va_to_foff
    blob = _exe_blob()
    at = va_to_foff(BEAST_MOVE_TICKS_VA)
    return [blob[at + body * 4] for body in range(BEAST_BODIES)]


def gait_steps(count: int = GAIT_COUNT) -> list[list[list[float]]]:
    """Смещения по походкам: [походка][направление] -> (dx, dy)."""
    import struct

    from .exetables import va_to_foff
    blob = _exe_blob()
    x_at, y_at = va_to_foff(GAIT_X_VA), va_to_foff(GAIT_Y_VA)
    out = []
    for gait in range(count):
        xs = struct.unpack_from("<8f", blob, x_at + gait * 32)
        ys = struct.unpack_from("<8f", blob, y_at + gait * 32)
        out.append([[round(x, 3), round(y, 3)] for x, y in zip(xs, ys)])
    return out

#: Шаг юнита по направлениям — таблицы движка 0x459AD4 (X) и 0x459D14 (Y),
#: набор для пешей ходьбы. Совпадает с таблицей соседних клеток 0x49CF68:
#: запад/восток — целая колонка (58), север/юг — два ряда (32), диагонали —
#: половина колонки и ряд. Индекс: 0=W, 1=NW, 2=N, 3=NE, 4=E, 5=SE, 6=S, 7=SW.
DIRECTION_STEPS = ((-58, 0), (-29, -16), (0, -32), (29, -16),
                   (58, 0), (29, 16), (0, 32), (-29, 16))


def direction_of(dx, dy):
    """Направление движка по вектору движения (экранные оси)."""
    best, best_score = 0, None
    for index, (sx, sy) in enumerate(DIRECTION_STEPS):
        length = (sx * sx + sy * sy) ** 0.5
        score = (dx * sx + dy * sy) / length
        if best_score is None or score > best_score:
            best, best_score = index, score
    return best


def _crop(width, height, pixels):
    """Обрезка по непрозрачным точкам; (sprite, left, top) либо None."""
    left, top, right, bottom = width, height, -1, -1
    for y in range(height):
        row = y * width
        for x in range(width):
            if pixels[row + x][3]:
                if x < left:
                    left = x
                if x > right:
                    right = x
                if y < top:
                    top = y
                bottom = y
    if right < left:
        return None
    out_w, out_h = right - left + 1, bottom - top + 1
    out = [pixels[(top + y) * width + left + x]
           for y in range(out_h) for x in range(out_w)]
    return Sprite(out_w, out_h, out), left, top


class HeroesRes:
    """Чтение кадров юнитов из HEROES.RES."""

    #: Где лежит таблица смещений записей и на сколько сдвинуты слои.
    #: У канона ноль и ноль; «Продолжение легенды» задаёт своё (см. ниже).
    offsets_at = OFFSETS_AT
    layer_shift = 0
    layer_limit = LAYER_COUNT

    def __init__(self, data):
        self.data = data
        self.offsets = struct.unpack_from(
            f'<{OFFSET_COUNT}I', data, self.offsets_at)

    @classmethod
    def from_game(cls):
        with open(game_file('HEROES.RES'), 'rb') as f:
            return cls(f.read())

    def animation(self, kind, direction):
        """Номера записей кадров для (блок, направление)."""
        base = kind * KIND_STRIDE + direction * DIR_STRIDE
        row = struct.unpack_from('<24h', self.data, base)
        count = row[0]
        return [index for index in row[1:1 + count]]

    def record_span(self, index):
        start = self.offsets[index]
        end = self.offsets[index + 1] if index + 1 < OFFSET_COUNT else len(self.data)
        return start, end

    def layer_entry(self, index, layer=0, table=IMAGE_TABLE_AT):
        """(смещение_данных, строка_холста) слоя или None, если слоя нет.

        Номер слоя КАНОННЫЙ: у чужой сборки он сдвигается своим
        ``layer_shift`` (см. LegendHeroesRes).
        """
        if not 0 <= layer < self.layer_limit:
            return None
        layer += self.layer_shift
        start, end = self.record_span(index)
        off, y = struct.unpack_from('<Hh', self.data, start + table + layer * 4)
        if not off or start + off >= end:
            return None
        return off, y

    def decode_layer(self, index, layer=0, palette=None, trim=True):
        """Слой кадра как Sprite.

        Возвращает ``(sprite, dx, dy)``: смещение левого верха спрайта
        относительно ТОЧКИ НОГ юнита (якорь (127, 144) холста 256×150) —
        якорь задан форматом, одинаков для всех кадров и не дрожит.
        """
        if palette is None:
            palette = read_palettes()[0]
        entry = self.layer_entry(index, layer)
        if entry is None:
            return None, 0, 0
        off, y_start = entry
        start, _ = self.record_span(index)
        sprite = decode_rle(self.data, start + off, palette=palette, mode=8)
        if sprite is None:
            return None, 0, 0
        if not trim:
            return sprite, -ANCHOR_X, y_start - ANCHOR_Y
        cropped = _crop(sprite.width, sprite.height, sprite.pixels)
        if cropped is None:
            return None, 0, 0
        sprite, left, top = cropped
        return sprite, left - ANCHOR_X, y_start + top - ANCHOR_Y

    def decode_shadow(self, index, layer=0, trim=True):
        """Теневая маска слоя как Sprite (чёрная, альфа по спанам).

        Возвращает ``(sprite, dx, dy)`` в тех же осях, что decode_layer.
        """
        entry = self.layer_entry(index, layer, table=SHADOW_TABLE_AT)
        if entry is None:
            return None, 0, 0
        off, y_start = entry
        start, end = self.record_span(index)
        pos = start + off
        if pos + 4 > end:
            return None, 0, 0
        width, height = struct.unpack_from('<HH', self.data, pos)
        if not (0 < width <= 1024 and 0 < height <= 1024):
            return None, 0, 0
        pos += 4 + height * 2                     # пропустить длины строк
        pixels = [(0, 0, 0, 0)] * (width * height)
        for y in range(height):
            x = 0
            while pos < end:
                n = struct.unpack_from('<b', self.data, pos)[0]
                pos += 1
                if n == 0:
                    break
                if n < 0:
                    x += n & 0x7F
                else:
                    row = y * width
                    for i in range(n):
                        if x + i < width:
                            pixels[row + x + i] = (0, 0, 0, 255)
                    x += n
        sprite = Sprite(width, height, pixels)
        if not trim:
            return sprite, -ANCHOR_X, y_start - ANCHOR_Y
        cropped = _crop(width, height, pixels)
        if cropped is None:
            return None, 0, 0
        sprite, left, top = cropped
        return sprite, left - ANCHOR_X, y_start + top - ANCHOR_Y


class LegendHeroesRes(HeroesRes):
    """HEROES.RES «Продолжения легенды»: тот же формат, две поправки.

    Числа ЗАМЕРЕНЫ, а не подобраны:

    * **таблица смещений записей** у него не на ``0x33E0``, а на
      ``0x3628`` (= ``OFFSETS_AT + 146*4``). По канонному адресу в его
      файле нули до 146-го индекса, по этому — 1400 ненулевых и 1399
      растущих пар подряд;
    * **в каждой таблице записи на два слоя больше**: у него их 56 против
      наших 54, шапка записи 0x1C0 против 0x1B0. Таблица теней идёт
      первой, поэтому таблица картинок начинается на восемь байт позже —
      отсюда и сдвиг ``layer_shift``. Номер слоя при этом ОБЩИЙ: наш слой
      L лежит под его L, просто читать его надо со сдвинутого места.
      Сверено по габаритам кадров: 298 совпадений из 298 на записях 8, 9,
      40, 120, 300 и 700, ни одного расхождения.

    Таблицы анимации (поза × направление → номера записей) у игр
    ПОБАЙТНО ОДИНАКОВЫ — 64 строки из 64, шаг на запад это записи 8…13 у
    обоих, — поэтому кадры сопоставляются по нашим же номерам.

    Два лишних слоя — это два его собственных тела: 6 (Иззарк, воин
    Жёлтых собак пустыни) и 7. Дальше таблицы нет, и предел обязан быть
    честным: при чтении «тела 8» разбор уходил в пиксели соседнего слоя и
    отдавал правдоподобную фигуру с мусорной полосой рядом, а ширина
    скакала от 138 до 703 точек.
    """

    offsets_at = 0x3628
    #: Таблица теней у него на два поля длиннее, значит картинки начинаются
    #: на 2 * 4 байта позже.
    layer_shift = 2
    #: 56 слоёв: 54 канонных плюс тела 6 и 7. Замерено по шапке записи.
    layer_limit = 56

    @classmethod
    def from_game(cls):
        from .donor import donor_file
        with open(donor_file('heroes.res'), 'rb') as stream:
            return cls(stream.read())
