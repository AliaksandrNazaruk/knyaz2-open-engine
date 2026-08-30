# -*- coding: utf-8 -*-
"""
GAME.0 … GAME.5 ↔ JSON. Это стартовые состояния мира для шести героев;
игра читает их только при начале новой игры.

Раскладка (813902 байта, порядок чтения загрузчиком VA 0x43D89B):

    0x00000  0x20000  предметы          8192 x 16
    0x20000  0x0C800  ОТРЯДЫ             200 x 256   -> в памяти 0x71E56C
    0x2C800  0x18A88  предметы на земле 1000 x 101
    0x45288  0x0109A  ПЕРЕХОДЫ           250 x 17    -> в памяти 0x7B2B6C
    0x46322  0x7D000  ЮНИТЫ             2000 x 256   -> в памяти 0x7B3C08
    0xC3322  0x0378C  ПОСЕЛЕНИЯ           12 x 0x4A1 -> в памяти 0x83D408
    0xC6AAE  0x000A0  события/рейды       10 x 16

Ключевая связка «кто где стоит» (подтверждена дизассемблером, VA 0x43C529
``mov dword ptr [0x84950C], 0x71E56C`` — глобальный указатель на текущий отряд):

    отряд.base_unit (u16 @+0x00)  — индекс первого юнита отряда в массиве юнитов
    отряд.map       (u16 @+0x08)  — номер карты <N>.KN2, где стоит отряд
    отряд.count     (u8  @+0x1C)  — сколько юнитов принадлежит отряду

Движок вычисляет юнита как ``units + (base_unit + i) * 256`` и ставит его на
карту по клетке (X = юнит@+0x14, Y = юнит@+0x12), см. VA 0x423B00.
Отряд №0 — это отряд игрока (герой = юнит №0), его ``map`` = стартовая локация.
"""
import json
import struct
from pathlib import Path

from .binrec import RecordTable
from .effects import OIL_MARK_AT
from .items import STACK_KIND
from .paths import game_file

NUL = bytes(1)
WORLD_SIZE = 813902
#: GAME.0 … GAME.5 — шесть стартовых миров, по одному на героя.
WORLD_COUNT = 6

T_ITEMS = RecordTable('items', 0x00000, 8192, 16, [
    ('kind',     0, 'u8'),    # 0-4 оружие/броня, 6-8 украшения, 9 зелья, 12 стрелы
    ('id',       3, 'u8'),
    ('durability', 4, 'f32'),
    ('max_durability', 8, 'f32'),
    ('poison',  12, 'u16'),
    ('enchant', 14, 'u16'),   # 5 свойств по 3 бита
])

T_PARTIES = RecordTable('parties', 0x20000, 200, 256, [
    ('base_unit', 0x00, 'u16'),   # индекс первого юнита отряда
    ('map',       0x08, 'u16'),   # номер карты <N>.KN2
    ('x',         0x0C, 'u16'),
    ('y',         0x10, 'u16'),
    ('count',     0x1C, 'u8'),    # сколько юнитов в отряде
])

T_GROUND = RecordTable('ground_items', 0x2C800, 1000, 101, [
    ('y', 5, 'u8'),
    ('x', 6, 'u8'),
])

#: КУЧИ НА ЗЕМЛЕ — то, что лежит по всему миру: ягоды, грибы, кошели,
#: связки стрел. Тысяча записей по 101 байту, и загрузчик карты
#: (VA 0x43DF48) отбирает из них те, у кого байт +8 равен номеру карты:
#:
#:     +0x00 i16  метка времени сбора      +0x02 i16  её пара
#:     +0x05 u8   строка клетки            +0x06 u8   столбец
#:     +0x08 u8   НОМЕР КАРТЫ
#:     +0x09 u8   где лежит: 0xFF на земле, иначе номер места в объекте
#:     +0x0B i16  спрайт кучи
#:     +0x0F i16  деньги в куче
#:     +0x11      сорок два слова предметов (VA 0x43346C берёт их отсюда)
#:
#: ОТРАСТАНИЕ. Собранная куча не исчезает — ей ставят метку времени
#: (VA 0x4136A8: ``метка = −1 − время/360``), и загрузчик показывает её
#: снова, когда ``метка * 360 + время > 0x1517``. То есть ягоды и грибы
#: возвращаются примерно через 5399 тиков после сбора.
GROUND_ITEMS_AT, GROUND_ITEMS_COUNT, GROUND_ITEMS_SIZE = 0x2C800, 1000, 101
GROUND_MAP_AT, GROUND_PLACE_AT = 0x08, 0x09
GROUND_SPRITE_AT, GROUND_MONEY_AT, GROUND_SLOTS_AT = 0x0B, 0x0F, 0x11
GROUND_SLOTS = 42
GROUND_ON_FLOOR = -1
GROUND_REGROW_STEP, GROUND_REGROW_AFTER = 0x168, 0x1517
#: БАЙТ +0x07 — РАЗГОВОР КУЧИ, И ЭТО НОВОВВЕДЕНИЕ «ПРОДОЛЖЕНИЯ ЛЕГЕНДЫ».
#: Приказ «обыскать» на её клетке открывает не обмен, а диалог БЕЗ
#: СОБЕСЕДНИКА номер 0x100 + байт (донорский 0x411BC6: `if (byte < 0xFE)
#: FUN_0043a300(0, byte + 0x100)`). Так сделаны семь чанов с маслом в
#: Ущелье возле Угорья (диалоги 277…283); 0xFE и 0xFF — обычные кучи.
#: У КАНОНА ЭТОЙ ВЕТКИ НЕТ (его 0x4115AC байт не читает), и байт у него
#: не заполняется — в записях стоит ноль, который читался бы как
#: несуществующий «диалог 256». Поэтому байт разбирается ТОЛЬКО у донора.
GROUND_DIALOG_AT, GROUND_NO_DIALOG = 0x07, 0xFE
GROUND_DIALOG_BASE = 0x100
#: Игры, чей движок умеет разговорные кучи (по имени профиля).
_GROUND_DIALOG_GAMES = ("Продолжение легенды",)


def ground_items(number: int, world: int = 0, clock: int = 0,
                 profile=None) -> list[dict]:
    """Кучи на земле этой карты (VA 0x43DF48, таблица 0x2C800).

    ``clock`` — игровое время: собранная куча возвращается, только когда
    ``метка * 360 + время`` перевалит за 5399.

    ``number`` — номер карты В ТОЙ ЖЕ ИГРЕ, что и профиль: тайники
    донорских карт лежат в ЕГО GAME.<мир> и под ЕГО номером.
    """
    data, layout = _game_bytes(world, profile)
    ground_at = layout["ground_items"][0]
    out = []
    for index in range(GROUND_ITEMS_COUNT):
        start = ground_at + index * GROUND_ITEMS_SIZE
        record = data[start:start + GROUND_ITEMS_SIZE]
        if len(record) < GROUND_ITEMS_SIZE or record[GROUND_MAP_AT] != number:
            continue
        stamp, pair = struct.unpack_from("<2h", record, 0)
        # правило отрастания — то же, что в загрузчике
        grown = (stamp >= 0 or stamp != pair or
                 stamp * GROUND_REGROW_STEP + clock > GROUND_REGROW_AFTER)
        if not grown:
            continue
        place = struct.unpack_from("<i", record, 6)[0] >> 24
        items = []
        classes = []
        item_records = []
        details = []
        for slot in range(GROUND_SLOTS):
            item = struct.unpack_from("<H", record, GROUND_SLOTS_AT + slot * 2)[0]
            if not item:
                continue
            found = item_class_of(data, item)
            if found is not None:
                items.append(found.name)
                classes.append(found.index)
                item_records.append(item)
                details.append(item_instance(data, item))
        # ЗНАК ПОЛЯ +0x0F — ЭТО ПРИЗНАК «КУЧА СПРЯТАНА», А НЕ ДОЛГ.
        #
        # Обыск берёт сумму по модулю (VA 0x4115DE зовёт abs), поэтому на
        # деньги знак не влияет. Зато он решает, ВИДНА ли куча: пока он
        # отрицателен, куча лежит «под землёй» — её не видно и не поднять,
        # обыскать можно только с Лопатой (класс 0x20, проверка
        # FUN_00434F8C в той же ветке VA 0x4115AC). Медное зеркало колдуна
        # переворачивает знак у всех спрятанных куч текущей карты
        # (FUN_00436C48, случай класса 35) — после него они просто лежат на
        # виду.
        raw_money = struct.unpack_from("<h", record, GROUND_MONEY_AT)[0]
        money = abs(raw_money)
        buried = raw_money < 0
        # РАЗГОВОРНАЯ КУЧА: байт +0x07 меньше 0xFE — щелчок открывает диалог
        # 0x100 + байт, а не обмен. Вещей и денег у такой обычно нет вовсе,
        # поэтому отсев пустых её пропускать не должен. Байт есть только у
        # донора (см. GROUND_DIALOG_AT): канонский движок его не читает, а в
        # канонских записях лежит ноль.
        from .profile import CANON as _CANON
        talkative = (profile or _CANON).name in _GROUND_DIALOG_GAMES
        dialog = (GROUND_DIALOG_BASE + record[GROUND_DIALOG_AT]
                  if talkative and record[GROUND_DIALOG_AT] < GROUND_NO_DIALOG
                  else None)
        if not items and not money and dialog is None:
            continue
        out.append({
            "index": index,
            "row": record[5], "col": record[6],
            # НОМЕР РАЗГОВОРА — В СВОЕЙ ИГРЕ; сдвиг в проектную нумерацию
            # делает сборщик вместе с деревом.
            **({"dialog": dialog} if dialog is not None else {}),
            # 0xFF (-1) — куча лежит прямо на земле; иначе она внутри
            # объекта, и до неё добираются, обыскав его
            "on_floor": place == GROUND_ON_FLOOR,
            "place": place,
            # ГНЕЗДО ВНУТРИ ОБЪЕКТА — байт +0x0A. Пара (place, slot) и есть
            # адрес места: загрузчик карты (VA 0x43DF48) кладёт номер живого
            # контейнера в старший байт записи обстановки по адресу
            #
            #     0x6AE45C + place * 0xC0 + slot * 0x0C
            #
            # а обстановка приезжает из самой карты: блок 0x3D384 файла
            # .KN2, тридцать объектов по шестнадцать гнёзд, гнездо 12 байт
            # (спрайт, слово палитры, экранные x и y). Проверено на карте 33:
            # все пять непольных контейнеров указывают на ЗАНЯТОЕ гнездо.
            "slot": record[10],
            "sprite": struct.unpack_from("<h", record, GROUND_SPRITE_AT)[0],
            "money": money,
            # СПРЯТАНА ЛИ КУЧА. Знак поля +0x0F; см. выше.
            "buried": buried,
            "items": items,
            # Имя — только подпись. Каноническая идентичность предмета
            # хранится номером класса в байте +3 записи GAME.x.
            "classes": classes,
            # Индекс записи — каноническая идентичность ЭКЗЕМПЛЯРА. Два
            # предмета одного класса имеют одинаковый байт +3, но разные
            # записи и потому могут нести разную крепость, отраву и чары.
            "item_records": item_records,
            # ЭКЗЕМПЛЯРНЫЕ поля записей (В10): крепость/износ float +4/+8,
            # слово чар +0xE, отрава +0xC — то, что терялось при экспорте
            # именами классов
            "details": details,
        })
    return out


