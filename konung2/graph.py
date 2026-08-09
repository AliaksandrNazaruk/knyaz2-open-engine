# -*- coding: utf-8 -*-
"""
`GRAPH.RES` — палитры и тайлы земли.

Раскладка снята с загрузчика (VA 0x43D214)::

    0x00000            0x20000 байт   256 палитр x 256 цветов x u16
    далее 9 x { u32 len; len байт }   служебные блоки (0x840BB8[i])
    u32 data_len
    0x1F40 байт                       таблица 1000 x {u32 offset; u32 palette}
    data_len байт                     данные тайлов

Проверка: конец последнего блока совпадает с размером файла байт в байт.

Земля рисуется функцией VA 0x424FD8. Слой 1 карты (`.KN2`, смещение 0)
хранит 160 строк по 160 байт: на клетку два байта — два наложенных тайла,
0 значит «нет тайла», иначе индекс равен ``байт - 1``. Экранные координаты::

    x = col * 0x74 + (0x3A if row & 1 else 0)
    y = row * 0x20
"""
from __future__ import annotations

import math
import struct

from .paths import game_file
from .res import LKP5TO8, PALETTE_BLOCK, Sprite, read_palettes

GRAPH_BLOCKS = 9
TILE_TABLE_SIZE = 0x1F40
TILE_SLOTS = TILE_TABLE_SIZE // 8

#: Шаг изометрической решётки земли (VA 0x42502C, 0x425047, 0x42504E).
TILE_STEP_X, TILE_STEP_Y, TILE_ODD_SHIFT = 0x74, 0x20, 0x3A
#: Размер тайла: 0x72 x 0x40 — константы в функции наложения (VA 0x43FD88).
TILE_WIDTH, TILE_HEIGHT = 0x72, 0x40
#: Слой тайлов в .KN2: 160 строк по 160 байт, по два тайла на клетку.
GROUND_AT, GROUND_ROWS, GROUND_STRIDE = 0, 160, 0xA0
#: Слой освещения: те же клетки, но один байт на клетку (VA 0x425238).
LIGHT_AT, LIGHT_STRIDE = 0x6400, 0x50

#: `LIGHTS.RES` (загрузчик VA 0x43D594): два служебных блока, затем 19 масок
#: локального тёплого света по 114 x 64 байта. VA 0x43FD70 сначала накладывает
#: оба тайла обычным source-over, затем осветляет красный и зелёный каналы.
LIGHT_HEADER = 0x1000 + 0xAC0
LIGHT_MASK_SIZE = TILE_WIDTH * TILE_HEIGHT       # 0x1C80, шаг в массиве 0x611010
LIGHT_LEVELS = 0x1F
#: ДЫМКА СВЕЧЕНИЯ (В11): второй «служебный» блок LIGHTS.RES — радиальная
#: маска яркости 64 x 43 (значения 0…43, углы нулевые). Загрузчик 0x43C228
#: кладёт её в 0x6A5598, а проходы кругов выделения (0x424514, 0x424FD8)
#: при флаге 0x849610 (Факел или Чистая слеза) рисуют её вокруг круга со
#: сдвигом (−0x20, −0x15) от его центра блитом-осветлением 0x43FBDC.
GLOW_AT, GLOW_WIDTH, GLOW_HEIGHT = 0x1000, 64, 43
GLOW_OFFSET = (-0x20, -0x15)


def glow_mask(data: bytes | None = None) -> bytes:
    """Маска дымки свечения: 64*43 байта яркости из LIGHTS.RES."""
    if data is None:
        with open(game_file('LIGHTS.RES'), 'rb') as stream:
            data = stream.read()
    return data[GLOW_AT:GLOW_AT + GLOW_WIDTH * GLOW_HEIGHT]
