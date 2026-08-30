# -*- coding: utf-8 -*-
"""
Профиль игры: где в этой сборке лежат данные.

Движок у «Крови Титанов» и «Продолжения легенды» ОДИН. Правила общие: тот же
формат карт, та же геометрия карты мира, тот же каталог объектов слот в слот,
та же раскладка `GAME.x`. Поэтому ядро переносится даром — сегодня это
проверено на плитках (все 141 донорская собирается нашей GRAPH.RES), на
объектах (326 гнёзд побайтно) и на жителях (наш map_units читает донорский
GAME.0: 52 населённые карты).

А вот АДРЕСА не переносятся ни один. Перебор всех 34 табличных констант ядра
дал ноль совпадений: у донора не совпало ни одной таблицы по своему адресу.
Иначе и быть не может — это другая сборка того же исходника, компоновщик
разложил данные заново.

Отсюда правило: адрес — это ДАННЫЕ ПРОФИЛЯ, а не константа в коде.

НЕИЗВЕСТНЫЙ АДРЕС ОБЯЗАН ПАДАТЬ. Ни одно поле здесь не «наследуется от
канона по умолчанию»: чужая сборка по канонному адресу возвращает не ошибку,
а правдоподобный мусор, и сегодня это уже стоило четырёх ложных находок
(таблица локаций «на 98 записей», сетка мира «по нашему адресу», выходы
«со сдвигом 13846»). Поэтому не найденное поле равно ``None`` и обращение к
нему бросает исключение с именем поля.
"""
from __future__ import annotations

import os
import struct
from dataclasses import dataclass, field, fields
from typing import Any

IMAGE_BASE = 0x400000


class UnknownAddress(LookupError):
    """Адрес для этой сборки ещё не найден."""


#: Разобранные exe по пути к файлу: байты и секции.
#:
#: КЕШ ЗДЕСЬ НЕ РОСКОШЬ. Без него `va_to_foff` перечитывал и заново разбирал
#: весь файл на КАЖДЫЙ вызов — а его зовут на каждую запись таблицы. На
#: донорском exe в 6.3 МБ чтение двух сотен классов предметов вставало
#: намертво, и тесты уходили в таймаут.
_LOADED: dict[str, tuple[bytes, list]] = {}


def sections(blob: bytes) -> list[tuple[str, int, int, int]]:
    """Секции PE из самого файла: имя, RVA, размер в файле, смещение.

    Разбор проверен тем, что на нашем exe воспроизводит константы, снятые
    вручную (тест в tests/test_donor_contract.py).
    """
    if blob[:2] != b"MZ":
        raise ValueError("не исполняемый файл: нет MZ")
    at = struct.unpack_from("<I", blob, 0x3C)[0]
    if blob[at:at + 4] != b"PE\0\0":
        raise ValueError(f"по 0x{at:X} нет подписи PE")
    count = struct.unpack_from("<H", blob, at + 6)[0]
    optional_size = struct.unpack_from("<H", blob, at + 20)[0]
    table = at + 24 + optional_size
    out = []
    for index in range(count):
        entry = table + index * 40
        name = blob[entry:entry + 8].rstrip(b"\0").decode("ascii", "replace")
        _, rva, raw_size, raw_at = struct.unpack_from("<IIII", blob, entry + 8)
        if raw_at and raw_size:
            out.append((name, rva, raw_size, raw_at))
    return out


@dataclass(frozen=True)
class StringTable:
    """Массив строк: где начало, какой шаг и сколько записей.

    Шаг не всегда четыре. У канона названия локаций — простой массив
    указателей, у донора те же названия лежат полем внутри записи в 46
    байт, и указатель на имя стоит в её начале.
    """
    at: int                      # файловое смещение начала таблицы
    stride: int                  # шаг между записями
    count: int                   # сколько записей
    pointer_at: int = 0          # где внутри записи лежит указатель


