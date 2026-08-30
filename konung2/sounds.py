# -*- coding: utf-8 -*-
"""
`SOUNDS.RES` — звуки: эффекты и фоновая музыка в одном контейнере.

Контейнер устроен как OBJECTS.RES: таблица 1000 × ``{u32 off; u32 size}``
с нулевого смещения, смещения отсчитываются от конца таблицы (0x1F40).
Конец последней записи совпадает с размером файла байт в байт.

Данные — сырой PCM без заголовков, и **формата ДВА**. В движке лежат два
разных WAVEFORMATEX, и слот звучит по тому, через какой путь его завели:

    эффекты, 0x8A7830 (заполняет VA 0x42A43C)   PCM, 1 канал, 22050, 16 бит
    музыка,  0x8A7A10 (заполняет VA 0x42CE0C)   PCM, 2 канала, 44100, 16 бит
                                                nAvgBytesPerSec 0x2B110,
                                                nBlockAlign 4

Музыку заводит VA 0x42D13C: она берёт смещение и размер из той же таблицы
(в памяти 0x6B6498), читает файл со сдвигом на 8000 = 0x1F40 и отдаёт буфер
DirectSound с форматом 0x8A7A10, ЗАЦИКЛЕННО (Play с флагом 1). Вызывают её
только со слотами 20…30 — это и есть музыкальные слоты, всё остальное
эффекты. Проверено и по данным: у слотов 20…30 средний скачок между
соседними отсчётами при чтении «через один» в 4…47 раз меньше, чем подряд,
то есть поток чередует два канала; у прочих слотов наоборот.

Раньше здесь стоял один формат на всё, и музыка выходила кашей на половинной
скорости — ровно тот случай, когда «трек не тот» на самом деле «трек не так
прочитан».

Ниже, после кодека, — КАНОН всей аудиосистемы: раскладка слотов, формулы
событий, позиционная громкость и панорама, шансы и лимиты. Всё снято с
konung2.exe (полный разбор — docs/AUDIO_AUDIT.md) и закреплено контрактным
тестом tests/test_audio_contract.py, который читает сам exe.
"""
from __future__ import annotations

import struct
import wave

from .paths import game_file

SOUND_SLOTS = 1000
SOUND_TABLE_SIZE = SOUND_SLOTS * 8            # 0x1F40
SAMPLE_WIDTH = 2                              # 16 бит в обоих форматах

#: Эффекты — WAVEFORMATEX 0x8A7830.
SAMPLE_RATE, CHANNELS = 22050, 1

#: Музыка — WAVEFORMATEX 0x8A7A10; слоты, которые движок заводит через 0x42D13C.
#:
#: ФОРМАТ ЗАДАЁТ МЕСТО ВЫЗОВА, А НЕ НОМЕР. 0x42D13C всегда берёт стереоформат
#: 44100, всё прочее играется моно 22050 — то есть «музыкальный слот» это
#: просто «слот, который куда-то передают в 0x42D13C». Отсюда и то, что у
#: двух игр наборы разные.
MUSIC_RATE, MUSIC_CHANNELS = 44100, 2
MUSIC_SLOTS = frozenset(range(20, 31))

#: Музыка «Продолжения легенды» — слоты 28…39, а НЕ канонные 20…30.
#: Доказано трижды и сходится:
#:   * дизасм: его проигрыватель музыки FUN_0042FED4, обёртка FUN_0041FA40
#:     зовёт его как `слот + 0x1C`, а выбор трека FUN_0043BC94 выдаёт только
#:     числа 0x1E…0x27 (30…39);
#:   * размеры: слоты 28…39 весят 4.6–8.2 МБ, соседние 20…27 и 42 — 19–66 КБ;
#:   * длительности при верном формате — 26.43…46.24 с, ровно канонный
#:     музыкальный диапазон; при канонной раскладке его музыка выходила
#:     105…185 с (вчетверо медленнее), а его эффекты — обрывками 0.11…0.37 с.
LEGEND_MUSIC_SLOTS = frozenset(range(28, 40))


def music_slots(game=None):
    """Музыкальные слоты своей игры: у донора они сдвинуты."""
    return LEGEND_MUSIC_SLOTS if game == 'legend' else MUSIC_SLOTS