def item_instance(data: bytes, item_index: int) -> dict:
    """Экземплярные поля записи предмета (В10): то, чего нет в классе."""
    record = data[T_ITEMS.offset + item_index * T_ITEMS.size:][:T_ITEMS.size]
    if len(record) < 16 or record[0] == 0xFF:
        return {}
    out: dict = {}
    if record[0] == STACK_KIND:
        # У стопки +4 — ЦЕЛОЕ количество, а не float-крепость. Раньше 30
        # стрел читались как 4.2e-44 и округлялись до ложной крепости 0.
        count = struct.unpack_from("<i", record, 4)[0]
        if 0 <= count < 1_000_000:
            out["count"] = count
        # Масло меняет байт +2 самой записи стрел с 0xFF на 0
        # (VA 0x41D954, case 87); метка живёт и умирает вместе со стопкой.
        if record[OIL_MARK_AT] == 0:
            out["oiled"] = True
    else:
        strength, top = struct.unpack_from("<2f", record, 4)
        # NaN и мусор в пустых записях наружу не выпускаем
        if strength == strength and abs(strength) < 1e6:
            out["strength"] = round(strength, 4)
        if top == top and abs(top) < 1e6 and top != strength:
            out["max"] = round(top, 4)
    poison = struct.unpack_from("<H", record, 0x0C)[0]
    # 0xFFFF — «поле не используется» (частый мусор пустых полей)
    if record[0] in (0x00, 0x01, 0x0C) and poison and poison != 0xFFFF:
        out["poison"] = poison
    word = struct.unpack_from("<H", record, 0x0E)[0]
    if word and word != 0xFFFF:
        out["enchant"] = word
    return out

T_EXITS = RecordTable('exits', 0x45288, 250, 17, [
    ('facing',    2, 'u8'),    # направление прибытия, копируется в отряд +0x18
    ('from_map',  3, 'u8'),    # карта-источник; 127 — запись без привязки к карте
    ('to_map',    4, 's8'),    # карта-назначения; -1 — уход с локации, -2 — особый
    ('entry_row', 5, 'u16'),   # строка сетки, куда встанет отряд (0..255)
    ('entry_col', 7, 'u16'),   # столбец сетки (0..159)
    ('row1',      9, 'u16'),   # зона-триггер на карте-источнике: угол 1
    ('col1',     11, 'u16'),
    ('row2',     13, 'u16'),   # угол 2
    ('col2',     15, 'u16'),
])

#: Значения to_map с особым смыслом
EXIT_LEAVE = -1     # уйти с локации (движок ставит текущую карту в -1)
EXIT_SPECIAL = -2   # особый переход (море/сюжет)


def exit_name(target: int, places: list[str] | None = None,
              profile=None) -> str:
    """Куда ведёт выход, по-человечески.

    Таблица мест глобальной карты короткая — сорок четыре записи, — и в ней
    только то, что видно на глобальной. Подземелья, интерьеры и прочие
    подлокации туда не попадают вовсе, а номера у них доходят до 54. Прежний
    расчёт на этом спотыкался: всё, чего не было в таблице мест, подписывалось
    «особый переход», и вход в подземную тюрьму (карта 16, выход на карту 48)
    выглядел сюжетной дверью, хотя это обычный переход.

    Порядок такой: сперва таблица мест — её имена игра пишет на глобальной
    карте, — потом общий список карт, и только для −1 и −2 служебные подписи
    движка. Отрицательное, кроме них, — дверь под ключ на карту |куда|
    (0x420900: класс 25 «Связка ключей» проверяется и тратится).

    ЧУЖОЙ ИГРЕ НАШ СПИСОК КАРТ НЕ ПОДСТАВЛЯЕМ. `LOCATIONS` — это наши
    названия по нашим номерам, и у донора карта 37 не «Пещера у Дубков»
    наша, а его собственная. Поэтому с чужим профилем остаётся честное
    «карта N».
    """
    from .names import LOCATIONS
    from .profile import CANON
    if places is None:
        places = location_names(profile=profile)
    if 0 <= target < len(places) and places[target]:
        return places[target]
    if target > 0:
        if profile is not None and profile is not CANON:
            return f"карта {target}"
        return LOCATIONS.get(target) or f"карта {target}"
    if target == EXIT_LEAVE:
        return "глобальная карта"
    if target == EXIT_SPECIAL:
        return "особый переход"
    if profile is not None and profile is not CANON:
        return f"запертая дверь: карта {-target}"
    return f"запертая дверь: {LOCATIONS.get(-target) or ('карта %d' % -target)}"


T_UNITS = RecordTable('units', 0x46322, 2000, 256, [
    ('y',        0x12, 'u8'),     # строка сетки карты (0..255), VA 0x423B05
    ('x',        0x14, 'u8'),     # столбец сетки карты (0..159), VA 0x423B11
    # +0x17 — ПОЗА, а не вид: установщик 0x416740 сравнивает с ним свой
    # довод и переключает позу через 0x429B2C, обнуляя счётчик анимации
    # +0xFB. Знакомый фильтр «боеспособного» (не 3, не 0xB, не 0xC) — это
    # позы смерти и падения. Имя ключа оставлено прежним, чтобы не ломать
    # пак и сейвы. Поза 4 — та, в которой лежат скелеты, кикиморы и ичетики
    # до своего появления (0x410010 уводит их в проигрывание анимации).
    ('kind',     0x17, 'u8'),     # ПОЗА (см. выше), не порода
    ('flags',    0x1A, 'u8'),
    ('side',     0x1B, 'u8'),     # сторона: свои бьют чужих (VA 0x41319C)
    ('experience', 0x22, 's32'),  # накопленный опыт (VA 0x413138)
    ('next_level', 0x2A, 's32'),  # порог следующего уровня
    ('free_xp',  0x48, 'u16'),    # свободный опыт: им платят за навыки
    ('hp',       0x4E, 's16'),
    ('hand',     0x58, 'u16'),    # предмет в руке (см. konung2/items.py)
    ('ranged',   0x5A, 'u16'),
    ('body',     0x5C, 'u16'),
    ('head',     0x5E, 'u16'),
    ('shield',   0x60, 'u16'),
    ('name_id',  0xF0, 'u8'),     # индекс в таблице имён из exe
    ('nick_id',  0xF1, 'u8'),
    ('level',    0xF3, 'u8'),
    ('face',     0xEF, 'u8'),     # номер портрета: +261 даёт спрайт INTERF
    ('armour',   0xF4, 'u8'),     # своя броня, без экипировки (VA 0x41A431)
])

#: Характеристики и навыки лежат в юните тремя блоками (konung2/progress.py):
#: базовые +0xC0, «до модификаторов» +0xC6, текущие +0xCC — по шесть байт,
#: и двадцать навыков с +0xD2.
UNIT_BASE_AT, UNIT_CURRENT_AT, UNIT_SKILLS_AT = 0xC0, 0xCC, 0xD2


def unit_stats(data: bytes, index: int, units_at: int | None = None) -> dict:
    """Характеристики, навыки и снаряжение юнита из стартового мира.

    ``units_at`` — начало таблицы юнитов ЭТОЙ сборки. Без него берётся
    канонное 0x46322, и на донорских данных это читало ЧУЖОЕ место: у него
    таблица на 0x49F68, и имя с клеткой (их map_units берёт по раскладке)
    выходили верными, а тело, палитра и здоровье — мусором. Жители Дубков
    оттого приезжали с телом 0 и палитрой −1 — и не рисовались вовсе.
    """
    from .progress import CHARACTERISTICS, SKILLS
    start = (T_UNITS.offset if units_at is None else units_at) \
        + index * T_UNITS.size
    record = data[start:start + T_UNITS.size]
    return {
        "index": index,
        "level": record[0xF3],
        "face": record[0xEF],
        "health": struct.unpack_from("<h", record, 0x4E)[0],
        "experience": struct.unpack_from("<i", record, 0x22)[0],
        "free_xp": struct.unpack_from("<H", record, 0x48)[0],
        "armour": record[0xF4],
        # своя отрава твари: её движок кладёт в удар и в плевок
        # (VA 0x41A7D0 и 0x41BB10)
        "venom": record[0xF6],
        # ПОЗА, в которой юнит лежит в мире (+0x17). Не украшение: скелеты,
        # кикиморы и ичетики расставлены в позе 4, и разбор занятия
        # (0x410010) начинается с проверки «поза 4 и кадр 0 — доигрывай
        # анимацию». Установщик позы — 0x416740.
        "pose": record[0x17],
        # СЧЁТЧИК ПОРОДЫ (+0xEE). У людей в этом байте признак «бьётся
        # метательным» (0x412FF4 его пересчитывает), а у зверей стрельбы нет
        # и байт занят по-разному, СМОТРЯ КАКАЯ ПОРОДА:
        #
        #   Скелет 0x4C — число подъёмов: 0x413894:275 при смерти уменьшает
        #                 его, возвращает полное здоровье и ставит позу 4;
        #   Пауки 0x4D и 0x4F — гейт своей ветки в ходьбе (0x413894:180
        #                 открывается только при нуле).
        #
        # Поэтому имя нейтральное: у Кикиморы там тоже не ноль, и называть
        # поле «подъёмами» было бы враньём.
        "breed_counter": record[0xEE],
        # Порода (+0x1A) и ТЕЛО (+0xFC). Тело — не украшение: человека
        # движок рисует слоем 0x30 + это число, а зверя целым набором
        # кадров с тем же номером (VA 0x424200 и 0x4267B8). У Велиславны
        # там единица — оттого она и женщина.
        "breed": record[0x1A],
        "body": record[0xFC],
        # Палитра юнита: dword +0x2E, и это байтовое смещение — номер
        # получается делением на 512 (VA 0x425DB4). У одной породы палитр
        # несколько, оттого твари одного вида разной масти.
        "palette": struct.unpack_from("<i", record, 0x2E)[0] // 512,
        # точность: с ней сравнивается бросок при ударе (VA 0x41FDD0 передаёт
        # этот байт в расчёт попадания)
        "accuracy": record[0x1F],
        # СКОРОСТЬ (+0x1D), знаковая. Формулу (Ловкость+Выносливость)/50
        # движок считает ТОЛЬКО отряду игрока (0x41C944:305 пишет её под
        # `if (отряд == 0)`, ещё герою в 0x438A00:749 и найму в 0x433070);
        # все прочие юниты живут со значением записи — в стартовых мирах
        # это ноль у всех. Отрицательная скорость особая: 0x41B3B8 отдаёт
        # её как есть, юнит медленнее базы и бег ему не положен (0x416574
        # ставит бит бега только при скорости >= 0).
        "speed": struct.unpack_from("<b", record, 0x1D)[0],
        "side": record[0x1B],
        # Чем юнит бьётся — байт unit+0xEE. В самом мире он хранится
        # прежним, но движок его пересчитывает, когда юнит впервые
        # задумывается (VA 0x412FF4 из 0x410010, разово по флажку +0x19|4):
        #
        #     unit+0xEE = (боеприпас в +0x50 && метательное в +0x5A) ? 1 : 0
        #
        # Поэтому у нас тот же расчёт, а не сохранённый байт: иначе лучники
        # Чёрного Бора, у которых и лук, и стрелы, полезли бы в рукопашную.
        "ranged_mode": bool(struct.unpack_from("<H", record, 0x50)[0]
                            and struct.unpack_from("<H", record, 0x5A)[0]),
        "ranged_mode_saved": bool(record[0xEE]),
        "characteristics": {
            name: record[UNIT_BASE_AT + i]
            for i, name in enumerate(CHARACTERISTICS)
        },
        "current": {
            name: record[UNIT_CURRENT_AT + i]
            for i, name in enumerate(CHARACTERISTICS)
        },
        "skills": {
            name: record[UNIT_SKILLS_AT + i]
            for i, name in enumerate(SKILLS)
            if record[UNIT_SKILLS_AT + i]
        },
        "equipment": {
            # боеприпас — свой слот, он же решает, стрелять юниту или нет
            "ammo": struct.unpack_from("<H", record, 0x50)[0],
            "hand": struct.unpack_from("<H", record, 0x58)[0],
            "ranged": struct.unpack_from("<H", record, 0x5A)[0],
            "body": struct.unpack_from("<H", record, 0x5C)[0],
            "head": struct.unpack_from("<H", record, 0x5E)[0],
            "shield": struct.unpack_from("<H", record, 0x60)[0],
        },
        # Деньги юнита и его мешок: без них не поторгуешь. Деньги — int
        # по +0x26, мешок — сорок два слова с +0x62 (VA 0x43346C кладёт
        # их в правый ряд обмена).
        "money": struct.unpack_from("<i", record, 0x26)[0],
        # Опыт и уровень (konung2/progress.py): накопленный опыт по +0x22,
        # порог следующего уровня по +0x2A, свободный опыт по +0x48. Они
        # есть у КАЖДОГО юнита, не только у героя.
        "experience": struct.unpack_from("<i", record, 0x22)[0],
        "next_level": struct.unpack_from("<i", record, 0x2A)[0],
        "free_xp": struct.unpack_from("<h", record, 0x48)[0],
        # Замок прокачки: пока не ноль, поднять ничего нельзя.
        "progress_lock": struct.unpack_from("<h", record, 0x4A)[0],
        "bag": [struct.unpack_from("<H", record, 0x62 + step * 2)[0]
                for step in range(42)],
        # Второй набор гнёзд — украшения: ожерелье, два браслета, два
        # кольца (VA 0x41E8D8). Вместе с ними едет слово прибавок из
        # записи предмета: без него украшение — просто вещь.
        "second": {
            name: struct.unpack_from("<H", record, 0xB6 + step * 2)[0]
            for step, name in enumerate(("necklace", "bracelet_1", "bracelet_2",
                                         "ring_1", "ring_2"))
        },
        "enchant": {
            name: item_enchant(data, struct.unpack_from("<H", record, 0xB6 + step * 2)[0])
            for step, name in enumerate(("necklace", "bracelet_1", "bracelet_2",
                                         "ring_1", "ring_2"))
        },
        # Отрава живёт в ЗАПИСИ предмета, а не в классе, поэтому её надо
        # снять именно с той пачки, что у юнита в руках. На Чёрном Бору
        # такие есть: у Славуна болты с отравой 5, у Святовита стрелы с 10.
        "poison_on": {
            slot: item_poison(data, struct.unpack_from("<H", record, at)[0])
            for slot, at in (("hand", 0x58), ("ammo", 0x50))
        },
    }