@dataclass(frozen=True)
class GameProfile:
    """Всё, что различается между сборками одного движка."""

    name: str
    directory: str
    exe: str

    #: Строковые таблицы.
    npc_names: StringTable | None = None
    location_names: StringTable | None = None

    #: Карта мира.
    world_grid_va: int | None = None
    world_markers_va: int | None = None
    world_arrivals_va: int | None = None
    #: Значок локации может лежать не отдельной таблицей, а полем записи:
    #: у донора это +0x08 внутри той же 46-байтовой записи локации.
    location_marker_at: int | None = None

    #: Куда сетка этой игры ложится на общую карту проекта: (строка, столбец).
    world_at: tuple[int, int] = (0, 0)

    #: Формат карт: сколько записей зон сверх нашего формата.
    extra_zones: int = 0

    #: Каталог объектов: последнее годное гнездо.
    last_object_slot: int | None = None

    #: КЛАССЫ ПРЕДМЕТОВ. Запись 32 байта, в начале указатель на название —
    #: по этому признаку таблица и находится. У донора она на 0x04F6F4, и
    #: поля от +0x11 лежат НА ОДИН БАЙТ РАНЬШЕ наших: хвост записи совпадает
    #: побайтно только со сдвигом (82 предмета из 211), без сдвига — ни разу.
    #: Имя по тому же номеру совпадает у 193 из 211.
    items_at: int | None = None           # файловое смещение таблицы
    items_field_shift: int = 0            # на сколько сдвинуты поля от +0x11

    #: GAME.<мир>: таблицы лежат подряд, без дыр, и раскладка — просто
    #: нарастающая сумма count*size. Проверено на каноне: семь таблиц дают
    #: в точности размер файла, 813902 байта. Значит достаточно знать длины.
    game_parties: int | None = None       # записей в таблице отрядов
    game_exits_at: int | None = None      # начало блока выходов
    game_exits_bytes: int | None = None   # его длина в байтах
    game_exit_size: int | None = None     # размер записи выхода
    #: НА СКОЛЬКО ПОЛЯ ЗАПИСИ ВЫХОДА СДВИНУТЫ ОТ КАНОННЫХ. У донора запись
    #: короче на байт, и всё, кроме первого заполнителя, лежит на байт
    #: раньше: поворот на +1 вместо +2, карта-источник на +2 вместо +3.
    game_exit_shift: int = 0
    game_units: int | None = None
    game_villages: int | None = None
    game_events: int | None = None

    #: ОБРАБОТЧИКИ РАЗГОВОРА: массив адресов кода. Ищется по признаку
    #: «подряд идущие указатели в секцию кода»: на нашем exe это даёт ровно
    #: одну таблицу нужной длины, на донорском — одну на 93 записи.
    handlers_at: int | None = None
    handlers_count: int | None = None

    #: QUESTS.RES: семь секций подряд, раскладка снова нарастающая сумма.
    #: Хранится списком (имя, длина) — смещения считаются, как в GAME.<мир>.
    quests_sections: tuple[tuple[str, int], ...] = ()

    #: Адреса, которые ещё не искали. Держим списком, чтобы работа была
    #: перечнем, а не туманом: каждое имя — одна находка.
    unknown: tuple[str, ...] = ()

    def file(self, name: str) -> str:
        return os.path.join(self.directory, name)

    def _loaded(self):
        path = self.file(self.exe)
        if path not in _LOADED:
            with open(path, "rb") as stream:
                blob = stream.read()
            _LOADED[path] = (blob, sections(blob))
        return _LOADED[path]

    def exe_bytes(self) -> bytes:
        return self._loaded()[0]

    def available(self) -> bool:
        return os.path.isfile(self.file(self.exe))

    def need(self, attribute: str) -> Any:
        """Значение поля; не найдено — падаем с внятным именем."""
        value = getattr(self, attribute)
        if value is None:
            raise UnknownAddress(
                f"{self.name}: адрес «{attribute}» для этой сборки не найден. "
                f"Читать по канонному нельзя: чужая сборка вернёт не ошибку, "
                f"а правдоподобный мусор")
        return value

    def quests_layout(self) -> dict[str, tuple[int, int]]:
        """Секции QUESTS.RES: имя -> (смещение, длина). Смещения считаются."""
        out, at = {}, 0
        for name, size in self.need("quests_sections"):
            out[name] = (at, size)
            at += size
        out["__end__"] = (at, 0)
        return out

    def game_layout(self) -> dict[str, tuple[int, int, int]]:
        """Раскладка GAME.<мир>: имя таблицы -> (смещение, записей, размер).

        Считается, а не хранится: таблицы лежат подряд, без дыр, и смещение
        каждой это сумма длин предыдущих. На каноне сумма всех семи даёт
        ровно размер файла, 813902 байта, — проверено тестом.

        Размеры записей это структуры движка, и они у двух игр одинаковы;
        различаются только ДЛИНЫ таблиц. У донора их четыре: отрядов 255
        вместо 200, юнитов 2007 вместо 2000, поселений 20 вместо 12, и
        блок выходов свой.
        """
        from .gamefile import (T_EVENTS, T_GROUND, T_ITEMS, T_PARTIES,
                               T_UNITS, T_VILLAGES)
        out: dict[str, tuple[int, int, int]] = {}
        at = 0
        for name, count, size in (
                ("items", T_ITEMS.count, T_ITEMS.size),
                ("parties", self.need("game_parties"), T_PARTIES.size)):
            out[name] = (at, count, size)
            at += count * size
        out["ground_items"] = (at, T_GROUND.count, T_GROUND.size)
        at += T_GROUND.count * T_GROUND.size
        # ВЫХОДЫ ЗАДАНЫ БЛОКОМ, А НЕ ЧИСЛОМ ЗАПИСЕЙ: длину блока даёт
        # арифметика файла, а число записей выводится из неё делением. У
        # канона это 250 по 17, у донора 350 по 16 — и в обоих случаях
        # остатка нет, что само по себе проверка размера записи.
        block = self.need("game_exits_at")
        if at != block:
            raise ValueError(f"{self.name}: выходы должны начинаться на "
                             f"0x{block:X}, а сумма предыдущих даёт 0x{at:X}")
        size = self.need("game_exit_size")
        count, remainder = divmod(self.need("game_exits_bytes"), size)
        if remainder:
            raise ValueError(f"{self.name}: блок выходов "
                             f"{self.game_exits_bytes} байт не делится на "
                             f"запись в {size} байт — размер записи неверен")
        out["exits"] = (at, count, size)
        at += count * size
        for name, count, size in (
                ("units", self.need("game_units"), T_UNITS.size),
                ("villages", self.need("game_villages"), T_VILLAGES.size),
                ("events", self.need("game_events"), T_EVENTS.size)):
            out[name] = (at, count, size)
            at += count * size
        out["__end__"] = (at, 0, 0)
        return out

    def va_to_foff(self, va: int) -> int | None:
        rva = va - IMAGE_BASE
        for _, section_rva, size, at in self._loaded()[1]:
            if section_rva <= rva < section_rva + size:
                return at + (rva - section_rva)
        return None


