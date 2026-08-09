# -*- coding: utf-8 -*-
"""
Ресурсные контейнеры .RES: палитры и спрайты.

Формат восстановлен по открытому движку Slavik (реимплементация «Князь 1»)
и сверен с файлами «Князь 2». Контейнерный уровень у второй части свой,
а кодек спрайтов и палитры — общие с первой.

GRAPH.RES   [0x20000 палитры: 256 палитр x 256 цветов x u16 X1R5G5B5]
            [курсоры] [блок тайлов: 512 x { u32 off; u32 palByteOff }]
OBJECTS.RES [u32 0][u32 firstOff][512 x { u32 off; u32 size }] — смещения от
            начала файла, записи без 8-байтового заголовка
LIGHTS.RES  без заголовка: карты интенсивности 0..100 (64x64, 64x43, 19 x 114x64)
SOUNDS.RES  таблица 1000 x { i32 off; i32 size } с нулевого смещения, данные
            с 8000; сэмплы — сырой PCM 22050 Гц, signed 16-bit LE, моно

Спрайт (RLE), одинаково для обеих частей:

    u16 w; u16 h; u16 line_len[h]      # длина упакованной строки в байтах
    далее по строкам:  n = u8
        n == 0      конец строки
        n & 0x80    пропустить (n & 0x7F) прозрачных пикселей
        иначе       серия из n пикселей: RL8 — n байт индексов палитры,
                                         RL16 — n значений u16 RGB555
"""
import struct

from .paths import game_file

PALETTE_BLOCK = 0x20000          # 256 палитр x 256 цветов x 2 байта
PALETTE_COUNT = 256
#: 5 бит -> 8 бит (GFX::Lkp5To8 из Slavik)
LKP5TO8 = [0, 8, 16, 24, 32, 41, 49, 57, 65, 74, 82, 90, 98, 106, 115, 123,
           131, 139, 148, 156, 164, 172, 180, 189, 197, 205, 213, 222, 230, 238, 246, 255]


def rgb555(v):
    """X1R5G5B5 -> (r, g, b) по таблице движка."""
    return (LKP5TO8[(v >> 10) & 0x1F], LKP5TO8[(v >> 5) & 0x1F], LKP5TO8[v & 0x1F])


def read_palettes(data=None):
    """Все 256 палитр из начала GRAPH.RES."""
    if data is None:
        with open(game_file('GRAPH.RES'), 'rb') as f:
            data = f.read(PALETTE_BLOCK)
    words = struct.unpack_from(f'<{PALETTE_BLOCK//2}H', data, 0)
    return [[rgb555(words[p*256 + i]) for i in range(256)] for p in range(PALETTE_COUNT)]


class Sprite:
    """Распакованный спрайт с альфа-каналом."""

    def __init__(self, width, height, pixels):
        self.width, self.height, self.pixels = width, height, pixels

    def to_image(self):
        from PIL import Image
        img = Image.new('RGBA', (self.width, self.height))
        img.putdata(self.pixels)
        return img

    def save(self, path):
        self.to_image().save(path)


def decode_rle(data, offset=0, palette=None, mode=8, max_size=4096):
    """Распаковать RLE-спрайт. mode: 8 — индексы палитры, 16 — RGB555."""
    if offset + 4 > len(data):
        return None
    w, h = struct.unpack_from('<HH', data, offset)
    if not (0 < w <= max_size and 0 < h <= max_size):
        return None
    pos = offset + 4 + h*2                      # пропускаем длины строк
    transparent = (0, 0, 0, 0)
    pixels = [transparent] * (w*h)
    for y in range(h):
        x = 0
        while True:
            if pos >= len(data):
                return None
            n = data[pos]; pos += 1
            if n == 0:
                break
            if n & 0x80:
                x += n & 0x7F
                continue
            if mode == 8:
                if pos + n > len(data):
                    return None
                for i in range(n):
                    idx = data[pos + i]
                    if x + i < w and palette:
                        r, g, b = palette[idx]
                        pixels[y*w + x + i] = (r, g, b, 255)
                pos += n
            else:
                if pos + n*2 > len(data):
                    return None
                for i in range(n):
                    v = struct.unpack_from('<H', data, pos + i*2)[0]
                    if x + i < w:
                        r, g, b = rgb555(v)
                        pixels[y*w + x + i] = (r, g, b, 255)
                pos += n*2
            x += n
            if x > w + 8:
                return None
    return Sprite(w, h, pixels)