def audio_format(slot, game=None):
    """(частота, каналов) для слота: музыка звучит не так, как эффекты."""
    if slot in music_slots(game):
        return MUSIC_RATE, MUSIC_CHANNELS
    return SAMPLE_RATE, CHANNELS

#: Выбор фонового трека (VA 0x437F48, карта в 0x8496C8):
#:   карта 26 -> 30; карта 27 -> 23; бой -> 28; поселение -> 24 + культура
#:   старейшины (0..2); карты 50+ -> 27; карты 28..32 -> 22; иначе -> 30.
#: Отдельно: глобальная карта -> 20 (выход, VA 0x4209FA), особый переход -> 21,
#: меню -> 29. Культуры сняты с живой игры (рантайм-байт юнита +0x1B).
TRACK_GLOBAL_MAP, TRACK_SPECIAL, TRACK_MENU, TRACK_BATTLE = 20, 21, 29, 28
VILLAGE_TRACK_BASE = 24

#: Культура старейшины по номеру карты поселения (peekmem, стенд 2026-08-04).
VILLAGE_CULTURES = {19: 0, 33: 0, 13: 0, 32: 0, 21: 0, 18: 0,
                    37: 1, 20: 1, 23: 1, 39: 1,
                    25: 2}


#: Те же роли у «Продолжения легенды» (FUN_0043BC94, музыка через FUN_0042FED4):
#:   бой -> 0x24, карта мира -> 0x25 (четыре места выхода на глобальную),
#:   поселение -> 0x20 + культура старейшины, прочее -> 0x26,
#:   а с флагом 1 записи локации (0x462C76 + карта*0x2E) -> 0x23.
#: Отдельные карты: 1 -> 0x26, 2 -> 0x1F, 5 -> 0x27, 29 -> 0x1E.
LEGEND_TRACK_GLOBAL_MAP, LEGEND_TRACK_BATTLE = 37, 36
LEGEND_TRACK_PLAIN, LEGEND_TRACK_FLAGGED = 38, 35
LEGEND_VILLAGE_TRACK_BASE = 32

#: Особые карты донора — прямо из FUN_0043BC94.
LEGEND_TRACK_BY_MAP = {1: 38, 2: 31, 5: 39, 29: 30}


def map_track(map_number, game=None, village=False, flagged=False):
    """Фоновый трек локации по правилам движка своей игры."""
    if game == 'legend':
        return legend_map_track(map_number, village, flagged)
    if map_number == 26:
        return 30
    if map_number == 27:
        return 23
    if map_number in VILLAGE_CULTURES:
        return VILLAGE_TRACK_BASE + VILLAGE_CULTURES[map_number]
    if map_number > 49:
        return 27
    if 27 < map_number <= 32:
        return 22
    return 30


def legend_map_track(map_number, village=False, flagged=False):
    """Фоновый трек локации «Продолжения легенды» (FUN_0043BC94).

    Три ветки правила сюда доехали как есть: особые карты, «поселение или
    нет» и бит 0 признаков локации (``konung2.donor.location_track_flag``).
    Не доехала одна, и она названа, чтобы не выглядеть сделанной:

    КУЛЬТУРА СТАРЕЙШИНЫ НЕ СНЯТА. Движок берёт её как
    ``0x74B0E4[байт +2 записи поселения] >> 24``, а 0x74B0E4 лежит ВНЕ секций
    exe — это данные его ``GAME.<мир>``, живые. У канона та же история, и там
    раскладка замерена стендом (VILLAGE_CULTURES); здесь замера нет, поэтому
    всем его поселениям достаётся культура 0, то есть слот 32. Это неточность
    выбора между тремя настоящими дорожками поселений, а не чужой звук.
    """
    if map_number in LEGEND_TRACK_BY_MAP:
        return LEGEND_TRACK_BY_MAP[map_number]
    if village:
        return LEGEND_VILLAGE_TRACK_BASE
    return LEGEND_TRACK_FLAGGED if flagged else LEGEND_TRACK_PLAIN