#: Диапазоны случайной фазы мерцания из VA 0x428628. Для статического content
#: pack берётся первая реально возможная фаза оригинального движка.
LIGHT_GREEN_MIN, LIGHT_RED_MIN = 8, 16
#: Уровни ночи (VA 0x429832, dword 0x00CECEBA): байт 0 -> 0x58E2C8 (синий),
#: байт 1 -> 0x58E2C9 (зелёный), байт 2 -> 0x58E2CA (красный).
NIGHT_LEVEL_BLUE, NIGHT_LEVEL_GREEN, NIGHT_LEVEL_RED = -70, -50, -50
#: Тик, с которого движок включает локальный свет: ветка «ночь» ставит
#: [0x8495CC] = 1 (VA 0x429806) при t >= i16 @0x45FC46.
LIGHT_FROM_TICK = 8100

# Maps whose dword at .KN2 +0x3D180 is non-zero have an additional 256x256
# animated underlay.  The original builds its displacement table at
# VA 0x43E023 and warps the GRAPH.RES tile at VA 0x43F46E/0x43F4D9.
ANIMATED_TILE_SIZE = 0x100
ANIMATED_WAVE_PERIOD = 0x80


#: Таблица постоянного освещения: dword на номер карты (VA 0x4617B0).
FIXED_LIGHT_VA = 0x4617B0


def fixed_light_word(number):
    """Сырая запись таблицы 0x4617B0 для карты."""
    from .exetables import va_to_foff
    from .paths import game_file
    with open(game_file('konung2.exe'), 'rb') as stream:
        stream.seek(va_to_foff(FIXED_LIGHT_VA) + number * 4)
        return struct.unpack('<I', stream.read(4))[0]


def fixed_light_map(number):
    """Карта со ВСЕГДА включённым локальным светом (пещеры и подземелья).

    VA 0x4295E4: ``[0x8495CC] = таблица_0x4617B0[карта] & 0xFF000000`` — старший
    байт записи включает проход VA 0x43FD70 независимо от времени суток; ночью
    флаг и так ставится в 1 (VA 0x429806).

    ЭТО НЕ ПРИЗНАК «СУТОК НЕТ» — старший байт стоит только у карт 1 и 2. Для
    «цикла нет» смотри :func:`fixed_light`, там сравнивается ВЕСЬ dword.
    """
    return bool(fixed_light_word(number) & 0xFF000000)


def fixed_light(number):
    """Постоянное освещение карты: есть ли суточный цикл и какие уровни.

    Загрузчик карты кладёт запись ЦЕЛИКОМ (VA 0x43DF48: ``[0x8495A4] =
    таблица[карта]``), а расчёт освещения смотрит именно её:

        if ([0x8495A4] == 0) { ... суточная кривая по 0x84962C % 0x5460 ... }
        else                 { уровень = таблица[карта] & 0xFFFFFF; }

    (VA 0x4295D8, строки 17 и 138 декомпилята.) То есть при ЛЮБОЙ ненулевой
    записи часы не спрашиваются вовсе, а уровень берётся из младших трёх
    байтов — знаковых: 0xBA это −70, 0xCE это −50, 0xFF это −1.

    Записи есть у семи карт: 1 и 2 (Дворец Повелителя и Лабиринт смерти) —
    0x01CECEBA, вечная глубокая ночь с флагом локального света; 45..49
    (пещеры, рудник, подземное капище, подземная тюрьма) — 0x00FFFFFF,
    почти дневной ровный свет и БЕЗ флага.
    """
    value = fixed_light_word(number)
    signed = lambda byte: byte - 256 if byte >= 128 else byte
    return {
        'value': value,
        # суточного цикла нет при любой ненулевой записи, а не только у карт
        # со старшим байтом
        'frozen': value != 0,
        'always': bool(value & 0xFF000000),
        'levels': {'blue': signed(value & 0xFF),
                   'green': signed((value >> 8) & 0xFF),
                   'red': signed((value >> 16) & 0xFF)},
    }


def _light_factors():
    """The 100 float32 rows built by VA 0x43CA8B (step = float32 0.01)."""
    value = 0.0
    result = []
    for _ in range(100):
        result.append(value)
        value = struct.unpack('<f', struct.pack('<f', value + 0.009999999776482582))[0]
    return tuple(result)