def class_kinds(world: int = 0) -> dict[int, int]:
    """Вид записи для каждого класса предмета.

    Вид — байт +0 записи предмета, и в таблице классов его нет: он
    известен только по самим вещам мира. А знать его надо, потому что
    именно вид решает гнездо: 0…4 снаряжение, 6 ожерелье, 7 браслет,
    8 кольцо, 9 зелье, 0x0C боеприпас.

    Свой мир идёт первым, но прорехи закрываются вещами ОСТАЛЬНЫХ миров:
    класс носит один и тот же вид везде (проверено по всем шести GAME.x —
    ни одного расхождения), а в одном мире класса может не быть вовсе.
    Так, «Ожерелье» (класс 60) в мире 0 лежит только в добыче сценария,
    и без чужих миров оно оставалось без вида — его нельзя было надеть.
    """
    kinds: dict[int, int] = {}
    for source in (world, *(w for w in range(WORLD_COUNT) if w != world)):
        try:
            with open(game_file(f"GAME.{source}"), "rb") as stream:
                data = stream.read()
        except OSError:
            continue
        for index in range(1, T_ITEMS.count):
            record = data[T_ITEMS.offset + index * T_ITEMS.size:][:T_ITEMS.size]
            if len(record) < 4 or record[0] == 0xFF:
                continue
            kinds.setdefault(record[3], record[0])
    return kinds


def item_enchant(data: bytes, item_index: int) -> int:
    """Слово прибавок записи предмета: u16 по +0x0E (VA 0x41C494)."""
    from .enchant import ENCHANT_AT
    if not item_index:
        return 0
    record = data[T_ITEMS.offset + item_index * T_ITEMS.size:][:T_ITEMS.size]
    if len(record) < 16 or record[0] == 0xFF:
        return 0
    return struct.unpack_from("<H", record, ENCHANT_AT)[0]


def item_poison(data: bytes, item_index: int) -> int:
    """Отрава записи предмета: u16 по +0x0C (VA 0x41A7D0 и 0x41BB10)."""
    from .effects import ITEM_POISON_AT
    if not item_index:
        return 0
    record = data[T_ITEMS.offset + item_index * T_ITEMS.size:][:T_ITEMS.size]
    if len(record) < 16 or record[0] == 0xFF:
        return 0
    #: Отраву движок читает только у руки и у боеприпаса; у прочих видов в
    #: этом поле лежит 0xFFFF, то есть «не про них».
    if record[0] not in (0x00, 0x01, 0x0C):
        return 0
    return struct.unpack_from("<H", record, ITEM_POISON_AT)[0]


def item_class_of(data: bytes, item_index: int, profile=None):
    """Класс предмета по его номеру в стартовом мире: байт +3 записи.

    Каталог классов — ТОЙ игры, чей это мир: таблицы двух сборок разные
    («Береста» донора сдвигает все номера), и донорский номер по канонному
    каталогу вернёт не ошибку, а чужой предмет.
    """
    from .items import read_items
    if not item_index:
        return None
    record = data[T_ITEMS.offset + item_index * T_ITEMS.size:][:T_ITEMS.size]
    if not record:
        return None
    catalogue = read_items(profile=profile) if profile is not None else read_items()
    index = record[3]
    return catalogue[index] if index < len(catalogue) else None


def _npc_names(count: int | None = None, profile=None) -> list[str]:
    """Имена и прозвища NPC из таблицы указателей внутри exe.

    Адрес, шаг и длина берутся у профиля игры: у канона это 0x4D48C, шаг 4,
    206 записей; у «Продолжения легенды» — 0x054054 и 211. Секции PE у него
    тоже свои, поэтому и пересчёт виртуального адреса в файловый другой —
    на этом легко обжечься и получить вместо имён машинный код.
    """
    from .profile import CANON, strings
    profile = profile or CANON
    names = strings(profile, profile.need("npc_names"))
    return names[:count] if count else names


#: ИМЕНА ТВАРЕЙ — ТАБЛИЦА ПОРОД 0x45FAE0. Печать имени юнита (VA 0x43000C)
#: для твари пород 0x41…0x53 берёт строку прямо по породе:
#:
#:     if ((+0x1A & 0x40) == 0 || 0x53 < (+0x1A & 0x7F))  имя + прозвище
#:     else  FUN_00442cac(..., PTR_0045FAE0[порода & 0x7F])
#:
#: Пока твари шли общим путём «имя+прозвище», у них выходило пустое имя с
#: заглушкой «житель N» — отсюда «все монстры не имеют своих названий».
BREED_NAMES_VA, BREED_NAMES_COUNT = 0x45FAE0, 0x54


def breed_names(profile=None) -> list[str]:
    """Названия пород тварей: индекс — порода (+0x1A & 0x7F)."""
    from .profile import CANON, strings
    profile = profile or CANON
    try:
        return strings(profile, profile.need("breed_names"))
    except (KeyError, AttributeError):
        pass
    # канонный exe: прямое чтение таблицы указателей
    from .exetables import va_to_foff
    from .interf import _string_at
    with open(game_file("konung2.exe"), "rb") as stream:
        data = stream.read()
    offset = va_to_foff(BREED_NAMES_VA)
    out = []
    for breed in range(BREED_NAMES_COUNT):
        pointer = struct.unpack_from("<I", data, offset + breed * 4)[0]
        out.append(_string_at(data, pointer)
                   if 0x440000 < pointer < 0x470000 else "")
    return out


#: ПРОЗВИЩА — ОТДЕЛЬНАЯ ТАБЛИЦА УКАЗАТЕЛЕЙ. Печать имени (VA 0x43000C)
#: читает имя из PTR_0046188C[+0xF0], а прозвище — из PTR_00461B70[+0xF1]:
#: это РАЗНЫЕ базы, и вторая начинается ровно через 185 указателей после
#: первой ((0x461B70 − 0x46188C) / 4 = 185). Пока прозвище бралось из
#: общей таблицы прямым индексом, наёмники получали чужие ИМЕНА вместо
#: прозвищ: «Оттар Исток» (имя №19) вместо «Оттар Волчий клык» (прозвище
#: №19 = запись 185+19=204). Сверка по мирам: Адльстайн Рыжий, Лейф
#: Тюлень, Кетиль Ворон, Харальт Острый клык — все сходятся.
#: Нулевое прозвище — «нет прозвища» (0x43000C: `if (+0xF1 != 0)`).
NPC_NICKNAMES_FROM = 185


def _npc_nickname(names: list[str], nick_id: int) -> str:
    """Прозвище по номеру — из хвоста таблицы имён (VA 0x461B70)."""
    if not nick_id:
        return ""
    at = NPC_NICKNAMES_FROM + nick_id
    return names[at] if at < len(names) else ""


#: ЧТЕНИЕ GAME.<мир> ИДЁТ ЧЕРЕЗ ПРОФИЛЬ ИГРЫ. Раскладка у двух сборок одного
#: движка разная — у «Продолжения легенды» отрядов 255 вместо 200, поселений
#: 20 вместо 12, выходов 350 по 16 байт вместо 250 по 17, — поэтому смещения
#: не берутся константами, а считаются профилем как нарастающая сумма длин.
#: Без профиля берётся канон, и всё работает как раньше.
def _game_bytes(world: int, profile=None):
    """Байты GAME.<мир> нужной игры и раскладка её таблиц.

    СОБРАННЫЙ МИР ПРИОРИТЕТЕН: если редактор пересобрал мир из
    исходников (project/worlds/build/GAME.N — наш M_UNIT,
    konung2/worlds.py), канонное чтение берёт его, и вся сборка пака
    видит правленый мир одной точкой. Файла нет — оригинал игры, как
    всегда. На чужие профили (донор) оверлей не распространяется.
    """
    from .profile import CANON
    profile = profile or CANON
    if profile is CANON:
        built = (Path(__file__).resolve().parents[1] / "project"
                 / "worlds" / "build" / f"GAME.{world}")
        if built.is_file():
            return built.read_bytes(), profile.game_layout()
    with open(profile.file(f"GAME.{world}"), "rb") as stream:
        return stream.read(), profile.game_layout()


def location_names(count: int = 44, profile=None) -> list[str]:
    """Названия локаций: таблица 0x4616D4, индекс — номер карты.

    С профилем читается таблица ТОЙ игры: у донора это не массив указателей,
    а поле внутри 46-байтовой записи локации, и подпись «карта 64 „Овраги у
    Комариной топи“» без него не получить — по канонному адресу чужая
    сборка отдаст не ошибку, а посторонние строки.
    """
    from .exetables import va_to_foff
    if profile is not None:
        from .profile import CANON, strings
        if profile is not CANON:
            return strings(profile, profile.need("location_names"))
    with open(game_file("konung2.exe"), "rb") as stream:
        blob = stream.read()
    names = []
    table = va_to_foff(0x4616D4)
    for index in range(count):
        pointer = struct.unpack_from("<I", blob, table + index * 4)[0]
        offset = va_to_foff(pointer) if 0x440000 < pointer < 0x470000 else None
        names.append(blob[offset:blob.index(b"\0", offset)].decode("cp866", "replace")
                     if offset else "")
    return names