#: «Кровь Титанов» — то, на чём стоит порт. Значения те же, что были
#: константами в модулях; профиль их не меняет, а собирает в одном месте.
CANON = GameProfile(
    name="Кровь Титанов",
    directory=os.environ.get(
        "KONUNG2_DIR",
        r"C:\Program Files (x86)\Князь - Коллекционное издание"
        r"\02. Князь 2 - Кровь Титанов"),
    exe="konung2.exe",
    npc_names=StringTable(at=0x4D48C, stride=4, count=206),
    location_names=StringTable(at=0x4D2D4, stride=4, count=44),
    world_grid_va=0x460174,
    world_markers_va=0x4615CC,
    world_arrivals_va=0x460028,
    location_marker_at=None,          # у канона значки отдельной таблицей
    world_at=(0, 22),
    extra_zones=0,
    last_object_slot=509,
    items_at=0x0496F0,
    game_parties=200,
    game_exits_at=0x45288,
    game_exits_bytes=250 * 17,
    game_exit_size=17,
    game_units=2000,
    game_villages=12,
    game_events=10,
    handlers_at=0x04EA90,
    handlers_count=76,
    quests_sections=(("dialog_nodes", 0x0FA00), ("phrase_table", 0x0BB80),
                     ("phrase_a", 0x05DC0), ("phrase_b", 0x05DC0),
                     ("dialog_roots", 0x00258), ("strings", 0x4B000),
                     ("quest_states", 0x004B0)),
)