def verify_sprite(data, offset, mode=8, min_wh=4, max_wh=1024):
    """Проверить, что по смещению лежит спрайт.

    Заголовок хранит длину каждой упакованной строки, и это отличная
    контрольная сумма: если разбор строки заканчивается ровно на заявленной
    длине для ВСЕХ строк, совпадение случайным быть практически не может.
    Возвращает (ширина, высота, размер_данных) или None.
    """
    if offset + 4 > len(data):
        return None
    w, h = struct.unpack_from('<HH', data, offset)
    if not (min_wh <= w <= max_wh and min_wh <= h <= max_wh):
        return None
    hdr = offset + 4 + h*2
    if hdr > len(data):
        return None
    lens = struct.unpack_from(f'<{h}H', data, offset + 4)
    pos = hdr
    for y in range(h):
        end = pos + lens[y]
        if end > len(data) or lens[y] == 0:
            return None
        x = 0
        while pos < end:
            n = data[pos]; pos += 1
            if n == 0:
                break
            if n & 0x80:
                x += n & 0x7F
            else:
                pos += n if mode == 8 else n*2
                x += n
        if pos != end or x > w:
            return None
    return w, h, pos - offset


def scan_sprites(data, mode=8, start=0, end=None, step=2, limit=None):
    """Найти все спрайты в блоке данных перебором с проверкой заголовка."""
    end = len(data) if end is None else min(end, len(data))
    pos = start
    found = []
    while pos < end:
        r = verify_sprite(data, pos, mode)
        if r:
            w, h, size = r
            found.append({'offset': pos, 'width': w, 'height': h, 'size': size, 'mode': mode})
            pos += max(size, step)
            if limit and len(found) >= limit:
                break
        else:
            pos += step
    return found


#: Таблица OBJECTS.RES: 1000 пар {u32 off; u32 size} с НУЛЕВОГО смещения.
OBJECTS_SLOTS = 1000
OBJECTS_TABLE_SIZE = OBJECTS_SLOTS * 8      # 0x1F40 = 8000 байт

#: Смещения в таблице отсчитываются от КОНЦА таблицы, а не от начала файла.
#: Загрузчик (VA 0x43D6B8) делает ``table[i].off += 0x1F40``.
OBJECTS_TABLE_BIAS = OBJECTS_TABLE_SIZE

#: У первых 30 слотов запись начинается с заголовка: 8 байт + анимации 1824 +
#: таблица кадров 4096 + привязки. Загрузчик (VA 0x43D6EA) для i < 30 делает
#: ``table[i].off += 0x1728``, то есть данные RLE идут с этого смещения.
OBJECTS_DYNAMIC_SLOTS = 30
OBJECTS_HEADER_SIZE = 0x1728                # 5928 байт