#: ЗОНА ПОЯВЛЕНИЯ ОТРЯДА (VA 0x415764). Движок при свежем входе на карту
#: рассыпает весь отряд по прямоугольнику из ЕГО ЖЕ записи, беря центр и
#: случайное смещение в половину зоны:
#:
#:     строка  = (строкаДо + строкаОт + 1) / 2 ± rand() % ((строкаДо − строкаОт) / 2)
#:     столбец = (столбецДо + столбецОт + 1) / 2 ± rand() % ((столбецДо − столбецОт) / 2)
#:
#: Знак каждой оси — свой бросок монеты. Попыток сто; годится клетка, у
#: которой младшие 12 бит нулевые, то есть проходимая. Не нашлось за сто —
#: отряд на этом обрывается (VA 0x43DFA9 пишет длину в +0x1C, то есть в
#: счётчик бойцов; «+0x0E» в прежней записи было short-индексом Ghidra).
#:
#: НО РАССЫПАЕТ НЕ ВСЕХ. Вызов огорожен двумя условиями (0x0043DF48):
#: обход отрядов начинается с записи 1 — отряд игрока не трогают вовсе, —
#: и у отряда должен быть СНЯТ бит 0x10 байта 0x1E (PARTY_KEEP_CELLS).
#: Стоит бит — записанные клетки в силе. Прежняя запись здесь утверждала
#: безусловно, что координаты игнорируются; на живых данных мира 0 это
#: неверно: бит стоит у 49 отрядов из 118, и все их 243 юнита несут
#: настоящие клетки, тогда как у остальных 423 из 432 записаны нули.
#:
#: Отсюда и звери с координатами (0,0) в GAME.x: их место назначает зона,
#: а не запись юнита. Без этого правила они все лежат в углу карты.
SPAWN_ROW_FROM, SPAWN_ROW_TO = 0x0C, 0x10
SPAWN_COL_FROM, SPAWN_COL_TO = 0x14, 0x16
SPAWN_TRIES = 100
#: Рассыпают НЕ ВСЕХ. Байт +0x1E записи отряда: пока он нулевой, отряда на
#: карте нет вовсе, а бит 0x10 решает судьбу координат — стоит, значит
#: юниты встают ТАМ, ГДЕ ЗАПИСАНЫ, снят — их рассыпает по зоне
#: (VA 0x43DF9C проверяет этот бит перед вызовом 0x415764).
#:
#: Отсюда и разница: у жителей Чёрного Бора бит стоит (0x92) и они на своих
#: местах, у звериных отрядов карты Волхва снят (0x40) — их разбрасывает.
PARTY_FLAGS_AT, PARTY_KEEP_CELLS = 0x1E, 0x10

#: КТО НА КОГО НАПАДАЕТ. Враждебность в движке — свойство не юнита, а его
#: ОТРЯДА, и решает её один проход по всем отрядам карты (VA 0x415B20):
#:
#:     +0x1E бит 0x01  это отряд игрока (стоит ровно у одного, №0)
#:     +0x1F бит 0x01  нападать на игрока
#:     +0x1F бит 0x04  нападать на другие отряды
#:     +0x1F бит 0x08  но только если игрок УЖЕ в бою
#:     +0x1F бит 0x80  нападать на отряд из [0x849538]
#:     +0x1F маска 0x4F — без единого её бита бой не объявляется вовсе
#:                        (VA 0x4159DC начинается с этой проверки)
#:
#: Условие нападения одно на все ветки: хоть один юнит цели стоит ВНУТРИ
#: прямоугольника отряда — того самого, по которому отряд рассыпают. То
#: есть зона появления и зона агрессии в движке ОДНА И ТА ЖЕ.
#:
#: Объявление боя (VA 0x4159DC): в +0x06 пишется сторона врага, в +0x1D —
#: единица, и всем юнитам отряда сбрасывается приказ.
#:
#: Конец боя (VA 0x415B20, хвост): если ни одной пары «мой юнит — вражеский»
#: не осталось ближе 840 пикселей по ОБЕИМ осям (VA 0x410784), +0x1D
#: обнуляется и приказы снимаются.
PARTY_WAR_AT = 0x1F
PARTY_IS_PLAYER = 0x01           # в +0x1E
#: Карта отряда — u16 +0x08. У отряда игрока это стартовая карта героя:
#: загрузка мира берёт номер текущей карты ровно отсюда (VA 0x438A00,
#: `0x8496C8 = отряд+0x08`).
PARTY_MAP_AT = 0x08
WAR_ON_PLAYER, WAR_ON_PARTIES = 0x01, 0x04
WAR_ONLY_IF_FIGHTING, WAR_ON_SPECIAL = 0x08, 0x80
WAR_ANY = 0x4F                   # маска VA 0x4159DC
PARTY_ENEMY_AT, PARTY_FIGHTING_AT = 0x06, 0x1D
#: Насколько далеко должны разойтись, чтобы бой кончился (VA 0x410784):
#: 840 пикселей по каждой оси в отдельности, не по прямой.
WAR_KEEP_RANGE = 0x348
#: Второй прямоугольник записи — границы карты; по нему гуляют в бою
#: породы 0x54 и 0x55 (VA 0x4111E8). Ряды и столбцы обоих чередуются:
#: ряды u16 по +0x0C/+0x0E/+0x10/+0x12, столбцы u8 по +0x14…+0x17.
ROAM_ROW_FROM, ROAM_ROW_TO = 0x0E, 0x12
ROAM_COL_FROM, ROAM_COL_TO = 0x15, 0x17


def party_combat(party_record: bytes) -> dict:
    """Боевые поля отряда: кто он и на кого бросается."""
    flags = party_record[PARTY_FLAGS_AT]
    war = party_record[PARTY_WAR_AT]
    return {
        "player": bool(flags & PARTY_IS_PLAYER),
        "war_flags": war,
        "on_player": bool(war & WAR_ON_PLAYER),
        "on_parties": bool(war & WAR_ON_PARTIES),
        "only_if_fighting": bool(war & WAR_ONLY_IF_FIGHTING),
        "on_special": bool(war & WAR_ON_SPECIAL),
        "can_fight": bool(war & WAR_ANY),
        "enemy_side": struct.unpack_from("<H", party_record, PARTY_ENEMY_AT)[0],
        "fighting": bool(party_record[PARTY_FIGHTING_AT]),
        "roam": {
            "row_from": struct.unpack_from("<H", party_record, ROAM_ROW_FROM)[0],
            "row_to": struct.unpack_from("<H", party_record, ROAM_ROW_TO)[0],
            "col_from": party_record[ROAM_COL_FROM],
            "col_to": party_record[ROAM_COL_TO],
        },
    }


def spawn_zone(party_record: bytes) -> dict:
    """Прямоугольник появления отряда из его записи."""
    flags = party_record[PARTY_FLAGS_AT]
    return {
        "row_from": struct.unpack_from("<H", party_record, SPAWN_ROW_FROM)[0],
        "row_to": struct.unpack_from("<H", party_record, SPAWN_ROW_TO)[0],
        "col_from": party_record[SPAWN_COL_FROM],
        "col_to": party_record[SPAWN_COL_TO],
        "tries": SPAWN_TRIES,
        # записанные координаты в силе, только когда бит стоит
        "keep_cells": bool(flags & PARTY_KEEP_CELLS),
        "flags": flags,
    }


#: РАБОЧИЕ МЕСТА — то, чем жители деревни заняты вместо стояния столбом
#: (VA 0x412C0C). У отряда есть таблица мест, у каждого юнита — список до
#: восьми номеров этих мест (``unit+0xE6``…``+0xED``, конец — отрицательное
#: значение). Место в таблице отряда лежит по ``+0x20 + номер*4``:
#:
#:     +0  вид работы и признаки; бит 0x10 — работа ночная
#:     +1  строка клетки
#:     +2  столбец
#:     +3  младшая половина — на сколько там задержаться,
#:         старшая — вес при выборе
#:
#: Как это работает: из списка юнита отбираются места, подходящие времени
#: суток, из них случайно выбирается одно с весом старшей половины, юнит
#: идёт туда и остаётся на срок из младшей. Придя, он встаёт не просто так,
#: а в рабочую позу — виды 0x70…0xA0 дают долгую работу (срок rand()%180+60),
#: прочие короткую (rand()%(срок*2)+15).
#:
#: ПЕРВОЕ место жителя — это его дом: у Мстислава место 0 (79, 26) и в
#: записи юнита стоят те же координаты.
WORKPLACES_AT, WORKPLACES_MAX = 0xE6, 8
WORKPLACE_TABLE_AT, WORKPLACE_STRIDE = 0x20, 4
WORKPLACE_NIGHT_BIT = 0x10
#: Виды долгой работы: у них свой срок и своя поза.
WORKPLACE_LONG_KINDS = (0x70, 0x80, 0x90, 0xA0)