class SoundsRes:
    """Чтение звуков из SOUNDS.RES."""

    def __init__(self, data):
        self.data = data
        self.entries = []
        for index in range(SOUND_SLOTS):
            off, size = struct.unpack_from('<2I', data, index * 8)
            if off == 0xFFFFFFFF:
                self.entries.append(None)
            else:
                self.entries.append((off + SOUND_TABLE_SIZE, size))

    @classmethod
    def from_game(cls):
        with open(game_file('SOUNDS.RES'), 'rb') as f:
            return cls(f.read())

    def pcm(self, slot):
        """Сырой PCM записи (s16le; частота и каналы — см. audio_format)."""
        entry = self.entries[slot]
        if entry is None:
            return None
        off, size = entry
        return self.data[off:off + size]

    def duration(self, slot):
        entry = self.entries[slot]
        if entry is None:
            return None
        rate, channels = audio_format(slot)
        return entry[1] / (rate * channels * SAMPLE_WIDTH)

    def save_wav(self, slot, path):
        pcm = self.pcm(slot)
        if pcm is None:
            return False
        rate, channels = audio_format(slot)
        with wave.open(str(path), 'wb') as out:
            out.setnchannels(channels)
            out.setsampwidth(SAMPLE_WIDTH)
            out.setframerate(rate)
            out.writeframes(pcm)
        return True


# ---------------------------------------------------------------------------
# КАНОН аудиосистемы движка. Каждая константа привязана к месту в exe.
# ---------------------------------------------------------------------------

#: Проигрыватель эффектов VA 0x42D660(слот, громкость, пан, луп):
#: одновременно не больше 45 буферов (массив 0x8A7744, счётчик 0x8A7A50),
#: звук тише −40 дБ не заводится вовсе, кэш-промах (слот не в 0x840D04)
#: молчит. Возвращает хэндл (индекс+1) — им же звук останавливают (0x42EAF0).
MAX_BUFFERS = 45
VOLUME_GATE = -4000
SILENCE = -10000

#: Вариация питча эффектов: три WAVEFORMATEX подряд (0x8A77F8, заполняет
#: VA 0x42CE0C), проигрыватель берёт случайный из трёх. Вариация положена
#: слотам 32…699 и пяти UI-слотам — это звуки попаданий (см. hit_slot).
PITCH_RATES = (22050, 19050, 25050)
PITCH_UI_SLOTS = frozenset({3, 5, 12, 13, 15})
PITCH_SLOT_FROM, PITCH_SLOT_TO = 0x20, 700


def pitched(slot):
    """Положена ли слоту случайная вариация частоты (ветка 0x42D660)."""
    if PITCH_SLOT_FROM <= slot < PITCH_SLOT_TO:
        return True
    return slot in PITCH_UI_SLOTS


#: Позиционный звук. Громкость (VA 0x43BC74): клетка -> мировые пиксели
#: якоря (0x43B974), расстояние до ЦЕНТРА ОКНА МИРА (камера + (442, 354) —
#: половины окна 884x709), линейный спад до нуля на 2048 px. Пан (VA
#: 0x43BC20): 62.5 сотых на колонку от центра экрана — произведение
#: констант 10000.0 (0x45933A) и 0.00625 (0x459342).
HEARING_RADIUS = 0x800
SCREEN_CENTER = (0x1BA, 0x162)
PAN_PER_COLUMN = 62.5
PAN_CENTER_SHIFT = 5           # пан меряется от (левая колонка + 5)