class ObjectsRes:
    """OBJECTS.RES: спрайты объектов карты.

    Раскладка (проверена на файле игры):

        0x00000            таблица 1000 x {u32 off; u32 size}
        слот 0             служебный блок 0..0x7DF70 (515 952 байта):
                           сама таблица, затем анимационные таблицы
        слоты 1..509       записи объектов, лежат в файле подряд
                           (508 из 508 пар смежны: off+size == следующий off)

    Номер слота для объекта карты — это поле ``sprite`` (s32 по смещению 0
    записи) плюс ``SIMPLE_SLOT_BASE``. Поле ``kind`` задаёт лишь класс и на
    выбор спрайта не влияет: один класс покрывает десятки слотов.
    """

    #: Простые объекты начинаются со слота 30: заголовки лежат в массиве
    #: 0x75835C, где элемент i соответствует слоту i + 30 (VA 0x43E7D8).
    SIMPLE_SLOT_BASE = OBJECTS_DYNAMIC_SLOTS

    @classmethod
    def slot_of(cls, obj):
        """Слот OBJECTS.RES для записи статического объекта карты."""
        return obj['sprite'] + cls.SIMPLE_SLOT_BASE

    def __init__(self, data):
        self.data = data
        self.entries = []
        for i in range(OBJECTS_SLOTS):
            off, size = struct.unpack_from('<II', data, i*8)
            if size in (0, 0xFFFFFFFF) or off == 0xFFFFFFFF:
                self.entries.append(None)
                continue
            off += OBJECTS_TABLE_BIAS          # смещение от конца таблицы
            self.entries.append((off, size) if off + size <= len(data) else None)

    def data_offset(self, slot):
        """Начало данных RLE записи: у первых 30 слотов после заголовка."""
        e = self.entries[slot]
        if e is None:
            return None
        return e[0] + (OBJECTS_HEADER_SIZE if slot < OBJECTS_DYNAMIC_SLOTS else 0)

    @property
    def service_block(self):
        """Служебный блок (слот 0): таблица и анимационные последовательности."""
        e = self.entries[0]
        return self.data[e[0]:e[0] + e[1]] if e else b''

    # --- служебный блок: запись с 8-байтовым заголовком ------------------
    SVC_HEADER = 0x1F40          # сразу за таблицей
    SVC_ANIMS = 0x1F48           # 48 x 38 байт
    SVC_FRAME_OFFSETS = 0x2668   # 512 пар i32 (тень, картинка)
    SVC_FRAME_ANCHORS = 0x3668   # i16 shd.x, shd.y, img.x, img.y
    SVC_DATA = 0x5168            # данные RLE
    #: Раскладка получена из кода (VA 0x416240): состояние — шаг 0x130,
    #: направление — шаг 0x26, номера кадров лежат с +8 записи.
    ANIM_STATES, ANIM_DIRS = 6, 8
    ANIM_STATE_STRIDE, ANIM_STRIDE = 0x130, 0x26
    #: Код читает номер кадра как *(u16*)(p + index*2 + 8), но по данным
    #: последовательность начинается с +2 и её длина совпадает со счётчиком
    #: в +0 (например count=12 и ровно 12 номеров 42,42,43,43…47,47).
    #: Значит индекс кадра в коде отсчитывается не от нуля; для чтения
    #: таблицы верна раскладка «u16 count, затем 18 номеров».
    ANIM_FRAMES_OFF, ANIM_FRAMES = 2, 18

    @property
    def ANIM_COUNT(self):
        return self.ANIM_STATES * self.ANIM_DIRS

    def animations(self):
        """48 последовательностей: 6 состояний x 8 направлений."""
        out = []
        for state in range(self.ANIM_STATES):
            for d in range(self.ANIM_DIRS):
                off = (self.SVC_ANIMS + state * self.ANIM_STATE_STRIDE
                       + d * self.ANIM_STRIDE)
                head = struct.unpack_from('<4H', self.data, off)
                ids = struct.unpack_from(f'<{self.ANIM_FRAMES}H', self.data,
                                         off + self.ANIM_FRAMES_OFF)
                out.append({'state': state, 'direction': d,
                            'head': list(head), 'frames': list(ids)})
        return out

    def frame_offsets(self, count=None):
        """Пары (смещение тени, смещение картинки) относительно SVC_DATA.

        Под таблицу отведено 512 слотов (4096 байт), но заполнены не все:
        в файле игры монотонная серия обрывается на 316-й паре, дальше нули.
        Поэтому по умолчанию возвращаются только заполненные записи.
        """
        out = []
        prev = -1
        limit = 512 if count is None else count
        for i in range(limit):
            shd, img = struct.unpack_from('<ii', self.data,
                                          self.SVC_FRAME_OFFSETS + i * 8)
            if count is None and not (0 <= img < len(self.data) and img > prev):
                break
            prev = img
            out.append((shd, img))
        return out

    #: У каждого кадра свой заголовок 8 байт (4 x i16 привязки), пиксели
    #: начинаются сразу за ним. Получено из кода: движок делает
    #: ``p = data + entry[4]; p += 8`` (VA 0x4162BE и др.).
    FRAME_HEADER = 8

    #: Слоты 30+ — простые объекты (постройки, ограды). У них заголовок
    #: 0x100 байт, данные RLE идут сразу за ним. Загрузчик (VA 0x43D72E)
    #: делает ``off += 0x100; size -= 0x100`` и копирует заголовок в
    #: отдельный массив 0x75835C + (slot - 30) * 0x100.
    SIMPLE_HEADER = 0x100
    #: Поля заголовка, проверенные по коду (VA 0x43E7D8 и 0x426953):
    #:   +0x00 s32  размер всей записи (совпал у 480 из 480 слотов)
    #:   +0x0C u32  палитра по умолчанию — байтовое смещение в блоке палитр
    #:              (индекс = значение / 512), как в таблице тайлов земли.
    #:              Движок копирует его в поле kind объекта карты, если там
    #:              ноль: постройку на карте можно перекрасить.
    #:   +0x14 s32  если > 0, у объекта есть дополнительные данные
    #:   +0xFD u8   счётчик, читается как *(s32*)(hdr+0xFA) >> 24
    SIMPLE_SIZE_AT, SIMPLE_KIND_AT, SIMPLE_EXTRA_AT = 0x00, 0x0C, 0x14
    #: Таблица состояний: 8 записей по 8 байт, в каждой пара смещений —
    #: маска перекрытия (+0x7C) и сам спрайт (+0x80); -1 значит «нет».
    #: Якоря лежат такой же таблицей: маски с +0xBC, спрайта с +0xC0.
    #: Прочитано из кода отрисовки (VA 0x426953 — маска, 0x426A7E — спрайт):
    #:     p = hdr + state * 8
    #:     x = pixel_x + *(i16*)(p + 0xC0);  y = pixel_y + *(i16*)(p + 0xC2)
    #:     sprite = data + *(u32*)(p + 0x80)
    SIMPLE_MASKS_AT, SIMPLE_FRAMES_AT = 0x7C, 0x80
    SIMPLE_MASK_ANCHORS_AT, SIMPLE_ANCHORS_AT = 0xBC, 0xC0
    SIMPLE_STATES, SIMPLE_STATE_STRIDE = 8, 8
    #: Дополнительные кадры постройки: стены и крыша. Назначение подтверждено
    #: вызовами draw в оригинальном рендерере (VA 0x425AA8).
    SIMPLE_WALLS_AT, SIMPLE_ROOF_AT = 0x08, 0x10
    SIMPLE_INTERIOR_AT = SIMPLE_WALLS_AT  # compatibility with older tooling
    #: Кадр: ``u16 w; u16 h; u16 rows[h];`` затем RLE. Распаковщик
    #: (VA 0x43F26C) читает w и h, прибавляет 4, затем ``esi = p + h * 2``.
    SIMPLE_FRAME_HEADER = 4

    def simple_header(self, slot):
        """Поля заголовка простого объекта."""
        e = self.entries[slot]
        if e is None or slot < OBJECTS_DYNAMIC_SLOTS:
            return None
        b = e[0]
        return {
            'size': struct.unpack_from('<i', self.data, b + self.SIMPLE_SIZE_AT)[0],
            'kind': struct.unpack_from('<I', self.data, b + self.SIMPLE_KIND_AT)[0],
            'extra': struct.unpack_from('<i', self.data, b + self.SIMPLE_EXTRA_AT)[0],
            'walls': struct.unpack_from('<i', self.data, b + self.SIMPLE_WALLS_AT)[0],
            'roof': struct.unpack_from('<i', self.data, b + self.SIMPLE_ROOF_AT)[0],
            'count': self.data[b + 0xFD],
            'group': self.data[b + 0xFE],
            'raw': bytes(self.data[b:b + self.SIMPLE_HEADER]),
        }

    def simple_palette(self, slot):
        """Номер палитры простого объекта из заголовка."""
        header = self.simple_header(slot)
        if header is None:
            return None
        index = header['kind'] // 512
        return index if index < PALETTE_COUNT else None

    def simple_frames(self, slot):
        """Состояния простого объекта: спрайт, маска и их якоря."""
        e = self.entries[slot]
        if e is None or slot < OBJECTS_DYNAMIC_SLOTS:
            return []
        out = []
        for state in range(self.SIMPLE_STATES):
            p = e[0] + state * self.SIMPLE_STATE_STRIDE
            off = struct.unpack_from('<i', self.data, p + self.SIMPLE_FRAMES_AT)[0]
            mask = struct.unpack_from('<i', self.data, p + self.SIMPLE_MASKS_AT)[0]
            if off == -1 or not 0 <= off < e[1]:
                continue
            dx, dy = struct.unpack_from('<2h', self.data, p + self.SIMPLE_ANCHORS_AT)
            mx, my = struct.unpack_from('<2h', self.data, p + self.SIMPLE_MASK_ANCHORS_AT)
            out.append({'state': state, 'offset': off, 'dx': dx, 'dy': dy,
                        'mask': mask if mask != -1 else None,
                        'mask_dx': mx, 'mask_dy': my})
        return out

    def simple_parts(self, slot):
        """Видимые части объекта в порядке отрисовки.

        Блоки данных идут подряд, а смещения указывают начала кадров::

            [0, A)     основной спрайт          A = hdr[0x7C]
            [A, B)     маска перекрытия         B = hdr[0x08]
            [B, C)     стены без крыши          C = hdr[0x10]
            [C, конец) крыша

        Маска не является видимым кадром: движок строит по ней списки
        перекрытий (VA 0x43F260). Видимые кадры рисуются в порядке main,
        walls, roof с одной координатой (VA 0x425AA8).
        """
        h = self.simple_header(slot)
        if h is None:
            return []
        parts = [('main', 0)]
        for name, off in (('walls', h['walls']), ('roof', h['roof'])):
            if off > 0:
                parts.append((name, off))
        return parts

    def decode_building(self, slot, palette=None, state=0, show_roof=True):
        """Compose a static object exactly as ``konung2.exe`` does at VA 0x425AA8.

        The main state frame, the frame at header ``+0x08`` and the optional
        roof at ``+0x10`` are drawn in this order at the *same* top-left
        coordinate.  The original renderer never bottom-aligns these frames.
        """
        layers = self.decode_building_layers(slot, palette=palette, state=state)
        order = ('main', 'walls', 'roof') if show_roof else ('main', 'walls')
        visible = [layers[name] for name in order if name in layers]
        if not visible:
            return None, 0, 0

        width = max(item[0].width for item in visible)
        height = max(item[0].height for item in visible)
        pixels = [(0, 0, 0, 0)] * (width * height)
        for sprite, _, _ in visible:
            for y in range(sprite.height):
                source = y * sprite.width
                target = y * width
                for x in range(sprite.width):
                    pixel = sprite.pixels[source + x]
                    if pixel[3]:
                        pixels[target + x] = pixel
        dx, dy = visible[0][1:]
        return Sprite(width, height, pixels), dx, dy

    def decode_building_layers(self, slot, palette=None, state=0):
        """Части постройки с отдельными якорями для управляемого рендера."""
        frames = self.simple_frames(slot)
        frame = next((f for f in frames if f['state'] == state), None)
        if frame is None:
            frame = frames[0] if frames else {'offset': 0, 'dx': 0, 'dy': 0}
        main = self.decode_simple(slot, palette=palette, offset=frame['offset'])
        if main is None:
            return {}
        result = {'main': (main, frame['dx'], frame['dy'])}

        header = self.simple_header(slot)
        if header is None:
            return result
        for name, offset in (('walls', header['walls']), ('roof', header['roof'])):
            if offset <= 0:
                continue
            sprite = self.decode_simple(slot, palette=palette, offset=offset)
            if sprite is not None:
                result[name] = (sprite, frame['dx'], frame['dy'])
        shadow = self.decode_shadow(slot, state=state)
        if shadow is not None:
            result['shadow'] = (shadow, frame.get('mask_dx', 0), frame.get('mask_dy', 0))
        return result

    def decode_shadow(self, slot, state=0):
        """Маска тени состояния — чёрная форма с альфой.

        Движок не рисует её пиксели: 0x43F260 регистрирует строки маски как
        спаны, а 0x440788 после всех объектов делит яркость фона под спанами
        пополам (``and 0x7BDF; shr 1``), не затемняя перекрытия дважды.
        """
        frames = self.simple_frames(slot)
        frame = next((f for f in frames if f['state'] == state), None)
        if frame is None or frame.get('mask') is None:
            return None
        e = self.entries[slot]
        base = e[0] + self.SIMPLE_HEADER + frame['mask']
        end = e[0] + e[1]
        if base + 4 > end:
            return None
        width, height = struct.unpack_from('<2H', self.data, base)
        if not (0 < width <= 4096 and 0 < height <= 2048):
            return None
        pos = base + 4 + height * 2
        transparent = (0, 0, 0, 0)
        pixels = [transparent] * (width * height)
        # Формат спанов, не пиксельный RLE (VA 0x43F30D, movsx):
        # байт > 0 — непрозрачный интервал длины n БЕЗ байтов данных,
        # байт < 0 — пропуск (n & 0x7F), 0 — конец строки.
        for y in range(height):
            x = 0
            while pos < end:
                n = self.data[pos]; pos += 1
                if n == 0:
                    break
                if n & 0x80:
                    x += n & 0x7F
                else:
                    for _ in range(n):
                        if x < width:
                            pixels[y * width + x] = (0, 0, 0, 255)
                        x += 1
        return Sprite(width, height, pixels)

    def frame_size(self, slot, offset=0):
        """Размер кадра без распаковки пикселей: ``u16 w; u16 h`` в его начале.

        Нужен доменному слою и редактору: габариты постройки должны быть
        известны без декодирования RLE и без палитры.
        """
        e = self.entries[slot]
        if e is None or slot < OBJECTS_DYNAMIC_SLOTS:
            return None
        base = e[0] + self.SIMPLE_HEADER + offset
        if base + self.SIMPLE_FRAME_HEADER > e[0] + e[1]:
            return None
        width, height = struct.unpack_from('<2H', self.data, base)
        if not (0 < width <= 4096 and 0 < height <= 2048):
            return None
        return width, height

    def decode_simple(self, slot, palette=None, offset=0):
        """Распаковать кадр простого объекта (постройки, ограды).

        ``offset`` — смещение кадра внутри данных слота: 0 — основной кадр,
        либо значение из :meth:`simple_frames`, ``walls`` или ``roof``.
        """
        e = self.entries[slot]
        if e is None or slot < OBJECTS_DYNAMIC_SLOTS:
            return None
        if palette is None:
            palette = read_palettes()[0]

        base = e[0] + self.SIMPLE_HEADER + offset
        end = e[0] + e[1]
        if base + self.SIMPLE_FRAME_HEADER > end:
            return None
        width, height = struct.unpack_from('<2H', self.data, base)
        if not (0 < width <= 4096 and 0 < height <= 2048):
            return None

        pos = base + self.SIMPLE_FRAME_HEADER + height * 2
        transparent = (0, 0, 0, 0)
        pixels = [transparent] * (width * height)
        for y in range(height):
            x = 0
            # строка читается до нулевого байта, как в движке (0x43F26C):
            # выход за ширину не завершает строку, лишнее отсекается
            while pos < end:
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
        return Sprite(width, height, pixels)

    def object_frames(self, slot):
        """Таблица кадров объекта: пары (смещение тени, смещение картинки)."""
        e = self.entries[slot]
        if e is None:
            return []
        table = e[0] + self.SVC_FRAME_OFFSETS - self.SVC_HEADER
        out, prev = [], -1
        for i in range(512):
            shd, img = struct.unpack_from('<ii', self.data, table + i * 8)
            if not (0 <= img < e[1] and img > prev):
                break
            prev = img
            out.append((shd, img))
        return out

    def decode_frame(self, slot, index, palette, shadow=False):
        """Распаковать кадр объекта в Sprite.

        Кадр ограничен своими смещениями: картинка идёт от ``img`` до ``shd``,
        тень — от ``shd`` до начала следующего кадра. Ширина выводится из
        данных: строки разделены байтом 0x00, длина строки не хранится.
        """
        frames = self.object_frames(slot)
        if not 0 <= index < len(frames):
            return None
        base = self.data_offset(slot)
        shd, img = frames[index]
        if shadow:
            start = base + shd
            end = base + (frames[index + 1][1] if index + 1 < len(frames) else shd)
        else:
            start, end = base + img, base + shd
        if end <= start:
            return None

        rows, pos = [], start + self.FRAME_HEADER
        while pos < end:
            row, x = [], 0
            while pos < end:
                n = self.data[pos]; pos += 1
                if n == 0:
                    break
                if n & 0x80:
                    row.extend([None] * (n & 0x7F))
                    x += n & 0x7F
                else:
                    row.extend(self.data[pos:pos + n])
                    pos += n
                    x += n
            rows.append(row)
        if not rows:
            return None

        width = max((len(r) for r in rows), default=0)
        transparent = (0, 0, 0, 0)
        pixels = [transparent] * (width * len(rows))
        for y, row in enumerate(rows):
            for x, v in enumerate(row):
                if v is not None:
                    r, g, b = palette[v]
                    pixels[y * width + x] = (r, g, b, 255)
        return Sprite(width, len(rows), pixels)

    def frame_anchor(self, slot, index):
        """Четыре i16 из заголовка кадра — точки привязки при отрисовке."""
        frames = self.object_frames(slot)
        if not 0 <= index < len(frames):
            return None
        off = self.data_offset(slot) + frames[index][1]
        return struct.unpack_from('<4h', self.data, off)

    def frame_span(self, index):
        """Границы данных кадра: от его смещения до ближайшего следующего."""
        offs = self.frame_offsets()
        marks = sorted({v for pair in offs for v in pair if v >= 0})
        shd, img = offs[index]
        nxt = next((m for m in marks if m > img), None)
        start = self.SVC_DATA + img
        return start, (self.SVC_DATA + nxt) if nxt else None

    @classmethod
    def from_game(cls):
        with open(game_file('OBJECTS.RES'), 'rb') as f:
            return cls(f.read())

    def record(self, i):
        e = self.entries[i]
        if e is None:
            return None
        off, size = e
        return self.data[off:off+size]

    def used(self):
        return [i for i, e in enumerate(self.entries) if e]