#: «Продолжение легенды». Заполняется по мере находок; чего нет — того нет,
#: и обращение к нему падает.
LEGEND = GameProfile(
    name="Продолжение легенды",
    directory=os.environ.get(
        "KONUNG25_DIR",
        r"C:\Program Files (x86)\Князь - Коллекционное издание"
        r"\02. Князь 2 - Продолжение легенды"),
    exe="konung25.exe",
    npc_names=StringTable(at=0x054050, stride=4, count=214),
    location_names=StringTable(at=0x052E58, stride=0x2E, count=100),
    world_grid_va=0x00461920,
    world_markers_va=None,            # значок лежит полем записи локации
    world_arrivals_va=None,
    location_marker_at=0x08,
    world_at=(10, 0),
    extra_zones=32,
    last_object_slot=587,
    # ОТРЯДОВ 255, А НЕ 200. Замерено по границам пустот в самом файле:
    # данные возобновляются на 0x2FF04 и 0x4898A против наших 0x2C804 и
    # 0x4528A, то есть сдвиг ровно +14080 = 55*256. Отсюда же следует начало
    # таблицы выходов, и с ним согласны все 963 арифметических решения.
    #
    # Что запись отряда читается верно, доказано отдельно: цепочка индексов
    # юнитов идёт без разрывов (1415+18=1433, +17=1450, +8=1458 и дальше).
    items_at=0x04F6F4,
    items_field_shift=1,
    game_parties=255,
    game_exits_at=0x48988,
    # ЗАПИСЬ ВЫХОДА У ДОНОРА 16 БАЙТ, А НЕ 17, И ПОЛЯ НА БАЙТ РАНЬШЕ. Снято
    # с дампа: по шагу 16 записи встают ровно, по 17 расползаются. Разбор
    # трёх раскладок на одном и том же блоке не оставляет выбора — «16 со
    # сдвигом» даёт 300 годных записей и НИ ОДНОЙ бракованной, «16 без
    # сдвига» ноль годных, прежняя догадка про 272 байта тоже ноль. Проверка
    # сама по себе не поддавки: на каноне она разводит верную раскладку
    # (185 годных, 0 брака) и ложную (11 против 186).
    game_exits_bytes=350 * 16,
    game_exit_size=16,
    game_exit_shift=1,
    # ПОСЕЛЕНИЯ И СОБЫТИЯ — из тех же пустот, с конца файла: данные
    # возобновляются на 0x0C6F68 и 0x0CCBFC, и обе длины выходят целыми,
    # 23700/1185 = 20 и 160/16 = 10.
    game_villages=20,
    game_events=10,
    # ЮНИТОВ 2000, КАК У КАНОНА, И БАЗА ТАБЛИЦЫ 0x49F68.
    #
    # Здесь стояло 2007 и база 0x49868 — ошибка, и вот чем она вскрыта.
    # Прежний довод был «различия миров начинаются там, где таблица юнитов»,
    # и он верный, а замер был неточный. Различия начинаются на 0x49F7A, то
    # есть на 0x12 от 0x49F68, — и ровно так же ведёт себя канон: там первое
    # различие на 0x46334, тоже база плюс 0x12. Это не совпадение, а поле:
    # +0x12 у юнита — строка клетки, и у нулевого юнита она в каждом мире
    # своя.
    #
    # Три независимых подтверждения:
    #   * содержимое. Записи выхода читаются подряд до 0x49C48, дальше 50
    #     пустых ровно до 0x49F68. При базе 0x49868 первые семь «юнитов»
    #     были бы кусками этих записей — и юнит 0 там выходит уровня 255
    #     без имени, тогда как на 0x49F68 это «Иззарк», уровень 1, здоровье
    #     1600, то есть герой самой игры;
    #   * ссылки отрядов. При новой базе НИ ОДИН отряд не указывает на
    #     пустую запись юнита, при прежней таких 83 из 798;
    #   * арифметика. 0x0C6F68 − 0x49F68 = 512000 = 2000 * 256 без остатка,
    #     а блок выходов выходит 5600 = 350 * 16, тоже без остатка.
    #
    # Прежнее «подтверждение содержимым» (отряд из девяти имён на карте 19)
    # ничего не доказывало: сдвиг на семь записей кратен размеру записи, и
    # по неверной базе читается такой же связный, но ЧУЖОЙ отряд.
    game_units=2000,
    # QUESTS.RES донора: 616200 байт против наших 469000. Границы сняты по
    # крупным пустотам и по подписи «таблица узлов кончается заполнителем
    # FF, следующая начинается нулями» — у нас так на 0x0FA00, у него на
    # 0x1F400. Узлов вдвое больше (32000 dword), таблица фраз ТА ЖЕ (6000
    # по восемь), phrase_a и phrase_b выросли до 10000, корни и состояния
    # квестов длиной как у нас. Сумма семи секций даёт размер файла до байта.
    handlers_at=0x055A98,
    handlers_count=93,
    quests_sections=(("dialog_nodes", 0x1F400), ("phrase_table", 0x0BB80),
                     ("phrase_a", 0x09C40), ("phrase_b", 0x09C40),
                     ("dialog_roots", 0x00258), ("strings", 0x57800),
                     ("quest_states", 0x004B0)),
    unknown=(
        # КУДА ОТРЯД ВСТАЁТ, ВОЙДЯ НА КАРТУ. Проверена и отвергнута догадка,
        # что это записи выхода с источником 127: на каноне, где таблица
        # прибытий известна, из восьми сравнимых записей сошлась ОДНА. Такие
        # записи — цели действия разговора «перенести отряд по переходу»,
        # они адресуются номером в таблице и с прибытием не связаны.
        "world_arrivals_va",
        "item_classes_va",            # предметы и артефакты
        "creatures_va",               # характеристики тварей
        # Таблица обработчиков НАЙДЕНА (93 записи), а вот СОВПАДЕНИЕ
        # НУМЕРАЦИИ с нашей не доказано. Побайтное сравнение кода не
        # годится — в инструкциях сидят абсолютные адреса; сравнение
        # размеров функций дало 8 совпадений из 76 при 8 и 10 у сдвигов,
        # то есть шум. Качественно похоже, что номера общие: простые
        # обработчики-сравнения совпали по размеру точно и на своих местах
        # (1, 2, 3, 5, 10, 11 — все по 60 байт), а разошлись сложные. Но
        # это довод, а не доказательство.
        "handler_numbering_shared",
    ),
)

PROFILES = {profile.name: profile for profile in (CANON, LEGEND)}


def strings(profile: GameProfile, table: StringTable) -> list[str]:
    """Прочитать строковую таблицу профиля.

    Одна функция на обе игры: различие целиком в StringTable, а чтение
    указателя и строки одинаковое.
    """
    blob = profile.exe_bytes()
    out = []
    for index in range(table.count):
        at = table.at + index * table.stride + table.pointer_at
        pointer = struct.unpack_from("<I", blob, at)[0]
        offset = (profile.va_to_foff(pointer)
                  if IMAGE_BASE < pointer < IMAGE_BASE + 0x400000 else None)
        if offset is None:
            out.append("")
            continue
        end = blob.find(b"\0", offset, offset + 120)
        raw = blob[offset:end] if end > offset else b""
        out.append(raw.decode("cp866", "replace")
                   if raw and all(byte >= 0x20 for byte in raw) else "")
    return out