_LIGHT_FACTORS = _light_factors()


def _brighten(value, level, maximum):
    """Таблица «плюс» (VA 0x43CB9E): value + round((max - value) * level/100)."""
    level = max(0, min(len(_LIGHT_FACTORS) - 1, int(level)))
    return value + round((maximum - value) * _LIGHT_FACTORS[level])


def _darken(value, level):
    """Таблица «минус» (VA 0x43CAD0): round(value * (1 - level/100)).

    Округление стоит ПОСЛЕ умножения — не ``value - round(value*f)``.
    Уровень неотрицательный: движок для level >= 0 берёт строку 0, то есть
    тождество (VA 0x442854, ``jns``), поэтому осветлять «минусом» нельзя.
    """
    level = max(0, min(len(_LIGHT_FACTORS) - 1, int(level)))
    return round(value * (1.0 - _LIGHT_FACTORS[level]))


def _lkp6to8(value):
    """Expand the green channel of an R5G6B5 framebuffer to 8 bits."""
    value = max(0, min(0x3F, value))
    return (value << 2) | (value >> 4)


def composite_sprites(*layers):
    """Наложить прозрачные спрайты в порядке от нижнего к верхнему.

    Обычная клетка земли рисуется движком двумя последовательными вызовами
    ``draw``.  Сборщику content pack нужен тот же результат в одном PNG, иначе
    второй байт клетки теряется или прозрачные участки тайла становятся
    чёрными.
    """
    visible = [sprite for sprite in layers if sprite is not None]
    if not visible:
        return None
    width = max(sprite.width for sprite in visible)
    height = max(sprite.height for sprite in visible)
    pixels = [(0, 0, 0, 0)] * (width * height)
    for sprite in visible:
        for y in range(sprite.height):
            source = y * sprite.width
            target = y * width
            for x in range(sprite.width):
                pixel = sprite.pixels[source + x]
                if pixel[3]:
                    pixels[target + x] = pixel
    return Sprite(width, height, pixels)


def read_light_masks(data=None):
    """Маски локального освещения из LIGHTS.RES."""
    if data is None:
        with open(game_file('LIGHTS.RES'), 'rb') as f:
            data = f.read()
    count = (len(data) - LIGHT_HEADER) // LIGHT_MASK_SIZE
    return [data[LIGHT_HEADER + i*LIGHT_MASK_SIZE:
                 LIGHT_HEADER + (i+1)*LIGHT_MASK_SIZE] for i in range(count)]