# ---- NEWHERO.RES: экран создания героя -----------------------------------

#: Формат вскрыт 2026-08-09 и сходится ДО ПОСЛЕДНЕГО БАЙТА файла:
#:
#:     блок:  u32 размер                 (= 4 + 2*h + сумма длин строк)
#:            u16 w, u16 h
#:            u16 длины_строк[h]
#:            RLE:  байт 0        конец строки
#:                  байт & 0x80   пропуск (байт & 0x7F) прозрачных пикселей
#:                  иначе         серия из n пикселей, следом 2*n байт X1R5G5B5
#:
#: Пиксели ШЕСТНАДЦАТИБИТНЫЕ, а не индексы палитры — потому палитры в файле и
#: нет. Проверено арифметикой: строка фона занимает 2058 байт, это ровно
#: 1024 пикселя по два байта плюс девять управляющих байт (серии не длиннее
#: 127) плюс завершающий ноль. Декодирование всех одиннадцати блоков даёт
#: точную объявленную ширину в каждой строке, без единого расхождения.
#:
#: Состав файла: фон экрана 1024x768, шесть портретов героев 76x87 и две
#: пары мелких картинок (94x13 и 55x12). Движок держит фон по указателю
#: 0x6B35C0, а портреты по 0x6B35C8 + вид*8 (VA 0x430DF4).
NEWHERO_BACKGROUND, NEWHERO_PORTRAITS = 0, 6