def position_volume(distance):
    """Громкость в сотых дБ по расстоянию до центра экрана (0x43BC74)."""
    if distance > HEARING_RADIUS:
        return SILENCE
    return -(distance * 10000 // HEARING_RADIUS)   # деление с усечением к нулю


def position_pan(column_delta):
    """Пан в сотых по смещению колонки от центра (0x43BC20, fistp = банковское)."""
    return round(column_delta * PAN_PER_COLUMN)


#: Слоты интерфейса и общих событий (карта вызовов — AUDIO_AUDIT.md §7, §9).
#: Слоты 0, 11 и 13 в данных ПУСТЫ — эти события в оригинале немые (13 —
#: вырезанные ШАГИ ГЕРОЯ, набор ходьбы в 0x429B2C); сироты — только 8 и 19
#: (слот 5 оказался выстрелом лука, слот 1 — и «надеть», и взвод самострела).
CLICK_SLOT = 6                 # щелчок интерфейса и пунктов меню (0x438A00 case 1)
CONFIRM_SLOT = 18              # подтверждение, вход в локацию, пробел
TAKE_SLOT = 17                 # взять/положить предмет (0x41D954)
LEVEL_UP_SLOT = 14             # gainExperience своего юнита (0x413110)
WINDOW_SLOT = 11               # открыть окно (0x436C48) — немой
EQUIP_SLOTS = (0, 1, 2)        # надеть предмет по виду (0x41E280/0x41E8D8)
SILENT_SLOTS = frozenset({0, 11, 13})
ORPHAN_SLOTS = frozenset({8, 19})

#: Попадания по человеку (VA 0x412570): промах или блок — слот 12, иначе по
#: типу брони в гнезде (тип — из класса предмета, таблица 0x45DB08 +0x10).
HIT_MISS_SLOT = 12
HIT_BODY_SLOT = 7
HIT_ARMOR_SLOTS = {0: 7, 1: 15, 5: 3}
HIT_ARMOR_DEFAULT = 9

#: Озвучка смены анимации ЧЕЛОВЕКА (VA 0x429B2C, ветка без бита зверя) —
#: switch по номеру набора: стойки/простои (0,6,0x10,0x12) с шансом 4 % —
#: ``актёр*8+35`` (слот ПУСТ — кряхтенье вырезано); ходьба (1,0x11) ТОЛЬКО
#: у героя — слот 13 (ПУСТ — шаги вырезаны); реакция на удар (2) —
#: ``актёр*8+36`` КРИК БОЛИ; смерти (3,0xB,0xC) — ``актёр*8+34`` КРИК
#: СМЕРТИ; выстрел (4) — по предмету в руке: класс слоя 0x15 (самострел)
#: — слот 1 (взвод), иначе слот 5 (лук); замах (8) — по типу оружия.
HURT_CRY_OFFSET = 4                # 0x24: актёр*8+36, крик боли
DEATH_CRY_OFFSET = 2               # 0x22: актёр*8+34, крик смерти
IDLE_VOICE_OFFSET = 3              # 0x23: слот пуст — немое кряхтенье
HERO_STEPS_SLOT = 13               # пуст — немые шаги героя
SHOT_BOW_SLOT, SHOT_CROSSBOW_SLOT = 5, 1
CROSSBOW_CLASS_LAYER = 0x15


def hurt_cry_slot(actor):
    """Крик боли: ``актёр*8 + 36`` (0x429B2C, набор 2)."""
    return RESPONSE_BASE + actor * RESPONSE_STRIDE + HURT_CRY_OFFSET


def death_cry_slot(actor):
    """Крик смерти: ``актёр*8 + 34`` (0x429B2C, наборы 3/0xB/0xC)."""
    return RESPONSE_BASE + actor * RESPONSE_STRIDE + DEATH_CRY_OFFSET


#: Замах человека (та же VA 0x429B2C, набор 8): по типу оружия в руке.
SWING_SLOTS = {0xD: 16, 0xF: 4}
SWING_DEFAULT = 10


def hit_slot(armor_type):
    """Слот звука попадания по типу брони цели (None — брони нет)."""
    if armor_type is None:
        return HIT_BODY_SLOT
    return HIT_ARMOR_SLOTS.get(armor_type, HIT_ARMOR_DEFAULT)


def swing_slot(weapon_type):
    """Слот звука замаха по типу оружия (None — голые руки)."""
    if weapon_type is None:
        return SWING_DEFAULT
    return SWING_SLOTS.get(weapon_type, SWING_DEFAULT)


#: Голосовые отклики людей. Выбор юнита (VA 0x42D308): восьмёрка актёра в
#: 32…79, играются варианты +5…+7 (``актёр*8 + 37 + rand%3``); дорожки
#: +2 и +4 записаны, но код их не зовёт. Один голосовой канал (0x84963C).
RESPONSE_BASE, RESPONSE_STRIDE = 32, 8
RESPONSE_OFFSET, RESPONSE_VARIANTS = 5, 3
RESPONSE_ACTORS = 6

#: «Эй, есть разговор!» (VA 0x410A08, case 2 — приказ «подойти и
#: заговорить»): пока игрок ИДЁТ к собеседнику и ещё не дошёл (|Δстрок| < 7
#: и |Δколонок| < 4 открывают разговор молча), из одинарного голосового
#: канала играется ``база + актёр_идущего*4 + rand%2``. База — по ТИПУ
#: собеседника: старший байт записи таблицы 0x45FE8D[тип] (байт
#: 0x45FE90+тип) нулевой — 700, иначе 702. Сетка 700…723 закрывается
#: целиком: 6 актёров × 2 базы × 2 варианта — «дублей» здесь нет, а вечная
#: предзагрузка героя (0x43D898, четыре слота 700+актёр*4) как раз покрывает
#: обе его базы.
TALK_REQUEST_BASE, TALK_REQUEST_BASE_ALT = 700, 702
TALK_REQUEST_STRIDE, TALK_REQUEST_VARIANTS = 4, 2
TALK_NEAR_ROWS, TALK_NEAR_COLS = 7, 4
#: Типы собеседников со второй базой: байт 0x45FE90[тип] ненулевой.
TALK_ALT_BASE_TYPES = frozenset({1, 5, 7, 8, 9, 17, 19})


def response_slot(actor, roll):
    """Отклик на выбор: ``актёр*8 + 37 + roll%3`` (VA 0x42D308)."""
    return RESPONSE_BASE + actor * RESPONSE_STRIDE + RESPONSE_OFFSET + roll % RESPONSE_VARIANTS


def talk_request_slot(actor, target_type, roll):
    """«Эй, есть разговор!»: база по типу собеседника, актёр — идущего."""
    base = (TALK_REQUEST_BASE_ALT if target_type in TALK_ALT_BASE_TYPES
            else TALK_REQUEST_BASE)
    return base + actor * TALK_REQUEST_STRIDE + roll % TALK_REQUEST_VARIANTS


#: Звери (VA 0x429B2C): слот от ВИДА (байт unit+0xFC), позиционно.
#: Смерть — блок 5, атака — блоки 3/0xB/0xC, стойка — блок 0 (шанс 4 %),
#: ходьба — блок 1 (шанс 24 %), бег — блок 2 (всегда).
CREATURE_BASE, CREATURE_STRIDE = 80, 8
CREATURE_DEATH, CREATURE_ATTACK, CREATURE_IDLE, CREATURE_RUN = 0, 2, 3, 4
IDLE_SOUND_PERCENT = 4         # rand%100 >= 96 (0x60)
WALK_SOUND_PERCENT = 24        # rand%100 >= 76 (0x4C)


def creature_slot(kind, action):
    """Слот действия зверя: ``вид*8 + 80 + {0,2,3,4}``."""
    return CREATURE_BASE + kind * CREATURE_STRIDE + action


#: Спец-звук состояния 4 (VA 0x413894): при входе зверя в набор 4 на кадре 1
#: играется ``запись_OBJECTS*8 + 49`` (байт unit+0x1A = 0x40|запись, слот
#: = (0x40|запись)*8 − 463). Записаны только запись 9 (лодка, слот 121) и
#: запись 15 (исчезающий дух, слот 169), и оба в оригинале не слышны:
#: предзагрузка карт грузит восьмёрки ``запись*8+80…87``, куда 49-е слоты
#: не попадают. Включение их в порт — флаг fixes, не канон.
SPECIAL_STATE = 4
SPECIAL_OFFSET = 49


def special_slot(record):
    """Спец-звук зверя по номеру записи динамики."""
    return record * CREATURE_STRIDE + SPECIAL_OFFSET


#: Амбиент карт (VA 0x438A00): раз в тик с шансом 1 % (rand%100 > 98) из
#: восьмёрки карты ``(карта−1)*8 + 256``; днём слоты +0…+4 (rand%5), после
#: заката (гейт ночного света, тик 8100) +5…+7 (rand%3+5), на картах с
#: фиксированным светом (таблица 0x4617B0 — пещеры) все 8 (rand%8).
#: Позиционирования нет. Карты 6…54; у 1…5 амбиента не записано.
AMBIENT_BASE, AMBIENT_STRIDE = 0x100, 8
AMBIENT_CHANCE_PERCENT = 1
AMBIENT_DAY_VARIANTS = 5
AMBIENT_NIGHT_OFFSET, AMBIENT_NIGHT_VARIANTS = 5, 3

#: У «Продолжения легенды» база восьмёрки ДРУГАЯ — 300, а не 256. Обе
#: очереди устроены одинаково, отличается одно число:
#:
#:   канон  (0x43DF48): local_20 = n + (карта - 1) * 8 + 0x100;
#:                      if (1 < *(int *)(&DAT_006b649c + local_20 * 8)) ...
#:   донор  (0x4417E0): local_20 = n + (карта - 1) * 8 + 300;
#:                      if (1 < *(int *)(&DAT_006def3c + local_20 * 8)) ...
#:
#: Пока к его картам применялась канонная база, амбиент брался на 44 слота
#: раньше и звучал чужими звуками: на «Военном лагере Повелителя» (его
#: карта 14) играли слоты 360…367 вместо 404…411 — короткие мужские
#: вскрики не к месту, по многу раз подряд.
#:
#: РАЗБИВКА ДЕНЬ/НОЧЬ И ШАНС ОСТАВЛЕНЫ КАНОННЫМИ. В его коде проверена
#: только очередь загрузки; что он делит восьмёрку так же (+0…+4 днём,
#: +5…+7 ночью) и бросает тот же 1% — не доказано, а выдумывать вторую
#: разницу там, где видна одна, не стоит.
LEGEND_AMBIENT_BASE = 300


def ambient_base(game=None):
    """База восьмёрки амбиента своей игры."""
    return LEGEND_AMBIENT_BASE if game == 'legend' else AMBIENT_BASE


def ambient_slots(map_number, game=None):
    """Восьмёрка амбиента карты."""
    base = ambient_base(game) + (map_number - 1) * AMBIENT_STRIDE
    return range(base, base + AMBIENT_STRIDE)


#: Память и стриминг (VA 0x43C228 / 0x43D898 / 0x43DF48 / 0x43F07C):
#: при старте и каждой загрузке сейва в вечный кэш идут слоты 0…19,
#: 32…79 и четвёрка «пошёл» текущего героя; при входе на карту в очередь
#: 0x843C64 встают амбиент карты и восьмёрки ``запись*8+80…87`` всех
#: записей динамики среди юнитов карты (записи 14 и 15 — принудительно);
#: главный цикл догружает ПО ОДНОМУ слоту за тик. Арена — 3.5 МБ.
PRELOAD_UI = range(0, 20)
PRELOAD_RESPONSES = range(32, 80)
PRELOAD_FORCED_RECORDS = (14, 15)
SOUND_ARENA_BYTES = 3_500_000


def creature_preload_slots(record):
    """Что кладёт в очередь карта за зверя записи record (0x43DF48)."""
    base = CREATURE_BASE + record * CREATURE_STRIDE
    return range(base, base + CREATURE_STRIDE)


def hero_talk_slots(actor):
    """Четвёрка «Эй, есть разговор!» героя — вечная предзагрузка (0x43D898).

    Четыре слота ``700 + актёр*4`` покрывают обе базы формулы: 700-я для
    обычных собеседников и 702-я для типов из TALK_ALT_BASE_TYPES.
    """
    base = TALK_REQUEST_BASE + actor * TALK_REQUEST_STRIDE
    return range(base, base + TALK_REQUEST_STRIDE)


#: Личные частоты голосов: KONUNG2/_VOICES, CSV «голос,поправка». Движок
#: (VA 0x42A43C) строит WAVEFORMATEX 22050+поправка и пишет индекс формата
#: в 0x8A7344[голос]; номер голоса — байт unit+0xF2 (говорящий диалога —
#: 0x849658). Реплики и отклики звучат на частоте своего голоса.
VOICE_BASE_RATE = 22050


def voice_rates(path=None):
    """Частоты голосов из _VOICES: {номер голоса: частота}.

    Файл — DOS-текст с Ctrl+Z (0x1A) в конце; движок читает его sscanf-ом
    «%i,%i» до EOF-флага, поэтому хвост после последней пары игнорируем.
    """
    if path is None:
        path = game_file(r'KONUNG2\_VOICES')
    rates = {}
    with open(path, 'r', encoding='ascii') as stream:
        for line in stream:
            line = line.strip().rstrip('\x1a').strip()
            if not line:
                continue
            voice, delta = (int(part) for part in line.split(','))
            rates[voice] = VOICE_BASE_RATE + delta
    return rates


def rules():
    """Канон аудио для content pack (assets/audio.json)."""
    return {
        'mixer': {
            'max_buffers': MAX_BUFFERS,
            'volume_gate': VOLUME_GATE,
            'silence': SILENCE,
            'music_binary_volume': True,     # 0x42D0E8: 0 или −10000
        },
        'pitch': {
            'rates': list(PITCH_RATES),
            'ui_slots': sorted(PITCH_UI_SLOTS),
            'slot_range': [PITCH_SLOT_FROM, PITCH_SLOT_TO],
        },
        'position': {
            'hearing_radius': HEARING_RADIUS,
            'screen_center': list(SCREEN_CENTER),
            'pan_per_column': PAN_PER_COLUMN,
            'pan_center_shift': PAN_CENTER_SHIFT,
        },
        'ui': {
            'click': CLICK_SLOT, 'confirm': CONFIRM_SLOT, 'take': TAKE_SLOT,
            'level_up': LEVEL_UP_SLOT, 'window': WINDOW_SLOT,
            'equip': list(EQUIP_SLOTS),
            'silent_slots': sorted(SILENT_SLOTS),
            'orphan_slots': sorted(ORPHAN_SLOTS),
        },
        'combat': {
            'miss': HIT_MISS_SLOT, 'body': HIT_BODY_SLOT,
            'armor': {str(k): v for k, v in HIT_ARMOR_SLOTS.items()},
            'armor_default': HIT_ARMOR_DEFAULT,
            'swing': {str(k): v for k, v in SWING_SLOTS.items()},
            'swing_default': SWING_DEFAULT,
            'hurt_cry_offset': HURT_CRY_OFFSET,
            'death_cry_offset': DEATH_CRY_OFFSET,
            'shot_bow': SHOT_BOW_SLOT,
            'shot_crossbow': SHOT_CROSSBOW_SLOT,
            'crossbow_layer': CROSSBOW_CLASS_LAYER,
        },
        'voices': {
            'response': {'base': RESPONSE_BASE, 'stride': RESPONSE_STRIDE,
                         'offset': RESPONSE_OFFSET, 'variants': RESPONSE_VARIANTS,
                         'actors': RESPONSE_ACTORS},
            'talk_request': {'base': TALK_REQUEST_BASE,
                             'alt_base': TALK_REQUEST_BASE_ALT,
                             'alt_base_types': sorted(TALK_ALT_BASE_TYPES),
                             'stride': TALK_REQUEST_STRIDE,
                             'variants': TALK_REQUEST_VARIANTS,
                             'near_rows': TALK_NEAR_ROWS,
                             'near_cols': TALK_NEAR_COLS},
            'greeting': {'base': 5500, 'per_actor': 5, 'period_ticks': 1024},
            'base_rate': VOICE_BASE_RATE,
            'rates': voice_rates(),
        },
        'creatures': {
            'base': CREATURE_BASE, 'stride': CREATURE_STRIDE,
            'death': CREATURE_DEATH, 'attack': CREATURE_ATTACK,
            'idle': CREATURE_IDLE, 'run': CREATURE_RUN,
            'idle_percent': IDLE_SOUND_PERCENT,
            'walk_percent': WALK_SOUND_PERCENT,
            'special_state': SPECIAL_STATE,
            'special_offset': SPECIAL_OFFSET,
        },
        'ambient': {
            'base': AMBIENT_BASE, 'stride': AMBIENT_STRIDE,
            'chance_percent': AMBIENT_CHANCE_PERCENT,
            'day_variants': AMBIENT_DAY_VARIANTS,
            'night_offset': AMBIENT_NIGHT_OFFSET,
            'night_variants': AMBIENT_NIGHT_VARIANTS,
        },
        'streaming': {
            'preload_ui': [PRELOAD_UI.start, PRELOAD_UI.stop],
            'preload_responses': [PRELOAD_RESPONSES.start, PRELOAD_RESPONSES.stop],
            'forced_records': list(PRELOAD_FORCED_RECORDS),
            'slots_per_tick': 1,
        },
        'tracks': {
            'global_map': TRACK_GLOBAL_MAP, 'special': TRACK_SPECIAL,
            'menu': TRACK_MENU, 'battle': TRACK_BATTLE,
            'village_base': VILLAGE_TRACK_BASE,
        },
    }