class GraphRes:
    """Палитры и тайлы земли."""

    def __init__(self, data):
        self.data = data
        pos = PALETTE_BLOCK
        self.blocks = []
        for _ in range(GRAPH_BLOCKS):
            length = struct.unpack_from('<I', data, pos)[0]
            pos += 4
            self.blocks.append((pos, length))
            pos += length
        self.data_size = struct.unpack_from('<I', data, pos)[0]
        pos += 4
        self.table_at = pos
        self.tiles_at = pos + TILE_TABLE_SIZE
        self._palettes = None

    @classmethod
    def from_game(cls):
        with open(game_file('GRAPH.RES'), 'rb') as f:
            return cls(f.read())

    @property
    def palettes(self):
        if self._palettes is None:
            self._palettes = read_palettes(self.data)
        return self._palettes

    def tile_entry(self, index):
        """(смещение данных, смещение палитры) для тайла."""
        if not 0 <= index < TILE_SLOTS:
            return None
        return struct.unpack_from('<2I', self.data, self.table_at + index * 8)

    def tile_palette(self, index):
        """Номер палитры тайла: движок хранит байтовое смещение в блоке."""
        entry = self.tile_entry(index)
        if entry is None:
            return None
        pal = entry[1] // 512
        return pal if pal < len(self.palettes) else None

    def raw_palette(self, index):
        """Палитра как есть: 256 значений u16 в формате X1R5G5B5."""
        return struct.unpack_from('<256H', self.data, index * 512)

    def decode_tile(self, index, palette=None):
        """Распаковать тайл земли."""
        entry = self.tile_entry(index)
        if entry is None:
            return None
        offset, pal_offset = entry
        if palette is None:
            index = self.tile_palette(index)     # незанятые записи дают мусор
            if index is None or self.tiles_at + offset + 4 > len(self.data):
                return None
            palette = self.palettes[index]

        base = self.tiles_at + offset
        width, height = struct.unpack_from('<2H', self.data, base)
        if not (0 < width <= 4096 and 0 < height <= 2048):
            return None
        pos = base + 4 + height * 2          # таблица длин строк пропускается
        transparent = (0, 0, 0, 0)
        pixels = [transparent] * (width * height)
        for y in range(height):
            x = 0
            while pos < len(self.data):
                n = self.data[pos]; pos += 1
                if n == 0:
                    break
                if n & 0x80:
                    x += n & 0x7F
                else:
                    for v in self.data[pos:pos + n]:
                        if x < width:
                            r, g, b = palette[v]
                            pixels[y * width + x] = (r, g, b, 255)
                        x += 1
                    pos += n
                if x > width:
                    break
        return Sprite(width, height, pixels)

    def compose_cell(self, lower, upper):
        """Обычная клетка: сначала первый тайл, затем второй (VA 0x424FD8)."""
        first = self.decode_tile(lower) if lower is not None else None
        second = self.decode_tile(upper) if upper is not None else None
        return composite_sprites(first, second)

    def animate_underlay(self, index, wave_phase=1, scroll_phase=1,
                         horizontal_scroll=True):
        """Return one exact frame of the original 256x256 map underlay.

        ``konung2.exe`` decodes the tile selected by the .KN2 dword at
        ``+0x3D180`` and then remaps it through a 256-entry sine table
        (VA 0x43E023, 0x43F46E).  Maps whose first mask byte does not have
        bit 7 set additionally rotate every row (VA 0x43F4D9).  The render
        loop increments both phases before producing its first frame, hence
        the deterministic defaults of one.
        """
        source = self.decode_tile(index)
        if source is None:
            return None
        if source.width != ANIMATED_TILE_SIZE or source.height != ANIMATED_TILE_SIZE:
            return source

        # The executable uses the truncated high word of
        # (sin(i * 3.14159 * 2 / 128) + 1) * 524288.
        displacement = [
            (int((math.sin(i * 3.14159 * 2.0 * 0.0078125) + 1.0) * 524288.0)
             >> 16) & 0xFFFF
            for i in range(ANIMATED_TILE_SIZE)
        ]
        phase = int(wave_phase) & (ANIMATED_WAVE_PERIOD - 1)
        size = ANIMATED_TILE_SIZE
        pixels = [(0, 0, 0, 0)] * (size * size)
        for y in range(size):
            x_shift = displacement[phase + (y & 0x7F)]
            target = y * size
            for x in range(size):
                source_y = (y + displacement[phase + (x & 0x7F)]) & 0xFF
                source_x = (x + x_shift) & 0xFF
                pixels[target + x] = source.pixels[source_y * size + source_x]

        if horizontal_scroll:
            shift = int(scroll_phase) & 0xFF
            if shift:
                for y in range(size):
                    start = y * size
                    row = pixels[start:start + size]
                    pixels[start:start + size] = row[-shift:] + row[:-shift]
        return Sprite(size, size, pixels)


    def _tile_indices(self, index):
        """Тайл как поле индексов палитры (None — прозрачно) и номер палитры."""
        entry = self.tile_entry(index)
        if entry is None:
            return None, None, 0, 0
        offset, pal_offset = entry
        base = self.tiles_at + offset
        width, height = struct.unpack_from('<2H', self.data, base)
        if not (0 < width <= 4096 and 0 < height <= 2048):
            return None, None, 0, 0
        pos = base + 4 + height * 2
        field = [None] * (width * height)
        for y in range(height):
            x = 0
            while pos < len(self.data):
                n = self.data[pos]; pos += 1
                if n == 0:
                    break
                if n & 0x80:
                    x += n & 0x7F
                else:
                    for v in self.data[pos:pos + n]:
                        if x < width:
                            field[y * width + x] = v
                        x += 1
                    pos += n
                if x > width:
                    break
        return field, pal_offset // 512, width, height

    def _cell_components(self, lower, upper):
        """Компонентный буфер клетки (VA 0x53C0AC): по (b5, g6, r5) на пиксель.

        Оба тайла распаковываются в ОДИН буфер (два вызова VA 0x442AF1), то
        есть непрозрачный пиксель верхнего тайла замещает нижний. Маска в этом
        не участвует — она влияет только на выбор канальных таблиц.
        """
        f0, p0, w, h = self._tile_indices(lower) if lower is not None else (None, None, 0, 0)
        f1, p1, w1, h1 = self._tile_indices(upper) if upper is not None else (None, None, 0, 0)
        w, h = max(w, w1), max(h, h1)
        if not w or not h:
            return None, 0, 0
        raw0 = self.raw_palette(p0) if p0 is not None else None
        raw1 = self.raw_palette(p1) if p1 is not None else None
        buffer = [None] * (w * h)
        for i in range(w * h):
            color = raw0[f0[i]] if f0 is not None and f0[i] is not None else None
            if f1 is not None and f1[i] is not None:
                color = raw1[f1[i]]
            # Движок проверяет развёрнутый dword палитры и пропускает ноль,
            # даже если в RLE стоял явный индекс.
            if not color:
                continue
            # Установленный оригинал идёт в 16 бит R5G6B5 ([0x8496F4] == 0x10):
            # зелёная компонента индексируется как component*4 (VA 0x43FEE7),
            # то есть 5 бит палитры разворачиваются в 6 бит кадра как g*2.
            buffer[i] = (color & 0x1F, ((color >> 5) & 0x1F) * 2, (color >> 10) & 0x1F)
        return buffer, w, h

    def _lit_pixel(self, comps, level, green_light, red_light,
                   blue_level, green_level, red_level):
        """Цвет пикселя клетки по VA 0x43FD70 при уровнях суток.

        Синий всегда идёт через таблицу текущего уровня ([0x58E2C4]) — маска
        на него не влияет. Красный и зелёный при ненулевой маске сначала
        осветляются «плюсом» мерцания (пересчёт компоненты, таблицы 0x476A50
        и 0x49D02C, VA 0x442890), а затем гасятся таблицей уровня
        ``уровень + маска`` (массивы указателей 0x476AD0 и 0x49D0AC строятся
        циклами VA 0x44283A и 0x442865: строка m = уровень + m, неотрицательный
        уровень даёт строку 0, то есть дневную яркость).
        """
        blue, green, red = comps
        if level:
            green = _brighten(green, green_light, 0x3F)
            red = _brighten(red, red_light, 0x1F)
        return (
            _darken(red, max(0, -(red_level + level))),
            _darken(green, max(0, -(green_level + level))),
            _darken(blue, -min(0, blue_level)),
        )

    def illuminate_cell(self, lower, upper, mask,
                        green_light=LIGHT_GREEN_MIN, red_light=LIGHT_RED_MIN,
                        blue_level=NIGHT_LEVEL_BLUE,
                        green_level=NIGHT_LEVEL_GREEN,
                        red_level=NIGHT_LEVEL_RED):
        """Клетка земли, освещённая маской, — как её рисует VA 0x43FD70."""
        buffer, w, h = self._cell_components(lower, upper)
        if buffer is None:
            return None
        pixels = [(0, 0, 0, 0)] * (w * h)
        for y in range(h):
            for x in range(w):
                i = y * w + x
                if buffer[i] is None:
                    continue
                level = mask[y * TILE_WIDTH + x] if x < TILE_WIDTH and y < TILE_HEIGHT else 0
                red, green, blue = self._lit_pixel(
                    buffer[i], level, green_light, red_light,
                    blue_level, green_level, red_level)
                pixels[i] = (LKP5TO8[red], _lkp6to8(green), LKP5TO8[blue], 255)
        return Sprite(w, h, pixels)

    def light_delta_cell(self, lower, upper, mask,
                         green_light=LIGHT_GREEN_MIN, red_light=LIGHT_RED_MIN,
                         green_level=NIGHT_LEVEL_GREEN,
                         red_level=NIGHT_LEVEL_RED):
        """Прибавка света: «клетка с маской» минус «та же клетка без маски».

        Движок не смешивает освещённую клетку с обычной — он рисует её сразу
        нужным цветом. Браузерный клиент так не может: ночной фильтр там общая
        заливка кадра. Поэтому в пак идёт РАЗНОСТЬ, которую клиент кладёт
        поверх готового кадра режимом ``lighter`` (сложение):

            результат = минус(c, |L|) + [минус(плюс(c, k), |L + m|) - минус(c, |L|)]

        Разность выбрана намеренно, а не готовый цвет: при m = 0 она РАВНА
        НУЛЮ по построению, поэтому у ауры нет ни ступеньки, ни тёмной каймы
        на краю маски — ровно как в движке, где m = 0 идёт по обычной ветке
        (VA 0x43FEAE). Синяя прибавка всегда нулевая: маска синий не трогает.

        Разложение ``минус(c, |L+m|) = минус(c, |L|) + m/100 * c`` показывает,
        что главный член прибавки от уровня суток НЕ зависит; от него зависит
        лишь вклад мерцания, поэтому разность считается на ночных уровнях —
        тех самых, при которых движок вообще включает локальный свет
        (VA 0x429806, тик 8100).
        """
        buffer, w, h = self._cell_components(lower, upper)
        if buffer is None:
            return None
        pixels = [(0, 0, 0, 0)] * (w * h)
        for y in range(h):
            for x in range(w):
                i = y * w + x
                if buffer[i] is None:
                    continue
                level = mask[y * TILE_WIDTH + x] if x < TILE_WIDTH and y < TILE_HEIGHT else 0
                if not level:
                    continue
                blue, green, red = buffer[i]
                lit_g = _darken(_brighten(green, green_light, 0x3F),
                                max(0, -(green_level + level)))
                lit_r = _darken(_brighten(red, red_light, 0x1F),
                                max(0, -(red_level + level)))
                base_g = _darken(green, -min(0, green_level))
                base_r = _darken(red, -min(0, red_level))
                pixels[i] = (
                    max(0, LKP5TO8[lit_r] - LKP5TO8[base_r]),
                    max(0, _lkp6to8(lit_g) - _lkp6to8(base_g)),
                    0,
                    255,
                )
        return Sprite(w, h, pixels)

    def blend_cell(self, lower, upper, mask):
        """Compatibility alias for the formerly misidentified light pass."""
        return self.illuminate_cell(lower, upper, mask)


def ground_cells(kn2, include_empty=False):
    """Клетки земли: (row, col, нижний тайл, верхний тайл, маска освещения).

    Индексы получаются вычитанием единицы, ноль означает «ничего нет».
    """
    out = []
    for row in range(GROUND_ROWS):
        base = GROUND_AT + row * GROUND_STRIDE
        light_base = LIGHT_AT + row * LIGHT_STRIDE
        for col in range(GROUND_STRIDE // 2):
            lower, upper = kn2.data[base + col*2], kn2.data[base + col*2 + 1]
            light = kn2.data[light_base + col]
            if lower or upper or include_empty:
                out.append((row, col,
                            lower - 1 if lower else None,
                            upper - 1 if upper else None,
                            light - 1 if light else None))
    return out


def cell_position(row, col):
    """Экранные координаты левого верхнего угла клетки земли."""
    x = col * TILE_STEP_X + (TILE_ODD_SHIFT if row & 1 else 0)
    return x, row * TILE_STEP_Y