def newhero_blocks(data=None):
    """Список блоков NEWHERO.RES: (смещение, w, h, смещение_данных, длины)."""
    if data is None:
        with open(game_file('NEWHERO.RES'), 'rb') as f:
            data = f.read()
    out = []
    at = 0
    while at + 8 <= len(data):
        size = struct.unpack_from('<I', data, at)[0]
        if size <= 0 or at + 4 + size > len(data):
            break
        w, h = struct.unpack_from('<2H', data, at + 4)
        rows = struct.unpack_from(f'<{h}H', data, at + 8)
        if 4 + 2 * h + sum(rows) != size:
            break
        out.append((at, w, h, at + 8 + 2 * h, rows))
        at += 4 + size
    return out


def newhero_sprite(index, data=None):
    """Разобрать блок в (w, h, пиксели RGBA). Прозрачное — нулевая альфа."""
    if data is None:
        with open(game_file('NEWHERO.RES'), 'rb') as f:
            data = f.read()
    blocks = newhero_blocks(data)
    if not 0 <= index < len(blocks):
        return None
    _, w, h, start, rows = blocks[index]
    pixels = [(0, 0, 0, 0)] * (w * h)
    pos = start
    for y in range(h):
        end = pos + rows[y]
        x = 0
        while pos < end:
            n = data[pos]
            pos += 1
            if n == 0:
                break
            if n & 0x80:
                x += n & 0x7F
                continue
            for i in range(n):
                value = struct.unpack_from('<H', data, pos + i * 2)[0]
                if x + i < w:
                    red, green, blue = rgb555(value)
                    pixels[y * w + x + i] = (red, green, blue, 255)
            pos += n * 2
            x += n
        pos = end
    return w, h, pixels