def workplaces(party_record: bytes, count: int | None = None) -> list[dict]:
    """Таблица рабочих мест отряда — до конца записи, а не первые тридцать два.

    ТРИДЦАТЬ ДВА БЫЛО ДОГАДКОЙ. Юниты ссылаются на слоты 32…38 у канона и до
    55 у донора, а обрезанная таблица их не содержала: житель искал своё
    место, не находил и оставался стоять. Сплошная проверка пака поймала это
    на тринадцати картах — Беглое, Поднебесье, Нижний лагерь и другие.

    Что таблица и правда идёт до конца записи, показал перебор: за 32-м
    слотом у канона 942 непустые записи, у донора 3093, и НИ ОДНОЙ с
    негодной клеткой (строка вне 1…255 или столбец вне 1…159). Будь там
    другие поля, мусор бы попался.
    """
    if count is None:
        count = max(0, (len(party_record) - WORKPLACE_TABLE_AT)
                    // WORKPLACE_STRIDE)
    out = []
    for slot in range(count):
        at = WORKPLACE_TABLE_AT + slot * WORKPLACE_STRIDE
        if at + WORKPLACE_STRIDE > len(party_record):
            break
        kind, row, col, weight = party_record[at:at + WORKPLACE_STRIDE]
        if not kind and not row and not col:
            continue
        out.append({
            "slot": slot, "kind": kind,
            "row": row, "col": col,
            # старшая половина — вес выбора, младшая — насколько задержаться
            "weight": weight >> 4, "stay": weight & 0x0F,
            "night": bool(kind & WORKPLACE_NIGHT_BIT),
            "long": (kind & 0xF0) in WORKPLACE_LONG_KINDS,
        })
    return out


def unit_workplaces(unit_record: bytes) -> list[int]:
    """Номера рабочих мест юнита: до восьми, конец — отрицательное."""
    out = []
    for step in range(WORKPLACES_MAX):
        value = unit_record[WORKPLACES_AT + step]
        if value >= 0x80:                 # знаковый байт: отрицательное — конец
            break
        out.append(value)
    return out


def map_parties(number: int, world: int = 0, profile=None) -> list[dict]:
    """Отряды, стоящие на карте, вместе с их боевыми полями.

    Отряд — единица враждебности: нападает не юнит, а отряд, и решает это
    один проход по всем отрядам карты (VA 0x415B20). Сторона юнита (+0x1B)
    равна НОМЕРУ его отряда, поэтому по стороне отряд и находится:
    ``0x71E56C + сторона * 0x100``.
    """
    data, layout = _game_bytes(world, profile)
    at, count, size = layout["parties"]
    out: list[dict] = []
    for party in range(count):
        record = data[at + party * size:][:size]
        if struct.unpack_from("<H", record, 0x08)[0] != number:
            continue
        if record[0x1C] == 0:
            continue
        entry = {
            "side": party,
            "first_unit": struct.unpack_from("<H", record, 0x00)[0],
            "count": record[0x1C],
            "zone": spawn_zone(record),
        }
        entry.update(party_combat(record))
        out.append(entry)
    return out


def player_party(world: int = 0, profile=None) -> dict | None:
    """Отряд игрока — запись №0 массива отрядов, в том же виде, что у
    ``map_parties``.

    Движок держит весь массив ``0x71E56C`` глобально: запись №0 существует
    на любой карте, и именно в неё замах врага по нашему юниту пишет войну
    (0x413894 кадр 2 -> 0x4159DC; гейт ``+0x1F & 0x4F`` проходит, потому
    что в GAME.x у отряда №0 стоит бит 0x40). Фильтр ``map_parties`` по
    номеру карты эту запись терял везде, кроме стартовой карты мира, — и
    автоответ отряда был мёртв.
    """
    data, layout = _game_bytes(world, profile)
    at, count, size = layout["parties"]
    if count < 1:
        return None
    record = data[at:at + size]
    entry = {
        "side": 0,
        "first_unit": struct.unpack_from("<H", record, 0x00)[0],
        "count": record[0x1C],
        "zone": spawn_zone(record),
    }
    entry.update(party_combat(record))
    return entry


def map_units(number: int, world: int = 0, profile=None) -> list[dict]:
    """Жители карты из стартового мира GAME.<world>.

    Юниты живут не в карте, а в отрядах: запись отряда называет номер карты
    (+0x08), первого юнита (+0x00) и сколько их (+0x1C) — сборщик сцены
    (VA 0x428240) перебирает отряды и берёт те, у которых карта совпала с
    текущей. Клетка юнита — байты +0x14 (столбец) и +0x12 (строка), сторона
    +0x1B, лицо +0xEF, имя и прозвище — номера в таблице имён из exe.
    """
    data, layout = _game_bytes(world, profile)
    names = _npc_names(profile=profile)
    breeds = breed_names(profile=profile)
    parties_at, parties_n, parties_size = layout["parties"]
    units_at, units_n, units_size = layout["units"]
    units: list[dict] = []
    for party in range(parties_n):
        record = data[parties_at + party * parties_size:][:parties_size]
        if struct.unpack_from("<H", record, 0x08)[0] != number:
            continue
        first = struct.unpack_from("<H", record, 0x00)[0]
        count = record[0x1C]
        for step in range(count):
            index = first + step
            if index >= units_n:
                continue
            unit = data[units_at + index * units_size:][:units_size]
            stats = unit_stats(data, index, units_at)
            # ТВАРЬ ЗОВЁТСЯ ПОРОДОЙ (VA 0x43000C): породы 0x41…0x53 берут
            # строку из таблицы 0x45FAE0, люди и породы старше — имя и
            # прозвище из своих таблиц.
            breed = unit[0x1A] & 0x7F
            if (unit[0x1A] & 0x40) and breed < BREED_NAMES_COUNT:
                full = breeds[breed] if breed < len(breeds) else ""
            else:
                name = names[unit[0xF0]] if unit[0xF0] < len(names) else ""
                # прозвище — из СВОЕЙ таблицы (0x461B70), см. _npc_nickname
                nick = _npc_nickname(names, unit[0xF1])
                full = f"{name} {nick}".strip()
            units.append({
                "index": index, "party": party,
                "name": (full or f"житель {index}"),
                # НОМЕРА ИМЕНИ И ПРОЗВИЩА, а не только собранная строка:
                # сами строки живут в exe, и по имени запись не
                # восстановить. Без этих чисел добавленный редактором
                # житель обречён быть тёзкой того, с кого снят
                # (см. worlds._write_unit).
                "name_id": unit[0xF0], "nick_id": unit[0xF1],
                "col": unit[0x14], "row": unit[0x12],
                # ЗОНА ПОЯВЛЕНИЯ отряда: по ней движок расставляет юнитов
                # при входе на карту — но ТОЛЬКО когда у отряда снят бит
                # keep_cells; стоит бит — координаты записи в силе. У
                # зверей в зоне-без-бита там нули (см. spawn_zone).
                "spawn_zone": spawn_zone(record),
                # Рабочие места: по ним житель и ходит по деревне.
                "workplaces": unit_workplaces(unit),
                # +0x17 звался здесь `kind`, но это ПОЗА (установщик 0x416740
                # сравнивает с ним свой довод). Имя выправлено; читателей у
                # старого не было — проверено поиском.
                "side": unit[0x1B], "pose": unit[0x17], "flags": unit[0x1A],
                # ПОВОРОТ (+0x18). Без него все жители смотрели в одну
                # сторону: клиент подставлял своё умолчание, и на входе в
                # локацию деревня стояла лицом вниз, пока ИИ не разводил её
                # по делам.
                #
                # Что это именно поворот, показали три схождения. Перебор
                # байтов +0x10…+0x2F у 865 жителей карт: условию «значения
                # только 0…7 и хотя бы три разных» отвечает ОДИН байт, этот.
                # В движке в него пишут переход между картами (0x420900:56 —
                # байтом +2 записи выхода, а это и есть её поле `facing`),
                # таблица входов с шагом шесть (0x422CCC, 0x435AA0, 0x4360A8)
                # и действия разговора (0x436C48 ставит 1 и 2). Нумерация та
                # же, что у нас: клиент уже применяет `facing` перехода прямо
                # как `direction`, без пересчёта.
                "direction": unit[0x18],
                # номер диалога юнита: с него начинается разговор (VA 0x4369A0)
                "dialog": unit[0xF2],
                "face": stats["face"], "level": stats["level"],
                "accuracy": stats["accuracy"],
                # скорость записи (+0x1D): у NPC движок её не пересчитывает
                "speed": stats["speed"],
                # отрава: своя у твари и та, что на самих вещах
                "venom": stats["venom"], "poison_on": stats["poison_on"],
                # порода и тело: по ним юнит и выглядит собой
                "breed": stats["breed"], "body": stats["body"],
                # счётчик породы (+0xEE): на нём держатся подъёмы скелета
                "breed_counter": stats["breed_counter"],
                "palette": stats["palette"],
                # стреляет ли: есть метательное и есть чем (VA 0x412FF4)
                "ranged_mode": stats["ranged_mode"],
                # чем торговать: деньги и мешок, названиями классов
                "money": stats["money"],
                "bag": [item_class_of(data, item).name
                        for item in stats["bag"]
                        if item and item_class_of(data, item)],
                "bag_classes": [item_class_of(data, item).index
                                for item in stats["bag"]
                                if item and item_class_of(data, item)],
                "bag_item_records": [item for item in stats["bag"]
                                     if item and item_class_of(data, item)],
                # экземплярные поля вещей мешка (В10), параллельно bag
                "bag_details": [item_instance(data, item)
                                for item in stats["bag"]
                                if item and item_class_of(data, item)],
                "health": stats["health"], "armour": stats["armour"],
                "characteristics": stats["characteristics"],
                "current": stats["current"], "skills": stats["skills"],
                "equipment": {
                    slot: (item_class_of(data, item).name
                           if item_class_of(data, item) else None)
                    for slot, item in stats["equipment"].items()
                },
                "equipment_classes": {
                    slot: (item_class_of(data, item).index
                           if item_class_of(data, item) else None)
                    for slot, item in stats["equipment"].items()
                },
                "equipment_item_records": {
                    slot: (item if item and item_class_of(data, item) else None)
                    for slot, item in stats["equipment"].items()
                },
                # то же для надетого: слово чар, крепость, отрава (В10)
                "equipment_details": {
                    slot: item_instance(data, item)
                    for slot, item in stats["equipment"].items()
                    if item and item_class_of(data, item)
                },
                "second": {
                    slot: (item_class_of(data, item).name
                           if item_class_of(data, item) else None)
                    for slot, item in stats["second"].items()
                },
                "second_classes": {
                    slot: (item_class_of(data, item).index
                           if item_class_of(data, item) else None)
                    for slot, item in stats["second"].items()
                },
                "second_item_records": {
                    slot: (item if item and item_class_of(data, item) else None)
                    for slot, item in stats["second"].items()
                },
                "second_details": {
                    slot: item_instance(data, item)
                    for slot, item in stats["second"].items()
                    if item and item_class_of(data, item)
                },
            })
    return units


#: ЗАПИСЬ ВЫХОДА ЧИТАЕТСЯ СО СДВИГОМ ПРОФИЛЯ. Поля одни и те же, но у
#: «Продолжения легенды» запись на байт короче нашей, и всё, кроме первого
#: заполнителя, лежит на байт раньше. Держим разбор одной функцией, чтобы
#: смещения не расходились между «всем графом» и «выходами карты».
def _exit_record(record: bytes, shift: int) -> dict:
    """Поля записи выхода. ``shift`` — насколько они ближе к началу."""
    return {
        "facing": record[2 - shift],
        "from_map": record[3 - shift],
        "to_map": struct.unpack_from("<b", record, 4 - shift)[0],
        "entry_row": struct.unpack_from("<H", record, 5 - shift)[0],
        "entry_col": struct.unpack_from("<H", record, 7 - shift)[0],
        "row1": struct.unpack_from("<H", record, 9 - shift)[0],
        "col1": struct.unpack_from("<H", record, 11 - shift)[0],
        "row2": struct.unpack_from("<H", record, 13 - shift)[0],
        "col2": struct.unpack_from("<H", record, 15 - shift)[0],
    }


def all_exits(world: int = 0, profile=None) -> list[dict]:
    """ВЕСЬ граф переходов: 250 записей, номер = место в таблице.

    `map_exits` отдаёт только переходы одной карты, а действие разговора 69
    «перенести отряд игрока по переходу» адресует запись НОМЕРОМ в этой самой
    таблице: движок берёт `0x7B2B6C + аргумент * 17` (VA 0x435AA0, снято
    дизассемблером — функции нет в декомпиляте) и читает оттуда карту
    назначения по +0x04, поворот по +0x02 и клетку входа по +0x05/+0x07.
    Номер может указывать на переход ЧУЖОЙ карты, поэтому нужен весь граф.

    Пустые записи (карта-источник 0 и назначение 0) остаются в списке: их
    места заняты, и номера сдвигать нельзя.
    """
    from .profile import CANON
    profile = profile or CANON
    data, layout = _game_bytes(world, profile)
    at, count, size = layout["exits"]
    shift = profile.game_exit_shift
    places = location_names(profile=profile)
    out = []
    for index in range(count):
        fields = _exit_record(data[at + index * size:][:size], shift)
        target = fields["to_map"]
        out.append({
            "index": index,
            "from_map": fields["from_map"],
            "to_map": target,
            "to_name": (places[target] if 0 <= target < len(places) else
                        ("глобальная карта" if target == EXIT_LEAVE
                         else "особый переход")),
            "facing": fields["facing"],
            "entry_row": fields["entry_row"],
            "entry_col": fields["entry_col"],
        })
    return out


def map_exits(number: int, world: int = 0, profile=None) -> list[dict]:
    """Выходы с карты: зона на ней, куда ведёт и куда ставит отряд.

    Запись выхода (T_EXITS) называет карту-источник (+0x03), назначение
    (+0x04: −1 уйти на глобальную карту, −2 особый переход), клетку прибытия
    и прямоугольник-триггер в клетках исходной карты.

    ``number`` — номер карты В ТОЙ ЖЕ ИГРЕ, что и профиль: у донора это его
    собственный номер, а не проектный. Перевод номеров — дело сборщика.
    """
    from .profile import CANON
    profile = profile or CANON
    data, layout = _game_bytes(world, profile)
    at, count, size = layout["exits"]
    shift = profile.game_exit_shift
    places = location_names(profile=profile)
    exits = []
    for index in range(count):
        fields = _exit_record(data[at + index * size:][:size], shift)
        if fields["from_map"] != number:
            continue
        target = fields["to_map"]
        rows = sorted((fields["row1"], fields["row2"]))
        cols = sorted((fields["col1"], fields["col2"]))
        exits.append({
            "index": index, "to_map": target,
            "to_name": exit_name(target, places, profile=profile),
            "facing": fields["facing"],
            "entry_row": fields["entry_row"],
            "entry_col": fields["entry_col"],
            "row1": rows[0], "row2": rows[1],
            "col1": cols[0], "col2": cols[1],
        })
    return exits


#: События (рейды): 10 записей по 16 байт. Разобраны по обработчику
#: разговора 23 (VA 0x435214) — он спрашивает «жив ли на карте отряд
#: события» и читает запись так:
#:
#:     +0x04  u8   номер отряда СЕЙЧАС идущего рейда (ноль — рейда нет)
#:     +0x09  u8   карта, на которой рейд сейчас
#:
#: В стартовых мирах оба поля нулевые: рейд ещё не запущен. Заполнены
#: другие — похоже, это заготовка: +0x00 вид (12 или 13), +0x01 отряд
#: (во всех семи записях GAME.0 это отряд 39: трое пятнадцатого уровня со
#: своей стороной), +0x06 время и +0x08 карта, куда рейд придёт.
#:
#: Отсюда важное следствие: в начале игры активных событий нет, и условие
#: «деревня занята стражниками Повелителя» у жителей Черного Бора НЕ
#: выполняется — эту ветку разговора движок пропускает.
T_EVENTS_AT, T_EVENTS_COUNT, T_EVENTS_SIZE = 0xC6AAE, 10, 16


def map_events(number: int, world: int = 0, profile=None) -> list[dict]:
    """Слоты заводчика бродячих отрядов, привязанные к этой карте.

    Это НЕ «сюжетные события»: десять записей `0x7B2ACC` — заводчик, и раз в
    шестнадцать тактов каждый свободный слот бросает жребий. Разбор целиком —
    в docs/LOCATION_SPEC.md, разрез 2. Раскладка записи снята дизассемблером:

        +0 dword  вес жребия: слот заводится, когда `rand() % 10000` БОЛЬШЕ
                  веса (0x41CE39). В GAME.0 веса 9997 и 9996, то есть
                  3-4 случая из 10000 за фазу — событие редкое.
        +4 байт   ЗАВЕДЁННЫЙ отряд, ноль — слот свободен (0x435214)
        +5, +7    копии +6 и +8, кладутся при заводе
        +6 байт   образец: что заводить
        +8 байт   образец: на какой карте
        +9 байт   карта заведённого, 0xFF — ещё нигде

    ПРЕЖНИЙ РАЗБОР БРАЛ ЗА НОМЕР ОТРЯДА БАЙТ +1 — а это второй байт веса:
    9997 это `0D 27 00 00`, и «отряд 39» (0x27) выходил у всех событий
    одинаковым. Бойцы, напечённые по этому номеру, к событию отношения не
    имели вовсе. Тем же промахом `kind` был младшим байтом веса.

    В отгруженных мирах заведённых событий НЕТ: `+4` всюду ноль, слоты ждут
    жребия. Поэтому у всех записей пака `active` ложно, а `units` пуст — и
    это правда о состоянии мира, а не потеря данных.

    ``number`` — номер карты В ТОЙ ЖЕ игре, что и профиль, как у `village`.
    """
    data, layout = _game_bytes(world, profile)
    at, count, size = layout["events"]
    parties_at, _, party_size = layout["parties"]
    units_at, _, unit_size = layout["units"]
    events = []
    for index in range(count):
        record = data[at + index * size:][:size]
        # Ноль в весе — слот не заведён вовсе: на нём движок обрывает обход
        # (`*local_48 != 0` в условии цикла 0x41C944).
        weight = struct.unpack_from("<I", record, 0)[0]
        if not weight:
            break
        party = record[4]
        target = record[9] if party else record[8]
        if target != number:
            continue
        units = []
        if party:
            party_record = data[parties_at + party * party_size:][:party_size]
            first = struct.unpack_from("<H", party_record, 0x00)[0]
            for step in range(party_record[0x1C]):
                unit = data[units_at + (first + step) * unit_size:][:unit_size]
                units.append({
                    "index": first + step, "col": unit[0x14], "row": unit[0x12],
                    "side": unit[0x1B], "level": unit[0xF3],
                    "health": struct.unpack_from("<h", unit, 0x4E)[0],
                    # Ими и решается «жив ли отряд события» (0x435214):
                    # бит 0x80 в +0x1A — труп, поза +0x17 из 3/0xB/0xC — тоже.
                    "flags": unit[0x1A], "pose": unit[0x17]})
        events.append({"index": index, "party": party, "map": target,
                       "active": bool(party), "weight": weight,
                       # образец: что заводить и куда — их копирует завод
                       "pattern": record[6], "home": record[8], "units": units})
    return events


#: Постройки: таблица 0x45D850 в exe, по 16 байт на вид — указатель на
#: название, пара слов и два одинаковых числа (похоже на цену в ресурсах).
BUILDING_TABLE_VA = 0x45D840
BUILDING_STRIDE = 16
BUILDING_COUNT = 64


def building_kinds() -> list[dict]:
    """Виды построек: название, спрайт и сроки.

    Запись шестнадцать байт, таблица с 0x45D840 — это видно по самому
    движку, который читает из неё поля со смещениями 4, 8 и 0x0C:

        +0x00  указатель на название
        +0x04  слово, старшая половина — НОМЕР СПРАЙТА для состояния 0
               (VA 0x4171CC: спрайт = этот номер + состояние)
        +0x08  срок постройки (VA 0x41C944: * 60 / число работников)
        +0x0C  срок одной ступени горения

    Раньше я читал её с 0x45D850 и все названия ехали на запись вперёд.
    Проверяется это на семи особых местах поселения: при верном чтении у
    каждого места одно назначение — дом старосты, изба знахаря, лавка,
    кузница, казарма, причал, колодец, — а при сдвинутом в одном месте
    оказываются и казарма, и кузница.
    """
    from .exetables import va_to_foff
    with open(game_file("konung2.exe"), "rb") as stream:
        blob = stream.read()
    table = va_to_foff(BUILDING_TABLE_VA)
    kinds = []
    for index in range(BUILDING_COUNT):
        pointer, packed, build, burn = struct.unpack_from(
            "<4I", blob, table + index * BUILDING_STRIDE)
        offset = va_to_foff(pointer) if 0x440000 < pointer < 0x470000 else None
        if offset is None:
            break
        kinds.append({
            "kind": index,
            "name": blob[offset:blob.index(NUL, offset)].decode("cp866", "replace"),
            # каждому виду принадлежат семь подряд идущих картинок — по
            # одной на состояние, от стройки до пепелища
            "sprite": packed >> 16,
            # Младшая половина того же слова — ТРЕБУЕМЫЕ «Строительные
            # навыки» (навык 18). Условие разговора 6 «можно заложить
            # постройку» сверяет её с ЛУЧШИМ навыком 18 в отряде деревни:
            #   uVar1 = *(ushort *)(&DAT_0045d844 + вид * 0x10);
            #   iVar2 = FUN_00432c9c(отряд деревни);
            #   if (iVar2 < uVar1) нельзя;                 (VA 0x434BC4)
            # а сама 0x432C9C проходит по юнитам отряда и берёт максимум
            # байта +0xE4 — это и есть навык 18 (0xE4 − 0xD2 = 18).
            # Числа подтверждают чтение: у изб и казарм единица, у кузницы
            # тройка — ценами в монетах такие быть не могут.
            "build_skill": packed & 0xFFFF,
            "flags": packed & 0xFFFF,
            "build_time": build, "burn_step": burn,
        })
    return kinds


#: Пять должностей деревни лежат по u16 с +0x3D0, а прилавки торговцев —
#: тремя списками, по одному на должность (VA 0x43346C):
#:
#:     должность 2  +0x3E0  22 места
#:     должность 3  +0x40E  32 места
#:     должность 4  +0x44E  39 мест
VILLAGE_ROLES = 5
VILLAGE_GOODS = {2: (0x3E0, 0x16), 3: (0x40E, 0x20), 4: (0x44E, 0x27)}
#: Деньги отряда — int по +0x26 записи отряда; монета в мешке считается по
#: 50 (VA 0x43346C: предмет вида 0x0B класса 0x24).
PARTY_MONEY_AT, COIN_VALUE, COIN_CLASS, COIN_KIND = 0x26, 50, 0x24, 0x0B


#: Отряд: вместимость и сколько сейчас. Обработчики разговора 36 и 43
#: (VA 0x433070 и 0x4338B0) кладут юнита в конец отряда — по адресу
#: ``(первый + сейчас) * 256`` — и увеличивают счётчик, а 43 сперва
#: проверяет, что «сейчас» не равно вместимости.
PARTY_CAPACITY_AT, PARTY_COUNT_AT = 0x1A, 0x1C


def party(index: int = 0, world: int = 0, profile=None) -> dict:
    """Отряд из стартового мира: место, вместимость и его юниты.

    С профилем читается мир ТОЙ игры: раскладка таблиц и каталог классов
    у донора свои. Классы предметов здесь остаются в НАТИВНОЙ нумерации
    той же игры — перевод в наши номера делает сборщик пака.
    """
    data, layout = _game_bytes(world, profile)
    parties_at, _, parties_size = layout["parties"]
    units_at = layout["units"][0]
    names = _npc_names(profile=profile)

    def class_of(item):
        return item_class_of(data, item, profile)

    record = data[parties_at + index * parties_size:][:parties_size]
    first = struct.unpack_from("<H", record, 0x00)[0]
    count = record[PARTY_COUNT_AT]
    # Родная карта бойцов — карта самого отряда (+0x08). В движке слот юнита
    # глобален, а в паке слоты разных карт пересекаются, поэтому клиент
    # различает записи парой «родная карта : слот»; без неё запись отряда
    # прятала чужого юнита с тем же слотом — «Ярл превращался в Белуна».
    home_map = struct.unpack_from("<H", record, PARTY_MAP_AT)[0]
    members = []
    for step in range(count):
        number = first + step
        unit = data[units_at + number * T_UNITS.size:][:T_UNITS.size]
        stats = unit_stats(data, number, units_at=units_at)
        name = names[unit[0xF0]] if unit[0xF0] < len(names) else ""
        # прозвище — из СВОЕЙ таблицы (0x461B70), см. _npc_nickname
        nick = _npc_nickname(names, unit[0xF1])
        members.append({
            "index": number, "home": home_map,
            "name": (f"{name} {nick}".strip() or f"юнит {number}"),
            "face": stats["face"], "level": stats["level"],
            # тело (+0xFC) — это и АКТЁР голоса: восьмёрка откликов на выбор
            # 32+тело*8 (VA 0x42D308) и приветствия 5500+тело*5 (0x438A00)
            "body": stats["body"],
            # ПАЛИТРА И ПОРОДА СПУТНИКА — такие же поля записи, как у жителя
            # (+0x2E и +0x1A). Их здесь не было, поэтому спутник приезжал в
            # пак с `palette: None`, а клиент подставлял ноль: покрасить его
            # было нечем, хотя движок красит каждого юнита его палитрой
            # (VA 0x425DB4).
            "palette": stats["palette"], "breed": stats["breed"],
            "health": stats["health"], "armour": stats["armour"],
            "accuracy": stats["accuracy"], "side": stats["side"],
            "characteristics": stats["characteristics"],
            "current": stats["current"], "skills": stats["skills"],
            "equipment": {
                slot: (class_of(item).name
                       if class_of(item) else None)
                for slot, item in stats["equipment"].items()
            },
            "equipment_classes": {
                slot: (class_of(item).index
                       if class_of(item) else None)
                for slot, item in stats["equipment"].items()
            },
            "equipment_item_records": {
                slot: (item if item and class_of(item) else None)
                for slot, item in stats["equipment"].items()
            },
            "dialog": unit[0xF2],
            # приказ юнита: 0x10 ждать, 0x30 идти за вожаком (VA 0x420BFC)
            "order": unit[0x16],
            # Свой мешок, свои деньги и свой опыт: панель персонажа
            # работает с ТЕМ юнитом, который выбран (VA 0x4292DC), поэтому
            # у спутника всё это должно быть своим.
            "money": stats["money"],
            "experience": stats["experience"],
            "next_level": stats["next_level"],
            "free_xp": stats["free_xp"],
            "progress_lock": stats["progress_lock"],
            "bag": [class_of(item).name
                    if class_of(item) else None
                    for item in stats["bag"]],
            "bag_classes": [
                (class_of(item).index
                 if item and class_of(item) else None)
                for item in stats["bag"]
            ],
            "bag_item_records": [
                (item if item and class_of(item) else None)
                for item in stats["bag"]
            ],
            # экземплярные поля мешка и надетого (В10): крепость, чары
            "bag_details": [item_instance(data, item)
                            if item and class_of(item) else {}
                            for item in stats["bag"]],
            "equipment_details": {
                slot: item_instance(data, item)
                for slot, item in stats["equipment"].items()
                if item and class_of(item)
            },
            "second": {
                slot: (class_of(item).name
                       if class_of(item) else None)
                for slot, item in stats["second"].items()
            },
            "second_classes": {
                slot: (class_of(item).index
                       if class_of(item) else None)
                for slot, item in stats["second"].items()
            },
            "second_item_records": {
                slot: (item if item and class_of(item) else None)
                for slot, item in stats["second"].items()
            },
            "second_details": {
                slot: item_instance(data, item)
                for slot, item in stats["second"].items()
                if item and class_of(item)
            },
            "poison_on": stats["poison_on"],
        })
    return {
        "index": index, "first": first, "count": count,
        "capacity": record[PARTY_CAPACITY_AT],
        "map": struct.unpack_from("<H", record, 0x08)[0],
        "money": struct.unpack_from("<i", record, PARTY_MONEY_AT)[0],
        "members": members,
    }


def party_money(party: int = 0, world: int = 0) -> int:
    """Деньги отряда из стартового мира."""
    with open(game_file(f"GAME.{world}"), "rb") as stream:
        data = stream.read()
    record = data[T_PARTIES.offset + party * T_PARTIES.size:][:T_PARTIES.size]
    return struct.unpack_from("<i", record, PARTY_MONEY_AT)[0]


def unit_role(unit_index: int, map_number: int, world: int = 0) -> int:
    """Должность юнита в поселении: место в списке плюс один (VA 0x415190).

    Ноль — обычный житель. Должности 2, 3 и 4 держат прилавки, и торговля
    с ними идёт по деревенским ценам.
    """
    settlement = village(map_number, world)
    if not settlement:
        return 0
    for step, official in enumerate(settlement["officials"]):
        if official and official == unit_index:
            return step + 1
    return 0


def _village_culture(map_number: int) -> int:
    """Культура старейшины деревни: славяне 0, викинги 1, византийцы 2.

    В рантайме движок держит её байтом +0x1B вожака (0x417BD8 берёт оттуда
    для классов снаряжения «культура·34 + 100», 0x437F48 — для музыки), но
    в файле GAME.x этот байт ещё занят стороной. Раскладка по картам снята
    при разборе музыки поселений (konung2/sounds.py VILLAGE_CULTURES).
    """
    from .sounds import VILLAGE_CULTURES
    return VILLAGE_CULTURES.get(map_number, 0)


def village(number: int, world: int = 0, profile=None) -> dict | None:
    """Поселение карты: постройки, люди и казна.

    Запись 0x4A1 байт, ищется по байту +0x03 — номеру карты (VA 0x43E6E4).
    Список построек идёт с +0x18 по 8 байт: вид, состояние, номер объекта
    карты. Первые семь мест — «особые»: именно их номерами спрашивает
    обработчик разговора 4 (VA 0x434AF0), а дальше идут обычные дома,
    сколько их — говорят байты +0x00 и +0x01 (n1 + n2 + 7).

    ``number`` — номер карты В ТОЙ ЖЕ ИГРЕ, что и профиль. У донора записей
    двадцать вместо наших двенадцати, и лежат они по своему смещению.
    """
    data, layout = _game_bytes(world, profile)
    at, count, size = layout["villages"]
    kinds = {kind["kind"]: kind["name"] for kind in building_kinds()}
    for index in range(count):
        record = data[at + index * size:][:size]
        if record[3] != number:
            continue
        total = record[0] + record[1] + 7
        buildings = []
        for slot in range(total):
            entry = record[0x18 + slot * 8: 0x18 + (slot + 1) * 8]
            if len(entry) < 8:
                break
            buildings.append({
                "slot": slot, "kind": entry[0],
                "name": kinds.get(entry[0], f"постройка {entry[0]}"),
                # «есть» проверяется так же, как в обработчике 4: либо
                # состояние, либо непустое слово +6
                "state": entry[1], "object": entry[2],
                "built": bool(entry[1] or struct.unpack_from("<H", entry, 6)[0]),
                "special": slot < 7,
            })
        # Должности: пять мест по u16 с +0x3D0. Должность юнита — номер его
        # места плюс один (VA 0x415190), и по ней же выбирается прилавок.
        officials = [struct.unpack_from("<H", record, 0x3D0 + step * 2)[0]
                     for step in range(VILLAGE_ROLES)]
        # Часы варки знахаря — dword +0x04 (VA 0x4176C8: декремент каждую
        # фазу, при значении < 1 перезаряд на 0x5A0 И выдача всех трёх
        # жетонов разом). В стартовых мирах везде ноль, то есть ПЕРВЫЙ же
        # тик деревни даёт знахарю полный набор жетонов — прилавок обязан
        # наполниться сразу, а не через полный круг в полчаса.
        brew_timer = struct.unpack_from("<i", record, 0x04)[0]
        # Прилавки торговцев: свой список на должность (VA 0x43346C).
        counters = {}
        for role, (offset, count) in VILLAGE_GOODS.items():
            goods = []
            for step in range(count):
                item = struct.unpack_from("<H", record, offset + step * 2)[0]
                if item:
                    goods.append(item)
            counters[role] = goods
        return {
            "map": number, "index": index,
            # +0x0C — НЕ КАЗНА, хотя ключ так и назван. Это счётчик
            # занятий у воеводы: 0x4181E8 убавляет его каждый такт деревни и
            # сбрасывает в 0x4B0 (1200), а больше к полю не притрагивается
            # никто. Доход же капает в +0x10 (0x41C944:250, 442). Ключ
            # оставлен прежним, чтобы не ломать пак и сейвы; читать его как
            # деньги нельзя.
            "treasury": struct.unpack_from("<i", record, 0x0C)[0],
            # +0x10 — казна ВЛАДЕНИЯ: обработчик 27 по её ненулевости
            # отвечает «деревня чья-то» (VA 0x435438), и в неё же капает
            # недельный доход (VA 0x41D722: add [поселение+0x10]).
            "owned": struct.unpack_from("<i", record, 0x10)[0],
            "owner": record[0x4A0],
            "flags": record[0x49C],
            # богатство деревни — байт +0x00: множитель дохода ×50
            # (VA 0x41D567…0x41D571, снято дизасмом)
            "wealth": record[0x00],
            # Те же два первых байта, но в роли РАЗМЕТКИ МЕСТ: число мест
            # равно n1 + n2 + 7, а условия разговора 4 и 6 при аргументе
            # больше шести берут место `байт +0x00 + 7` и отказывают, если
            # байт +0x01 нулевой (VA 0x434AF0, 0x434BC4). Отдаём их явно:
            # у «wealth» своя роль, и смешивать их в клиенте нельзя.
            "slots_a": record[0x00],
            "slots_b": record[0x01],
            # статус +0x49D выбирает строку делителей дохода и порог
            # раздачи товара (VA 0x41D5CA, 0x417BD8)
            "status": record[0x49D],
            # мастер поселения — номер юнита в +0x3D6 (VA 0x417BD8)
            "master": struct.unpack_from("<H", record, 0x3D6)[0],
            # культура старейшины: в рантайме — байт +0x1B вожака, в
            # файле выводится по карте (см. _village_culture)
            "culture": _village_culture(number),
            # Сторона деревни — байт +0x02. Ею движок ИНДЕКСИРУЕТ ТАБЛИЦУ
            # ОТРЯДОВ, когда деревня ополчается: зажигательная стрела зовёт
            # FUN_004159dc(&DAT_0071e56c + village[2] * 0x80, сторона стрелка)
            # (VA 0x41FDD0), то есть войну объявляет ОДИН отряд, а не все
            # отряды карты.
            "side": record[0x02],
            # ОТРЯД ДЕРЕВНИ: сколько мест ему отведено в массиве юнитов
            # (+0x1A) и сколько занято (+0x1C). Юниты отряда лежат подряд
            # (`первый + i`), поэтому вырасти за отведённый кусок отряд не
            # может — и на этой паре стоит отказ «сделать собеседника
            # жителем»: FUN_004338B0 первым делом сравнивает +0x1C с +0x1A и
            # при равенстве возвращает ноль. У деревень запас заложен
            # намеренно (Борье 14 из 17), у прочих отрядов +0x1A равно числу
            # бойцов, то есть места нет вовсе.
            "squad_places": data[T_PARTIES.offset
                                 + record[0x02] * T_PARTIES.size + 0x1A],
            "squad_people": data[T_PARTIES.offset
                                 + record[0x02] * T_PARTIES.size + 0x1C],
            "buildings": buildings,
            "officials": officials,
            "people": [unit for unit in officials if unit],
            "goods": counters,
            # часы варки знахаря (+0x04): в мирах нули — первый тик даёт
            # все три жетона сразу (0x4176C8, ветка «< 1»)
            "brew_timer": brew_timer,
        }
    return None


def villages(world: int = 0, profile=None) -> list[dict]:
    """ВСЕ поселения мира, а не только своё на карте.

    Движок держит блок целиком (0x83D408 у нас) и читает его один раз, а
    вход на карту лишь находит в нём свою запись. Разговор при этом может
    спросить про деревню, где игрок не был: обработчик 35 «Продолжения
    легенды» ищет поселение по номеру карты среди двадцати (FUN_0043f670).

    Перебираем ЗАПИСИ, а не номера карт: каждая сама называет свою карту
    байтом +0x03, и перебор номеров заставлял бы перечитывать файл сотни раз.
    """
    data, layout = _game_bytes(world, profile)
    at, count, size = layout["villages"]
    out = []
    for index in range(count):
        number = data[at + index * size + 3]
        if not number:
            continue
        record = village(number, world, profile=profile)
        if record:
            out.append(record)
    return out


def hero_stats(index: int = 0, profile=None) -> dict:
    """Герой стартового мира GAME.<index> — юнит номер 0.

    Снаряжение отдаётся уже названиями классов: номера в слотах указывают на
    записи таблицы предметов того же файла, а класс лежит в их байте +3.

    С профилем читается мир ТОЙ игры: смещение таблицы юнитов и каталог
    классов у донора свои (см. game_layout), по канонным адресам его файл
    отдаёт не ошибку, а мусор — тело 0 и палитру −1, как это уже было с
    жителями.
    """
    data, layout = _game_bytes(index, profile)
    stats = unit_stats(data, 0, units_at=layout["units"][0])

    def classify(number):
        return item_class_of(data, number, profile)

    # Сохраняем номера записей до замены оборудования подписями классов.
    # Это единственный канонический ключ экземпляра внутри GAME.<index>.
    stats["equipment_item_records"] = dict(stats["equipment"])
    stats["bag_item_records"] = list(stats["bag"])
    stats["second_item_records"] = dict(stats["second"])
    stats["equipment_details"] = {
        slot: item_instance(data, number)
        for slot, number in stats["equipment"].items()
        if number and classify(number)
    }
    stats["bag_details"] = [
        item_instance(data, number)
        if number and classify(number) else {}
        for number in stats["bag"]
    ]
    stats["second_details"] = {
        slot: item_instance(data, number)
        for slot, number in stats["second"].items()
        if number and classify(number)
    }
    stats["equipment_classes"] = {
        slot: (classify(number).index if classify(number) else None)
        for slot, number in stats["equipment"].items()
    }
    stats["bag_classes"] = [
        (classify(number).index
         if number and classify(number) else None)
        for number in stats["bag"]
    ]
    stats["second_classes"] = {
        slot: (classify(number).index if classify(number) else None)
        for slot, number in stats["second"].items()
    }
    stats["equipment"] = {
        slot: (classify(number).name if classify(number) else None)
        for slot, number in stats["equipment"].items()
    }
    return stats

#: Поселения: 12 записей x 0x4A1 байт (12 * 1185 = 0x378C — весь блок).
#: Именно наличие записи с нужным номером карты делает локацию поселением:
#: движок (VA 0x43E6E4) перебирает 12 записей и ищет ту, у которой байт +3
#: совпадает с текущей картой. Если не нашёл — указатель 0x849538 остаётся
#: нулевым, и первый же «деревенский» объект на карте роняет игру.
T_VILLAGES = RecordTable('villages', 0xC3322, 12, 0x4A1, [
    ('n1',    0x00, 'u8'),    # вместе с n2 задаёт длину внутреннего списка
    ('n2',    0x01, 'u8'),    # (кол-во = n1 + n2 + 7, записи по 8 байт с +0x18)
    ('id',    0x02, 'u8'),    # идентификатор поселения
    ('map',   0x03, 'u8'),    # номер карты <N>.KN2
    ('state', 0x41, 'u8'),    # состояние (3 — у части лагерей)
])

T_EVENTS = RecordTable('events', 0xC6AAE, 10, 16, [
    ('when', 0, 'u32'),
    ('p1',   6, 'u16'),
    ('p2',   8, 'u16'),
])

TABLES = [T_ITEMS, T_PARTIES, T_GROUND, T_EXITS, T_UNITS, T_VILLAGES, T_EVENTS]


class GameWorld:
    """Стартовое состояние мира одного героя."""

    def __init__(self, index, data):
        assert len(data) == WORLD_SIZE, f"размер {len(data)} != {WORLD_SIZE}"
        self.index = index
        self.data = bytearray(data)

    @classmethod
    def from_game(cls, index):
        with open(game_file(f'GAME.{index}'), 'rb') as f:
            return cls(index, f.read())

    # --- отряды и юниты -------------------------------------------------
    def parties(self):
        """Все отряды мира. Отряд №0 — отряд игрока."""
        return T_PARTIES.unpack(self.data)['records']

    def parties_on_map(self, map_number):
        return [p for p in self.parties() if p.get('map') == map_number]

    def unit_raw(self, index):
        off = T_UNITS.offset + index * T_UNITS.size
        return bytes(self.data[off:off + T_UNITS.size])

    def set_unit_raw(self, index, raw):
        assert len(raw) == T_UNITS.size
        off = T_UNITS.offset + index * T_UNITS.size
        self.data[off:off + T_UNITS.size] = raw

    def party_units(self, party):
        """Индексы юнитов, принадлежащих отряду."""
        base, cnt = party.get('base_unit', 0), party.get('count', 0)
        return list(range(base, base + cnt))

    def units_on_map(self, map_number):
        """Все юниты, стоящие на карте: [(индекс, отряд), ...]"""
        out = []
        for p in self.parties_on_map(map_number):
            for u in self.party_units(p):
                out.append((u, p))
        return out

    def free_unit_slots(self):
        """Слоты массива юнитов, не занятые ни одним отрядом."""
        used = set()
        for p in self.parties():
            used.update(self.party_units(p))
        return [i for i in range(2000) if i not in used]

    def free_party_slot(self):
        used = {p['slot'] for p in self.parties()}
        for i in range(200):
            if i not in used:
                return i
        raise RuntimeError('свободных слотов отрядов нет')

    def add_party(self, map_number, units, x=0, y=0, template_party=None):
        """Создать отряд на карте из готовых записей юнитов (list of bytes).

        Юниты кладутся в непрерывный свободный диапазон — движок читает их
        как срез ``base_unit .. base_unit+count``.
        """
        import struct as _s
        free = self.free_unit_slots()
        n = len(units)

        # Отряд — это непрерывный срез base..base+count, поэтому нельзя брать
        # слоты вплотную за чужим отрядом: подрастёт дружина игрока — и наши
        # юниты молча станут её частью. Селимся за самым дальним занятым слотом.
        claimed = set()
        for p in self.parties():
            claimed.update(self.party_units(p))
        after = (max(claimed) + 1) if claimed else 0

        base = None
        for start in (after, 0):
            for i in range(len(free) - n + 1):
                if free[i] >= start and free[i + n - 1] - free[i] == n - 1:
                    base = free[i]
                    break
            if base is not None:
                break
        if base is None:
            raise RuntimeError('нет непрерывного диапазона слотов юнитов')
        for k, raw in enumerate(units):
            self.set_unit_raw(base + k, raw)

        slot = self.free_party_slot()
        tmpl = template_party or {}
        raw = bytearray(bytes.fromhex(tmpl['raw']) if 'raw' in tmpl
                        else T_PARTIES.default_record(self.data))
        _s.pack_into('<H', raw, 0x00, base)
        _s.pack_into('<H', raw, 0x08, map_number)
        _s.pack_into('<H', raw, 0x0C, x)
        _s.pack_into('<H', raw, 0x10, y)
        raw[0x1C] = n
        off = T_PARTIES.offset + slot * T_PARTIES.size
        self.data[off:off + T_PARTIES.size] = raw
        return {'party_slot': slot, 'base_unit': base, 'count': n}

    # --- поселения ------------------------------------------------------
    def villages(self):
        """Поселения: деревни, лагеря, торговый пост. Ключ — номер карты."""
        return [v for v in T_VILLAGES.unpack(self.data)['records'] if v.get('map')]

    def village_of_map(self, map_number):
        for v in self.villages():
            if v.get('map') == map_number:
                return v
        return None

    def free_village_slot(self):
        used = {v['slot'] for v in self.villages()}
        for i in range(12):
            if i not in used:
                return i
        raise RuntimeError('свободных слотов поселений нет (всего 12)')

    def add_village(self, map_number, template_map, village_id=None):
        """Объявить карту поселением, скопировав запись существующего.

        Без такой записи движок не найдёт поселение для карты, оставит
        указатель 0x849538 нулевым и упадёт на первом же дворе или частоколе.
        """
        src = self.village_of_map(template_map)
        if src is None:
            raise ValueError(f'карта {template_map} не является поселением')
        slot = self.free_village_slot()
        raw = bytearray(bytes.fromhex(src['raw']))
        raw[3] = map_number
        if village_id is not None:
            raw[2] = village_id
        off = T_VILLAGES.offset + slot * T_VILLAGES.size
        self.data[off:off + T_VILLAGES.size] = raw
        return slot

    # --- переходы между локациями ---------------------------------------
    def exits(self):
        """Граф переходов: откуда, куда, где встанет отряд, зона-триггер."""
        return T_EXITS.unpack(self.data)['records']

    def exits_from_map(self, map_number):
        return [e for e in self.exits() if e.get('from_map') == map_number]

    def free_exit_slot(self):
        used = {e['slot'] for e in self.exits()}
        for i in range(250):
            if i not in used:
                return i
        raise RuntimeError('свободных слотов переходов нет')

    def add_exit(self, from_map, to_map, entry_row, entry_col,
                 zone, facing=1, template=None):
        """Добавить переход. zone = (row1, col1, row2, col2) на карте-источнике."""
        raw = bytearray(bytes.fromhex(template['raw']) if template
                        else T_EXITS.default_record(self.data))
        raw[2] = facing
        raw[3] = from_map
        struct.pack_into('<b', raw, 4, to_map)
        struct.pack_into('<HH', raw, 5, entry_row, entry_col)
        struct.pack_into('<4H', raw, 9, *zone)
        slot = self.free_exit_slot()
        off = T_EXITS.offset + slot * T_EXITS.size
        self.data[off:off + T_EXITS.size] = raw
        return slot

    def clear_exits(self, map_number):
        """Убрать все переходы, привязанные к карте."""
        default = T_EXITS.default_record(self.data)
        doomed = [e['slot'] for e in self.exits_from_map(map_number)]
        for slot in doomed:
            off = T_EXITS.offset + slot * T_EXITS.size
            self.data[off:off + T_EXITS.size] = default
        return len(doomed)

    def clone_exits(self, source, target, keep_links=False):
        """Перенести краевые зоны карты-образца на её клон.

        Зоны переходов задаются в координатах конкретной карты, поэтому у
        клона нельзя оставлять зоны прежней локации: если та была меньше,
        её «края» окажутся посреди новой карты, и игрок будет проваливаться
        на глобальную карту прямо на деревенской улице.

        По умолчанию копируются только зоны ухода с локации (to_map = -1).
        Связи с конкретными локациями и особые переходы не копируются: они
        односторонние — на той стороне обратной записи нет.
        """
        removed = self.clear_exits(target)
        added = 0
        for e in self.exits_from_map(source):
            if e.get('to_map') != EXIT_LEAVE and not keep_links:
                continue
            raw = bytearray(bytes.fromhex(e['raw']))
            raw[3] = target
            slot = self.free_exit_slot()
            off = T_EXITS.offset + slot * T_EXITS.size
            self.data[off:off + T_EXITS.size] = raw
            added += 1
        return removed, added

    def border_exits(self, map_number):
        """Краевые зоны «уйти с локации» (to_map = -1) — готовые проходимые полосы."""
        return [e for e in self.exits_from_map(map_number)
                if e.get('to_map') == EXIT_LEAVE and (e.get('row2') or e.get('col2'))]

    @staticmethod
    def _inward_point(zone, clearance=10):
        """Точка сразу за краевой полосой, внутри карты."""
        r1, c1, r2, c2 = zone
        if (r2 - r1) <= (c2 - c1):          # полоса тонкая по строкам — край сверху/снизу
            row = r2 + clearance if r1 <= clearance else max(0, r1 - clearance)
            return row, (c1 + c2) // 2
        col = c2 + clearance if c1 <= clearance else max(0, c1 - clearance)
        return (r1 + r2) // 2, col

    def link_via_border(self, map_a, map_b, clearance=10):
        """Связать две карты, переделав по одной краевой зоне на каждой.

        Краевые полосы уже нарисованы разработчиками и заведомо проходимы,
        поэтому переход получается рабочим без ручного подбора координат.
        Возвращает (слот_на_A, слот_на_B) или None, если свободных полос нет.
        """
        ba, bb = self.border_exits(map_a), self.border_exits(map_b)
        if not ba or not bb:
            return None
        ea, eb = ba[0], bb[0]
        zone_a = (ea['row1'], ea['col1'], ea['row2'], ea['col2'])
        zone_b = (eb['row1'], eb['col1'], eb['row2'], eb['col2'])
        entry_on_b = self._inward_point(zone_b, clearance)
        entry_on_a = self._inward_point(zone_a, clearance)

        for rec, to_map, entry in ((ea, map_b, entry_on_b), (eb, map_a, entry_on_a)):
            raw = bytearray(bytes.fromhex(rec['raw']))
            struct.pack_into('<b', raw, 4, to_map)
            struct.pack_into('<HH', raw, 5, entry[0], entry[1])
            off = T_EXITS.offset + rec['slot'] * T_EXITS.size
            self.data[off:off + T_EXITS.size] = raw
        return ea['slot'], eb['slot']

    def link_maps(self, map_a, map_b, at_a, at_b, span=3, clearance=10):
        """Связать две карты в обе стороны.

        at_a / at_b — клетка (row, col) на каждой карте, где стоит переход.
        Зона-триггер делается квадратом со стороной 2*span вокруг клетки,
        а точка входа отодвигается на clearance по строке, чтобы прибывший
        отряд не оказался внутри триггера и не улетел обратно.
        """
        (ra, ca), (rb, cb) = at_a, at_b
        zone_a = (max(0, ra - span), max(0, ca - span), ra + span, ca + span)
        zone_b = (max(0, rb - span), max(0, cb - span), rb + span, cb + span)
        entry_a = (max(0, ra - span - clearance), ca)   # куда попадём, вернувшись на A
        entry_b = (max(0, rb - span - clearance), cb)   # куда попадём, придя на B
        s1 = self.add_exit(map_a, map_b, entry_b[0], entry_b[1], zone_a)
        s2 = self.add_exit(map_b, map_a, entry_a[0], entry_a[1], zone_b)
        return s1, s2

    # --- распаковка / сборка -------------------------------------------
    def unpack(self, path):
        doc = {'world_index': self.index}
        for t in TABLES:
            doc[t.name] = t.unpack(self.data)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        return doc

    @classmethod
    def pack(cls, path, index=None):
        with open(path, encoding='utf-8') as f:
            doc = json.load(f)
        data = bytearray(WORLD_SIZE)
        for t in TABLES:
            table = doc[t.name]
            blob = t.pack(table)
            data[t.offset:t.offset + len(blob)] = blob
        return cls(index if index is not None else doc['world_index'], bytes(data))

    def save(self, path):
        with open(path, 'wb') as f:
            f.write(bytes(self.data))
