"""Минимальный локальный сервер web-адаптера и content pack."""
from __future__ import annotations

import argparse
import gzip
import json
import mimetypes
import re
import shutil
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import BinaryIO
from urllib.parse import unquote, urlsplit


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WEB_ROOT = Path(__file__).resolve().with_name("static")
DEFAULT_CONTENT_ROOT = REPOSITORY_ROOT / "content_build"
PROJECT_MAPS = REPOSITORY_ROOT / "project" / "maps"


def project_map_dir(number: int) -> Path | None:
    """Папка проектной карты по номеру: каталоги зовутся «NN_имя»."""
    mark = f"{number:02d}_"
    for folder in sorted(PROJECT_MAPS.iterdir()):
        if folder.is_dir() and folder.name.startswith(mark):
            return folder
    return None


#: НОВАЯ КАРТА С НУЛЯ (фаза 11). Пустой проект в духе авторского
#: clear_cell: вся сетка 4FFF:0000 (0xFFF в младших битах = непроходимая
#: глушь — как чистый лист старого редактора, землю расчищают кистью),
#: слои тайлов чёрные, таблицы map.json пустые (дефолты: объекты и
#: оверлеи 0xFF — сентинел «слота нет», вода нулевая). Жителей и выходов
#: у нового номера в GAME.0 нет — сборка честно даёт пустое население,
#: наполнение кладут фазы 1-3 (editor_units_add и далее).
NEW_MAP_HEADER = (
    "# сетка карты: 256 строк по 160 клеток, формат LO:HI (hex)",
    "# LO=4FFF — пустая клетка (0xFFF в младших битах = непроходимо)",
)
#: Простой транслит для имени каталога: идентификаторы — латиницей.
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e",
    "ё": "e", "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k",
    "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "",
    "э": "e", "ю": "yu", "я": "ya",
}


def _map_slug(name: str) -> str:
    letters = []
    for sign in str(name).lower():
        if sign.isascii() and (sign.isalnum()):
            letters.append(sign)
        elif sign in _TRANSLIT:
            letters.append(_TRANSLIT[sign])
        else:
            letters.append("_")
    folded = "".join(letters)
    while "__" in folded:
        folded = folded.replace("__", "_")
    return folded.strip("_") or "karta"


def editor_map_create(number: int, name: str) -> tuple[bool, str, dict]:
    """Создать пустой проект карты: grid.txt, layer1/2.png, map.json,
    scenario.json. Сборка подхватит папку по глобу NN_*."""
    from PIL import Image
    number = int(number)
    if not 1 <= number <= 254:
        return False, f"номер карты {number} вне 1-254", {}
    if project_map_dir(number) is not None:
        return False, f"карта {number} уже есть: " \
                      f"{project_map_dir(number).name}", {}
    folder = PROJECT_MAPS / f"{number:02d}_{_map_slug(name)}"
    folder.mkdir(parents=True)
    line = " ".join(["4FFF:0000"] * GRID_COLS)
    (folder / "grid.txt").write_text(
        chr(10).join([*NEW_MAP_HEADER, *([line] * GRID_ROWS)]) + chr(10),
        encoding="utf-8")
    Image.new("L", (160, 160), 0).save(folder / "layer1.png")
    Image.new("L", (160, 80), 0).save(folder / "layer2.png")
    empty_val = {"records": []}
    document = {
        "map_number": number,
        "name": str(name),
        # ЧЬЯ ЭТА КАРТА. Правки редактора разрешены только своим картам:
        # карты обеих игр — канон, их файлы обязаны оставаться байт в
        # байт равными оригиналу (project — распакованная игра, а не
        # песочница). Признак ставится при создании и никогда не
        # приписывается канонным папкам задним числом.
        "origin": {"editor": True},
        # 160 (0xA0) — канонный флаг освещения ВСЕХ карт игры; ноль
        # оставляет сцену чёрной (запечённые уровни без дневного света)
        "light_flag": 160,
        "objects": {"_default": "ff" * 36, "_count": 1000, "_size": 36,
                    **empty_val},
        "dynamic": {"_default": "ff" * 12, "_count": 1000, "_size": 12,
                    **empty_val},
        "light": {"_default": "00" * 32, "_count": 16, "_size": 32,
                  **empty_val},
        "zones": {"_default": "ff" * 192, "_count": 30, "_size": 192,
                  **empty_val},
    }
    (folder / "map.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=1),
        encoding="utf-8")
    (folder / "scenario.json").write_text("{}", encoding="utf-8")
    return True, str(folder), {"dir": folder.name, "map": number}


#: ПОРОГ ПРИЁМА ВЫХОДА — те же поля, что требует сборка. Держим список
#: здесь, а не в UI: сборка (builder._project_exits) валит сборку
#: исключением, если чего-то нет, а редактор обязан сказать об этом
#: сразу, а не через минуту неудачной выпечки.
EXIT_REQUIRED = ("to_map", "row1", "row2", "col1", "col2")
EXIT_FIELDS = (*EXIT_REQUIRED, "to_name", "entry_row", "entry_col",
              "facing")


def editor_exit_save(number: int, patch: dict) -> tuple[bool, str, dict]:
    """Выходы карты — переходы к соседям.

    Сборка УЖЕ умеет их читать из `map.json["exits"]`
    (builder._project_exits) и проверяет поля; ручки записи не было
    вовсе, и связать две карты мышью было нельзя в принципе — кисть
    «Выход» на экране проходимости красит лишь бит клетки, а бит без
    записи перехода никуда не ведёт.

    Виды патча (как у оверлеев):
      {}                       — список;
      {add: {...}}             — новая дверь в конец;
      {index, ...поля}         — правка двери по месту в списке;
      {index, removed: true}   — убрать дверь.

    Прямоугольник нормализуем сами (row1<=row2, col1<=col2): человек
    тянет рамку мышью в любую сторону, и требовать от него порядка углов
    незачем — сборка всё равно отсортирует, но валидатор до сборки
    показывал бы вывернутую зону.
    """
    folder = project_map_dir(number)
    if folder is None:
        return False, f"нет проектной карты с номером {number}", {}
    file = folder / "map.json"
    if not file.is_file():
        return False, "у карты нет map.json", {}
    document = json.loads(file.read_text(encoding="utf-8"))
    doors = document.setdefault("exits", [])
    if not isinstance(doors, list):
        return False, "поле exits в map.json не список", {}

    def tidy_up(door: dict) -> dict:
        rows = sorted((int(door["row1"]), int(door["row2"])))
        cols = sorted((int(door["col1"]), int(door["col2"])))
        door.update(row1=rows[0], row2=rows[1],
                     col1=cols[0], col2=cols[1])
        return door

    was_changed = False
    reply: dict = {}
    if "add" in patch:
        fresh_one = {k: patch["add"][k] for k in EXIT_FIELDS
                 if k in (patch["add"] or {})}
        missing = [k for k in EXIT_REQUIRED if k not in fresh_one]
        if missing:
            return False, f"у выхода нет полей: {', '.join(missing)}", {}
        #: ОТРИЦАТЕЛЬНЫЕ НАЗНАЧЕНИЯ — КАНОН, а не ошибка: -1 это выход
        #: на глобальную карту (подавляющее большинство переходов игры,
        #: см. карту 19), -2 — особый переход. Проверка «карта есть в
        #: проекте» касается только настоящих номеров карт; из-за неё
        #: кисть выхода не могла поставить обычный выход на глобальную.
        if (int(fresh_one["to_map"]) >= 0
                and project_map_dir(int(fresh_one["to_map"])) is None):
            return False, (f"выход ведёт на карту {fresh_one['to_map']}, "
                           f"а такой в проекте нет"), {}
        fresh_one.setdefault("to_name", "")
        fresh_one.setdefault("entry_row", 0)
        fresh_one.setdefault("entry_col", 0)
        fresh_one.setdefault("facing", 0)
        doors.append(tidy_up(fresh_one))
        reply["index"] = len(doors) - 1
        was_changed = True
    elif "index" in patch:
        at = int(patch["index"])
        if not 0 <= at < len(doors):
            return False, f"выхода {at} у карты нет", {}
        if patch.get("removed"):
            doors.pop(at)
        else:
            door = doors[at]
            for key_ in EXIT_FIELDS:
                if key_ in patch:
                    door[key_] = (str(patch[key_]) if key_ == "to_name"
                                   else int(patch[key_]))
            if ("to_map" in patch and int(door["to_map"]) >= 0
                    and project_map_dir(int(door["to_map"])) is None):
                return False, (f"выход ведёт на карту {door['to_map']}, "
                               f"а такой в проекте нет"), {}
            tidy_up(door)
        reply["index"] = at
        was_changed = True
    if was_changed:
        file.write_text(json.dumps(document, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    reply["exits"] = doors
    reply["count"] = len(doors)
    return True, str(file) if was_changed else f"{len(doors)} выходов", reply


def _free_number() -> int:
    """Первый незанятый номер карты: копия снимается одним щелчком, и
    придумывать номер человеку незачем. Ноль — свободных не осталось,
    вызывающий отвергнет его проверкой диапазона."""
    taken = set()
    for folder in PROJECT_MAPS.iterdir():
        num_, _, _ = folder.name.partition("_")
        if folder.is_dir() and num_.isdigit():
            taken.add(int(num_))
    for n_ in range(1, 255):
        if n_ not in taken:
            return n_
    return 0


def editor_map_copy(source: int, number: int,
                    name: str = "") -> tuple[bool, str, dict]:
    """Снять свою копию с карты — в том числе с КАНОННОЙ.

    Канон правится только так: файлы игры обязаны остаться байт в байт
    равными оригиналу, поэтому редактор их не пишет вовсе. Раньше из
    этого следовал тупик: открыть «Морской лагерь», чтобы сделать по его
    образцу свою деревню, было можно, а сделать хоть что-нибудь — нет, и
    единственным выходом оставалось начать с пустого поля. Копия снимает
    тупик: та же карта, все слои, объекты и жители на местах, но своя —
    с origin.editor, и пиши что хочешь.

    Копируются ВСЕ файлы папки (grid.txt, layer1/2.png, map.json и
    прочее, что там лежит), у копии правятся номер, имя и происхождение.
    Черновой слой донора не тянем: scenario.json копии начинается пустым,
    иначе в свежей карте оказались бы чужие незапечённые правки.
    """
    import shutil
    source, number = int(source), int(number)
    donor_rec = project_map_dir(source)
    if donor_rec is None:
        return False, f"нет карты-источника с номером {source}", {}
    if not 1 <= number <= 254:
        return False, f"номер карты {number} вне 1-254", {}
    if project_map_dir(number) is not None:
        return False, f"карта {number} уже есть: " \
                      f"{project_map_dir(number).name}", {}
    donor_stuff = {}
    donor_path = donor_rec / "map.json"
    if donor_path.is_file():
        try:
            donor_stuff = json.loads(donor_path.read_text(encoding="utf-8"))
        except ValueError:
            donor_stuff = {}
    name_ = str(name) or f"{donor_stuff.get('name') or donor_rec.name} (копия)"
    folder = PROJECT_MAPS / f"{number:02d}_{_map_slug(name_)}"
    shutil.copytree(donor_rec, folder)
    donor_stuff["map_number"] = number
    donor_stuff["name"] = name_
    #: ПРОИСХОЖДЕНИЕ ПЕРЕПИСЫВАЕТСЯ ЦЕЛИКОМ. У канонной карты в origin
    #: лежит {game, map} — из какой игры и под каким номером она взята;
    #: сохранив это рядом с editor:true, мы бы получили карту, которая
    #: одновременно и своя, и «из игры». Держим прежнее отдельным полем.
    donor_stuff["origin"] = {"editor": True,
                           "copied_from": {"map": source,
                                           "dir": donor_rec.name,
                                           "was": donor_stuff.get("origin")}}
    (folder / "map.json").write_text(
        json.dumps(donor_stuff, ensure_ascii=False, indent=1),
        encoding="utf-8")
    (folder / "scenario.json").write_text("{}", encoding="utf-8")
    return True, str(folder), {"dir": folder.name, "map": number,
                              "from": source}


#: Слои редактора: маршрут -> (ключ патчей, префикс id, ключ добавлений,
#: префикс НОВЫХ записей — такие уходят целыми в список добавлений).
#: СКОЛЬКО ВЕЩЕЙ КЛАСТЬ В КУЧУ. Замер по всему паку (702 кучи): у
#: авторов максимум ШЕСТЬ, и то однажды; чаще всего одна. Жёсткого
#: предела в клиенте я не нашла — окно обмена показывает список, а не
#: сетку мест, — поэтому это не «предел игры», а наша сдержанность:
#: восемь, с запасом над авторским максимумом. Если найдётся настоящий
#: предел движка, число сюда и придёт.
PILE_ITEMS_LIMIT = 8

EDITOR_LAYERS = {
    "unit": ("editor_units", ("unit_",), "editor_units_add", "unit_new_"),
    "loot": ("editor_loot", ("pile_",), "editor_loot_add", "pile_new_"),
    # канонный реквизит зовётся legacy:<карта>:prop:<slot>
    "prop": ("editor_props", ("legacy:", "prop_new_"),
             "editor_props_add", "prop_new_"),
}


def editor_save(number: int, layer: str, entry_id: str,
                patch: dict) -> tuple[bool, str]:
    """Записать редакторский патч в project/maps/<карта>/map.json.

    Пишутся ключи `editor_units`/`editor_loot` — их применяет сборка
    пака (builder, `_editor_unit_apply`/`_editor_loot_apply`, белые
    списки полей там же). Здесь патч лишь складывается: чужие ключи
    сборка отбросит сама, а хранить их в проекте безвредно и честно —
    видно, что редактор просил. НОВЫЕ кучи (id вида pile_new_*) уходят
    целыми записями в список `editor_loot_add`.
    """
    if layer not in EDITOR_LAYERS:
        return False, f"неизвестный слой «{layer}»"
    layer_key, prefix, additions_key, new_prefix = EDITOR_LAYERS[layer]
    if not isinstance(entry_id, str) or not entry_id.startswith(prefix):
        return False, f"id обязан начинаться с одного из {prefix}"
    if not isinstance(patch, dict) or not patch:
        return False, "пустой патч"
    folder = project_map_dir(number)
    if folder is None:
        return False, f"нет проектной карты с номером {number}"
    # СЦЕНАРНЫЙ ФАЙЛ, НЕ map.json: сборка читает слои units/loot/editor_*
    # из source/scenario.json (_export_scenario), а map.json — метаданные
    # карты. Первая версия ручки писала в map.json, и правки НЕ ДОЕЗЖАЛИ
    # до пака — юнит-тесты звали функции напрямую и разрыва не видели.
    file = folder / "scenario.json"
    document = (json.loads(file.read_text(encoding="utf-8"))
                if file.is_file() else {})
    if entry_id.startswith(new_prefix):
        listing = document.setdefault(additions_key, [])
        for record in listing:
            if record.get("id") == entry_id:
                #: СЛОВАРИ СЛИВАЕМ, А НЕ ПОДМЕНЯЕМ. Инспектор шлёт по
                #: одному числу за раз: {"stats": {"armour": 15}}. Плоский
                #: update() заменял ВЕСЬ `stats`, и правка второго числа
                #: стирала первое — жизнь пропадала, едва тронешь броню.
                #: У слоёв ниже это уже сделано; здесь не было.
                for name_, value in patch.items():
                    if isinstance(value, dict) and isinstance(record.get(name_),
                                                              dict):
                        record[name_].update(value)
                    else:
                        record[name_] = value
                break
        else:
            listing.append({"id": entry_id, **patch})
    else:
        layer_id = document.setdefault(layer_key, {})
        record = layer_id.setdefault(entry_id, {})
        for name_, value in patch.items():
            if isinstance(value, dict) and isinstance(record.get(name_),
                                                         dict):
                record[name_].update(value)
            else:
                record[name_] = value
    file.write_text(json.dumps(document, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return True, f"{file}"


#: КЛЕТКИ ЗЕМЛИ. «Два тайла на клетку» старого редактора — это пара
#: байтов (нижний, верхний) в слое layer1.png проекта (160 рядов по 80
#: клеток, ДВА пикселя на клетку: x=col*2 нижний, x=col*2+1 верхний), а
#: «свет» клетки — байт в layer2.png (160x80, пиксель на клетку). Ноль —
#: «пусто», иначе индекс тайла ПЛЮС ОДИН (konung2/graph.py:ground_cells).
GROUND_ROWS, GROUND_COLS = 160, 80
TILES_PER_PAGE = 50


def _light_xy(row: int, col: int) -> tuple[int, int]:
    """Пиксель СВЕТА клетки в layer2.png. Канонный байт лежит ЛИНЕЙНО
    (row * 80 + col — страйд света 0x50, konung2/graph.py:LIGHT_STRIDE),
    а PNG записан шириной 160: пиксель — линейный индекс, свёрнутый в
    160 столбцов. Прямое (col, row) попадало в чужую клетку — баг
    фазы 7, пойман тестом маршрутов API v2."""
    linear = row * GROUND_COLS + col
    return linear % 160, linear // 160


def _ground_layers(number: int):
    folder = project_map_dir(number)
    if folder is None:
        return None, None, f"нет проектной карты с номером {number}"
    layer1 = folder / "layer1.png"
    layer2 = folder / "layer2.png"
    if not layer1.is_file() or not layer2.is_file():
        return None, None, "у карты нет слоёв layer1/layer2"
    return layer1, layer2, ""


#: Мазки земли сериализуются: каждый POST читает и пишет PNG целиком,
#: и параллельные кисти затирали друг друга (живой прогон прототипа:
#: из 120 кликов доехало 40). Пакетная кисть решает то же по-крупному.
_GROUND_LOCK = __import__("threading").Lock()


def editor_ground_save(number: int, row: int, col: int,
                       patch: dict) -> tuple[bool, str, dict]:
    """Правка клетки земли: lower/upper — в layer1.png, light — в
    layer2.png. Пустой патч — прочитать. Значения: None/0 — стереть,
    иначе индекс тайла (внутрь пишется индекс+1, как в .KN2).

    ПАКЕТНАЯ КИСТЬ: patch["cells"] = [{row, col, lower?, upper?,
    light?}, …] — мазок области одной записью файла; row/col довода
    тогда лишь точка peek."""
    if not (0 <= row < GROUND_ROWS and 0 <= col < GROUND_COLS):
        return False, f"клетка земли ({row},{col}) вне сетки", {}
    layer1, layer2, trouble = _ground_layers(number)
    if trouble:
        return False, trouble, {}
    from PIL import Image
    with _GROUND_LOCK:
        img1 = Image.open(layer1).convert("L")
        img2 = Image.open(layer2).convert("L")
        strokes = list(patch.get("cells") or [])
        if patch and not strokes:
            strokes = [{"row": row, "col": col,
                      **{k: patch[k] for k in ("lower", "upper", "light")
                         if k in patch}}]
        if strokes:
            px1 = img1.load()
            px2 = img2.load()

            def code(value):
                return 0 if value in (None, -1) \
                    else (int(value) + 1) & 0xFF

            for stroke in strokes:
                r, c = int(stroke.get("row", -1)), int(stroke.get("col", -1))
                if not (0 <= r < GROUND_ROWS and 0 <= c < GROUND_COLS):
                    continue
                if "lower" in stroke:
                    px1[c * 2, r] = code(stroke["lower"])
                if "upper" in stroke:
                    px1[c * 2 + 1, r] = code(stroke["upper"])
                if "light" in stroke:
                    px2[_light_xy(r, c)] = code(stroke["light"])
            img1.save(layer1)
            img2.save(layer2)
    bottom_part = img1.getpixel((col * 2, row))
    top_part = img1.getpixel((col * 2 + 1, row))
    light = img2.getpixel(_light_xy(row, col))
    return True, str(layer1.parent), {
        "lower": bottom_part - 1 if bottom_part else None,
        "upper": top_part - 1 if top_part else None,
        "light": light - 1 if light else None,
    }


#: СЛОВАРЬ ДЕКОРА БЕРЁТСЯ ИЗ САМОЙ ИГРЫ.
#:
#: Декор (T_DYNAMIC) — это спрайт GRAPH.RES, положенный на карту в
#: пикселях: берега, кувшинки, камыши, ими прикрыта нарочно неполная
#: базовая мозаика. Каталога у него не было вовсе, и постановка стояла
#: закрытой: номера объектов из ДРУГОЙ таблицы, и подстановка одного
#: вместо другого молча клала в карту чужой спрайт.
#:
#: Придумывать список неоткуда — берём тот, которым игра пользуется
#: сама: обход распакованных карт и подсчёт, какой спрайт где стоит.
#: Заодно это и есть подпись человеку («стоит на 37 картах, 611 раз»),
#: пока у декора нет имён.
_DECOR_VOCABULARY: dict[str, list[dict]] = {}


def _decor_vocabulary(game: str) -> list[dict]:
    if game in _DECOR_VOCABULARY:
        return _DECOR_VOCABULARY[game]
    seen: dict[int, dict] = {}
    for folder in sorted(PROJECT_MAPS.glob("*")):
        file = folder / "map.json"
        if not file.is_file():
            continue
        try:
            document = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if _map_game(document) != game:
            continue
        number = document.get("map_number")
        for record in ((document.get("dynamic") or {}).get("records") or ()):
            sprite = record.get("id")
            if sprite is None or int(sprite) in (0, 0xFFFF):
                continue
            entry = seen.setdefault(int(sprite), {
                "id": int(sprite), "count": 0, "maps": []})
            entry["count"] += 1
            if number is not None and number not in entry["maps"]:
                entry["maps"].append(number)
    listing = sorted(seen.values(), key=lambda z_: -z_["count"])
    _DECOR_VOCABULARY[game] = listing
    return listing


DECOR_PER_PAGE = 48


def editor_decor_page(page: int, content_root=None,
                      game: str = "canon") -> tuple[bool, str, dict]:
    """Страница каталога декора: спрайты T_DYNAMIC с превью.

    Превью печёт тем же способом, что и сборка (`GraphRes.decode_tile`),
    в тот же каталог пака — картинка выходит та же, что ляжет на карту.
    """
    from konung2.graph import GraphRes
    game = game if game in ("canon", "legend") else "canon"
    root = Path(content_root or DEFAULT_CONTENT_ROOT)
    folder = root / "assets" / "terrain_overlays"
    folder.mkdir(parents=True, exist_ok=True)
    prefix = "legend" if game == "legend" else ""
    graph = None
    listing = _decor_vocabulary(game)
    start = max(0, int(page)) * DECOR_PER_PAGE
    rows = []
    from PIL import Image
    for entry in listing[start:start + DECOR_PER_PAGE]:
        file = folder / f"{prefix}{entry['id']}.png"
        size = None
        if not file.is_file():
            if graph is None:
                if game == "legend":
                    from konung2 import donor
                    graph = donor.graph() if donor.available() else None
                else:
                    graph = GraphRes.from_game()
            if graph is None:
                continue
            try:
                sprite = graph.decode_tile(entry["id"])
            except (ValueError, IndexError, OSError):
                continue
            if sprite is None:
                continue
            sprite.save(str(file))
            size = (sprite.width, sprite.height)
        if size is None:
            try:
                with Image.open(file) as picture:
                    size = picture.size
            except OSError:
                continue
        #: Размер нужен призраку постановки: декор кладётся серединой под
        #: курсор, а в записи лежит левый верхний угол.
        rows.append({**entry, "width": size[0], "height": size[1],
                     "url": f"/content/assets/terrain_overlays/{file.name}"})
    return True, f"страница {page}", {
        "decor": rows, "page": int(page), "game": game,
        "pages": max(1, (len(listing) + DECOR_PER_PAGE - 1) // DECOR_PER_PAGE),
        "total": len(listing)}


def editor_tiles_page(page: int,
                      content_root=None) -> tuple[bool, str, dict]:
    """Страница палитры тайлов: печёт недостающие превью в пак
    (assets/ground/editor_tile_N.png) и отдаёт список ссылок."""
    from konung2.graph import GraphRes, TILE_SLOTS
    root = Path(content_root or DEFAULT_CONTENT_ROOT)
    folder = root / "assets" / "ground"
    folder.mkdir(parents=True, exist_ok=True)
    graph = GraphRes.from_game()
    start = max(0, int(page)) * TILES_PER_PAGE
    row_ = []
    for index in range(start, min(start + TILES_PER_PAGE, TILE_SLOTS)):
        try:
            if graph.tile_entry(index) is None:
                continue
        except (ValueError, IndexError):
            continue
        file = folder / f"editor_tile_{index}.png"
        if not file.is_file():
            try:
                sprite = graph.compose_cell(index, None)
            except (ValueError, IndexError, OSError):
                continue
            if sprite is None:
                continue
            sprite.save(str(file))
        row_.append({"index": index,
                    "url": f"/content/assets/ground/{file.name}"})
    return True, f"страница {page}", {
        "tiles": row_, "page": int(page),
        "pages": (TILE_SLOTS + TILES_PER_PAGE - 1) // TILES_PER_PAGE,
    }


#: КАТАЛОГ ОБЪЕКТОВ ПАКА. Паспорт assets/objects/index.json перечисляет
#: все испечённые пары «гнездо+палитра+состояние» с готовыми картинками —
#: каталог строится из него, без новой выпечки. Добавление кладёт запись
#: в таблицу `objects` map.json проекта (T_OBJECTS): сборка сама испечёт
#: слои и рамку, как у родных. Слот — ЗА ПОСЛЕДНИМ занятым (движок
#: останавливает чтение на первом пустом). Поле kind записи — байтовое
#: смещение палитры (индекс * 0x200; ноль движок подменяет палитрой
#: заголовка ресурса, VA 0x43E7D8); поле sprite = гнездо каталога минус
#: SIMPLE_SLOT_BASE (30).
OBJECTS_PER_PAGE = 24


#: ГРУППЫ КАТАЛОГА ОБЪЕКТОВ — РАЗМЕЧЕНЫ ГЛАЗАМИ, ПО ЛИСТУ НА ГРУППУ.
#: В данных семантики нет: поле kind у объекта — палитра, а не класс,
#: поэтому единственный честный источник — смотреть спрайты. Первая
#: разметка по общим контактным листам съехала на несколько слотов
#: почти везде (в «срубах» лежали пещеры, в «навесах» — идолы, в
#: «костях» — избы); эта собрана по отдельному листу НА КАЖДУЮ группу
#: (scratchpad/grp_*.png, 29.08.2026) и тем же способом проверена после
#: правки. Слоты идут СЕРИЯМИ «стройплощадка → каркас → готовое →
#: пепелище» — серию не рвём, вся лежит в группе готовой постройки.
OBJECT_GROUPS = (
    (range(30, 33), "yards"),            # частокольные дворы-загоны
    ((304,), "yards"),                   # бревенчатый настил-загон
    (range(33, 65), "buildings"),        # избы и дома со своими фазами
    ((67, 68), "props"),                 # квестовый цветок и крошка-точка
    (range(69, 90), "buildings"),
    (range(90, 98), "yurts"),            # вежи с гнутыми крышами и их фазы
    (range(98, 104), "longhouses"),      # бараки в фазах и пепелищах
    (range(104, 118), "buildings"),
    (range(118, 125), "longhouses"),     # длинный дом: стройка → пожар
    ((125,), "props"),                   # одинокая чёрная яма
    (range(126, 138), "wells"),          # колодцы: сруб, ворот, журавль, фазы
    (range(138, 147), "haystacks"),      # стога, гумно, обгоревшие скирды
    (range(147, 171), "trees"),          # кроны, берёзы, ели, кусты
    (range(171, 227), "fences"),         # частокол с фазами, рвы, одиночные колья
    (range(227, 235), "fences"),         # жердевые слеги-перила
    (range(235, 244), "rocks"),          # валуны, останец, грот, дольмен
    (range(244, 254), "idols"),          # каменная голова и резные столбы
    (range(254, 286), "sheds"),          # навесы и круглокрышие сараи с фазами
    (range(286, 289), "buildings"),      # изба и её тёмные сараи
    (range(289, 297), "longhouses"),     # стройка хлева, два хлева, мшелый барак
    ((297, 300), "byzantine"),           # белокаменный дом, стена с рельефом
    (range(298, 300), "flags"),          # каменные столбы-вехи
    (range(301, 304), "flags"),          # тумба-веха и два прапора на шестах
    (range(305, 311), "buildings"),      # изба недострой → пепелище
    ((65,), "piers"),                    # бревенчатый мост
    (range(311, 315), "piers"),          # сваи, настилы, причал с бочками
    (range(315, 317), "bones"),          # малые золотые черепа
    ((317,), "props"),                   # горшок
    (range(318, 350), "snags"),          # сухостой и коряги
    (range(350, 391), "dungeon"),        # лиловый набор пещер: скалы, черепа,
                                         # статуи, врата, гроты
    (range(392, 396), "bones"),          # черепа зверей на степной земле
    (range(396, 421), "barns"),          # клети-амбары с шатровыми крышами
    (range(424, 432), "fences"),         # заострённые колья россыпью
    (range(449, 471), "camp"),           # шатры, каркасы, вешала, шест
    ((477,), "camp"),                    # зелёный шатёр
    (range(483, 489), "rocks"),          # песчаниковые останцы
    (range(489, 501), "byzantine"),      # постаменты с рельефами и стены
    (range(501, 509), "furniture"),      # каменные скамьи и торговые стеллажи
)
#: ГРУППЫ ВТОРОЙ ИГРЫ — СВОИ. У «Продолжения легенды» свой OBJECT.RES:
#: те же номера гнёзд означают другие вещи (30 у канона — двор-загон, у
#: легенды — сруб избы), поэтому канонная разметка на его картах врала бы
#: подписями. Размечено глазами по пятнадцати контактным листам всего
#: каталога (579 записей, tools-скрипт листов в скретче сессии).
LEGEND_OBJECT_GROUPS = (
    #: ОДИНОЧКИ ИДУТ ПЕРВЫМИ: выборка отдаёт первое совпадение, и
    #: внутри длинных полос попадаются чужаки — их видно только глазами
    #: на листе группы, чем пересмотр и полезен.
    ((65,), "piers"),                    # бревенчатый мост
    ((66,), "bones"),                    # костяк на земле
    ((67, 68), "props"),                 # цветок и крошка-точка
    (range(551, 557), "camp"),           # шесты и растяжки лагеря
    ((524, 525), "props"),               # обжиговые печи
    ((235,), "rocks"),                   # горка валунов посреди изгородей
    ((513, 519, 520, 523), "sheds"),     # навесы на столбах среди ворот
    (range(30, 90), "buildings"),        # избы: сруб → дом → пепелище
    (range(90, 97), "yurts"),            # вежи с гнутыми крышами
    (range(97, 125), "longhouses"),      # длинные дома, хлева и их фазы
    ((125,), "props"),                   # одинокая яма
    (range(126, 147), "wells"),          # колодцы, ворот, котлы на треногах
    (range(147, 171), "trees"),          # кроны, ели, берёзы, кусты
    (range(171, 236), "fences"),         # частокол, рвы, колья, слеги
    (range(236, 244), "rocks"),          # валуны, грот, дольмен
    (range(244, 254), "idols"),          # каменные головы и резные столбы
    (range(254, 300), "sheds"),          # южные навесы и сараи с фазами
    ((300,), "idols"),                   # каменная тумба
    (range(301, 304), "flags"),          # прапоры на шестах
    (range(304, 311), "buildings"),      # бревенчатая изба и её фазы
    (range(311, 315), "piers"),          # сваи, настилы, причал с бочками
    (range(315, 317), "bones"),          # черепа
    ((317,), "furniture"),               # горшок-корчага
    (range(318, 350), "snags"),          # сухостой и коряги
    (range(350, 366), "rocks"),          # лиловые останцы подземелья
    (range(366, 371), "bones"),          # лиловые черепа и костяки
    (range(371, 375), "rocks"),          # пещера, растрескавшаяся земля
    (range(375, 379), "idols"),          # статуи
    (range(379, 392), "dungeon"),        # входы в пещеры, врата, кладка
    (range(392, 396), "bones"),          # черепа зверей
    (range(396, 424), "barns"),          # клети и вышки с шатровыми крышами
    (range(424, 432), "props"),          # брёвна и щепки россыпью
    (range(432, 446), "piers"),          # настилы и плоты
    (range(446, 467), "camp"),           # круглый шатёр, палатки, торг
    (range(467, 474), "byzantine"),      # белокаменные стены, ротонда, колонна
    (range(474, 481), "camp"),           # синие шатры
    (range(481, 483), "flags"),          # знамёна
    (range(483, 489), "rocks"),          # песчаниковые останцы
    (range(489, 494), "idols"),          # постаменты с рельефами
    (range(494, 501), "byzantine"),      # каменные стены и плиты
    (range(501, 503), "furniture"),      # каменные скамьи
    (range(509, 513), "trees"),          # пеньки и поросль
    (range(513, 525), "fences"),         # ворота, створы, частокол, навесы
    (range(526, 559), "trees"),          # кусты, пальмы, южные деревья
    (range(559, 561), "east"),           # глинобитные дома
    (range(561, 563), "piers"),          # лестницы-сходни
    (range(563, 565), "camp"),           # торговые палатки
    (range(565, 570), "byzantine"),      # колонны
    (range(570, 587), "east"),           # восточный город: дома, мечеть, руины
    ((587,), "props"),                   # кострище
)

OBJECT_GROUP_LABELS = (
    ("buildings", "избы и дома"), ("longhouses", "длинные дома и сараи"),
    ("yurts", "вежи и юрты"), ("yards", "дворы и загоны"),
    ("sheds", "навесы"), ("barns", "клети и амбары"),
    ("wells", "колодцы"), ("haystacks", "стога и сено"),
    ("fences", "заборы и частокол"), ("trees", "деревья и кусты"),
    ("snags", "коряги и сухостой"), ("rocks", "камни и скалы"),
    ("idols", "идолы и столбы"), ("flags", "знамёна и вехи"),
    ("piers", "мостки и причалы"), ("camp", "лагерь и шатры"),
    ("byzantine", "византийский двор"), ("furniture", "лавки и мебель"),
    ("dungeon", "подземелье"), ("bones", "кости и черепа"),
    ("east", "восточный город"), ("props", "прочее"),
)


def object_group(slot: int, game: str = "canon") -> str:
    """Группа каталога для гнезда OBJECTS.RES; вне разметки — «прочее».

    РАЗМЕТКА У КАЖДОЙ ИГРЫ СВОЯ: номера гнёзд у канона и у легенды
    означают разные вещи, и общая таблица подписывала бы чужое.
    """
    table = LEGEND_OBJECT_GROUPS if game == "legend" else OBJECT_GROUPS
    for spots, group in table:
        if slot in spots:
            return group
    return "props"


def editor_objects_page(page: int,
                        content_root=None,
                        game: str = "canon") -> tuple[bool, str, dict]:
    """Страница каталога объектов из паспорта пака.

    `game` — чьи спрайты отдавать: у «Продолжения легенды» свой
    OBJECTS.RES, и на его картах канонный каталог промахивался мимо
    каждой записи — здания Тиграта не отображались вовсе.
    """
    game = game if game in ("canon", "legend") else "canon"
    #: в паспорте игра донора записана ПОЛНЫМ ИМЕНЕМ («Продолжение
    #: легенды», ключ кладёт assets.game), а ручки и клиент живут на
    #: короткое «legend» — сопоставляем здесь
    from konung2 import donor
    wanted_game = "canon" if game == "canon" else donor.LEGEND_NAME
    root = Path(content_root or DEFAULT_CONTENT_ROOT)
    passport = root / "assets" / "objects" / "index.json"
    if not passport.is_file():
        return False, "в паке нет паспорта объектов", {}
    records = json.loads(passport.read_text(encoding="utf-8"))
    row_ = []
    for key_ in sorted(records):
        game_name, slot, pal, state_ = key_.split(":", 3)
        if game_name != wanted_game:
            continue
        picture = records[key_]
        layers_map = picture.get("layers") or {}
        # ВИД ОБЪЕКТА — ПО СЛОЯМ И СОСТОЯНИЮ, а не по номеру: постройка,
        # в которую можно войти, несёт отдельные стены и крышу (движок
        # прячет крышу над юнитом), а ненулевое состояние — это фаза
        # лестницы строительства и развалины.
        kind_ = ("building" if "walls" in layers_map and "roof" in layers_map
               else "ruin" if int(state_) else "prop")
        #: группы размечены глазами у ОБЕИХ игр, каждая своей таблицей:
        #: одно и то же гнездо у них означает разные вещи
        row_.append({"slot": int(slot), "palette": int(pal),
                    "state": int(state_), "kind": kind_,
                    "group": object_group(int(slot), game),
                    "url": "/content/" + picture["path"],
                    "width": picture["width"],
                    "height": picture["height"],
                    "offset_x": picture.get("offset_x", 0),
                    "offset_y": picture.get("offset_y", 0),
                    "layers": layers_map})
    row_.sort(key=lambda x: (x["slot"], x["palette"], x["state"]))
    pages_total = max(1, (len(row_) + OBJECTS_PER_PAGE - 1) // OBJECTS_PER_PAGE)
    start = max(0, int(page)) * OBJECTS_PER_PAGE
    return True, f"страница {page}", {
        "items": row_[start:start + OBJECTS_PER_PAGE],
        "page": int(page), "pages": pages_total, "total": len(row_),
        "game": game,
        #: чипы фильтра клиент строит по этому списку — подписи и порядок
        #: живут в одном месте с разметкой
        #: чипы отдаём только для тех групп, что на этой игре ЕСТЬ:
        #: пустой чип «византийский двор» на пустынной карте — обещание,
        #: за которым ничего нет
        "groups": [{"key": key_, "label": label}
                   for key_, label in OBJECT_GROUP_LABELS
                   if any(z_["group"] == key_ for z_ in row_)],
    }


def editor_object_move(number: int, patch: dict) -> tuple[bool, str, dict]:
    """Перенести запись T_OBJECTS: {slot, x, y}.

    Отдельно от добавления: тело без `add` раньше уходило в
    `editor_object_add` и вместо переноса плодило новый объект.
    """
    folder = project_map_dir(number)
    if folder is None:
        return False, f"нет проектной карты с номером {number}", {}
    slot = patch.get("slot")
    if slot is None:
        return False, "не сказано, какую запись двигать (slot)", {}
    file = folder / "map.json"
    document = json.loads(file.read_text(encoding="utf-8"))
    records = (document.get("objects") or {}).get("records") or []
    record = next((r for r in records if int(r["slot"]) == int(slot)), None)
    if record is None:
        return False, f"объекта в слоте {slot} нет", {}
    #: ДОМ ЕДЕТ ВМЕСТЕ СО СТЕНАМИ. Клетки размечены под СТАРЫМ местом:
    #: сдвинув одну картинку, мы оставили бы невидимую коробку на прежнем
    #: и дыру на новом. Снимаем штамп до правки, ставим после.
    was_stamped = False
    try:
        was_stamped = bool(_stamp_apply(folder, record, int(slot),
                                        remove_it=True))
    except (OSError, ValueError):
        was_stamped = False
    # координаты живут в pixel_x/pixel_y (старая схема звала их так же)
    for key_, field in (("x", "pixel_x"), ("y", "pixel_y")):
        if patch.get(key_) is not None:
            record[field] = int(patch[key_])
            record.pop("raw", None)      # поля важнее сырых байтов
    #: СОСТОЯНИЕ И ПАЛИТРА — ТОЖЕ ПРАВКА НА МЕСТЕ, а не «убрать и
    #: поставить заново». Состояние это фаза постройки (стройка, целое,
    #: руины), палитра — раскраска; менять их, стирая запись и ставя
    #: новую, значит терять слот и порядок в таблице. Ручка принимала
    #: только координаты, и сменить фазу дома было нечем.
    if patch.get("state") is not None:
        record["state"] = int(patch["state"]) & 0xFF
        record.pop("raw", None)
    if patch.get("palette") is not None:
        #: палитра лежит байтовым смещением с шагом 0x200 (VA 0x43E7D8)
        record["kind"] = (int(patch["palette"]) * 0x200) & 0xFFFFFFFF
        record.pop("raw", None)
    file.write_text(json.dumps(document, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    #: ШТАМП СТАВИМ ВСЕГДА, а не только если он был. Дома, поставленные
    #: до появления штампов, так и остались бы картинками без стен;
    #: сдвиг на ноль пикселей — это и есть «обвести постройку заново».
    cells = 0
    try:
        cells = _stamp_apply(folder, record, int(slot))
    except (OSError, ValueError):
        cells = 0
    if not cells and was_stamped:
        cells = 0
    return True, str(file), {"slot": int(slot),
                             "x": record.get("pixel_x"),
                             "y": record.get("pixel_y"),
                             "state": record.get("state"),
                             "kind": record.get("kind"), "cells": cells}


def _object_is_sentinel(r: dict) -> bool:
    """Запись-«стоп»: sprite = -1 — движок обрывает чтение таблицы на
    ней. В records такие попадают, когда дефолт карты — иной паттерн."""
    if "sprite" in r:
        return int(r["sprite"]) < 0
    if "id" in r:
        # старая сериализация звала поле нулевого смещения «id»
        return int(r["id"]) in (0xFFFF, 0xFFFFFFFF, -1)
    raw_data = str(r.get("raw") or "")
    return raw_data[:8].lower() == "ffffffff"


#: ГОТОВАЯ ПОСТРОЙКА, А НЕ КАРТИНКА. Дом в этой игре держится не на
#: записи объекта, а на КЛЕТКАХ вокруг неё: кольцо глуши — стены, клетки
#: с битом 0x20 — нутро, клетки с номером записи в старших битах —
#: footprint (по нему движок снимает крышу над отрядом, VA 0x428253), а
#: пара клеток без «внутренней» внизу — вход. Пока их не разметишь, герой
#: ходит сквозь дом и крыша не снимается никогда.
#:
#: Разметку не выдумываем: она снята с канонных карт (tools/
#: building_stamps.py — согласие большинства встреч каждой постройки).
_STAMPS: dict | None = None


def _building_stamps() -> dict:
    global _STAMPS
    if _STAMPS is None:
        file = Path(__file__).resolve().parents[1] / "data" / "building_stamps.json"
        try:
            _STAMPS = (json.loads(file.read_text(encoding="utf-8"))
                       .get("stamps") or {})
        except (OSError, ValueError):
            _STAMPS = {}
    return _STAMPS


def _object_cell(record: dict) -> tuple[int, int]:
    """Клетка, в которой стоит объект (пиксели записи по сетке 58x16)."""
    x, y = int(record.get("pixel_x") or 0), int(record.get("pixel_y") or 0)
    row = max(0, (y - 16) // 16)
    col = max(0, (x - (29 if row % 2 else 58)) // 58)
    return row, col


#: Биты, которыми распоряжается штамп: низ — проходимость (0xFFF), NoFly
#: (0x4000) и пол (0x8000); верх — номер постройки (0x1F) и «внутренняя»
#: (0x20). Свет (0x40) не трогаем: он от карты, а не от дома.
#: Числами, а не именами CELL_*: те объявлены ниже по файлу, рядом с
#: кистью клеток, и на импорте их ещё нет.
_STAMP_LOW = 0x0FFF | 0x4000 | 0x8000
_STAMP_HIGH = 0x1F | 0x20


def _grid_lines(folder: Path):
    file = folder / "grid.txt"
    lines = file.read_text(encoding="utf-8").splitlines()
    head = [line for line in lines if line.startswith("#")]
    grid = [line for line in lines if line and not line.startswith("#")]
    return file, head, grid


def _stamp_of(folder: Path, record: dict) -> dict | None:
    """Штамп постройки: игра карты + гнездо + состояние.

    ИГРА В КЛЮЧЕ ОБЯЗАТЕЛЬНА: OBJECTS.RES у двух игр свой, и гнездо 47 в
    каноне — одна изба, а у «Продолжения легенды» другая. Общий ключ
    ставил бы под чужой дом чужие стены.
    """
    nest = int(record.get("sprite") or 0) + 30
    state = int(record.get("state") or 0)
    try:
        document = json.loads((folder / "map.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        document = {}
    game_name = _map_game(document)
    stamps = _building_stamps()
    return (stamps.get(f"{game_name}:{nest}:{state}")
            #: у старых библиотек игры в ключе не было
            or stamps.get(f"{nest}:{state}"))


def _stamp_apply(folder: Path, record: dict, slot: int,
                 remove_it: bool = False) -> int:
    """Разметить (или снять) клетки постройки. Возвращает сколько клеток."""
    stamp = _stamp_of(folder, record)
    if not stamp:
        return 0
    file, head, grid = _grid_lines(folder)
    if len(grid) != GRID_ROWS:
        return 0
    rows = [line.split() for line in grid]
    row0, col0 = _object_cell(record)
    #: НАЧАЛО ШТАМПА — УГОЛ СЛЕДА, а не клетка объекта: пиксельная точка
    #: записи попадает то в одну клетку, то в соседнюю, поэтому смещение
    #: до угла снято вместе со штампом (tools/building_stamps.py).
    top, left = stamp.get("anchor") or [0, 0]
    row0, col0 = row0 - int(top), col0 - int(left)
    touched = 0
    for cell in stamp["cells"]:
        row, col = row0 + int(cell["dr"]), col0 + int(cell["dc"])
        if not (0 <= row < GRID_ROWS and 0 <= col < GRID_COLS):
            continue
        lo_hex, _, hi_hex = rows[row][col].partition(":")
        low, high = int(lo_hex, 16), int(hi_hex, 16)
        if remove_it:
            #: снимаем ТОЛЬКО своё: чужую разметку соседнего дома или
            #: забора, попавшую под наш штамп, оставляем как есть
            if cell["own"] and (high & 0x1F) != slot + 1:
                continue
            low &= ~_STAMP_LOW
            high &= ~_STAMP_HIGH
        else:
            low = (low & ~_STAMP_LOW) | (int(cell["low"]) & _STAMP_LOW)
            high = (high & ~_STAMP_HIGH) | (int(cell["high"]) & 0x20)
            if cell["own"]:
                high |= (slot + 1) & 0x1F
        rows[row][col] = f"{low:04X}:{high:04X}"
        touched += 1
    grid = [" ".join(line) for line in rows]
    file.write_text("\n".join(head + grid) + "\n", encoding="utf-8")
    return touched


def _stamp_renumber(folder: Path, records: list) -> None:
    """Переписать номера построек в клетках после сдвига слотов.

    Слоты при удалении уплотняются, а в клетке лежит НОМЕР ЗАПИСИ: без
    этого прохода дом остался бы помечен номером соседа — крыша
    снималась бы не над тем домом, а проход остался бы от чужой стены.
    """
    file, head, grid = _grid_lines(folder)
    if len(grid) != GRID_ROWS:
        return
    rows = [line.split() for line in grid]
    for row in range(GRID_ROWS):
        for col in range(GRID_COLS):
            lo_hex, _, hi_hex = rows[row][col].partition(":")
            high = int(hi_hex, 16)
            if high & 0x1F:
                rows[row][col] = f"{lo_hex}:{high & ~0x1F:04X}"
    for record in records:
        slot = int(record["slot"])
        nest = int(record.get("sprite") or 0) + 30
        stamp = _building_stamps().get(f"{nest}:{int(record.get('state') or 0)}")
        if not stamp:
            continue
        row0, col0 = _object_cell(record)
        top, left = stamp.get("anchor") or [0, 0]
        row0, col0 = row0 - int(top), col0 - int(left)
        for cell in stamp["cells"]:
            if not cell["own"]:
                continue
            row, col = row0 + int(cell["dr"]), col0 + int(cell["dc"])
            if not (0 <= row < GRID_ROWS and 0 <= col < GRID_COLS):
                continue
            lo_hex, _, hi_hex = rows[row][col].partition(":")
            high = (int(hi_hex, 16) & ~0x1F) | ((slot + 1) & 0x1F)
            rows[row][col] = f"{lo_hex}:{high:04X}"
    file.write_text("\n".join(head + [" ".join(line) for line in rows]) + "\n",
                    encoding="utf-8")


def editor_object_add(number: int, patch: dict) -> tuple[bool, str, dict]:
    """Новая запись T_OBJECTS в map.json проекта: {slot, palette, state,
    x, y} — гнездо каталога и мировая точка."""
    from konung2.binrec import new_record
    from konung2.res import ObjectsRes
    folder = project_map_dir(number)
    if folder is None:
        return False, f"нет проектной карты с номером {number}", {}
    file = folder / "map.json"
    if not file.is_file():
        return False, "у карты нет map.json", {}
    document = json.loads(file.read_text(encoding="utf-8"))
    block = document.setdefault("objects", {
        "_default": "ff" * 36, "_count": 1000, "_size": 36,
        "records": []})
    records = block.setdefault("records", [])
    # СЕНТИНЕЛ НЕ ЗАНИМАЕТ СЛОТ. Запись со sprite=-1 — «стоп» движка:
    # вставая ЗА ней, добавка невидима оригиналу (поймано валидатором
    # на карте 23 — записи 283-285 за сентинелом 282). Сентинелы
    # вычищаются (дефолт пустого слота сам начинается с ffffffff), а
    # выжившие записи перенумеровываются ПЛОТНО — у канона слоты и так
    # подряд с нуля, подтягивается только хвост из-за сентинела.
    records[:] = sorted((r for r in records if not _object_is_sentinel(r)),
                       key=lambda r: int(r["slot"]))
    for at, record in enumerate(records):
        record["slot"] = at
    slot = len(records)
    if slot >= int(block.get("_count") or 1000):
        return False, "все слоты объектов заняты", {}
    records.append(new_record(
        block, slot,
        sprite=int(patch["slot"]) - ObjectsRes.SIMPLE_SLOT_BASE,
        kind=(int(patch.get("palette") or 0) * 0x200) & 0xFFFFFFFF,
        pixel_x=int(patch.get("x") or 0) & 0xFFFF,
        pixel_y=int(patch.get("y") or 0) & 0xFFFF,
        state=int(patch.get("state") or 0) & 0xFF))
    records.sort(key=lambda r: int(r["slot"]))
    file.write_text(json.dumps(document, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    #: ДОМ СТАВИТСЯ ГОТОВЫМ. Одна запись объекта — это только картинка;
    #: стены, нутро и вход живут в клетках, и без них герой ходит сквозь
    #: дом, а крыша не снимается. Обводим клетки штампом, снятым с
    #: канонных карт. Штампа нет (реквизит, дерево) — просто ставим.
    cells = 0
    if slot < 30:                       # номер постройки в клетке — 5 бит
        try:
            cells = _stamp_apply(folder, records[slot], slot)
        except (OSError, ValueError):
            cells = 0
    return True, str(file), {"record_slot": slot,
                             "count": len(records), "cells": cells}


#: БЕСТИАРИЙ. Справочник пород собирается из самого пака: скан юнитов
#: всех карт даёт связку «порода -> тело, имя, образец записи» (statы,
#: характеристики и навыки снимаются с реального юнита — добавленный
#: зверь получает честные числа, не выдуманные), палитры-масти — из
#: shared.json, превью — кадр stand с листа тварей.
_BESTIARY_CACHE: dict | None = None


#: ВОСЕМЬ ТЕЛ ЧЕЛОВЕКА — ЭТО ЧЕТЫРЕ НАРОДА НА ДВА ПОЛА, а не восемь
#: безымянных номеров. Установлено сведением тел с культурами деревень
#: (konung2/sounds.py VILLAGE_CULTURES, движок знает славян, викингов и
#: византийцев байтом +0x1B вожака):
#:     тело 0 — славяне 27 карт, тело 1 — славяне;
#:     тело 2 — викинги 35 карт, тело 3 — викинги;
#:     тело 4 — византийцы 9 карт, тело 5 — византийцы;
#:     тела 6 и 7 на деревенских картах не живут вовсе — это четвёртый
#:     народ, «Жёлтые собаки пустыни» (имена Ясин, Гафур, Гюльнар,
#:     Зейда), и культуры в записи поселения у него нет.
#: Пол читается по именам: чётные тела мужские (Слав, Крок, Повелитель,
#: Воин), нечётные женские (Светослава, Кримхильда, Прасковья, Адиль).
HUMAN_BODIES = {
    0: "Славяне · мужчина", 1: "Славяне · женщина",
    2: "Викинги · мужчина", 3: "Викинги · женщина",
    4: "Византийцы · мужчина", 5: "Византийцы · женщина",
    6: "Народ пустыни · мужчина", 7: "Народ пустыни · женщина",
}


#: ИМЯ ТВАРИ — ИЗ ТАБЛИЦЫ ПОРОД ИГРЫ (0x45FAE0, konung2.gamefile).
#: Печать имени (VA 0x43000C) берёт строку прямо по породе, но ТОЛЬКО
#: для 0x41…0x53; выше движок идёт общим путём «имя + прозвище», то есть
#: это ИМЕННЫЕ персонажи (Баба-Яга, Жар-Птица, Хозяин горы, Позвизд), а
#: не порода со своим названием. Каталог показывал их по имени первого
#: попавшегося жителя — отсюда строка «житель 813» (заглушка пустого
#: имени) вместо дракона.
#:
#: Облик у таких персонажей — обычное тело твари, поэтому подписываем их
#: по ТЕЛУ, размеченному глазами (зум спрайтов, 29.08.2026):
BEAST_BODIES = {
    0: "муравей", 2: "болотник", 7: "моховик",
    14: "жена", 15: "муж", 16: "волхв",
    18: "Баба-Яга · Королева Нежити", 22: "Жар-Птица",
    23: "Крылатый дракон", 24: "Позвизд",
}
_BREED_NAMES: list[str] | None = None


def _breed_names() -> list[str]:
    """Названия пород 0x41…0x53 из exe; при неудаче — пустой список."""
    global _BREED_NAMES
    if _BREED_NAMES is None:
        try:
            from konung2.gamefile import breed_names
            _BREED_NAMES = list(breed_names())
        except Exception:                      # exe нет или он чужой
            _BREED_NAMES = []
    return _BREED_NAMES


def _beast_name(breed: int, body: int, sample_name: str = "") -> str:
    """Как звать тварь в каталоге: таблица пород, иначе облик тела."""
    table = _breed_names()
    if breed <= 0x53 and breed < len(table) and table[breed]:
        return table[breed]
    look = BEAST_BODIES.get(body)
    if look in ("Баба-Яга · Королева Нежити", "Жар-Птица",
                "Крылатый дракон", "Позвизд"):
        return look
    if look:
        return f"Персонаж · {look}"
    #: неизвестное тело — честно номерами, а не чужим именем жителя
    return (f"Персонаж · тело {body}" if breed > 0x53
            else f"Порода 0x{breed:02x} · тело {body}")


def _body_set(common: dict, game_name: str, body: int, palette: int) -> dict:
    """Набор кадров тела: игра+форма+масть, откат на форму без игры.

    Тот же порядок, каким выбирает клиент (actor.js bodyKey) и
    `_unit_frame`. Пусто — такого тела в паке НЕТ: у канона, например,
    нет слоёв под тела 6 и 7 (народ пустыни живёт только во второй игре).
    """
    sets = (common.get("hero") or {}).get("body_layers") or {}
    return ((game_name and sets.get(f"{game_name}:{body}:{palette}"))
            or sets.get(f"{body}:{palette}") or sets.get(str(body)) or {})


def _beast_preview(bundles: dict, sheets: list, body: int,
                   coat: int) -> dict | None:
    """Кадр «стоит» твари данной масти — прямо с листа набора."""
    bundle = (bundles.get(str(body)) or {}).get(str(coat)) or {}
    stand_frames = bundle.get("stand") or []
    frames = (stand_frames[4] if len(stand_frames) > 4
              else (stand_frames[0] if stand_frames else []))
    if not frames:
        return None
    frame = frames[0]
    sheet = sheets[frame["sheet"]] if frame["sheet"] < len(sheets) else None
    if not sheet:
        return None
    return {
        "url": "/content/" + sheet["path"],
        "x": frame["x"], "y": frame["y"],
        "width": frame["width"], "height": frame["height"],
        # клиент режет кадр из листа фоном — без размеров листа вырез
        # не отмасштабировать
        "sheet_width": sheet["width"], "sheet_height": sheet["height"],
        # смещения нужны холсту: он ставит кадр от «ног»
        "offset_x": frame.get("offset_x", 0),
        "offset_y": frame.get("offset_y", 0),
    }


def editor_bestiary(content_root=None) -> tuple[bool, str, dict]:
    global _BESTIARY_CACHE
    root = Path(content_root or DEFAULT_CONTENT_ROOT)
    if _BESTIARY_CACHE is not None:
        return True, "из кэша", _BESTIARY_CACHE
    shared_path = root / "shared.json"
    if not shared_path.is_file():
        return False, "в паке нет shared.json", {}
    common = json.loads(shared_path.read_text(encoding="utf-8"))
    beasts = common.get("creatures") or {}
    bundles = beasts.get("sets") or {}
    sheets = beasts.get("sheets") or []
    breeds: dict[tuple, dict] = {}
    #: таблица вещей той карты, с которой снят образец: нужна превью
    #: человека, чтобы собрать надетое (ссылки вида instance:КЛАСС:…)
    sample_goods: dict[tuple, dict] = {}
    for map_rec in sorted((root / "maps").iterdir(),
                        key=lambda x: (len(x.name), x.name)):
        file = map_rec / "map.json"
        if not file.is_file():
            continue
        try:
            document = json.loads(file.read_text(encoding="utf-8"))
        except ValueError:
            continue
        for unit in document.get("units") or []:
            breed_id = int(unit.get("breed") or 0)
            body_num = int(unit.get("body") or 0)
            #: ЛЮДИ ТОЖЕ ЖИТЕЛИ, А ИХ ТУТ НЕ БЫЛО.
            #:
            #: Бит 0x40 у породы означает «имя берётся из таблицы пород»
            #: (gamefile.py:920) — то есть это ТВАРЬ. Отбор по нему
            #: выбрасывал из каталога всех людей: 532 юнита шести пород
            #: (0x00 обычный человек — 444 записи, 0x01…0x05 — породы
            #: именных персонажей) против 856 тварей. В списке
            #: оставались 23 строки, и «добавить НПС» в редакторе было
            #: физически невозможно: человека взять неоткуда.
            #:
            #: Причина отбора была не в замысле, а в превью: у твари
            #: кадр берётся прямо с листа, а человек рисуется послойно
            #: из тела и надетого, и такого кадра в наборах нет. Но
            #: собрать его есть чем — _unit_frame делает ровно это для
            #: жителей пака.
            #:
            #: КЛЮЧ У ЛЮДЕЙ — ПАРА «ПОРОДА И ТЕЛО». У твари тело одно на
            #: породу, а у человека тела 0…7 это РАЗНЫЕ люди: чётные
            #: мужские, нечётные женские, и сложение у них разное
            #: (0 славянин, 2 воин, 6 южанин…). Одной строкой «человек»
            #: их не выбрать.
            #: ПОРОДЫ 0x01…0x05 ПОКА НЕ ПРЕДЛАГАЕМ. Это породы именных
            #: персонажей (Бьорн Рауф, Ярун, Пересвет…), 88 записей на
            #: всю игру, и чем они отличаются от обычного человека в
            #: правилах — не разобрано. Ставить их наугад значит
            #: раздавать неизвестные свойства. Обычный человек (0x00) —
            #: это 444 записи, то есть подавляющее большинство жителей.
            human_flag = breed_id == 0
            if not human_flag and not breed_id & 0x40:
                continue
            #: ИГРА ЖИВЁТ У МАСТИ, А НЕ У ВИДА. Тела 6 и 7 (народ
            #: пустыни) есть только у «Продолжения легенды» — в каноне
            #: слоёв под них нет вовсе, и собранный канонным набором
            #: житель выходил цветным шумом. При этом делить сам вид по
            #: играм нельзя: список раздваивался бы («Славяне» канона и
            #: «Славяне» легенды). Вид один на тело, а каждая масть несёт
            #: свою игру — тем же ключом, каким рисует клиент (bodyKey).
            unit_game = str(unit.get("game") or "canon")
            #: КЛЮЧ ТВАРИ — ТОЖЕ ПАРА «ПОРОДА И ТЕЛО». Тварь ключевалась
            #: одной породой, а у 0x56 тел шесть: под одной строкой
            #: «Верховный волхв» прятались Баба-Яга, Жар-Птица, Хозяин
            #: горы и прочие — поставить их было нельзя вовсе.
            key_ = (breed_id, body_num)
            #: МАСТИ ЧЕЛОВЕКА — ИЗ ЖИВЫХ ЗАПИСЕЙ, А НЕ ИЗ ТАБЛИЦЫ ТВАРЕЙ.
            #: creatures.sets описывает окраски ТВАРЕЙ; у человека там
            #: пусто или случайный остаток, и превью выходило голым или
            #: не выходило вовсе. Берём то, во что люди этого тела
            #: одеты в самой игре.
            if human_flag:
                coat = [unit_game, int(unit.get("palette") or 0)]
                former = breeds.get(key_)
                if former:
                    if coat not in former["coats"]:
                        former["coats"].append(coat)
                    continue
            elif key_ in breeds:
                continue
            bundle = bundles.get(str(body_num)) or {}
            breeds[key_] = {
                "breed": breed_id, "body": body_num, "human": human_flag,
                #: масти человека парами «игра + номер»; у твари наборы
                #: общие для обеих игр, там хватает номера
                "coats": [[unit_game, int(unit.get("palette") or 0)]]
                if human_flag else [],
                #: ИМЯ ТВАРИ — ИЗ ТАБЛИЦЫ ПОРОД, а не от первого
                #: попавшегося жителя: та строка врала («житель 813»
                #: вместо дракона — это заглушка пустого имени).
                "name": (HUMAN_BODIES.get(body_num, f"Человек · тело {body_num}")
                         if human_flag
                         else _beast_name(breed_id, body_num,
                                          unit.get("name") or "")),
                #: и у человека, и у именного персонажа имя берётся из
                #: exe и к породе не привязано — показываем, кто ТАК
                #: выглядит в самой игре
                #: «житель 813» — не имя, а заглушка пустого имени (у
                #: твари выше таблицы пород его в записи просто нет);
                #: показывать её как «кто ТАК выглядит» бессмысленно
                "looks_like": (unit.get("name")
                               if ((human_flag or breed_id > 0x53)
                                   and not re.fullmatch(
                                       r"житель \d+", unit.get("name") or ""))
                               else None),
                "palettes": ([] if human_flag
                             else sorted(int(p) for p in bundle)),
                "sample": {k_: unit.get(k_) for k_ in (
                    "level", "money", "speed", "venom", "stats",
                    "characteristics", "skills", "face")},
                #: снаряжение образца нужно превью человека: без него
                #: выйдет голое тело, а в игре такого жителя не бывает
                "equipment": unit.get("equipment") if human_flag else None,
            }
            if human_flag:
                sample_goods[key_] = document.get("items") or {}
    #: КАДР НА КАЖДУЮ МАСТЬ. Превью было одно — по первой масти, — и им
    #: же холст рисовал уже поставленного жителя: какую масть ни возьми,
    #: на карте стоял первый цвет, иногда диковинный (зелёная кожа,
    #: малиновая рубаха). Человека собираем послойно — тем же способом,
    #: каким его рисует игра и жители пака (_unit_frame); кадра «человек»
    #: на листе тварей нет и быть не может. `preview` остаётся первым
    #: ради совместимости.
    for key_, record in breeds.items():
        shots = []
        pairs = (sorted(record.get("coats") or [])
                 if record.get("human")
                 else [["canon", coat] for coat in record["palettes"]])
        for coat_game, coat in pairs:
            if record.get("human"):
                #: МАСТЬ ПРЕДЛАГАЕМ ТОЛЬКО ТУ, ЧТО ЕСТЬ ЧЕМ НАРИСОВАТЬ.
                #: Житель, поставленный редактором, уезжает в пак и
                #: возвращается в этот же каталог — и если кадров его тела
                #: в паке нет (канонных слоёв под народ пустыни не
                #: существует), каталог предлагал бы сам себе цветной шум.
                #: `_unit_frame` в таком случае молча падает на общий набор
                #: палитры, поэтому спрашиваем набор напрямую.
                if record["body"] and not _body_set(common, coat_game,
                                                    record["body"], coat):
                    continue
                #: ТЕЛО ПОКАЗЫВАЕМ ГОЛЫМ. Прежде превью собиралось со
                #: снаряжением ОБРАЗЦА — а образцы одеты, до пяти слотов:
                #: в каталоге стояли восемь фигур в доспехах и с оружием,
                #: хотя поставленный житель приходит без единой вещи.
                #: Одевают его теперь в инспекторе.
                shot = _unit_frame(common, record["breed"], record["body"],
                                   coat, 6, None, sample_goods.get(key_),
                                   coat_game)
            else:
                shot = _beast_preview(bundles, sheets, record["body"], coat)
            if shot:
                shots.append({"palette": coat, "game": coat_game,
                              "frame": shot})
        if shots:
            record["previews"] = shots
            record["preview"] = shots[0]["frame"]
            record["palettes"] = [shot["palette"] for shot in shots]
        record.pop("coats", None)
    #: ОДНО ИМЯ НА ДВА ОБЛИКА — НЕ ИМЯ. Таблица пород даёт одну строку на
    #: породу, а тел у породы бывает несколько (у 0x47 к канонному лешему
    #: добавляется тело, поставленное редактором): две строки «Леший»
    #: подряд неразличимы. Дописываем номер тела ровно там, где двоится.
    #: Номер тела дописываем ТОЛЬКО там, где имя иначе повторяется: у
    #: 0x56 обликов шесть, но зовутся они по-разному (Баба-Яга,
    #: Жар-Птица, волхв) — там номер был бы шумом.
    times: dict[str, int] = {}
    for record in breeds.values():
        if not record.get("human"):
            times[record["name"]] = times.get(record["name"], 0) + 1
    for record in breeds.values():
        if not record.get("human") and times.get(record["name"], 0) > 1:
            record["name"] = f"{record['name']} · тело {record['body']}"
    #: НЕЧЕМ НАРИСОВАТЬ — НЕ ПРЕДЛАГАЕМ. Вид без единой годной масти
    #: означает, что кадров его тела в паке нет; строка каталога для него
    #: обещала бы жителя, которого нельзя ни увидеть, ни собрать.
    #: люди впереди тварей: «добавить НПС» — это в первую очередь
    #: человек, и искать его в хвосте списка из тридцати строк неверно
    row_ = sorted((z_ for z_ in breeds.values() if z_.get("previews")),
                 key=lambda x: (not x.get("human"), x["breed"], x["body"]))
    for record in row_:
        record.pop("equipment", None)      # служебное, наружу не нужно
    _BESTIARY_CACHE = {"breeds": row_}
    return True, "собрано из пака", _BESTIARY_CACHE


#: ВОДА-ПОДЛОЖКА. Блок .KN2 +0x3D184 (в kn2.py исторически звался
#: T_LIGHT) — карта 16 рядов x 32 столбца, байт на клетку 256x256 px:
#: ненулевой — здесь сквозь землю видна анимированная подложка (вода).
#: «Water N of 512» старого редактора — счёт ненулевых байтов. Тип
#: анимации у КАРТЫ ЦЕЛИКОМ: загрузчик (VA 0x43DF48) собирает OR всех
#: 512 байтов, и бит 0x80 выбирает стоячую волну Lake (VA 0x43F46E)
#: против течения Stream (VA 0x43F4D9); редактор потому писал 0x80 во
#: все клетки Lake-карт и 0x40 — Stream-карт. Номер тайла подложки —
#: light_flag. В map.json проекта блок лежит разреженно: records =
#: [{slot: ряд, raw: hex64}] только для рядов, отличных от _default
#: (а дефолт у RecordTable — «самое частое», он бывает и не нулевым).
WATER_ROWS, WATER_COLS = 16, 32
WATER_LAKE, WATER_STREAM = 0x80, 0x40


def _map_game(document: dict) -> str:
    """«canon» или «legend» — по паспорту происхождения карты проекта."""
    from konung2 import donor
    origin = (document.get("origin") or {}).get("game")
    return "legend" if origin == donor.LEGEND_NAME else "canon"


def _water_read(document: dict) -> list[bytearray]:
    block = document.get("light") or {}
    empty_val = block.get("_default") or ("0" * (WATER_COLS * 2))
    rows = [bytearray.fromhex(empty_val) for _ in range(WATER_ROWS)]
    for record in block.get("records") or []:
        slot = int(record.get("slot", -1))
        if 0 <= slot < WATER_ROWS:
            rows[slot] = bytearray.fromhex(record["raw"])
    return rows


def _water_write(document: dict, rows: list[bytearray]) -> None:
    block = document.setdefault("light", {})
    block.setdefault("_default", "0" * (WATER_COLS * 2))
    block.setdefault("_count", WATER_ROWS)
    block.setdefault("_size", WATER_COLS)
    empty_val = bytes.fromhex(block["_default"])
    block["records"] = [{"slot": slot, "raw": row_.hex()}
                       for slot, row_ in enumerate(rows)
                       if bytes(row_) != empty_val]


def editor_water_save(number: int, patch: dict) -> tuple[bool, str, dict]:
    """Правка воды: {row, col, value} — value 0 осушает, иное заливает
    канонным байтом типа карты; {stream: bool} — переписать тип ВСЕХ
    клеток (0x40 течёт / 0x80 стоит); {tile: N} — номер тайла подложки.
    Пустой патч — прочитать состояние."""
    folder = project_map_dir(number)
    if folder is None:
        return False, f"нет проектной карты с номером {number}", {}
    file = folder / "map.json"
    if not file.is_file():
        return False, "у карты нет map.json", {}
    document = json.loads(file.read_text(encoding="utf-8"))
    rows = _water_read(document)

    def map_type() -> int:
        common = 0
        for row_ in rows:
            for byte_val in row_:
                common |= byte_val
        #: пустая таблица -> Lake: родной редактор при OR == 0 ставит кисть
        #: 0x80 (FUN_00419EC0), у нас же первый мазок на сухой карте лился
        #: Stream'ом
        if common == 0:
            return WATER_LAKE
        return WATER_LAKE if common & 0x80 else WATER_STREAM

    was_changed = False
    #: ПАЧКА КЛЕТОК ОДНИМ ТЕЛОМ — как у земли (editor_ground_save).
    #: Клик по клетке уходил отдельным запросом, и КАЖДЫЙ ложился
    #: отдельной записью в журнал отмены — общий на весь сервер и
    #: глубиной 30. Одно озеро вытесняло оттуда всю прежнюю работу.
    if isinstance(patch.get("cells"), list):
        type_num = map_type()
        for stroke in patch["cells"]:
            row, col = int(stroke.get("row", -1)), int(stroke.get("col", -1))
            if not (0 <= row < WATER_ROWS and 0 <= col < WATER_COLS):
                return False, f"клетка воды ({row},{col}) вне сетки 16x32", {}
            rows[row][col] = type_num if stroke.get("value") else 0
        was_changed = bool(patch["cells"])
    elif "value" in patch:
        row, col = int(patch.get("row", -1)), int(patch.get("col", -1))
        if not (0 <= row < WATER_ROWS and 0 <= col < WATER_COLS):
            return False, f"клетка воды ({row},{col}) вне сетки 16x32", {}
        rows[row][col] = map_type() if patch["value"] else 0
        was_changed = True
    if "stream" in patch:
        byte_val = WATER_STREAM if patch["stream"] else WATER_LAKE
        for row_ in rows:
            for col_i in range(WATER_COLS):
                if row_[col_i]:
                    row_[col_i] = byte_val
        was_changed = True
    if "tile" in patch:
        document["light_flag"] = int(patch["tile"]) & 0xFFFFFFFF
        was_changed = True
    if was_changed:
        _water_write(document, rows)
        file.write_text(json.dumps(document, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    tally = sum(1 for row_ in rows for byte_val in row_ if byte_val)
    reply = {"tile": int(document.get("light_flag") or 0),
             "stream": map_type() == WATER_STREAM,
             "count": tally, "limit": WATER_ROWS * WATER_COLS}
    if "row" in patch:
        r, c = int(patch["row"]), int(patch["col"])
        if 0 <= r < WATER_ROWS and 0 <= c < WATER_COLS:
            reply["value"] = rows[r][c]
    return True, str(file), reply


#: ОВЕРЛЕИ ЛАНДШАФТА (режим SPRITE старого редактора). Таблица .KN2
#: +0x31600 — 1000 записей по 12 байт: слот GRAPH.RES, палитра и
#: абсолютная экранная точка; движок рисует их в порядке слотов сразу
#: после земли (VA 0x42543D) — берега, кувшинки, камыши. В map.json
#: проекта — блок `dynamic` (sparse-records, пустая запись 12xFF).
#: Палитру записи сборка всё равно подменяет палитрой самого GRAPH
#: (VA 0x43E4E9), поэтому панель её не правит.
SPRITE_SLOTS = 1000


def _pack_pile(number: int, pile_id: str,
              content_root=None) -> dict | None:
    """Куча СОБРАННОЙ карты по id — основа, поверх которой ляжет патч."""
    file = (Path(content_root or DEFAULT_CONTENT_ROOT) / "maps"
            / str(number) / "map.json")
    if not file.is_file():
        return None
    try:
        document = json.loads(file.read_text(encoding="utf-8"))
    except ValueError:
        return None
    for pile in document.get("loot") or []:
        if pile.get("id") == pile_id:
            return pile
    return None


def editor_loot_item(number: int, payload: dict,
                     content_root=None) -> tuple[bool, str, dict]:
    """Положить вещь в кучу или вынуть её оттуда.

    ССЫЛКА ЭКЗЕМПЛЯРА, А НЕ КЛАССА. В куче лежат не «виды» вещей, а
    записи: ``instance:<класс>:<источник>:<хвост>`` (см. actor.js,
    actorNewItemRef). Хвост различает записи между собой — иначе два
    одинаковых меча в одной куче считались бы одной вещью. Класс — это
    index записи каталога, он же номер в ключе ``class:N``.

    ПОЛНЫЙ СПИСОК, А НЕ ПРИБАВКА. Сборка пишет патч поверх кучи целиком
    (``pile[key] = value``, builder._editor_loot_apply), поэтому в патч
    уходит ВЕСЬ новый список. Для кучи из пака основу берём из собранной
    карты, для своей — из scenario.json: иначе первая же добавка стёрла
    бы то, что в куче уже лежало.

    Пустой словарь в ``details`` — это СВЕЖАЯ вещь: клиент берёт
    прочность из класса, когда своей нет (``actor.wear[ref] ??
    item.durability``). Для боеприпаса кладём ``count`` — им игра
    считает заряды.
    """
    pile_id = payload.get("id")
    if not isinstance(pile_id, str) or not pile_id:
        return False, "не сказано, в какую кучу класть (id)", {}
    folder = project_map_dir(number)
    if folder is None:
        return False, f"нет проектной карты с номером {number}", {}
    file = folder / "scenario.json"
    document = (json.loads(file.read_text(encoding="utf-8"))
                if file.is_file() else {})
    #: откуда брать нынешнее содержимое: своя куча живёт целиком в
    #: scenario.json, чужая — в паке, а в scenario.json от неё только патч
    own_one = pile_id.startswith("pile_new_")
    if own_one:
        record = next((z_ for z_ in document.get("editor_loot_add") or []
                       if z_.get("id") == pile_id), None)
        if record is None:
            return False, f"кучи {pile_id} нет среди своих", {}
        goods = list(record.get("items") or [])
        details = list(record.get("details") or [])
    else:
        basis = _pack_pile(number, pile_id, content_root)
        if basis is None:
            return False, (f"кучи {pile_id} нет в собранной карте — "
                           f"соберите карту (Build) и повторите"), {}
        patch_ = (document.get("editor_loot") or {}).get(pile_id) or {}
        goods = list(patch_.get("items", basis.get("items") or []))
        details = list(patch_.get("details", basis.get("details") or []))
    #: details идут ПАРАЛЛЕЛЬНО items, и разъехавшись однажды они
    #: перепутают прочность и заряды у всех вещей ниже по списку
    while len(details) < len(goods):
        details.append({})
    del details[len(goods):]

    remove_it = payload.get("remove_item")
    if remove_it is not None:
        at = int(remove_it)
        if not 0 <= at < len(goods):
            return False, f"в куче нет вещи номер {at}", {}
        goods.pop(at)
        details.pop(at)
        msg = f"вещь вынута, осталось {len(goods)}"
    else:
        addition = payload.get("add_item") or {}
        ref = str(addition.get("ref") or "")
        matched = re.match(r"^(?:class|instance):(\d+)", ref)
        if not matched:
            return False, ("вещь задают ссылкой вида class:N из каталога "
                           "(/catalog/items)"), {}
        cls = int(matched.group(1))
        okay, _, catalog = editor_items_page(content_root)
        names = {z_["ref"]: z_ for z_ in (catalog.get("items") or [])}
        item_record = names.get(f"class:{cls}")
        if okay and item_record is None:
            return False, f"вещи class:{cls} нет в каталоге", {}
        if len(goods) >= PILE_ITEMS_LIMIT:
            return False, (f"в куче уже {PILE_ITEMS_LIMIT} вещей — "
                           f"столько редактор и кладёт (у авторов "
                           f"максимум шесть)"), {}
        #: ХВОСТ ОБЯЗАН БЫТЬ УНИКАЛЬНЫМ, А НЕ ПРОСТО РАЗНЫМ. Брать его
        #: от длины списка нельзя: вынул первую вещь, положил новую — и
        #: номер повторился, две записи слились бы в одну. Времени в
        #: сборке нет (пак детерминирован), поэтому берём наибольший из
        #: уже занятых номеров и прибавляем единицу.
        taken = [int(m_.group(1)) for m_ in
                   (re.search(rf"^instance:\d+:editor:{re.escape(pile_id)}"
                              rf":(\d+)$", str(s_)) for s_ in goods) if m_]
        tail = f"{pile_id}:{max(taken, default=-1) + 1}"
        goods.append(f"instance:{cls}:editor:{tail}")
        state_: dict = {}
        num_val = addition.get("count")
        if num_val is not None:
            state_["count"] = max(1, int(num_val))
        details.append(state_)
        msg = (f"{(item_record or {}).get('name', ref)} → в кучу, "
                 f"теперь вещей {len(goods)}")
    ok_, reply = editor_save(number, "loot", pile_id,
                            {"items": goods, "details": details})
    if not ok_:
        return False, reply, {}
    return True, msg, {"items": goods, "details": details}


#: СКОЛЬКО ЯЧЕЕК В ПОЯСЕ. Сорок две (konung2/interf.py BELT: окно
#: показывает двенадцать, номер первой видимой лежит в 0x849714, и
#: движок прокручивает пояс сам, когда предмет попадает за край).
BELT_CELLS = 42


def editor_unit_belt(number: int, payload: dict,
                     content_root=None) -> tuple[bool, str, dict]:
    """Положить вещь в пояс жителя или вынуть её: {id, add_item|remove_item}.

    ПОЯС — ЭТО `bag`, а не отдельная таблица: сорок две ячейки, из них
    двенадцать видно разом. Ссылки в нём такие же, как в куче
    (`instance:<класс>:<источник>:<хвост>`), и `bag_details` идут
    параллельно списку — прочность, заряды, слово чар.

    Правится ТОЛЬКО житель draft-слоя: у жителя мира пояс лежит в
    байтах записи (0x?? в GAME.<мир>), и писать его надо ручкой мира,
    а не слоем карты. Молча подменять одно другим нельзя.
    """
    ident = payload.get("id")
    if not isinstance(ident, str) or not ident.startswith("unit_new_"):
        return False, ("пояс правится у жителя, поставленного редактором; "
                       "у жителя мира он лежит в исходниках мира"), {}
    folder = project_map_dir(number)
    if folder is None:
        return False, f"нет проектной карты с номером {number}", {}
    file = folder / "scenario.json"
    document = (json.loads(file.read_text(encoding="utf-8"))
                if file.is_file() else {})
    record = next((z_ for z_ in document.get("editor_units_add") or []
                   if z_.get("id") == ident), None)
    if record is None:
        return False, f"жителя {ident} нет среди своих", {}
    belt = list(record.get("bag") or [])
    details = list(record.get("bag_details") or [])
    #: details идут ПАРАЛЛЕЛЬНО поясу: разъехавшись однажды, они
    #: перепутают заряды и прочность у всех вещей ниже по списку
    while len(details) < len(belt):
        details.append({})
    del details[len(belt):]

    remove_it = payload.get("remove_item")
    if remove_it is not None:
        at = int(remove_it)
        if not 0 <= at < len(belt):
            return False, f"в поясе нет вещи номер {at}", {}
        belt.pop(at)
        details.pop(at)
        msg = f"вещь снята с пояса, осталось {len(belt)}"
    else:
        addition = payload.get("add_item") or {}
        ref = str(addition.get("ref") or "")
        matched = re.match(r"^(?:class|instance):(\d+)", ref)
        if not matched:
            return False, ("вещь задают ссылкой вида class:N из каталога "
                           "(/catalog/items)"), {}
        cls = int(matched.group(1))
        okay, _, catalog = editor_items_page(content_root)
        names = {z_["ref"]: z_ for z_ in (catalog.get("items") or [])}
        item_record = names.get(f"class:{cls}")
        if okay and item_record is None:
            return False, f"вещи class:{cls} нет в каталоге", {}
        if len(belt) >= BELT_CELLS:
            return False, (f"пояс полон: {BELT_CELLS} ячеек — столько же, "
                           f"сколько у игры"), {}
        #: хвост уникален по наибольшему занятому, а не по длине списка:
        #: снял первую вещь, положил новую — и номер бы повторился
        taken = [int(m_.group(1)) for m_ in
                   (re.search(rf"^instance:\d+:editor:{re.escape(ident)}"
                              rf":(\d+)$", str(s_)) for s_ in belt) if m_]
        belt.append(f"instance:{cls}:editor:{ident}:"
                    f"{max(taken, default=-1) + 1}")
        state_: dict = {}
        num_val = addition.get("count")
        if num_val is not None:
            state_["count"] = max(1, int(num_val))
        details.append(state_)
        msg = (f"{(item_record or {}).get('name', ref)} → в пояс, "
                 f"теперь вещей {len(belt)}")
    record["bag"] = belt
    record["bag_details"] = details
    file.write_text(json.dumps(document, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return True, msg, {"bag": belt, "bag_details": details}


def editor_sprite_save(number: int, patch: dict) -> tuple[bool, str, dict]:
    """Правка оверлея: {slot, x, y} — перенос; {slot, id} — смена
    спрайта GRAPH; {slot, removed} — очистить запись; {add: {id, x, y}}
    — новая запись в первый свободный слот. Пустой патч — список."""
    from konung2.binrec import new_record
    folder = project_map_dir(number)
    if folder is None:
        return False, f"нет проектной карты с номером {number}", {}
    file = folder / "map.json"
    if not file.is_file():
        return False, "у карты нет map.json", {}
    document = json.loads(file.read_text(encoding="utf-8"))
    block = document.setdefault("dynamic", {
        "_default": "ff" * 12, "_count": SPRITE_SLOTS, "_size": 12,
        "records": []})
    records = block.setdefault("records", [])
    was_changed = False
    reply: dict = {}
    if "add" in patch:
        fresh_val = patch["add"] or {}
        # ЗА ПОСЛЕДНИМ занятым, не в дырку: движок читает таблицу до
        # первого пустого слота (сентинел 0x80000000 в 0x43DF48) — запись
        # в дырке оставила бы хвост списка невидимым оригиналу.
        taken = [int(r["slot"]) for r in records]
        slot = (max(taken) + 1) if taken else 0
        if slot >= int(block.get("_count") or SPRITE_SLOTS):
            return False, "все слоты оверлеев заняты", {}
        records.append(new_record(
            block, slot,
            id=int(fresh_val.get("id", 0)) & 0xFFFF,
            kind=int(fresh_val.get("kind", 0)) & 0xFFFF,
            pixel_x=int(fresh_val.get("x", 0)) & 0xFFFF,
            pixel_y=int(fresh_val.get("y", 0)) & 0xFFFF))
        records.sort(key=lambda r: int(r["slot"]))
        reply["slot"] = slot
        was_changed = True
    elif "slot" in patch:
        slot = int(patch["slot"])
        record = next((r for r in records if int(r["slot"]) == slot), None)
        if record is None:
            return False, f"оверлея в слоте {slot} нет", {}
        if patch.get("removed"):
            # С КОМПАКТАЦИЕЙ: движок читает таблицу до первого пустого
            # слота — дырка от удаления спрятала бы хвост. Записи после
            # удалённой съезжают на слот вниз.
            records.remove(record)
            for tail in records:
                if int(tail["slot"]) > slot:
                    tail["slot"] = int(tail["slot"]) - 1
        else:
            # поля кладутся ПОВЕРХ raw при сборке (binrec.pack), сам
            # raw не трогаем — неизвестные байты записи целы
            if "x" in patch:
                record["pixel_x"] = int(patch["x"]) & 0xFFFF
            if "y" in patch:
                record["pixel_y"] = int(patch["y"]) & 0xFFFF
            if "id" in patch:
                record["id"] = int(patch["id"]) & 0xFFFF
            reply["slot"] = slot
        was_changed = True
    if was_changed:
        file.write_text(json.dumps(document, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    visible_ones = [r for r in records if int(r.get("id", 0xFFFF)) != 0xFFFF]
    reply["count"] = len(visible_ones)
    if not patch:
        reply["records"] = [{"slot": int(r["slot"]), "id": int(r["id"]),
                             "x": int(r["pixel_x"]), "y": int(r["pixel_y"])}
                            for r in visible_ones]
    return True, str(file), reply


#: НОВЫЙ ВРАЖИЙ ОТРЯД. Отряды приходят из GAME-файлов, в .KN2 их нет —
#: добавление живёт слоем editor_warbands_add в scenario.json; сборка
#: подмешивает записи к отрядам ВСЕХ миров. Сторона нового отряда — по
#: свободному номеру (двести записей движка, 0x71E56C).
#: Что редактору можно менять у отряда. Зеркало builder.EDITOR_WARBAND_*:
#: если списки разойдутся, правка молча не доедет до пака.
#: `side` сюда не входит намеренно — это ключ записи И номер стороны его
#: бойцов (gamefile.map_parties: «сторона юнита равна НОМЕРУ его
#: отряда»), сменив его, мы оторвали бы отряд от собственных юнитов.
BAND_FIELDS = frozenset({
    "war_flags", "on_player", "on_parties", "on_special",
    "only_if_fighting", "can_fight", "enemy_side", "fighting", "player",
})
BAND_ZONES = frozenset({"zone", "roam"})


def editor_warband_patch(number: int, payload: dict) -> tuple[bool, str, dict]:
    """Править существующий отряд: {side, patch}.

    ДВА АДРЕСА У ОДНОЙ ПРАВКИ. Отряд, заведённый редактором, живёт
    целиком в `editor_warbands_add` — его запись и правим на месте.
    Отряд ИГРЫ в проекте не лежит вовсе: он читается из GAME.<мир> при
    сборке, и трогать его там нельзя (канон). Для него правка ложится
    отдельным слоем `editor_warbands` (ключ — номер стороны), а сборка
    кладёт слой поверх отрядов КАЖДОГО мира.

    Зоны сливаются по ключам, а не заменяются целиком: правка «сдвинуть
    верхнюю границу» не должна съедать остальные три числа.
    """
    side_num = payload.get("side")
    if side_num is None:
        return False, "не сказано, какой отряд править (side)", {}
    side_num = int(side_num)
    patch_ = payload.get("patch")
    if not isinstance(patch_, dict) or not patch_:
        return False, "пустой патч", {}
    fields, surplus = {}, []
    for name_, value in patch_.items():
        if name_ in BAND_FIELDS:
            fields[name_] = value
        elif name_ in BAND_ZONES and isinstance(value, dict):
            fields[name_] = value
        else:
            surplus.append(name_)
    if surplus:
        return False, (f"эти поля отряда редактор не правит: "
                       f"{', '.join(sorted(surplus))}"), {}
    folder = project_map_dir(number)
    if folder is None:
        return False, f"нет проектной карты с номером {number}", {}
    file = folder / "scenario.json"
    document = (json.loads(file.read_text(encoding="utf-8"))
                if file.is_file() else {})
    own = next((z_ for z_ in document.get("editor_warbands_add") or []
                 if int(z_.get("side", -1)) == side_num), None)
    if own is not None:
        target, dest = own, "свой отряд"
    else:
        layer_id = document.setdefault("editor_warbands", {})
        target, dest = layer_id.setdefault(str(side_num), {}), "отряд игры"
    for name_, value in fields.items():
        if name_ in BAND_ZONES:
            nest = target.setdefault(name_, {})
            if isinstance(nest, dict):
                nest.update(value)
            else:
                target[name_] = dict(value)
        else:
            target[name_] = value
    _band_war_sync(target, fields)
    file.write_text(json.dumps(document, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return True, f"отряд {side_num} ({dest}) поправлен", {"side": side_num}


#: ВРАЖДА ЛЕЖИТ В ДВУХ ВИДАХ, А ФАКТ ОДИН. У движка это ОДИН байт +0x1F
#: (konung2/gamefile.py: WAR_ON_PLAYER=0x01, WAR_ON_PARTIES=0x04,
#: WAR_ONLY_IF_FIGHTING=0x08, WAR_ON_SPECIAL=0x80), а наружу он разобран
#: галочками. Патч ставил ровно то, что прислали, и виды разъезжались:
#: снятая галочка «нападает на игрока» оставляла war_flags=1 — наш
#: клиент считал отряд мирным (units.js смотрит on_player), а вывоз в
#: формат игры пишет БАЙТ (konung2/worlds.py:154), то есть В САМОЙ ИГРЕ
#: отряд остался бы враждебным. Держим оба вида в согласии в одном
#: месте: пришёл байт — пересчитываем галочки, пришла галочка — правим
#: бит.
_WAR_BITS = {"on_player": 0x01, "on_parties": 0x04,
             "only_if_fighting": 0x08, "on_special": 0x80}


def _band_war_sync(target: dict, fields: dict) -> None:
    if "war_flags" in fields:
        war = int(target.get("war_flags") or 0) & 0xFF
        for name_, bit in _WAR_BITS.items():
            target[name_] = bool(war & bit)
        target["can_fight"] = bool(war & 0x4F)
        return
    touched = [name_ for name_ in _WAR_BITS if name_ in fields]
    if not touched:
        return
    war = int(target.get("war_flags") or 0) & 0xFF
    for name_ in touched:
        bit = _WAR_BITS[name_]
        war = (war | bit) if target.get(name_) else (war & ~bit)
    target["war_flags"] = war
    target["can_fight"] = bool(war & 0x4F)


def editor_warband_add(number: int, patch: dict) -> tuple[bool, str, dict]:
    """Добавить отряд: {side?, row, col, hostile?} — зона вокруг клетки.

    hostile=false — МИРНЫЙ отряд (жители): без боевых бит (+0x1F = 0 —
    маска 0x4F пуста, бой не объявляется вовсе) и с битом keep_cells —
    жители стоят там, где поставлены, а не рассыпаются по зоне.
    """
    folder = project_map_dir(number)
    if folder is None:
        return False, f"нет проектной карты с номером {number}", {}
    file = folder / "scenario.json"
    document = (json.loads(file.read_text(encoding="utf-8"))
                if file.is_file() else {})
    listing = document.setdefault("editor_warbands_add", [])
    taken = {int(z_.get("side", -1)) for z_ in listing}
    side_num = int(patch.get("side") or 0)
    #: ПОДСЕЛИТЬ, А НЕ ПЛОДИТЬ. Каждый клик по холсту заводил НОВЫЙ отряд:
    #: пятнадцать сторон редактора (185…199) кончались на шестнадцатом
    #: жителе, и дальше расстановка молча ломалась — «юниты не
    #: устанавливаются». Отряд заводится один раз, а следующие бойцы
    #: подселяются в него же; новый начинается по явной просьбе (кнопка
    #: «отряд» шлёт fresh).
    if not side_num and not patch.get("fresh"):
        wanted = bool(patch.get("hostile", True))
        mine = [z_ for z_ in listing
                if bool(z_.get("on_player")) == wanted]
        if mine:
            return True, str(file), {"warband": mine[-1], "reused": True}
    if not side_num:
        #: ПОЛОСА РЕДАКТОРА — 185…199, И ЭТО ЗАМЕРЕНО. Сторона
        #: индексирует таблицу отрядов мира, то есть она ОБЩАЯ на мир, а
        #: не на карту: столкнувшись с чужой, отряд получил бы чужих
        #: бойцов. Замер по всем 141 карте пака: игра занимает 166 сторон
        #: и НИ ОДНОЙ в 185…199 (190 и 191 там — наши же черновые с
        #: карты 63). Прежде брали 190…199 — десять штук, и они
        #: кончились на первой же живой карте.
        side_num = next((s_ for s_ in range(185, 200) if s_ not in taken), 0)
        if not side_num:
            #: ПОЛОСА КОНЧИЛАСЬ — ЗАБИРАЕМ ПУСТОЙ ОТРЯД. Отряд заводится
            #: вместе с первым бойцом, а при удалении бойцов остаётся:
            #: каждая проба съедала сторону навсегда. Переиспользуем
            #: ТОЛЬКО когда свободных нет — иначе два отряда подряд
            #: завести было бы нельзя, второй забирал бы первый, ещё
            #: пустой.
            sides_with_fighters = {int(u_.get("side", -1))
                        for u_ in document.get("editor_units_add") or []}
            vacant = next((s_ for s_ in sorted(taken) if s_ not in sides_with_fighters),
                          None)
            if vacant is None:
                return False, ("свободных сторон для новых отрядов не "
                               "осталось: редактор берёт 185…199, и все "
                               "пятнадцать заняты бойцами. Уберите "
                               "ненужный отряд на вкладке «Отряды»"), {}
            side_num = vacant
            listing[:] = [z_ for z_ in listing
                         if int(z_.get("side", -1)) != vacant]
            taken.discard(vacant)
    if not 0 < side_num < 200:
        return False, f"сторона {side_num} вне 1-199", {}
    if side_num in taken:
        return False, f"сторона {side_num} уже добавлена", {}
    row_, col_i = int(patch.get("row") or 0), int(patch.get("col") or 0)
    hostile_flag = patch.get("hostile", True)
    record = {
        "side": side_num, "player": False, "can_fight": True,
        "fighting": False, "enemy_side": 0,
        # бит 0x01: нападать на игрока; бит 0x04 зоны: на отряд можно
        # нападать (байты +0x1F и +0x1E записи движка); 0x10 keep_cells
        "on_player": bool(hostile_flag), "on_parties": False, "on_special": False,
        "only_if_fighting": False, "war_flags": 0x01 if hostile_flag else 0x00,
        "count": 0, "first_unit": 0,
        "roam": {"row_from": 0, "row_to": 0, "col_from": 0, "col_to": 0},
        "zone": {"row_from": max(0, row_ - 20), "row_to": min(255, row_ + 20),
                 "col_from": max(0, col_i - 20), "col_to": min(159, col_i + 20),
                 "flags": 0x04 if hostile_flag else 0x14,
                 "keep_cells": not hostile_flag, "tries": 100},
    }
    listing.append(record)
    file.write_text(json.dumps(document, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return True, str(file), {"warband": record}


#: Рабочее место компилятора квестов — посылка сообщества: исходники
#: .QST, словарь _DEFINES.QST и Win32-компилятор M_QUEST.exe (работает
#: на Win11 из коробки; рецепт снят 24.08 и закреплён живым тестом —
#: собранный им QUESTS.RES побайтово равен перекомпиляции 2021 года).
QUESTS_DIR = (REPOSITORY_ROOT / "project" / "community" / "k2_tools"
              / "qcompiler" / "KONUNG2" / "QUESTS")
QUESTS_COMPILER = QUESTS_DIR.parent / "RESOURCE" / "M_QUEST.exe"


def editor_quests_compile() -> tuple[bool, str]:
    """Прогнать авторский компилятор по konung2.qst — как его батник:
    из каталога QUESTS, со словарём и логом. Возвращает статистику.

    ЧЕСТНОЕ ОГРАНИЧЕНИЕ: пак читает QUESTS.RES из каталога игры
    (profile.file), а не отсюда — собранный файл модер доносит туда
    осознанным шагом; ручка лишь заменяет DOS-эпоху компиляции.
    """
    if not QUESTS_COMPILER.is_file():
        return False, "нет M_QUEST.exe (посылка k2_tools не на месте)"
    done_flag = subprocess.run(
        [str(QUESTS_COMPILER), "konung2.qst", "-d_DEFINES.QST", "-l"],
        cwd=str(QUESTS_DIR), capture_output=True, text=True,
        encoding="cp866", errors="replace", stdin=subprocess.DEVNULL,
        timeout=120)
    tail = (done_flag.stdout or "").strip().splitlines()[-6:]
    if done_flag.returncode != 0 or "Error" in (done_flag.stdout or ""):
        return False, "; ".join(tail) or f"код {done_flag.returncode}"
    return True, "; ".join(tail)


def editor_unit_save(number: int, unit_id: str,
                     patch: dict) -> tuple[bool, str]:
    """Старое имя ручки юнитов — тонкая обёртка над общей."""
    return editor_save(number, "unit", unit_id, patch)


#: Сетка проекта: 256 строк по 160 клеток «LO:HI» (hex) — сериализация
#: сетки .KN2 (konung2/kn2.py). Ландшафт правится ПРЯМО здесь: grid.txt
#: и есть источник, отдельный слой завёл бы ему второго хозяина.
GRID_ROWS, GRID_COLS = 256, 160
#: ПОЛНАЯ КАРТА БИТ КЛЕТКИ (дизасм 24.08; слово u32 = LO:HI grid.txt,
#: кисть признаков старого редактора DAT_00640AEC пишет их OR'ом):
#:   LO 0-11  0xFFF   NoWay: 0 свободна / 0xFFF глушь (VA 0x4414A7);
#:                    в рантайме здесь же метка занявшего юнита
#:   LO 12    0x1000  клетка выхода с карты (курсор перехода, 0x428B88;
#:                    ставится зоной выхода, не кнопкой кисти)
#:   LO 13    0x2000  РАНТАЙМ «в клетке куча» (0x423360) — не признак
#:   LO 14    0x4000  NoFly: глушит стрелы (0x41FDD0, 0x414AF8)
#:   LO 15    0x8000  Transparency: юнит с клетки рисуется ПОВЕРХ,
#:                    отложенным списком (0x425DB4 байт+1 & 0x80)
#:   HI 0-4   0x1F    номер объекта 1-30 (списки юнитов по объектам,
#:                    0x428240 & 0x1F0000)
#:   HI 5     0x20    Inner: интерьер — юнит виден лишь при активном
#:                    объекте (0x428240 & 0x200000)
#:   HI 6     0x40    Light: daylit — юнит в клетке рисуется дневной
#:                    палитрой (0x425DB4 байт+2 & 0x40)
#:   HI 7     0x80    UpOff: пишется редактором, финальным движком
#:                    НЕ читается (масок 0x800000 к сетке нет)
CELL_BLOCK_MASK = 0x0FFF
CELL_EXIT_BIT = 0x1000
CELL_SOLID_BIT = 0x4000
CELL_TRANSPARENT_BIT = 0x8000
CELL_OBJECT_MASK = 0x1F       # в слове HI
CELL_INNER_BIT = 0x20
CELL_LIGHT_BIT = 0x40
CELL_UPOFF_BIT = 0x80


def editor_cell_save(number: int, row: int, col: int,
                     patch: dict) -> tuple[bool, str, dict]:
    """Правка одной клетки grid.txt; пустой патч — только прочитать.

    В патче: blocked (низ 12 бит -> 0xFFF/0), solid, exit, transparent
    (биты LO), inner, light, upoff (биты HI), object (номер объекта
    0-30, 0 — отвязать). Возвращает итоговые lo/hi и разбор битов.
    """
    if not (0 <= row < GRID_ROWS and 0 <= col < GRID_COLS):
        return False, f"клетка ({row},{col}) вне сетки", {}
    folder = project_map_dir(number)
    if folder is None:
        return False, f"нет проектной карты с номером {number}", {}
    file = folder / "grid.txt"
    if not file.is_file():
        return False, "у карты нет grid.txt", {}
    lines = file.read_text(encoding="utf-8").splitlines()
    grid = [line for line in lines
             if line and not line.startswith("#")]
    if len(grid) != GRID_ROWS:
        return False, f"grid.txt: {len(grid)} строк, нужно {GRID_ROWS}", {}
    head = [line for line in lines
             if line.startswith("#")]
    cells = grid[row].split()
    if len(cells) != GRID_COLS:
        return False, f"строка {row}: {len(cells)} клеток", {}
    lo_hex, _, hi_hex = cells[col].partition(":")
    lo, hi = int(lo_hex, 16), int(hi_hex, 16)
    # ПАКЕТНАЯ КИСТЬ: patch["cells"] = [{row, col, blocked?…}, …] —
    # правка области одной записью файла (урок пакетной кисти земли)
    if patch.get("cells"):
        for stroke in patch["cells"]:
            r, c = int(stroke.get("row", -1)), int(stroke.get("col", -1))
            if not (0 <= r < GRID_ROWS and 0 <= c < GRID_COLS):
                continue
            row_ = grid[r].split()
            l_hex, _, h_hex = row_[c].partition(":")
            l, h = int(l_hex, 16), int(h_hex, 16)
            if "blocked" in stroke:
                l = (l & ~CELL_BLOCK_MASK) | (CELL_BLOCK_MASK
                                              if stroke["blocked"] else 0)
            for key_, bit_val in (("solid", CELL_SOLID_BIT),
                              ("exit", CELL_EXIT_BIT),
                              ("transparent", CELL_TRANSPARENT_BIT)):
                if key_ in stroke:
                    l = (l | bit_val) if stroke[key_] else (l & ~bit_val)
            # hi-биты пачкой — иначе кисть света областью молча теряется
            for key_, bit_val in (("inner", CELL_INNER_BIT),
                              ("light", CELL_LIGHT_BIT),
                              ("upoff", CELL_UPOFF_BIT)):
                if key_ in stroke:
                    h = (h | bit_val) if stroke[key_] else (h & ~bit_val)
            row_[c] = f"{l:04X}:{h:04X}"
            grid[r] = " ".join(row_)
        file.write_text(chr(10).join([*head, *grid]) + chr(10),
                        encoding="utf-8")
        cells = grid[row].split()
        lo_hex, _, hi_hex = cells[col].partition(":")
        lo, hi = int(lo_hex, 16), int(hi_hex, 16)
        patch = {}
    if patch:
        if "blocked" in patch:
            lo = (lo & ~CELL_BLOCK_MASK) | (CELL_BLOCK_MASK
                                            if patch["blocked"] else 0)
        for key_, bit_val in (("solid", CELL_SOLID_BIT),
                          ("exit", CELL_EXIT_BIT),
                          ("transparent", CELL_TRANSPARENT_BIT)):
            if key_ in patch:
                lo = (lo | bit_val) if patch[key_] else (lo & ~bit_val)
        for key_, bit_val in (("inner", CELL_INNER_BIT),
                          ("light", CELL_LIGHT_BIT),
                          ("upoff", CELL_UPOFF_BIT)):
            if key_ in patch:
                hi = (hi | bit_val) if patch[key_] else (hi & ~bit_val)
        if "object" in patch:
            num_ = int(patch["object"] or 0)
            if not 0 <= num_ <= 30:
                return False, f"номер объекта {num_} вне 0-30", {}
            hi = (hi & ~CELL_OBJECT_MASK) | num_
        cells[col] = f"{lo:04X}:{hi:04X}"
        grid[row] = " ".join(cells)
        file.write_text(chr(10).join([*head, *grid]) + chr(10),
                        encoding="utf-8")
    return True, str(file), {
        "lo": lo, "hi": hi,
        "blocked": (lo & CELL_BLOCK_MASK) == CELL_BLOCK_MASK,
        "solid": bool(lo & CELL_SOLID_BIT),
        "exit": bool(lo & CELL_EXIT_BIT),
        "transparent": bool(lo & CELL_TRANSPARENT_BIT),
        "inner": bool(hi & CELL_INNER_BIT),
        "light": bool(hi & CELL_LIGHT_BIT),
        "upoff": bool(hi & CELL_UPOFF_BIT),
        "object": hi & CELL_OBJECT_MASK,
    }

# ═══ API v2 РЕДАКТОРА (docs/EDITOR_SPEC.md) ═════════════════════════════
#
# Чистый JSON-интерфейс для ВНЕШНЕГО UI редактора (Claude Design):
# проект — единственный источник истины, холст рендерится из этих
# ответов, Build — операция API. CORS открыт: сервер локальный.

def api_maps(content_root=None) -> tuple[bool, str, dict]:
    """Все карты проекта: номер, каталог, имя, есть ли черновые правки и
    собрана ли карта в пак.

    Признаки нужны фильтрам списка («с draft-правками», «не собраны»):
    без них UI пришлось бы спрашивать состояние каждой из полутора сотен
    карт по отдельности. Оба ответа дешёвые — наличие непустого
    scenario.json и наличие map.json в паке.
    """
    root = Path(content_root or DEFAULT_CONTENT_ROOT)
    row_ = []
    for folder in sorted(PROJECT_MAPS.iterdir()):
        if not folder.is_dir() or "_" not in folder.name:
            continue
        num_, _, _ = folder.name.partition("_")
        if not num_.isdigit():
            continue
        name_ = ""
        file = folder / "map.json"
        if file.is_file():
            try:
                name_ = json.loads(file.read_text(
                    encoding="utf-8")).get("name") or ""
            except ValueError:
                pass
        draft_rec = folder / "scenario.json"
        has_edits = False
        if draft_rec.is_file():
            try:
                document = json.loads(draft_rec.read_text(encoding="utf-8"))
                has_edits = any(document.get(key_)
                                  for key_ in document)
            except ValueError:
                has_edits = False
        #: МОЖНО ЛИ ЭТУ КАРТУ ПРАВИТЬ — ГЛАВНЫЙ ПРИЗНАК, А ЕГО НЕ БЫЛО.
        #: Полторы сотни карт обеих игр лежат тут вперемешку со своими, и
        #: список ничем их не различал. Человек открывал «Морской лагерь»,
        #: получал полностью живой на вид редактор — кисти, каталог, вещь
        #: едет за курсором, — а на записи сервер отвечал отказом
        #: (_канон_под_защитой), холст перечитывался, и вещь прыгала
        #: назад. Со стороны это ровно «объекты не перемещаются, половина
        #: не работает». Отдаём признак, чтобы UI мог сказать правду
        #: ДО первого клика.
        row_.append({"map": int(num_), "dir": folder.name, "name": name_,
                    "draft": has_edits,
                    "editable": _editor_map(int(num_)),
                    "built": (root / "maps" / num_.lstrip("0")
                              / "map.json").is_file()
                             or (root / "maps" / str(int(num_))
                                 / "map.json").is_file()})
    return True, f"{len(row_)} карт", {"maps": row_}


def _draft_of(folder: Path) -> dict:
    file = folder / "scenario.json"
    if not file.is_file():
        return {}
    try:
        return json.loads(file.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def _draft_with_frames(draft_rec: dict, root: Path, game_name: str) -> dict:
    """Дать поставленным редактором жителям их собственный кадр.

    Холст рисовал черновых жителей ПРЕВЬЮ ПОРОДЫ — то есть первой
    мастью каталога: какую масть ни выбери, на карте стоял первый цвет.
    Кадр считается тем же способом, что у жителей пака (_unit_frame), и
    по СВОИМ полям записи.
    """
    additions = draft_rec.get("editor_units_add")
    if not isinstance(additions, list) or not additions:
        return draft_rec
    common = _shared_of(root)
    if not common:
        return draft_rec
    fresh = []
    for record in additions:
        if not isinstance(record, dict) or record.get("frame"):
            fresh.append(record)
            continue
        #: игра у жителя своя (народ пустыни на нашей карте — «legend»),
        #: карта решает лишь тогда, когда житель молчит
        frame = _unit_frame(common, int(record.get("breed") or 0),
                            int(record.get("body") or 0),
                            int(record.get("palette") or 0),
                            int(record.get("direction") or 6),
                            record.get("equipment"), None,
                            str(record.get("game") or game_name))
        fresh.append({**record, "frame": frame} if frame else record)
    return {**draft_rec, "editor_units_add": fresh}


def api_map_state(number: int,
                  content_root=None) -> tuple[bool, str, dict]:
    """Состояние карты для холста редактора: метаданные, вода,
    объекты и оверлеи (палитра уже разрешённая), draft-слои."""
    folder = project_map_dir(number)
    if folder is None:
        return False, f"нет проектной карты с номером {number}", {}
    document = json.loads((folder / "map.json").read_text(encoding="utf-8"))
    water = _water_read(document)

    def object_fields(r: dict) -> dict | None:
        # ИСТИНА — raw С ПОЛЯМИ ПОВЕРХ (как собирает binrec.pack).
        # Канонные записи старых map.json зовут поле нулевого смещения
        # «id» (старая схема), новые — «sprite»; raw переживает обе.
        import struct as _st
        raw_data = bytes.fromhex(r["raw"]) if r.get("raw") else bytes(36)
        sprite = _st.unpack_from("<i", raw_data, 0)[0]
        kind = _st.unpack_from("<I", raw_data, 4)[0]
        x = _st.unpack_from("<H", raw_data, 30)[0]
        y = _st.unpack_from("<H", raw_data, 32)[0]
        state = raw_data[35]
        if "sprite" in r:
            sprite = int(r["sprite"])
        elif "id" in r:
            sprite = int(r["id"])
        if "kind" in r:
            kind = int(r["kind"])
        if "pixel_x" in r:
            x = int(r["pixel_x"])
        if "pixel_y" in r:
            y = int(r["pixel_y"])
        if "state" in r:
            state = int(r["state"])
        if sprite < 0 or kind in (0xFFFF, 0xFFFFFFFF):
            return None
        return {"slot": int(r["slot"]), "sprite": sprite,
                "resource_slot": sprite + 30,
                # kind — байтовое смещение палитры (шаг 0x200); 0 —
                # палитра заголовка ресурса (VA 0x43E7D8)
                "palette": (kind // 0x200) or None,
                "state": state, "x": x, "y": y}

    objects = [field for field in
               (object_fields(r) for r in
                (document.get("objects") or {}).get("records") or [])
               if field is not None]
    overlays = [{
        "slot": int(r["slot"]), "id": int(r.get("id") or 0),
        "x": int(r.get("pixel_x") or 0), "y": int(r.get("pixel_y") or 0),
    } for r in (document.get("dynamic") or {}).get("records") or []
        if int(r.get("id") or 0xFFFF) != 0xFFFF]
    root = Path(content_root or DEFAULT_CONTENT_ROOT)
    pack = root / "maps" / str(number) / "map.json"
    common = 0
    for row_ in water:
        for byte_val in row_:
            common |= byte_val
    return True, str(folder), {
        #: editable — можно ли эту карту писать. Без него холст выглядел
        #: живым на канонной карте: кисти активны, вещь едет за курсором,
        #: а запись отвергалась (_канон_под_защитой) и вещь прыгала назад.
        "meta": {"map": number, "dir": folder.name,
                 "name": document.get("name") or "",
                 "editable": _editor_map(number),
                 #: чья это карта: спрайты объектов и тела жителей у двух
                 #: игр разные, клиент по этому полю выбирает каталог
                 "game": _map_game(document),
                 "light_flag": int(document.get("light_flag") or 0)},
        "water": {"tile": int(document.get("light_flag") or 0),
                  "stream": not bool(common & 0x80),
                  "count": sum(1 for row_ in water for b_ in row_ if b_),
                  "rows": [row_.hex() for row_ in water]},
        "objects": {"records": objects},
        "overlays": {"records": overlays},
        #: ОБЪЯВЛЕННЫЕ выходы карты, а не запечённые. Холст до сих пор
        #: рисовал только те, что уже в паке (api_pack_units → exits), —
        #: то есть поставленную, но ещё не собранную дверь человек не
        #: видел вовсе и не мог ни поправить, ни убрать.
        "exits": document.get("exits") or [],
        "draft": _draft_with_frames(_draft_of(folder), root,
                                    _map_game(document)),
        "pack": {"built": pack.is_file(),
                 "mtime": int(pack.stat().st_mtime) if pack.is_file()
                 else None},
    }


def api_terrain(number: int) -> tuple[bool, str, dict]:
    """Тайлы земли и свет: три матрицы индексов (0 — пусто)."""
    layer1, layer2, trouble = _ground_layers(number)
    if trouble:
        return False, trouble, {}
    from PIL import Image
    img1 = Image.open(layer1).convert("L")
    img2 = Image.open(layer2).convert("L")
    bottom_part, top_part, light = [], [], []
    for row in range(GROUND_ROWS):
        bottom_part.append([img1.getpixel((col * 2, row))
                    for col in range(GROUND_COLS)])
        top_part.append([img1.getpixel((col * 2 + 1, row))
                     for col in range(GROUND_COLS)])
        light.append([img2.getpixel(_light_xy(row, col))
                     for col in range(GROUND_COLS)])
    return True, str(layer1.parent), {
        "rows": GROUND_ROWS, "cols": GROUND_COLS,
        # внутри PNG лежит индекс+1 — наружу отдаём индексы, 0 = пусто
        "lower": [[b_ - 1 if b_ else None for b_ in row_] for row_ in bottom_part],
        "upper": [[b_ - 1 if b_ else None for b_ in row_] for row_ in top_part],
        "light": [[b_ - 1 if b_ else None for b_ in row_] for row_ in light],
    }


def api_cells(number: int) -> tuple[bool, str, dict]:
    """Сетка проходимости целиком, строками «LO:HI»."""
    folder = project_map_dir(number)
    if folder is None:
        return False, f"нет проектной карты с номером {number}", {}
    file = folder / "grid.txt"
    if not file.is_file():
        return False, "у карты нет grid.txt", {}
    grid = [line.split() for line in
             file.read_text(encoding="utf-8").splitlines()
             if line and not line.startswith("#")]
    return True, str(file), {"rows": GRID_ROWS, "cols": GRID_COLS,
                             "cells": grid}


#: КАДР ЮНИТА ДЛЯ ХОЛСТА — ПО ПРАВИЛАМ КЛИЕНТА.
#:
#: Холст рисовал юнитов точками, и карта не была похожа на игру. Чтобы
#: показать то же, что видит игрок, кадр выбирается тем же путём, что в
#: actor.js: поза «stand» нужного направления даёт НОМЕР ЗАПИСИ (record),
#: а набор тела по этому номеру — кусок листа. Тварей (бит 0x40 породы)
#: рисует свой набор creatures.sets[тело][масть].
#:
#: Правило выбора набора тела повторяет actorBody: ключ «форма:масть»,
#: откат на форму, откат на набор масти. Разойдётся с клиентом — юнит на
#: холсте будет в чужой раскраске.
_SHARED_CACHE: dict | None = None


def _shared_of(root: Path) -> dict:
    global _SHARED_CACHE
    if _SHARED_CACHE is None:
        file = root / "shared.json"
        _SHARED_CACHE = (json.loads(file.read_text(encoding="utf-8"))
                         if file.is_file() else {})
    return _SHARED_CACHE


def _layer_frame(common: dict, layer_id: int, record: str,
                 pal: int) -> dict | None:
    """Кадр слоя снаряжения: ключ «слой:палитра», откат на слой."""
    bundles = (common.get("hero") or {}).get("equipment") or {}
    bundle = bundles.get(f"{layer_id}:{pal}") or bundles.get(str(layer_id)) or {}
    return (bundle.get("frames") or {}).get(record)


def _item_of(goods: dict, ref) -> dict | None:
    """Класс вещи по ссылке юнита: «instance:209:…» -> items[class:209]."""
    if not ref or not goods:
        return None
    if ref in goods:
        return goods[ref]
    line = str(ref)
    if line.startswith("instance:"):
        num_ = line.split(":")[1]
        return goods.get(f"class:{num_}")
    return next((z_ for z_ in goods.values() if z_.get("name") == line), None)


def _unit_frame(common: dict, breed: int, body: int, palette: int,
                direction: int = 6, equipment: dict | None = None,
                goods: dict | None = None, game_name: str = "") -> dict | None:
    """Кадр «стоит» для юнита: СЛОИ тела и надетого, снизу вверх.

    Порядок слоёв — не выдумка, а сценарий из пака
    (hero.rules.equipment_draw): тело, за ним доспех, затем пять шагов
    своего направления из таблицы движка 0x4627D0. Со спины щит в руке
    уходит под оружие, а щит за спиной ложится последним — потому и
    сценарий у каждого направления свой.
    """
    def sheet_frame(sheets, frame):
        if not frame or frame.get("sheet") is None:
            return None
        sheet = sheets[frame["sheet"]] if frame["sheet"] < len(sheets) else None
        if not sheet:
            return None
        return {"url": "/content/" + sheet["path"],
                "x": frame["x"], "y": frame["y"],
                "width": frame["width"], "height": frame["height"],
                "offset_x": frame.get("offset_x", 0),
                "offset_y": frame.get("offset_y", 0),
                "sheet_width": sheet["width"], "sheet_height": sheet["height"]}

    if int(breed or 0) & 0x40:                       # тварь — свой набор
        beasts = common.get("creatures") or {}
        sheets = beasts.get("sheets") or []
        bundle = ((beasts.get("sets") or {}).get(str(body)) or {}).get(
            str(palette)) or {}
        stand_frames = bundle.get("stand") or []
        frames = (stand_frames[direction] if direction < len(stand_frames) else None)             or (stand_frames[0] if stand_frames else None)
        first_one = sheet_frame(sheets, (frames or [None])[0])
        return dict(first_one, layers=[first_one]) if first_one else None

    hero = common.get("hero") or {}
    sheets = hero.get("sheets") or []
    poses = (hero.get("animations") or {}).get("peace") or {}
    stand_frames = poses.get("stand") or []
    frames = (stand_frames[direction] if direction < len(stand_frames) else None)         or (stand_frames[0] if stand_frames else None)
    basis = (frames or [None])[0]
    if not basis:
        return None
    record = str(basis.get("record"))
    body_sheets = hero.get("body_layers") or {}
    #: НАБОР ТЕЛА — С ИГРОЙ ЮНИТА. Пак печёт тела «Продолжения легенды»
    #: под ключом legend:{форма}:{палитра} (палитры игр расходятся 38 из
    #: 256), и юнит несёт поле game. Без этого народ пустыни Тиграта
    #: рисовался канонным телом по чужому номеру палитры — «болванчики».
    #: Игровой клиент так и выбирает (actor.js bodyKey).
    bundle = ((body_sheets.get(f"{game_name}:{body}:{palette}")
               if game_name else None)
             or body_sheets.get(f"{body}:{palette}") or body_sheets.get(str(body))
             or (hero.get("bodies") or {}).get(str(palette)) or {})
    payload = sheet_frame(sheets, (bundle.get("frames") or {}).get(record))
    if not payload:
        return None

    layers_map = [payload]
    rules_doc = (hero.get("rules") or {}).get("equipment_draw") or {}
    scenario = (rules_doc.get("script") or [])
    dir_steps = scenario[direction] if direction < len(scenario) else []
    goods = goods or {}

    def add_rec(stride):
        thing = _item_of(goods, (equipment or {}).get(stride.get("slot")))
        if not thing or not thing.get("layer"):
            return
        if stride.get("kind") is not None and thing.get("kind") != stride["kind"]:
            return
        if stride.get("not_kind") is not None and thing.get("kind") == stride["not_kind"]:
            return
        # «когда» разбираем просто: мирная стойка, оружие в руке
        when_at = stride.get("when")
        if when_at in ("at_rest", "shooting"):
            return
        frame = _layer_frame(common, thing["layer"] + (stride.get("offset") or 0),
                            record, thing.get("palette") or 0)
        layer_id = sheet_frame(sheets, frame)
        if layer_id:
            layers_map.append(layer_id)

    for stride in rules_doc.get("before") or []:
        if stride.get("step") == "layer":
            add_rec(stride)
    for code in dir_steps:
        for stride in (rules_doc.get("steps") or {}).get(str(code)) or []:
            add_rec(stride)
    return dict(payload, layers=layers_map)


def editor_names_page() -> tuple[bool, str, dict]:
    """Имена и прозвища людей — из таблицы exe.

    В GAME.<мир> имени НЕТ: запись юнита хранит номера (0xF0 имя, 0xF1
    прозвище), а строки лежат в исполняемом файле игры. Придумать своё
    имя нельзя — можно только выбрать из авторской таблицы, и список
    для этого выбора отдаёт эта ручка.

    Тварей это не касается: у пород 0x41…0x53 имя берётся из таблицы
    пород по самому байту породы, и номера имени у них не смотрят.
    """
    try:
        from konung2.gamefile import _npc_names, NPC_NICKNAMES_FROM
        table = _npc_names()
    except Exception as trouble:
        return False, f"таблица имён недоступна: {trouble}", {}
    names = [{"id": n_, "name": name_}
             for n_, name_ in enumerate(table[:NPC_NICKNAMES_FROM])
             if n_ and name_]
    nicknames = [{"id": n_, "name": table[NPC_NICKNAMES_FROM + n_]}
                for n_ in range(1, len(table) - NPC_NICKNAMES_FROM)
                if table[NPC_NICKNAMES_FROM + n_]]
    return True, f"{len(names)} имён, {len(nicknames)} прозвищ", {
        "names": names, "nicknames": nicknames}


def editor_items_page(content_root=None) -> tuple[bool, str, dict]:
    """Носимые вещи каталога: чем можно одеть юнита.

    Слой и палитра берутся из класса вещи — тем же путём, каким их читает
    отрисовка (VA 0x425DB4 ставит палитру ПРЕДМЕТА перед его слоем).
    Поэтому список годится и для показа, и для записи в юнита.
    """
    root = Path(content_root or DEFAULT_CONTENT_ROOT)
    #: вещи лежат в каждой карте; берём первую собранную — каталог общий
    for map_rec in sorted((root / "maps").iterdir(),
                        key=lambda x: (len(x.name), x.name)):
        file = map_rec / "map.json"
        if not file.is_file():
            continue
        goods = (json.loads(file.read_text(encoding="utf-8"))
                .get("items") or {})
        if not goods:
            continue
        row_ = []
        for key_, thing in goods.items():
            if not key_.startswith("class:") or not thing.get("layer"):
                continue
            icon = thing.get("icon") or {}
            row_.append({"ref": key_, "name": thing.get("name") or key_,
                        "slot": thing.get("slot"), "layer": thing["layer"],
                        "palette": thing.get("palette") or 0,
                        "kind": thing.get("kind"),
                        #: ПУТЬ ЗНАЧКА — ГОТОВЫЙ К ПОКАЗУ. Отдавали
                        #: "assets/icons/87.png", а сервер держит паковые
                        #: файлы под /content/: браузер получал 404 и
                        #: значка не было ни одного. Отдаём то, что
                        #: можно поставить в src как есть, — как это
                        #: давно делает каталог объектов.
                        "icon": ("/content/" + icon["path"]
                                 if icon.get("path") else None),
                        "icon_width": icon.get("width"),
                        "icon_height": icon.get("height"),
                        #: ЧИСЛА ВЕЩИ. Они лежат в паке рядом с именем и
                        #: не отдавались вовсе, отчего выбор вещи был
                        #: выбором вслепую: список имён без цены, веса,
                        #: силы удара и требования к владельцу.
                        "power": thing.get("power"),
                        "durability": thing.get("durability"),
                        "price": thing.get("price"),
                        "weight": thing.get("weight"),
                        "range_cells": thing.get("range_cells"),
                        "requirement": thing.get("requirement"),
                        "requires": thing.get("requires"),
                        "ammo": thing.get("ammo")})
        row_.sort(key=lambda z_: (z_["slot"] or "", z_["name"]))
        return True, f"{len(row_)} носимых вещей", {"items": row_}
    return False, "в паке нет собранных карт", {}


#: ЧТО ЗНАЧИТ КАЖДОЕ ЧИСЛО ПОСЕЛЕНИЯ. Смысл байта живёт рядом с
#: разбором (konung2/gamefile.py village), и врать о нём нельзя — а
#: соблазн велик: ключ `treasury` называется казной, но КАЗНОЙ НЕ
#: ЯВЛЯЕТСЯ. Подписи отдаём с данными, чтобы экран не сочинял свои.
VILLAGE_NOTES = {
    "owned": "казна владения (+0x10): в неё капает недельный доход, и "
             "по её ненулевости обработчик 27 отвечает «деревня чья-то»",
    "owner": "чьё владение (+0x4A0)",
    "wealth": "богатство (+0x00): множитель дохода ×50",
    "status": "статус (+0x49D): строка делителей дохода и порог",
    "flags": "признаки поселения (+0x49C)",
    "treasury": "НЕ КАЗНА (+0x0C): счётчик занятий воеводы — такт "
                "деревни убавляет его и сбрасывает в 1200. Деньги "
                "лежат в «казне владения»",
    "slots_a": "разметка мест, первый байт (+0x00): мест = a + b + 7",
    "slots_b": "разметка мест, второй байт (+0x01); при нуле условия "
               "разговора 4 и 6 отказывают",
    "side": "сторона деревни (+0x02): ею движок индексирует таблицу "
            "отрядов, когда деревня ополчается — это ключ, не настройка",
    "master": "мастер поселения (+0x3D6): номер юнита",
    "officials": "должностные лица: пять мест с +0x3D0, номера юнитов; "
                 "должность = место + 1, по ней же выбирается прилавок",
    "squad_places": "мест в отряде деревни (+0x1A записи ОТРЯДА)",
    "squad_people": "занято мест (+0x1C записи отряда): при равенстве "
                    "«сделать собеседника жителем» уже нельзя",
    "culture": "культура старейшины (выводится по карте)",
    "brew_timer": "часы варки знахаря (+0x04): при нуле первый же тик "
                  "даёт все три жетона разом",
}


#: ЧТО РЕДАКТОРУ МОЖНО ТРОГАТЬ У ПОСЕЛЕНИЯ. Зеркало
#: builder.EDITOR_VILLAGE_FIELDS — разойдутся, и правка молча не доедет.
#:
#: Чего тут НЕТ и почему:
#:   master, officials, people — это НОМЕРА ЮНИТОВ в таблице мира, и на
#:     них держится маршрутизация разговоров (обработчик 30 спрашивает
#:     «занимает ли собеседник должность N», VA 0x435550). Сменить их
#:     врозь с самими юнитами — оторвать деревню от её жителей;
#:   side — байт +0x02, которым движок ИНДЕКСИРУЕТ таблицу отрядов,
#:     когда деревня ополчается (VA 0x41FDD0). Это ключ, а не настройка;
#:   squad_places / squad_people — не поля поселения вовсе: они читаются
#:     из записи ОТРЯДА (+0x1A и +0x1C), и править их надо там;
#:   workplaces, goods, culture, brew_timer, index, map — производные:
#:     первые две собираются из чужих таблиц, остальные вычисляются.
VILLAGE_FIELDS = frozenset({
    "owned", "owner", "wealth", "status", "flags", "treasury",
    "slots_a", "slots_b",
})
#: Постройки правятся по слоту: {"buildings": {"7": {"built": true}}}
VILLAGE_BUILDING = frozenset({"built", "state", "object"})


def api_village(number: int, content_root=None,
                world: int | None = None) -> tuple[bool, str, dict]:
    """Поселение СОБРАННОЙ карты — со словами вместо чисел.

    ЗАПИСЬ СВОЯ В КАЖДОМ МИРЕ: должностные лица деревни в каждом
    GAME.<мир> другие, и клиент берёт запись мира своего героя
    (`village_by_world`). Отдаём ту же, что увидит игра.
    """
    root = Path(content_root or DEFAULT_CONTENT_ROOT)
    file = root / "maps" / str(number) / "map.json"
    if not file.is_file():
        return False, f"карта {number} не собрана в пак", {}
    document = json.loads(file.read_text(encoding="utf-8"))
    record = document.get("village")
    if world is not None:
        own_one = (document.get("village_by_world") or {}).get(str(world))
        if own_one is not None:
            record = own_one
    if not record:
        return False, f"на карте {number} поселения нет", {}
    #: ЖИТЕЛИ ПО ИМЕНАМ, А НЕ ПО НОМЕРАМ. officials — это индексы юнитов
    #: в таблице мира; человеку номер 369 не говорит ничего.
    #: номер юнита в мире лежит в его id («unit_369»), отдельного поля
    #: index у паковой записи нет — сборка кладёт номер именно в id
    by_number = {}
    for u_ in document.get("units") or []:
        matched = re.match(r"^unit_(\d+)$", str(u_.get("id") or ""))
        if matched:
            by_number[int(matched.group(1))] = u_.get("name")
    #: правки редактора, ещё не попавшие в пак: показываем то, что
    #: человек уже задал, а не вчерашний снимок сборки
    edits = {}
    folder = project_map_dir(number)
    if folder is not None:
        scenario = folder / "scenario.json"
        if scenario.is_file():
            try:
                edits = (json.loads(scenario.read_text(encoding="utf-8"))
                          .get("editor_village") or {})
            except ValueError:
                edits = {}
    return True, f"поселение {record.get('index')}", {
        "village": record,
        "draft": edits,
        "names": {str(n_): i_ for n_, i_ in by_number.items() if i_},
        #: подписи полей — здесь, а не в клиенте: смысл байта живёт
        #: рядом с разбором, и врать о нём нельзя
        "notes": VILLAGE_NOTES,
    }


def editor_village_save(number: int, payload: dict) -> tuple[bool, str, dict]:
    """Правка поселения: {patch: {...}} и {buildings: {"слот": {...}}}.

    Ложится слоем `editor_village` в scenario.json; сборка кладёт его
    поверх записи поселения КАЖДОГО мира (как и правки отрядов).
    """
    patch_ = payload.get("patch")
    if not isinstance(patch_, dict) or not patch_:
        return False, "пустой патч", {}
    fields, buildings, surplus = {}, {}, []
    for name_, value in patch_.items():
        if name_ == "buildings" and isinstance(value, dict):
            for slot, edit in value.items():
                if not isinstance(edit, dict):
                    surplus.append(f"buildings.{slot}")
                    continue
                foreign_ones = set(edit) - VILLAGE_BUILDING
                if foreign_ones:
                    surplus.extend(f"buildings.{slot}.{k_}" for k_ in foreign_ones)
                    continue
                buildings[str(int(slot))] = edit
        elif name_ in VILLAGE_FIELDS:
            fields[name_] = value
        else:
            surplus.append(name_)
    if surplus:
        return False, (f"эти поля поселения редактор не правит: "
                       f"{', '.join(sorted(surplus))}"), {}
    if not fields and not buildings:
        return False, "пустой патч", {}
    folder = project_map_dir(number)
    if folder is None:
        return False, f"нет проектной карты с номером {number}", {}
    file = folder / "scenario.json"
    document = (json.loads(file.read_text(encoding="utf-8"))
                if file.is_file() else {})
    layer_id = document.setdefault("editor_village", {})
    layer_id.update(fields)
    if buildings:
        nest = layer_id.setdefault("buildings", {})
        for slot, edit in buildings.items():
            nest.setdefault(slot, {}).update(edit)
    file.write_text(json.dumps(document, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    how_many = len(fields) + len(buildings)
    return True, f"поселение: правок {how_many}", {"village": layer_id}


def _unit_number(record: dict) -> int:
    """Номер жителя в мире: он лежит в id вида «unit_369»."""
    matched = re.match(r"^unit_(\d+)$", str(record.get("id") or ""))
    return int(matched.group(1)) if matched else -1


def _name_numbers(world: int, number: int) -> dict[int, tuple[int, int]]:
    """Номера имени и прозвища жителей мира — по индексу юнита.

    В ПАКЕ ИХ НЕТ: сборка кладёт собранную строку `name`, а номера
    (0xF0 и 0xF1) остаются в исходниках мира. Редактору нужны именно
    они: переименование пишет номер, а не строку — строки имени в
    GAME.<мир> не существует вовсе.

    Поля `name_id`/`nick_id` появились в экспорте позже самих файлов
    мира, поэтому в старых записях они пусты. Байты при этом на
    месте — берём их из `raw`, а не гоним экспорт заново.
    """
    file = PROJECT_WORLDS / str(world) / "maps" / f"{number}.json"
    if not file.is_file():
        return {}
    try:
        document = json.loads(file.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    outcome: dict[int, tuple[int, int]] = {}
    for record in document.get("units") or []:
        at = record.get("index")
        if at is None:
            continue
        name_, nickname = record.get("name_id"), record.get("nick_id")
        if name_ is None or nickname is None:
            raw_data = record.get("raw")
            if not raw_data:
                continue
            raw_bytes = bytes.fromhex(raw_data)
            if len(raw_bytes) <= 0xF1:
                continue
            name_, nickname = raw_bytes[0xF0], raw_bytes[0xF1]
        outcome[int(at)] = (int(name_), int(nickname))
    return outcome


def api_pack_units(number: int, content_root=None,
                   world: int | None = None) -> tuple[bool, str, dict]:
    """Жители СОБРАННОГО пака — их редактор патчит, не создаёт.

    НАСЕЛЕНИЕ ЗАВИСИТ ОТ МИРА. Выбор героя — это выбор мира, и состав
    карты у них разный: во Дворце Повелителя в мирах 0…4 четверо, а в
    мире Анастасии семеро — Мунд и ещё воин у правого края. Пока
    отдавался только базовый список, редактор их не показывал, и карта
    выглядела неполной.
    """
    root = Path(content_root or DEFAULT_CONTENT_ROOT)
    file = root / "maps" / str(number) / "map.json"
    if not file.is_file():
        return False, f"карта {number} не собрана в пак", {}
    document = json.loads(file.read_text(encoding="utf-8"))
    if world is not None:
        by_worlds = document.get("units_by_world") or {}
        if_any = by_worlds.get(str(world))
        if if_any is not None:
            document = dict(document, units=if_any)
        bands = (document.get("warbands_by_world") or {}).get(str(world))
        if bands is not None:
            document = dict(document, warbands=bands)
    common = _shared_of(root)
    name_numbers = _name_numbers(world, number) if world is not None else {}
    units_ = [{
        "id": u.get("id"), "name": u.get("name"),
        "breed": u.get("breed"), "body": u.get("body"),
        "palette": u.get("palette"), "level": u.get("level"),
        "side": u.get("side"), "party": u.get("party"),
        "cell": u.get("cell"), "dialog_number": u.get("dialog_number"),
        "health": (u.get("stats") or {}).get("health"),
        #: ЧИСЛА ЖИТЕЛЯ ОТДАЁМ ЦЕЛИКОМ. В паке у него лежит всё —
        #: characteristics, stats, skills, деньги, скорость, сумка, — а
        #: наружу уходило четырнадцать полей без них. Панель юнита в
        #: редакторе честно печатала `юнит.characteristics?.[ключ]` и
        #: получала undefined, то есть «?» в каждой строке: «не видно
        #: статов у нпс» было чистой правдой, и виновата была ручка, а
        #: не панель. Полей немного и они плоские — режима «покажи
        #: подробности» тут не нужно.
        #: номера имени: ими и правится имя жителя мира (строки имени в
        #: GAME.<мир> нет), см. _номера_имён
        "name_id": name_numbers.get(_unit_number(u), (None, None))[0],
        "nick_id": name_numbers.get(_unit_number(u), (None, None))[1],
        "characteristics": u.get("characteristics"),
        "current": u.get("current"), "stats": u.get("stats"),
        "skills": u.get("skills"), "money": u.get("money"),
        "speed": u.get("speed"), "venom": u.get("venom"),
        "face": u.get("face"), "role": u.get("role"),
        #: сумка — это ВЕЩИ при юните, не надетое; details несёт имена
        "bag": u.get("bag"), "bag_details": u.get("bag_details"),
        "equipment_details": u.get("equipment_details"),
        "workplaces": u.get("workplaces"),
        # кадр для холста: редактор рисует юнита так же, как игра
        "frame": _unit_frame(common, u.get("breed") or 0,
                             u.get("body") or 0, u.get("palette") or 0,
                             int(u.get("direction") or 6),
                             u.get("equipment"), document.get("items"),
                             str(u.get("game") or "")),
        "equipment": u.get("equipment"),
        "position": u.get("position"),
    } for u in document.get("units") or []]
    #: ЧТО ЛЕЖИТ В КУЧЕ — А НЕ ТОЛЬКО СКОЛЬКО. Наружу шло одно число
    #: («items: 3»), и посмотреть состав клада было негде: ни в списке,
    #: ни в панели. Между тем пак несёт и ссылки вещей, и их количества
    #: (details), а имена вещей лежат рядом, в таблице items карты.
    #: Ссылка вида «instance:204:game:0:1825» несёт номер КЛАССА вторым
    #: числом — по нему имя и ищется (тем же путём, что и снаряжение
    #: юнита: класс → запись class:N).
    map_goods = document.get("items") or {}
    def _pile_good(ref, detail):
        matched = re.match(r"^(?:instance|class):(\d+)", str(ref or ""))
        record = (map_goods.get(f"class:{matched.group(1)}")
                  if matched else None) or {}
        return {"ref": ref,
                "class": f"class:{matched.group(1)}" if matched else None,
                "name": record.get("name"),
                "icon": ("/content/" + (record.get("icon") or {})["path"]
                         if (record.get("icon") or {}).get("path") else None),
                "count": (detail or {}).get("count"),
                "price": record.get("price"),
                "weight": record.get("weight")}
    piles = [{
        "id": p.get("id"), "cell": p.get("cell"),
        "money": p.get("money"), "buried": p.get("buried"),
        "items": len(p.get("items") or []),
        "contents": [_pile_good(s_, d_) for s_, d_ in
                     zip(p.get("items") or [],
                         (p.get("details") or []) + [None] * len(
                             p.get("items") or []))],
    } for p in document.get("loot") or []]
    # ВЫХОДЫ КАРТЫ — двери и переходы к соседям: холст рисует их зоны,
    # иначе связь карт видна только в игре
    exits = [{
        "to": d_.get("to_name") or d_.get("to"),
        "rows": [d_.get("row1"), d_.get("row2")],
        "cols": [d_.get("col1"), d_.get("col2")],
        # ПИКСЕЛЬНАЯ РАМКА — там, где дверь стоит на самом деле: по
        # клеткам зона выходит смещённой, а игрок видит проём ровно
        # в этом прямоугольнике
        "box": [d_.get("left"), d_.get("top"), d_.get("right"),
                d_.get("bottom")],
        "entry": {"row": d_.get("entry_row"), "col": d_.get("entry_col")},
    } for d_ in (document.get("exits") or [])
        if d_.get("row1") is not None]
    # ДЕКОР (T_DYNAMIC) — берега, кувшинки, камыши. Движок рисует их
    # сразу после земли и до объектов: ими прикрыта нарочно неполная
    # базовая мозаика, и без них уличные карты выглядят дырявыми.
    decor = [{
        "slot": o_.get("record_slot"), "sprite": o_.get("resource_slot"),
        "palette": o_.get("palette"),
        "x": (o_.get("position") or {}).get("x"),
        "y": (o_.get("position") or {}).get("y"),
        "url": "/content/" + (o_.get("frame") or {}).get("asset", ""),
        "width": (o_.get("frame") or {}).get("width"),
        "height": (o_.get("frame") or {}).get("height"),
    } for o_ in ((document.get("terrain") or {}).get("overlays") or [])
        if (o_.get("frame") or {}).get("asset")]
    #: КЛЮЧ ГЛУБИНЫ ОБЪЕКТОВ — ТОЛЬКО ИЗ ПАКА, а не вычисленный заново.
    #:
    #: Движок сортирует сцену по нижнему краю кадра, но у построек с
    #: битом 0x08 заголовка ключ поднят на четверть высоты (VA 0x426B75:
    #: линия глубины идёт по подошве ПЕРЕДНЕЙ СТЕНЫ, и юнит перед домом
    #: рисуется поверх). Ни этого бита, ни sort_height в паспорте
    #: объектов нет — считать ключ в редакторе значит гадать, а
    #: konung2/world/geometry.py прямо предупреждает: проверять
    #: картинкой или формулой из декомпилята, а не своей арифметикой
    #: (один раз уже уехало на 183…450 точек). Сборка это уже
    #: посчитала — отдаём готовое, по слоту записи.
    depths = {}
    for o_ in (document.get("props") or []) + (document.get("buildings") or []):
        box = o_.get("bounds") or {}
        if o_.get("record_slot") is not None and "sort_y" in box:
            depths[int(o_["record_slot"])] = int(box["sort_y"])
    return True, str(file), {
        "units": units_, "loot": piles, "exits": exits, "decor": decor,
        "warbands": document.get("warbands") or [],
        "object_depth": depths,
    }


def editor_object_remove(number: int, slot: int) -> tuple[bool, str, dict]:
    """Удалить запись T_OBJECTS с компактацией хвоста (дырка обрезала
    бы чтение движка на первом пустом слоте)."""
    folder = project_map_dir(number)
    if folder is None:
        return False, f"нет проектной карты с номером {number}", {}
    file = folder / "map.json"
    document = json.loads(file.read_text(encoding="utf-8"))
    records = (document.get("objects") or {}).get("records") or []
    record = next((r for r in records if int(r["slot"]) == slot), None)
    if record is None:
        return False, f"объекта в слоте {slot} нет", {}
    #: КЛЕТКИ УХОДЯТ ВМЕСТЕ С ДОМОМ. Убрали картинку, а стены остались бы
    #: стоять невидимой коробкой — герой упирался бы в пустое место.
    cleared = 0
    try:
        cleared = _stamp_apply(folder, record, slot, remove_it=True)
    except (OSError, ValueError):
        cleared = 0
    records.remove(record)
    for tail in records:
        if int(tail["slot"]) > slot:
            tail["slot"] = int(tail["slot"]) - 1
    file.write_text(json.dumps(document, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    #: НОМЕРА В КЛЕТКАХ СДВИНУЛИСЬ ВМЕСТЕ СО СЛОТАМИ. В клетке лежит
    #: номер ЗАПИСИ: без переписи дом остался бы помечен номером соседа —
    #: и крыша снималась бы не над тем домом.
    if cleared:
        try:
            _stamp_renumber(folder, records)
        except (OSError, ValueError):
            pass
    return True, str(file), {"count": len(records), "cells_cleared": cleared}


def api_unit_delete(number: int, unit_id: str) -> tuple[bool, str, dict]:
    """Добавленный юнит изымается из draft, житель пака помечается
    removed (сам пак неприкосновенен)."""
    folder = project_map_dir(number)
    if folder is None:
        return False, f"нет проектной карты с номером {number}", {}
    if unit_id.startswith("unit_new_"):
        file = folder / "scenario.json"
        document = _draft_of(folder)
        listing = document.get("editor_units_add") or []
        left_over = [u for u in listing if u.get("id") != unit_id]
        if len(left_over) == len(listing):
            return False, f"добавленного юнита {unit_id} нет", {}
        document["editor_units_add"] = left_over
        file.write_text(json.dumps(document, ensure_ascii=False,
                                   indent=1), encoding="utf-8")
        return True, str(file), {"deleted": unit_id}
    ok_, reply = editor_save(number, "unit", unit_id, {"removed": True})
    return ok_, reply, ({"deleted": unit_id} if ok_ else {})


def api_loot_delete(number: int, pile_id: str) -> tuple[bool, str, dict]:
    folder = project_map_dir(number)
    if folder is None:
        return False, f"нет проектной карты с номером {number}", {}
    if pile_id.startswith("pile_new_"):
        file = folder / "scenario.json"
        document = _draft_of(folder)
        listing = document.get("editor_loot_add") or []
        left_over = [x for x in listing if x.get("id") != pile_id]
        if len(left_over) == len(listing):
            return False, f"добавленной кучи {pile_id} нет", {}
        document["editor_loot_add"] = left_over
        file.write_text(json.dumps(document, ensure_ascii=False,
                                   indent=1), encoding="utf-8")
        return True, str(file), {"deleted": pile_id}
    ok_, reply = editor_save(number, "loot", pile_id, {"removed": True})
    return ok_, reply, ({"deleted": pile_id} if ok_ else {})


def api_warband_delete(number: int, side: int) -> tuple[bool, str, dict]:
    folder = project_map_dir(number)
    if folder is None:
        return False, f"нет проектной карты с номером {number}", {}
    file = folder / "scenario.json"
    document = _draft_of(folder)
    listing = document.get("editor_warbands_add") or []
    left_over = [w for w in listing if int(w.get("side", -1)) != side]
    if len(left_over) == len(listing):
        return False, f"добавленного отряда {side} нет", {}
    document["editor_warbands_add"] = left_over
    file.write_text(json.dumps(document, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return True, str(file), {"deleted": side}


#: ОДНА СБОРКА ЗА РАЗ. Кнопка Build редактора: фоновый процесс с логом,
#: статус — опросом. Вторая сборка при живой первой получает отказ.
_BUILD: dict = {"proc": None, "job": 0, "log": None, "maps": []}


def api_build_start(maps: list) -> tuple[bool, str, dict]:
    import subprocess as _sp
    if _BUILD["proc"] is not None and _BUILD["proc"].poll() is None:
        return False, f"сборка {_BUILD['job']} ещё идёт", {
            "job": _BUILD["job"], "running": True}
    numbers = sorted({int(n) for n in maps or []})
    _BUILD["job"] += 1
    _BUILD["maps"] = numbers
    journal = REPOSITORY_ROOT / ".editor_build.log"
    _BUILD["log"] = journal
    command = ["python", "-m", "knyaz2.content", "build",
               "--output", "content_build"]
    for num_ in numbers:
        command += ["--map", str(num_)]
    _BUILD["proc"] = _sp.Popen(
        command, cwd=str(REPOSITORY_ROOT),
        stdout=journal.open("wb"), stderr=_sp.STDOUT,
        stdin=_sp.DEVNULL)
    return True, "сборка пошла", {"job": _BUILD["job"], "maps": numbers}


def api_build_status() -> tuple[bool, str, dict]:
    process = _BUILD["proc"]
    if process is None:
        return True, "сборок не было", {"running": False, "job": 0}
    code = process.poll()
    tail = []
    if _BUILD["log"] and Path(_BUILD["log"]).is_file():
        lines = Path(_BUILD["log"]).read_text(
            encoding="utf-8", errors="replace").strip().splitlines()
        tail = lines[-3:]
    return True, "статус", {
        "running": code is None, "job": _BUILD["job"],
        "maps": _BUILD["maps"],
        "code": code, "tail": tail,
    }


#: UNDO/REDO — СНИМКАМИ ФАЙЛОВ. Каждая мутация API v2 сначала кладёт в
#: журнал сжатые копии файлов карты, которые тронет (по слою пути они
#: известны наперёд); undo возвращает файлы и переносит запись в
#: redo-стек. Глубина ограничена — журнал живёт в памяти процесса; git
#: проекта остаётся «вечным undo».
UNDO_DEPTH = 30
_UNDO: list[dict] = []
_REDO: list[dict] = []

#: Какие файлы карты трогает слой мутации. Слой, которого здесь нет,
#: НЕ попадает в журнал отмены: Ctrl+Z после него молча откатывает
#: ПРЕДЫДУЩУЮ правку — так было с выходами и деревней.
_LAYER_FILES = {
    "terrain": ("layer1.png", "layer2.png"),
    "water": ("map.json",),
    "objects": ("map.json",),
    "overlays": ("map.json",),
    "exits": ("map.json",),
    "cells": ("grid.txt",),
    "units": ("scenario.json",),
    "loot": ("scenario.json",),
    "warbands": ("scenario.json",),
    "village": ("scenario.json",),
}


def _mutation_files(path_str: str) -> list[Path]:
    parts_ = path_str.strip("/").split("/")
    tail = parts_[2:]
    if len(tail) == 5 and tail[0] == "worlds" and tail[2] == "maps":
        return [PROJECT_WORLDS / tail[1] / "maps" / f"{tail[3]}.json"]
    if len(tail) == 3 and tail[:2] == ["story", "dialog"]:
        # какой файл держит диалог — узнаётся разбором; снимаем ВСЕ
        # qst и их json-разборы разом дорого, поэтому находим хозяина
        try:
            for file_name, document in _story_files().items():
                for item in document["items"]:
                    if item["kind"] == "script" and item["name"] ==                             unquote(tail[2]):
                        return [PROJECT_STORY / "qst" / file_name,
                                PROJECT_STORY / "files"
                                / f"{file_name}.json"]
        except FileNotFoundError:
            return []
        return []
    if len(tail) >= 3 and tail[0] == "maps":
        folder = project_map_dir(int(tail[1]))
        if folder is None:
            return []
        names = _LAYER_FILES.get(tail[2]) or ()
        return [folder / name_ for name_ in names]
    return []


def _journal_snapshot(path_str: str) -> dict | None:
    files = _mutation_files(path_str)
    if not files:
        return None
    return {"path": path_str, "files": {
        str(file): (gzip.compress(file.read_bytes(), 1)
                    if file.is_file() else None)
        for file in files}}


def _journal_push(snapshot: dict | None) -> None:
    if not snapshot:
        return
    _UNDO.append(snapshot)
    del _UNDO[:-UNDO_DEPTH]
    _REDO.clear()


def _snapshot_apply(snapshot: dict) -> dict:
    """Вернуть файлы из снимка, сняв встречный снимок для другого стека."""
    oncoming = {"path": snapshot["path"], "files": {}}
    for name_, packed_data in snapshot["files"].items():
        file = Path(name_)
        oncoming["files"][name_] = (gzip.compress(file.read_bytes(), 1)
                                   if file.is_file() else None)
        if packed_data is None:
            if file.is_file():
                file.unlink()
        else:
            file.write_bytes(gzip.decompress(packed_data))
    return oncoming


def api_undo() -> tuple[bool, str, dict]:
    if not _UNDO:
        return False, "откатывать нечего", {}
    snapshot = _UNDO.pop()
    _REDO.append(_snapshot_apply(snapshot))
    return True, f"откатил {snapshot['path']}", {
        "undone": snapshot["path"], "left": len(_UNDO)}


def api_redo() -> tuple[bool, str, dict]:
    if not _REDO:
        return False, "повторять нечего", {}
    snapshot = _REDO.pop()
    _UNDO.append(_snapshot_apply(snapshot))
    return True, f"вернул {snapshot['path']}", {
        "redone": snapshot["path"], "left": len(_REDO)}


def api_history() -> tuple[bool, str, dict]:
    return True, "журнал", {
        "undo": [z_["path"] for z_ in _UNDO],
        "redo": [z_["path"] for z_ in _REDO]}


# ── ВАЛИДАТОР КАРТЫ ──────────────────────────────────────────────────────
def api_validate(number: int, content_root=None) -> tuple[bool, str, dict]:
    """Ошибки и предупреждения карты: битые ссылки, дырки таблиц,
    юниты в глуши, отсутствие выходов. Лимиты держит сам формат."""
    folder = project_map_dir(number)
    if folder is None:
        return False, f"нет проектной карты с номером {number}", {}
    errs: list[str] = []
    troubles: list[str] = []
    root = Path(content_root or DEFAULT_CONTENT_ROOT)
    document = json.loads((folder / "map.json").read_text(encoding="utf-8"))

    # 1. T_OBJECTS/T_DYNAMIC: движок читает до первого «стопа» —
    # дырки и записи за сентинелом невидимы оригиналу
    for table, mark in (("objects", "объектов"),
                           ("dynamic", "оверлеев")):
        all_of = sorted(((document.get(table) or {}).get("records") or []),
                     key=lambda r: int(r["slot"]))
        sentinels = [int(r["slot"]) for r in all_of if _object_is_sentinel(r)]
        slots = [int(r["slot"]) for r in all_of
                 if not _object_is_sentinel(r)]
        if sentinels and slots and max(slots) > min(sentinels):
            errs.append(
                f"записи {mark} за сентинелом (стоп в слоте "
                f"{min(sentinels)}, записи до {max(slots)}): оригинальный "
                f"движок их не увидит")
        if slots and slots != list(range(slots[0], slots[0] + len(slots))):
            errs.append(
                f"дырки в таблице {mark} (слоты {slots[:8]}…): движок "
                f"обрежет чтение на первом пустом слоте")
        if slots and slots[0] != 0:
            troubles.append(f"таблица {mark} начинается со слота {slots[0]}")

    # 2. объекты: гнездо есть в каталоге пака
    passport = root / "assets" / "objects" / "index.json"
    nests = set()
    if passport.is_file():
        for key_ in json.loads(passport.read_text(encoding="utf-8")):
            game_name, slot, *_ = key_.split(":")
            if game_name == "canon":
                nests.add(int(slot))
        for r in (document.get("objects") or {}).get("records") or []:
            if _object_is_sentinel(r):
                continue
            nest = int(r.get("sprite", r.get("id", -1))) + 30
            if nest - 30 >= 0 and nest not in nests:
                troubles.append(f"объект в слоте {r['slot']}: гнезда "
                            f"{nest} нет в каталоге пака")

    # 3. draft-юниты: клетка в границах и не глушь, сторона знакома
    grid = None
    grid_file = folder / "grid.txt"
    if grid_file.is_file():
        grid = [line.split() for line in
                 grid_file.read_text(encoding="utf-8").splitlines()
                 if line and not line.startswith("#")]
    draft_list = _draft_of(folder)
    sides = {int(w.get("side", -1))
               for w in draft_list.get("editor_warbands_add") or []}
    pack = root / "maps" / str(number) / "map.json"
    if pack.is_file():
        pack_doc = json.loads(pack.read_text(encoding="utf-8"))
        for w in pack_doc.get("warbands") or []:
            sides.add(int(w.get("side", -1)))
        for lst in (pack_doc.get("warbands_by_world") or {}).values():
            for w in lst:
                sides.add(int(w.get("side", -1)))
    for unit in draft_list.get("editor_units_add") or []:
        name_ = unit.get("id") or "?"
        cell = unit.get("cell") or {}
        row_, col_i = int(cell.get("row", -1)), int(cell.get("col", -1))
        if not (0 <= row_ < GRID_ROWS and 0 <= col_i < GRID_COLS):
            errs.append(f"{name_}: клетка ({row_},{col_i}) вне сетки")
        elif grid is not None:
            lo = int(grid[row_][col_i].partition(":")[0], 16)
            if (lo & CELL_BLOCK_MASK) == CELL_BLOCK_MASK:
                errs.append(f"{name_}: клетка ({row_},{col_i}) — глушь")
        side_num = unit.get("side")
        if side_num is not None and int(side_num) not in sides:
            troubles.append(f"{name_}: сторона {side_num} не знакома ни отрядам "
                        f"пака, ни добавленным")

    # 4. вода у лимита формата: полная таблица — 512 клеток
    water_rows = _water_read(document)
    flooded = sum(1 for row_ in water_rows for b_ in row_ if b_)
    if flooded >= 480:
        troubles.append(f"вода у лимита: {flooded}/512 клеток формата .KN2")

    # 5. выходы: клетка выхода на карте есть? (бит 0x1000)
    if grid is not None:
        has_exit = any(
            int(cell.partition(":")[0], 16) & CELL_EXIT_BIT
            for line in grid for cell in line)
        if not has_exit:
            troubles.append("нет клеток подсказки выхода (бит 0x1000 — "
                        "курсор перехода); сами переходы задают зоны "
                        "выходов мира, проверьте их")

    return True, f"ошибок {len(errs)}, предупреждений {len(troubles)}", {
        "errors": errs, "warnings": troubles}


# ── СХЕМЫ ФОРМ ───────────────────────────────────────────────────────────
#: UI строит формы инспектора из этого словаря; новые поля доезжают без
#: правок UI. type: number|text|checkbox|select.
EDITOR_SCHEMA = {
    "unit": [
        {"key": "name", "type": "text", "label": "имя"},
        {"key": "level", "type": "number", "label": "уровень",
         "min": 1, "max": 99},
        {"key": "money", "type": "number", "label": "деньги", "min": 0},
        {"key": "palette", "type": "number", "label": "палитра"},
        {"key": "dialog_number", "type": "number", "label": "диалог №",
         "help": "255 — молчит; дерево перепекается сборкой"},
        {"key": "stats.health", "type": "number", "label": "здоровье"},
        {"key": "stats.armour", "type": "number", "label": "броня"},
        {"key": "speed", "type": "number", "label": "скорость"},
        {"key": "venom", "type": "number", "label": "яд"},
    ],
    "cell": [
        {"key": "blocked", "type": "checkbox", "label": "глушь (NoWay)"},
        {"key": "solid", "type": "checkbox",
         "label": "глушит стрелы (NoFly)"},
        {"key": "exit", "type": "checkbox", "label": "выход с карты"},
        {"key": "transparent", "type": "checkbox",
         "label": "юнит поверх (Transparency)"},
        {"key": "inner", "type": "checkbox", "label": "интерьер (Inner)"},
        {"key": "light", "type": "checkbox",
         "label": "дневной свет (Light)"},
        {"key": "upoff", "type": "checkbox",
         "label": "UpOff (движок не читает)"},
        {"key": "object", "type": "number", "label": "объект №",
         "min": 0, "max": 30},
    ],
    "water": [
        {"key": "stream", "type": "checkbox", "label": "Stream (течёт)",
         "help": "переключает тип ВСЕХ клеток карты"},
        {"key": "tile", "type": "number", "label": "тайл подложки"},
    ],
    "overlay": [
        {"key": "id", "type": "number", "label": "спрайт GRAPH"},
        {"key": "x", "type": "number", "label": "x"},
        {"key": "y", "type": "number", "label": "y"},
    ],
    "object": [
        {"key": "state", "type": "number", "label": "состояние",
         "help": "кадр из заголовка объекта"},
        {"key": "palette", "type": "number", "label": "палитра"},
        {"key": "x", "type": "number", "label": "x"},
        {"key": "y", "type": "number", "label": "y"},
    ],
    "loot": [
        {"key": "money", "type": "number", "label": "деньги", "min": 0},
        {"key": "buried", "type": "checkbox", "label": "тайник"},
    ],
    "warband": [
        {"key": "side", "type": "number", "label": "сторона",
         "min": 1, "max": 199},
        {"key": "on_player", "type": "checkbox",
         "label": "нападает на игрока"},
        {"key": "war_flags", "type": "number", "label": "флаги войны",
         "help": "бит 0x01 игрок, 0x04 отряды, 0x08 лишь в бою, "
                 "0x80 деревня; без битов 0x4F не воюет"},
    ],
}


# ── МИРЫ (исходники project/worlds, EDITOR_VISION E2) ────────────────────
PROJECT_WORLDS = REPOSITORY_ROOT / "project" / "worlds"


def api_worlds() -> tuple[bool, str, dict]:
    """Слоты героев: чьё это население и куда его писать.

    ОБЩИЙ НОМЕР — НЕ КЛЮЧ, и здесь это стоило бы дорого. Пак ключует
    население НОМЕРОМ СЛОТА ГЕРОЯ (units_by_world, 0…8), а слот — это
    ПАРА «игра + мир» (konung2.donor.HERO_SLOTS): слот 2 это канонный
    мир 2, а слот 1 — мир 1 ДОНОРСКОЙ игры, и это разные файлы.
    Исходники же в project/worlds — только канонные, папка N значит
    канонный мир N.

    Пока список отдавал голые номера папок, показ и запись разъезжались
    молча: редактор показывал население слота 1 (донорского), а правка
    по тому же числу ушла бы в КАНОННЫЙ мир 1 — в чужие данные, без
    единого признака, что что-то не так. Отдаём пару целиком и признак,
    можно ли слот править.
    """
    from konung2 import donor
    row_ = []
    for slot, pair in enumerate(donor.HERO_SLOTS):
        game_name, world_ = pair
        folder = PROJECT_WORLDS / str(world_)
        own = game_name == "canon" and (folder / "meta.json").is_file()
        record = {"slot": slot, "game": game_name, "world": world_,
                  #: править можно только то, чьи исходники у нас есть
                  "editable": own, "hero": None, "start_map": None,
                  "maps": 0, "map_numbers": []}
        if own:
            document = json.loads(
                (folder / "meta.json").read_text(encoding="utf-8"))
            record["hero"] = (document.get("hero") or {}).get("name")
            record["start_map"] = document.get("start_map")
            record["maps"] = len(document.get("maps") or {})
            #: НОМЕРА КАРТ, А НЕ ТОЛЬКО СЧЁТ. В мире 79 карт игры, и
            #: карты, СОЗДАННОЙ РЕДАКТОРОМ, среди них нет: у неё в
            #: исходниках мира нет записи вовсе. Редактор об этом не
            #: знал и предлагал тумблер «пишем в: мир» на любой карте —
            #: а запись падала с «карты 63 в мире 0 нет». Человек видел
            #: доступный на вид путь, который не работает никогда.
            record["map_numbers"] = sorted(
                int(i_.stem) for i_ in (folder / "maps").glob("*.json")
                if i_.stem.isdigit())
        row_.append(record)
    #: ИМЯ ГЕРОЯ — ИЗ ПАКА, И ПО НОМЕРУ СЛОТА. В мета-файлах мира его нет,
    #: и список выходил безымянным («0 ·», «1 ·»): выбирать героя по
    #: номеру можно только помня, кто где живёт. Имена лежат в
    #: shared.json (hero.starts) — том же месте, откуда их берёт экран
    #: «Новая игра», и там они перечислены В ПОРЯДКЕ СЛОТОВ. Прежде их
    #: разбирали по native_world, и для донорских героев это давало
    #: чужое имя: у слота 1 и канонного мира 1 номер один, а герой
    #: разный.
    common = Path(DEFAULT_CONTENT_ROOT) / "shared.json"
    if common.is_file():
        try:
            starts = (json.loads(common.read_text(encoding="utf-8"))
                      .get("hero") or {}).get("starts") or []
            for record in row_:
                #: своё объявление мира важнее общего списка: meta.json
                #: описывает ИМЕННО эти исходники, а shared.json —
                #: заполняет пробелы, прежде всего у донорских слотов,
                #: у которых своей папки нет вовсе
                slot = record["slot"]
                if not record.get("hero") and slot < len(starts):
                    record["hero"] = starts[slot].get("name")
        except ValueError:
            pass
    return True, f"{len(row_)} слотов героев", {"worlds": row_}


def api_world_meta(world: int) -> tuple[bool, str, dict]:
    meta = PROJECT_WORLDS / str(world) / "meta.json"
    if not meta.is_file():
        return False, f"мир {world} не экспортирован "                       f"(python -m konung2.worlds)", {}
    return True, str(meta), json.loads(meta.read_text(encoding="utf-8"))


#: ЧТО ВООБЩЕ ДОЕЗЖАЕТ ДО ИГРЫ. Список снят с konung2.worlds._write_unit
#: и _write_party — только эти поля сборка мира кладёт поверх raw,
#: остальное осело бы в json и молча не доехало. Белый список нужен и с
#: другой стороны: ручка писала ЛЮБОЕ поле, включая сам `raw`, — одна
#: опечатка в теле запроса стирала бы запись юнита целиком.
WORLD_UNIT_FIELDS = frozenset({
    "accuracy", "armour", "body", "breed", "breed_counter",
    "characteristics", "col", "current", "dialog", "direction",
    "experience", "face", "free_xp", "health", "level", "money",
    #: name_id/nick_id — НОМЕРА в таблицах exe (0xF0 и 0xF1), не строки:
    #: самих строк в GAME.<мир> нет. Без них добавленный житель обречён
    #: быть тёзкой записи, с которой снят. Список имён отдаёт
    #: /catalog/names.
    "name_id", "nick_id",
    "next_level", "palette", "pose", "row", "side", "skills", "speed",
    "venom",
})
WORLD_BAND_FIELDS = frozenset({
    "col", "count", "enemy_side", "fighting", "first_unit", "flags",
    "pose", "row", "war_flags", "zone", "roam", "on_player",
    "on_parties", "only_if_fighting", "on_special", "can_fight",
})


def _world_filter(fields: dict, allowed: frozenset) -> tuple[dict, list]:
    suitable = {k_: z_ for k_, z_ in fields.items() if k_ in allowed}
    surplus = sorted(set(fields) - allowed)
    return suitable, surplus


def api_world_unit_patch(world: int, number: int,
                         patch: dict) -> tuple[bool, str, dict]:
    """Правка юнита мира ПРЯМО в исходнике project/worlds: {index,
    patch} — поля ложатся в запись юнита карты; сборка мира кладёт их
    поверх raw. Это E2: мир редактируем без draft-заплаток."""
    file = PROJECT_WORLDS / str(world) / "maps" / f"{number}.json"
    if not file.is_file():
        return False, f"карты {number} в мире {world} нет", {}
    num_ = int(patch.get("index", -1))
    document = json.loads(file.read_text(encoding="utf-8"))
    unit = next((u for u in document.get("units") or []
                 if int(u.get("index", -1)) == num_), None)
    if unit is None:
        return False, f"юнита {num_} на карте {number} нет", {}
    fields, surplus = _world_filter(patch.get("patch") or {}, WORLD_UNIT_FIELDS)
    if surplus:
        return False, (f"эти поля сборка мира не пишет и до игры они не "
                       f"доедут: {', '.join(surplus)}"), {}
    if not fields:
        return False, "патч пуст", {}
    for key_, value in fields.items():
        if isinstance(value, dict) and isinstance(unit.get(key_), dict):
            unit[key_].update(value)
        else:
            unit[key_] = value
    file.write_text(json.dumps(document, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return True, str(file), {"index": num_, "unit": {
        k: unit.get(k) for k in ("name", "level", "side", "row", "col")}}


def _world_occupancy(world: int, documents: dict) -> tuple[set, set, dict]:
    """Что уже занято в таблицах мира: слоты отрядов и слоты юнитов.

    ПРАВДА — В БАЙТАХ GAME.<мир>, а не в нашем экспорте: отряд считается
    существующим, когда его счётчик (+0x1C) не ноль (так его и видит
    движок — map_parties пропускает нулевые). Но к байтам добавляем и то,
    что объявлено в json и ещё не собрано: иначе два добавления подряд
    выдали бы один и тот же свободный слот.

    Слот отряда И ЕСТЬ его сторона: «сторона юнита (+0x1B) равна НОМЕРУ
    его отряда» (konung2/gamefile.py map_parties, VA 0x415B20). Поэтому
    выбирая слот, мы выбираем и номер стороны.
    """
    import struct
    from konung2.worlds import _game_bytes
    data, layout = _game_bytes(world)
    o_start, o_total, o_stride = layout["parties"]
    _, u_total, _ = layout["units"]
    bands, units_ = set(), set()

    def occupy(first_one: int, how_many: int) -> None:
        for stride in range(how_many):
            if 0 <= first_one + stride < u_total:
                units_.add(first_one + stride)

    for slot in range(o_total):
        record = data[o_start + slot * o_stride:][:o_stride]
        first_one = struct.unpack_from("<H", record, 0x00)[0]
        tally, capacity = record[0x1C], record[0x1A]
        map_rec = struct.unpack_from("<H", record, 0x08)[0]
        war = record[0x1F]
        #: СЛОТ ОТРЯДА СВОБОДЕН, ТОЛЬКО ЕСЛИ ЗАПИСЬ ПУСТА ЦЕЛИКОМ.
        #: Одного «счётчик равен нулю» мало: в каждом мире есть СЕМЬ
        #: слотов с нулевым счётом, но заполненными map (140…146),
        #: war_flags 0x41 и first_unit — это зарезервированные записи, и
        #: заняв такую, мы бы её затёрли. (Мир 0: слоты 103, 105, 107,
        #: 109, 111, 113, 115 — сверено по байтам во всех шести мирах.)
        if tally or map_rec or war or first_one:
            bands.add(slot)
        #: ВМЕСТИМОСТЬ (+0x1A) ЗАНИМАЕТ МЕСТО НАПЕРЁД. У отряда игрока
        #: счёт 3, а вместимость 9: остальные шесть слотов ждут
        #: спутников, и первый же наём затрёт того, кого мы бы туда
        #: посадили. Держим занятым весь [first, first+max(счёт,
        #: вместимость)) — и у записей с нулевым счётом тоже.
        occupy(first_one, max(tally, capacity))
    for document in documents.values():
        for band in document.get("parties") or []:
            slot = int(band.get("slot", band.get("side", -1)))
            if slot >= 0:
                bands.add(slot)
            occupy(int(band.get("first_unit") or 0),
                   int(band.get("count") or 0))
        for unit in document.get("units") or []:
            units_.add(int(unit["index"]))
    #: КВЕСТ УМЕЕТ СНИМАТЬ ЮНИТА С КАРТЫ ПО НОМЕРУ. Обработчик 46
    #: (docs/ENGINE_TICK.md: «снятие юнита с карты») зовётся из дерева
    #: разговоров с ненулевыми аргументами — это индексы юнитов, и
    #: посаженный туда житель однажды молча исчезнет посреди игры.
    #: Читаем их у самого сюжета, а не держим списком: поменяются
    #: квесты — поменяется и запрет.
    for num_ in _quest_victims():
        units_.add(num_)
    return bands, units_, {"parties": o_total, "units": u_total}


_QUEST_VICTIMS: set | None = None


def _quest_victims() -> set:
    """Номера юнитов, которых сюжет снимает с карты обработчиком 46."""
    global _QUEST_VICTIMS
    if _QUEST_VICTIMS is None:
        try:
            from konung2.quests import Dialogs
            calls = Dialogs.from_game().handler_calls().get(46) or {}
            _QUEST_VICTIMS = {int(a_) for a_ in calls if int(a_) > 0}
        except Exception:
            #: сюжета под рукой нет — запрет не наложить, но и падать
            #: из-за этого нельзя: слоты просто чуть менее осторожны
            _QUEST_VICTIMS = set()
    return _QUEST_VICTIMS


def _world_documents(world: int) -> dict:
    """Все карты мира разом: таблицы общие, и занятость считается по ним."""
    folder = PROJECT_WORLDS / str(world) / "maps"
    done_flag = {}
    if folder.is_dir():
        for file in folder.glob("*.json"):
            try:
                done_flag[file.stem] = json.loads(
                    file.read_text(encoding="utf-8"))
            except ValueError:
                continue
    return done_flag


def editor_world_unit_add(world: int, number: int,
                          patch: dict) -> tuple[bool, str, dict]:
    """Новый житель в мир — своим отрядом в свободном слоте.

    ПОЧЕМУ СВОИМ, А НЕ В ЧУЖОЙ. Юниты живут не в карте, а в отрядах:
    отряд называет первого юнита (+0x00) и сколько их (+0x1C), и движок
    читает ровно этот НЕПРЕРЫВНЫЙ диапазон (VA 0x428240). Дописать
    бойца в существующий отряд можно, только если слот сразу за его
    хвостом свободен, — а он свободен лишь у 115 отрядов из 946: таблица
    упакована вплотную. Переезжать же отряд в свободный участок нельзя:
    на индексы юнитов ссылается запись деревни (village.master,
    officials, people), а её сборка мира НЕ переписывает — старейшина и
    торговцы оторвались бы молча.

    Поэтому основной путь — новый отряд: свободный слот (их около сорока
    в каждом мире) плюс свободный слот юнита (свободных больше тысячи).
    Ничего существующего при этом не двигается вовсе.

    ИМЯ НАСЛЕДУЕТСЯ ОТ ОБРАЗЦА: имена лежат в таблице exe, а не в
    GAME.<мир> (номер имени — байт +0xF0), и сборка мира их не пишет.
    Новый житель зовётся так же, как тот, с кого снята запись.
    """
    if not (PROJECT_WORLDS / str(world) / "maps" / f"{number}.json").is_file():
        return False, f"карты {number} в мире {world} нет", {}
    documents = _world_documents(world)
    own = documents.get(str(number)) or {}
    taken_bands, taken_units, sizes = _world_occupancy(world, documents)

    #: ОБРАЗЕЦ — ЖИВАЯ ЗАПИСЬ ЭТОЙ ЖЕ КАРТЫ. Без него у нового юнита
    #: поля вне белого списка (а их большинство) взялись бы из случайных
    #: байтов свободного слота.
    samples = own.get("units") or []
    sample = next((u for u in samples
                    if int(u.get("side", -1)) == int(patch.get("like_side", -1))),
                   None) or (samples[0] if samples else None)
    if sample is None or not sample.get("raw"):
        return False, ("на этой карте нет ни одного жителя мира, с чьей "
                       "записи снять образец — добавить пока не с чего"), {}

    side_num = patch.get("side")
    if side_num is not None:
        #: рост существующего отряда — только если хвост свободен
        side_num = int(side_num)
        band = next((x for x in own.get("parties") or []
                      if int(x.get("slot", x.get("side", -1))) == side_num),
                     None)
        if band is None:
            return False, f"отряда {side_num} на карте {number} нет", {}
        tail = int(band.get("first_unit") or 0) + int(band.get("count") or 0)
        if tail in taken_units or tail >= sizes["units"]:
            return False, (f"отряд {side_num} вплотную упёрся в соседа: слот "
                           f"{tail} занят. Движок читает бойцов отряда "
                           f"подряд, а двигать отряд нельзя — на индексы "
                           f"ссылается деревня. Добавьте отдельным отрядом "
                           f"(без поля side)"), {}
        unit_slot, band_slot, new_band = tail, side_num, None
        band["count"] = int(band.get("count") or 0) + 1
    else:
        band_slot = next((s_ for s_ in range(sizes["parties"])
                           if s_ not in taken_bands), None)
        unit_slot = next((s_ for s_ in range(sizes["units"])
                          if s_ not in taken_units), None)
        if band_slot is None or unit_slot is None:
            return False, "в мире не осталось свободных слотов", {}
        band_sample = next(iter(own.get("parties") or []), {})
        #: ЗОНА ПОЯВЛЕНИЯ — НЕ ДЕКОРАЦИЯ, А ГЛАВНОЕ ЗДЕСЬ ПОЛЕ. При
        #: свежем входе на карту движок рассыпает отряд по этому
        #: прямоугольнику случайно и ПЕРЕЗАПИСЫВАЕТ клетки юнита
        #: (FUN_00415764, вызов из 0x0043DF48). Первая версия копировала
        #: зону у образца — и клик мышью оказывался враньём: житель
        #: уезжал туда, где стоит чужой отряд. На живых данных мира 0
        #: это видно насквозь: бит 0x10 стоит у 49 отрядов из 118, и
        #: все их 243 юнита несут настоящие клетки, а у прочих 423 из
        #: 432 записаны нули — координаты им попросту не нужны.
        #:
        #: Держим двойную защиту. Бит 0x10 (zone.keep_cells, байт 0x1E)
        #: велит движку оставить записанное. Вырожденный прямоугольник
        #: 1x1 даёт тот же ответ и БЕЗ бита: при row_from == row_to
        #: разброс равен нулю, а центр (r + r + 1) // 2 == r.
        #: Бродяжничество (0x0E/0x12/0x15/0x17) — ДРУГИЕ байты, их
        #: сборка мира не пишет, и они приезжают с образцом в raw.
        from konung2.gamefile import PARTY_KEEP_CELLS
        line = int(patch.get("row", sample.get("row") or 0))
        col_ = int(patch.get("col", sample.get("col") or 0))
        zone = dict(patch.get("zone") or {
            "row_from": line, "row_to": line,
            "col_from": col_, "col_to": col_})
        zone["flags"] = int(zone.get("flags") or
                            (band_sample.get("zone") or {}).get("flags")
                            or 0) | PARTY_KEEP_CELLS
        new_band = {
            "slot": band_slot, "side": band_slot,
            "first_unit": unit_slot, "count": 1, "map": number,
            "zone": zone,
            #: вражду не выдумываем: у мирного образца она мирная
            "war_flags": int(patch.get("war_flags",
                                       band_sample.get("war_flags") or 0)),
        }
        if band_sample.get("raw"):
            new_band["raw"] = band_sample["raw"]
        own.setdefault("parties", []).append(new_band)

    #: ЗАПИСЬ — ПОЛНАЯ КОПИЯ ОБРАЗЦА, а не огрызок из пары полей. На
    #: байты это не влияет (их несёт raw), но json обязан читаться: с
    #: половиной полей в None инспектор редактора показывал бы пустоту,
    #: а повторный экспорт мира выдал бы совсем другую запись.
    #:
    #: МЕСТА РАБОТЫ НЕ НАСЛЕДУЕМ. workplaces — это занятые места в
    #: деревне (кузня, лавка), и скопировав их, мы посадили бы двоих на
    #: одно место. Новый житель приходит без должности.
    #: Места работы живут В БАЙТАХ записи (0xE6, до восьми, конец —
    #: отрицательный байт: konung2/gamefile.py unit_workplaces), поэтому
    #: чистить их надо в самом клоне, а не в полях json.
    from konung2.gamefile import WORKPLACES_AT
    raw_bytes = bytearray(bytes.fromhex(sample["raw"]))
    raw_bytes[WORKPLACES_AT] = 0xFF
    new_one = json.loads(json.dumps(sample))
    new_one["workplaces"] = []
    new_one.update({"index": unit_slot, "raw": raw_bytes.hex(),
                  "side": band_slot, "party": band_slot,
                  "row": int(patch.get("row", sample.get("row") or 0)),
                  "col": int(patch.get("col", sample.get("col") or 0))})
    fields, surplus = _world_filter(patch.get("patch") or {}, WORLD_UNIT_FIELDS)
    if surplus:
        return False, (f"эти поля сборка мира не пишет и до игры они не "
                       f"доедут: {', '.join(surplus)}"), {}
    new_one.update(fields)
    own.setdefault("units", []).append(new_one)
    file = PROJECT_WORLDS / str(world) / "maps" / f"{number}.json"
    file.write_text(json.dumps(own, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return True, str(file), {
        "index": unit_slot, "side": band_slot,
        "new_party": new_band is not None,
        "name": new_one.get("name"),
        "free_parties": sizes["parties"] - len(taken_bands) - 1,
        "free_units": sizes["units"] - len(taken_units) - 1}


def api_world_party_patch(world: int, number: int,
                          patch: dict) -> tuple[bool, str, dict]:
    """Правка отряда мира: {slot, patch} — зона, вражда, счёт."""
    file = PROJECT_WORLDS / str(world) / "maps" / f"{number}.json"
    if not file.is_file():
        return False, f"карты {number} в мире {world} нет", {}
    slot = int(patch.get("slot", -1))
    document = json.loads(file.read_text(encoding="utf-8"))
    band = next((x for x in document.get("parties") or []
                  if int(x.get("slot", x.get("side", -1))) == slot), None)
    if band is None:
        return False, f"отряда {slot} на карте {number} нет", {}
    fields, surplus = _world_filter(patch.get("patch") or {}, WORLD_BAND_FIELDS)
    if surplus:
        return False, (f"эти поля сборка мира не пишет и до игры они не "
                       f"доедут: {', '.join(surplus)}"), {}
    if not fields:
        return False, "патч пуст", {}
    for key_, value in fields.items():
        if isinstance(value, dict) and isinstance(band.get(key_),
                                                     dict):
            band[key_].update(value)
        else:
            band[key_] = value
    file.write_text(json.dumps(document, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return True, str(file), {"slot": slot}


def api_world_build(world: int) -> tuple[bool, str, dict]:
    """Собрать GAME.<мир> из исходников — секунды: мир после этого
    читается всеми одной точкой (_game_bytes берёт собранный файл
    приоритетно); пак пересобирать по-прежнему нужно (Build)."""
    from konung2.worlds import build_world
    try:
        file = build_world(world, PROJECT_WORLDS)
    except (OSError, ValueError, KeyError) as trouble:
        return False, str(trouble), {}
    return True, str(file), {"built": file.name,
                             "bytes": file.stat().st_size}


def api_world_map(world: int, number: int) -> tuple[bool, str, dict]:
    file = PROJECT_WORLDS / str(world) / "maps" / f"{number}.json"
    if not file.is_file():
        return False, f"карты {number} в мире {world} нет", {}
    return True, str(file), json.loads(file.read_text(encoding="utf-8"))


# ── СЮЖЕТ (E3): .QST ↔ JSON, узловой редактор диалогов ──────────────────
PROJECT_STORY = REPOSITORY_ROOT / "project" / "story"


def _story_files() -> dict:
    """Разбор исходников сюжета проекта (после konung2-story экспорта)."""
    from konung2.story import load_sources
    root_ = PROJECT_STORY / "qst"
    if not root_.is_dir():
        raise FileNotFoundError(
            "сюжет не экспортирован: python -m konung2.story")
    return load_sources(root_)


def api_story() -> tuple[bool, str, dict]:
    """Сводка сюжета: файлы, диалоги, токены, валидация."""
    from konung2.story import validate_story
    try:
        files = _story_files()
    except FileNotFoundError as trouble:
        return False, str(trouble), {}
    summary = validate_story(files)
    #: СВОЙ ДИАЛОГ ИЛИ АВТОРСКИЙ — по тому, есть ли файл в посылке
    #: исходников: канонные .QST только для чтения (правка канонного
    #: дерева меняет разговор на всех картах сразу), свои живут своими
    #: файлами. Без этой пометки в списке из полутора сотен строк не
    #: видно, какие три из них твои.
    from konung2.story import QUESTS_DIR
    dialogs = []
    for file_name, document in files.items():
        own = not (QUESTS_DIR / file_name).is_file()
        for item in document["items"]:
            if item["kind"] != "script":
                continue
            section_count = sum(1 for n in item["nodes"]
                         if n.get("type") == "section")
            dialogs.append({"name": item["name"], "file": file_name,
                            "own": own, "sections": section_count})
    tokens = []
    for document in files.values():
        for item in document["items"]:
            if item["kind"] == "token":
                tokens.append({"name": item["name"],
                               "text": item.get("text")})
    from konung2.story import script_numbers
    try:
        numbers = script_numbers()
    except OSError:
        numbers = {}
    for dialog in dialogs:
        dialog["number"] = numbers.get(dialog["name"])
    return True, f"{len(dialogs)} диалогов", {
        "dialogs": dialogs, "tokens": tokens,
        "validation": {k: summary[k] for k in
                       ("dialogs", "unknown_tokens", "unused_tokens",
                        "unknown_globals", "global_entries")},
    }


def api_story_dialog(name: str) -> tuple[bool, str, dict]:
    """Граф одного диалога для узлового редактора: узлы (switch/
    section) + достижимость."""
    from konung2.story import validate_dialog
    try:
        files = _story_files()
    except FileNotFoundError as trouble:
        return False, str(trouble), {}
    for file_name, document in files.items():
        for item in document["items"]:
            if item["kind"] == "script" and item["name"] == name:
                clean_ones = [{k: v for k, v in n.items() if k != "raw"}
                          for n in item["nodes"]]
                #: ЗАПИСИ ЖУРНАЛА ЖИВУТ В ТОКЕНАХ ЭТОГО ЖЕ ФАЙЛА.
                #: Токен со своим {TEXT} — это строка журнала игрока
                #: (её печёт таблица квестов), и до сих пор задать её
                #: можно было только при заведении диалога: в панели
                #: токенов не было вовсе, и в журнал уходило машинное
                #: «Имя_Диалога: задание взято.» с подчёркиваниями.
                tokens = [{"name": z_["name"], "text": z_.get("text")}
                          for z_ in document["items"]
                          if z_.get("kind") == "token"]
                return True, file_name, {
                    "file": file_name, "name": name,
                    "header": item.get("header"),
                    "nodes": clean_ones,
                    "tokens": tokens,
                    "validation": validate_dialog(item),
                }
    return False, f"диалога «{name}» нет", {}


#: ПЕРЕВОД ИМЕНИ В ИМЯ ФАЙЛА. Компилятору всё равно, а вот в каталоге
#: сюжета файлы восьмибуквенные латинские (BADHEAL.QST, MERC_RM2.QST) —
#: держим тот же вид, чтобы свои файлы не выделялись видом и открывались
#: любым инструментом.
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def _story_file_name(name: str, taken: set[str]) -> str:
    latin = []
    for sign in name:
        low = sign.lower()
        if low in _TRANSLIT:
            latin.append(_TRANSLIT[low])
        elif sign.isascii() and sign.isalnum():
            latin.append(sign)
    stem = ("".join(latin).upper() or "QUEST")[:8]
    file_name = f"{stem}.QST"
    number = 1
    while file_name in taken:
        tail = str(number)
        file_name = f"{stem[:8 - len(tail)]}{tail}.QST"
        number += 1
    return file_name


#: Типографика, которой нет в cp866: правим сами (замена однозначная), а
#: на всё прочее незаписуемое отвечаем отказом с перечнем знаков —
#: молча портить чужой текст нельзя.
#:
#: ЁЛОЧКИ ТОЖЕ В СПИСКЕ: кодировка их не знает (Python на U+00AB
#: отвечает «character maps to undefined»), а в русской реплике они
#: первые кандидаты. Авторские диалоги обходятся простыми кавычками
#: — так же пишем и мы.
_CP866_FIX = {"—": "-", "–": "-", "―": "-", "…": "...", " ": " ",
              "«": '"', "»": '"',
              "“": '"', "”": '"', "„": '"', "‘": "'", "’": "'"}


def _story_file_tail(text: str) -> str:
    """Хвост файла .QST: один перевод строки и метка конца.

    ПОВТОРНОЕ СОХРАНЕНИЕ НЕ ДОЛЖНО МЕНЯТЬ ФАЙЛ. Разбор забирает хвост
    файла как есть, а вывод дописывает свой перевод строки — и файл рос
    на байт с каждой правкой (замер: три сохранения подряд, 2112 → 2113
    → 2114). Пустые строки в конце не значат ничего, поэтому приводим их
    к одному виду.
    """
    return text.rstrip("\r\n \t\x1a") + "\n\x1a"


def _cp866_text(text: str) -> tuple[str, str]:
    clean = "".join(_CP866_FIX.get(sign, sign) for sign in text or "")
    bad = sorted({sign for sign in clean
                  if sign.encode("cp866", "ignore") == b""})
    return clean, "".join(bad)


def _squad_index(map_number: int, side: int, content_root) -> int | None:
    """Место отряда в счёте карты — довод условия «карта зачищена».

    Условие `<?all_killed:N>` разбирается как `карта = N & 0xFF`,
    `отряд = N >> 8` (dialog.js, обработчик 0), а отряды считаются так:
    берутся все НЕ свои юниты, их стороны сортируются по возрастанию, и
    номер отряда — место стороны в этом списке (mapstate.js mapSquads).
    Считать это руками — верный способ ошибиться: у своей карты 64
    мирный житель занимал место 0, а скелет — место 1, хотя враждебный
    отряд на карте один.
    """
    root = Path(content_root or DEFAULT_CONTENT_ROOT)
    file = root / "maps" / str(map_number) / "map.json"
    if not file.is_file():
        return None
    document = json.loads(file.read_text(encoding="utf-8"))
    own = {band.get("side") for band in document.get("warbands") or []
           if band.get("player")}
    sides = sorted({unit.get("side") for unit in document.get("units") or []
                    if unit.get("side") not in own})
    return sides.index(side) if side in sides else None


def api_story_dialog_new(patch: dict, content_root) -> tuple[bool, str, dict]:
    """Завести СВОЙ диалог: файл, включение в сборку, номер.

    Руками это пять шагов, и четыре из них были вне редактора: написать
    .QST, дописать `#include` в KONUNG2.QST, скомпилировать, найти номер
    в QUESTS.LOG и вписать его юниту. Здесь всё, кроме привязки к юниту
    (её делает инспектор), — одной ручкой.

    КОМПИЛЯЦИЯ — ВОРОТА, как у правки диалога: файлы пишутся, сюжет
    собирается целиком, и если компилятор ругнулся — обе записи
    откатываются, чтобы сюжет проекта не остался сломанным.
    """
    from konung2.story import QUESTS_DIR, load_sources, render_file
    name = (patch.get("name") or "").strip().replace(" ", "_")
    if not name:
        return False, "у диалога должно быть имя", {}
    if not re.fullmatch(r"[\wЀ-ӿ]+", name):
        return False, ("в имени диалога только буквы, цифры и подчёркивание: "
                       f"«{name}» компилятор не примет"), {}
    root_ = PROJECT_STORY / "qst"
    if not root_.is_dir():
        return False, "сюжет не экспортирован: python -m konung2.story", {}
    files = load_sources(root_)
    for file_name, document in files.items():
        for item in document.get("items") or ():
            if item.get("kind") == "script" and item.get("name") == name:
                return False, (f"диалог «{name}» уже есть в {file_name}"), {}
    file_name = _story_file_name(name, set(files) | {
        entry.name for entry in QUESTS_DIR.iterdir()})

    def clean(text: str, what: str) -> str:
        body, bad = _cp866_text(text)
        if bad:
            raise ValueError(f"{what}: знаки «{bad}» не пишутся в cp866 — "
                             "замените их")
        return body

    kind = patch.get("kind") or "plain"
    try:
        greeting = clean(patch.get("greeting")
                         or "Здравствуй, добрый человек.", "первая реплика")
        answer = clean(patch.get("answer") or "И тебе не хворать.", "ответ")
        items: list[dict] = []
        nodes: list[dict] = []
        if kind == "quest":
            # квест «убей отряд»: номер отряда считаем сами — руками его
            # выводят из карты и стороны, и это первое, где ошибаются
            map_number = int(patch.get("map") or 0)
            side = int(patch.get("side") or 0)
            place = _squad_index(map_number, side, content_root)
            if place is None:
                return False, (f"на карте {map_number} нет отряда стороны "
                               f"{side} — соберите карту в пак и выберите "
                               "отряд из списка"), {}
            aim = map_number + (place << 8)
            stem = re.sub(r"\W+", "_", name.upper())[:24]
            take, done = f"{stem}_ЗАДАНИЕ", f"{stem}_СДЕЛАНО"
            items.append({"kind": "token", "name": take, "text": clean(
                patch.get("journal_take")
                or f"{name}: задание взято.", "запись журнала (задание)")})
            items.append({"kind": "token", "name": done, "text": clean(
                patch.get("journal_done")
                or f"{name}: задание выполнено.",
                "запись журнала (выполнено)")})
            money = max(0, int(patch.get("money") or 25))
            experience = max(0, int(patch.get("exp") or 100))
            texts = {key: clean(patch.get(key) or fallback, key) for
                     key, fallback in (
                ("remind", "Враг ещё жив — не тяни, добрый человек."),
                ("reward", "Управился! Держи, что обещано."),
                ("after", "Спокойно у нас теперь, спасибо тебе."))}
            nodes = [
                {"type": "switch", "name": "*", "cases": [
                    {"cond": f"(<{done}>)", "target": "ПОСЛЕ"},
                    {"cond": f"(<{take}>&<?all_killed:{aim}>)",
                     "target": "НАГРАДА"},
                    {"cond": f"(<{take}>)", "target": "НАПОМИНАНИЕ"},
                    {"cond": "()", "target": "ЗНАКОМСТВО"}]},
                {"type": "section", "name": "ЗНАКОМСТВО",
                 "reply": {"texts": [{"text": greeting}]},
                 "answers": [
                     {"do": f"<+{take}>", "target": "END_OF_DIALOG",
                      "texts": [{"text": answer}]},
                     {"target": "END_OF_DIALOG",
                      "texts": [{"text": "Мне некогда."}]}]},
                {"type": "section", "name": "НАПОМИНАНИЕ",
                 "reply": {"texts": [{"text": texts["remind"]}]},
                 "answers": [{"target": "END_OF_DIALOG",
                              "texts": [{"text": "Иду."}]}]},
                {"type": "section", "name": "НАГРАДА",
                 "reply": {"texts": [{"text": texts["reward"]}]},
                 "answers": [{"do": f"<-{take}><+{done}>"
                              f"<money:{money}><exp:{experience}>",
                              "target": "END_OF_DIALOG",
                              "texts": [{"text": "Живите с миром."}]}]},
                {"type": "section", "name": "ПОСЛЕ",
                 "reply": {"texts": [{"text": texts["after"]}]},
                 "answers": [{"target": "END_OF_DIALOG",
                              "texts": [{"text": "Доброго дня."}]}]}]
        else:
            nodes = [{"type": "section", "name": "*",
                      "reply": {"texts": [{"text": greeting}]},
                      "answers": [{"target": "END_OF_DIALOG",
                                   "texts": [{"text": answer}]}]}]
    except ValueError as trouble:
        return False, str(trouble), {}
    comment = clean(patch.get("comment") or "", "пометка")
    #: Шапка и пустые строки между блоками — как в авторских файлах:
    #: свой .QST человек будет читать и править глазами.
    items.insert(0, {"kind": "plain",
                     "raw": f"*  свой диалог: {name}\n\n"})
    items = [part for item in items
             for part in (item, {"kind": "gap", "raw": "\n"})]
    items.append({"kind": "script", "name": name, "dirty": True,
                  "header": "{SCRIPT=%s%s" % (
                      name, f" ({comment})" if comment else ""),
                  "nodes": [{**node, "dirty": True} for node in nodes]})
    text_ = render_file({"file": file_name, "items": items})

    project = root_ / "KONUNG2.QST"
    before = project.read_bytes() if project.is_file() else None
    if before is None:
        return False, ("нет project/story/qst/KONUNG2.QST — сборка сюжета "
                       "не найдёт новый файл"), {}
    #: Включение — последней строкой, ПЕРЕД меткой конца файла (0x1A):
    #: так номера токенов и деревьев ложатся ЗА канонными, и канон не
    #: съезжает (сверка 0…151 с игровым QUESTS.RES после этого — ноль
    #: расхождений).
    mark = before.endswith(b"\x1a")
    body = before[:-1] if mark else before
    joint = f"\r\n*  свой диалог: {name}\r\n#include {file_name.lower()}\r\n"
    (root_ / file_name).write_bytes(text_.encode("cp866"))
    project.write_bytes(body + joint.encode("cp866")
                        + (b"\x1a" if mark else b""))
    ok_, note_, _ = api_story_compile()
    if not ok_:
        (root_ / file_name).unlink(missing_ok=True)
        project.write_bytes(before)
        return False, "компилятор отверг: " + note_, {}
    from konung2.story import script_numbers
    number = script_numbers().get(name)
    return True, (f"диалог «{name}» заведён: {file_name}, номер {number}; "
                  + note_), {"name": name, "file": file_name,
                             "number": number}


def api_story_dialog_drop(name: str) -> tuple[bool, str, dict]:
    """Убрать СВОЙ диалог: файл, строка включения, пересборка сюжета.

    Без этого опечатка в имени оставалась в сюжете навсегда. Ворота
    жёсткие, и вот почему:

    * канонные файлы не трогаем вовсе — их правка меняет разговор всей
      игре (тот же уговор, что у правки диалога);
    * убрать можно только ПОСЛЕДНИЙ по счёту диалог. Номера деревьев
      задаёт порядок компиляции: выньте средний — и все, кто за ним,
      сдвинутся на единицу, а `dialog_number` у юнитов останется
      прежним, и жители заговорят чужими репликами;
    * если номер кому-то назначен, сперва отвяжите — иначе тот же сдвиг,
      только сразу и молча.
    """
    from konung2.story import QUESTS_DIR, load_sources, script_numbers
    root_ = PROJECT_STORY / "qst"
    files = load_sources(root_)
    file_name = next((name_ for name_, doc in files.items()
                      if any(item.get("kind") == "script"
                             and item.get("name") == name
                             for item in doc.get("items") or ())), None)
    if file_name is None:
        return False, f"диалога «{name}» нет", {}
    if (QUESTS_DIR / file_name).is_file():
        return False, (f"{file_name} — авторский файл игры, он только для "
                       "чтения"), {}
    numbers = script_numbers()
    number = numbers.get(name)
    if number is not None and number != max(numbers.values()):
        return False, (f"«{name}» идёт номером {number}, а последний — "
                       f"{max(numbers.values())}: если убрать его сейчас, "
                       "все диалоги за ним сдвинутся, и юниты заговорят "
                       "чужими репликами. Убирайте с конца."), {}
    for folder in sorted(PROJECT_MAPS.glob("*")):
        scenario = folder / "scenario.json"
        if not scenario.is_file():
            continue
        document = json.loads(scenario.read_text(encoding="utf-8"))
        for unit in document.get("editor_units_add") or ():
            if unit.get("dialog_number") == number:
                return False, (f"диалог {number} назначен юниту "
                               f"«{unit.get('name')}» в {folder.name} — "
                               "сперва отвяжите его в инспекторе"), {}
    project = root_ / "KONUNG2.QST"
    before = project.read_bytes()
    kept = [line for line in before.decode("cp866").splitlines(True)
            if file_name.lower() not in line.lower()
            and line.strip() != f"*  свой диалог: {name}"]
    (root_ / file_name).unlink(missing_ok=True)
    #: ХВОСТ ПРИВОДИМ К ОДНОМУ ВИДУ. Выброшенные строки включения
    #: оставляли после себя пустые, и от каждой пары «завёл — убрал»
    #: файл проекта прирастал двумя (замер: пять пустых строк перед
    #: меткой конца после трёх проб).
    project.write_bytes(_story_file_tail(
        "".join(kept)).encode("cp866"))
    (PROJECT_STORY / "files" / f"{file_name}.json").unlink(missing_ok=True)
    ok_, note_, _ = api_story_compile()
    if not ok_:
        project.write_bytes(before)
        return False, "компилятор отверг: " + note_, {}
    return True, f"диалог «{name}» убран ({file_name}); " + note_, {
        "name": name, "file": file_name}


def api_story_dialog_save(name: str, patch: dict) -> tuple[bool, str,
                                                           dict]:
    """Записать диалог из JSON: перерендер файла в project/story/qst и
    КОМПИЛЯЦИЯ-ВОРОТА — M_QUEST в песочнице обязан собрать сюжет без
    ошибок, иначе правка откатывается."""
    import shutil
    import subprocess
    import tempfile
    from konung2.story import (QUESTS_DIR, load_sources, parse_file,
                               render_file, validate_dialog)
    nodes = patch.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        return False, "в патче нет узлов диалога", {}
    #: ТИПОГРАФИКУ ПРАВИМ ДО ЗАПИСИ. Текст приходит из браузера, где
    #: длинное тире, многоточие и ёлочки набираются сами собой, а в
    #: cp866 их нет: без этого сохранение падало прямо на `encode`
    #: невнятным «charmap codec can't encode character», и человек терял
    #: набранную реплику. Однозначные замены делаем молча, на всё прочее
    #: незаписуемое отвечаем списком знаков.
    strange: set[str] = set()

    def _plain(value):
        if isinstance(value, dict):
            return {key_: _plain(item) for key_, item in value.items()}
        if isinstance(value, list):
            return [_plain(item) for item in value]
        if isinstance(value, str):
            #: ХВОСТОВЫЕ ПРОБЕЛЫ КОПИЛИСЬ ОТ СОХРАНЕНИЯ К СОХРАНЕНИЮ:
            #: разбор берёт текст вместе с отступом перед закрывающей
            #: скобкой, а вывод дописывает свой перевод строки — за три
            #: правки реплика «Доброго дня.» обросла двумя пустыми
            #: строками. Правому краю в диалоге значить нечего.
            body, bad = _cp866_text(value.rstrip())
            strange.update(bad)
            return body
        return value

    nodes = _plain(nodes)
    if strange:
        return False, ("эти знаки не пишутся в cp866: "
                       + "".join(sorted(strange))), {}
    root_ = PROJECT_STORY / "qst"
    files = load_sources(root_)
    # СЮЖЕТ ИГРЫ — ТОЖЕ КАНОН. Правка канонного дерева меняет разговор
    # на ВСЕХ картах сразу (сборка печёт деревья юнитов из общего
    # QUESTS.RES), и один такой заход уже испортил диалог Лешего всей
    # игре. Свои квесты живут своими файлами: канонные .QST — те, что
    # лежат в посылке авторских исходников, они только для чтения.
    native = next((name_ for name_, doc in files.items()
                   if any(item.get("kind") == "script" and
                          item.get("name") == name
                          for item in doc.get("items") or ())), None)
    if native and (QUESTS_DIR / native).is_file():
        return False, (
            f"диалог «{name}» лежит в {native} — это авторский сюжет "
            f"игры, он держится байт в байт равным исходникам. Свои "
            f"квесты пишите своим файлом: он подключается к сборке "
            f"сюжета и не трогает канон."), {}
    for file_name, document in files.items():
        for at, item in enumerate(document["items"]):
            if item["kind"] != "script" or item["name"] != name:
                continue
            new_one = {"kind": "script", "name": name,
                     "header": item.get("header"), "dirty": True,
                     "nodes": [{**n, "dirty": True} for n in nodes]}
            for n in new_one["nodes"]:
                n.pop("raw", None)
            checkup = validate_dialog(new_one)
            if checkup["errors"]:
                return False, "; ".join(checkup["errors"]), {
                    "validation": checkup}
            document["items"][at] = new_one
            #: ТОКЕНЫ ПРАВИМ ЗДЕСЬ ЖЕ. Правленому токену снимаем `raw`
            #: (иначе вывод напишет прежний текст байт в байт), новый
            #: кладём ПЕРЕД скриптом: компилятор читает файл сверху вниз,
            #: и объявление обязано идти раньше упоминания.
            wanted = patch.get("tokens")
            if isinstance(wanted, list):
                known = {z_["name"]: z_ for z_ in document["items"]
                         if z_.get("kind") == "token"}
                fresh = []
                for row in wanted:
                    name_t = str(row.get("name") or "").strip()
                    if not re.fullmatch(r"[\wЀ-ӿ]+", name_t):
                        return False, (f"имя записи «{name_t}»: только "
                                       "буквы, цифры и подчёркивание"), {}
                    body = (row.get("text") or "").strip() or None
                    if name_t in known:
                        known[name_t]["text"] = body
                        known[name_t].pop("raw", None)
                    else:
                        fresh.append({"kind": "token", "name": name_t,
                                      "text": body})
                for row in reversed(fresh):
                    document["items"].insert(at, row)
                    document["items"].insert(at + 1,
                                             {"kind": "gap", "raw": "\n"})
            text_ = _story_file_tail(render_file(document)).encode("cp866")
            # ворота: собрать ВЕСЬ сюжет с этой правкой в песочнице
            with tempfile.TemporaryDirectory() as tmp_dir:
                sandbox = Path(tmp_dir) / "KONUNG2"
                shutil.copytree(QUESTS_DIR.parent, sandbox)
                for name_b, file_b in files.items():
                    data = (text_ if name_b == file_name
                              else render_file(file_b).encode("cp866"))
                    (sandbox / "QUESTS" / name_b).write_bytes(data)
                done_flag = subprocess.run(
                    [str(sandbox / "RESOURCE" / "M_QUEST.exe"),
                     "konung2.qst", "-d_DEFINES.QST", "-l"],
                    cwd=str(sandbox / "QUESTS"), capture_output=True,
                    text=True, encoding="cp866", errors="replace",
                    stdin=subprocess.DEVNULL, timeout=120)
                tail = (done_flag.stdout or "").strip().splitlines()[-3:]
                if done_flag.returncode != 0 or "Error" in (
                        done_flag.stdout or ""):
                    return False, "компилятор отверг: " + "; ".join(
                        tail), {"validation": checkup}
                #: ВОРОТА СОБРАЛИ СЮЖЕТ ЦЕЛИКОМ — ЗАБИРАЕМ ЕГО.
                #:
                #: Прежде из песочницы брался только вердикт, а
                #: project/story/QUESTS.RES оставался прежним: пак печёт
                #: деревья именно из него, и правка, показанная в панели,
                #: в игру НЕ ПОПАДАЛА. Поймано живым прогоном — в собранной
                #: карте не оказалось ветки, добавленной пять минут назад;
                #: со стороны это «сохранил, собрал, а в игре по-старому».
                #: Отдельная кнопка «Скомпилировать сюжет» для этого не
                #: нужна: тот же прогон уже сделан здесь.
                shutil.copy2(sandbox / "QUESTS" / "QUESTS.RES",
                             PROJECT_STORY / "QUESTS.RES")
                journal = sandbox / "QUESTS" / "QUESTS.LOG"
                if journal.is_file():
                    shutil.copy2(journal, PROJECT_STORY / "QUESTS.LOG")
            (root_ / file_name).write_bytes(text_)
            # разбор в files/*.json — вслед за qst, чтобы не разъехались
            (PROJECT_STORY / "files" / f"{file_name}.json").write_text(
                json.dumps(parse_file(text_.decode("cp866"),
                                      file_name),
                           ensure_ascii=False, indent=1),
                encoding="utf-8")
            return True, f"записан в {file_name}; " + "; ".join(tail), {
                "file": file_name, "validation": checkup}
    return False, f"диалога «{name}» нет", {}


def api_play(num_: int, content_root,
             start: tuple[int, int] | None = None) -> tuple[bool, str, dict]:
    """Адрес пробы: карта, новая партия и (не обязательно) клетка старта.

    ПРОБА ИДЁТ С ЧИСТОГО ЛИСТА. Сохранение помнит карту сильнее пака
    (mapstate.js): без этого «Play» продолжал прошлый заход и показывал
    жителей ИЗ ПАМЯТИ — правки в паке были верные, а в игре выходил
    вчерашний юнит (живая проверка на карте 64). Об этом же говорит и
    ответ: «новая партия» человеку видно до запуска, а не после.

    «ИГРАТЬ ОТСЮДА» — клетка `start`. Без неё герой встаёт в точку входа
    карты и до места правки идёт пешком: на своей карте 64 это восемь
    десятков клеток в один конец, и на них уходило больше времени, чем
    на саму правку. Клетка уезжает в адрес и там становится записью
    прибытия — тем же путём, каким на карту приводит дверь.
    """
    root = Path(content_root or DEFAULT_CONTENT_ROOT)
    if not (root / "maps" / str(num_) / "map.json").is_file():
        return False, f"карта {num_} не собрана в пак", {}
    address = f"/?map={num_}&fresh=1"
    note = "играть · НОВАЯ партия (сейв не читается)"
    if start is not None:
        row, col = start
        if not (0 <= row < GRID_ROWS and 0 <= col < GRID_COLS):
            return False, f"клетка {row}:{col} вне карты", {}
        address += f"&at={row},{col}"
        note += f" · с клетки {row}:{col}"
        #: Глухую клетку не запрещаем — клиент расходится кольцами и
        #: ставит героя рядом (app.js, «прибытие в камень»), — но говорим
        #: об этом заранее: иначе «поставил старт в стену» выглядит как
        #: промах редактора.
        folder = project_map_dir(num_)
        if folder is not None and (folder / "grid.txt").is_file():
            _, _, grid = _grid_lines(folder)
            if row < len(grid):
                words = grid[row].split()
                if col < len(words):
                    low = int(words[col].split(":")[0], 16)
                    if low & CELL_BLOCK_MASK:
                        note += " (клетка глухая — герой встанет рядом)"
    return True, note, {"redirect": address}


def api_story_compile() -> tuple[bool, str, dict]:
    """Собрать QUESTS.RES из project/story/qst (наш M_QUEST-прогон);
    итог кладётся в project/story/QUESTS.RES."""
    import shutil
    import subprocess
    import tempfile
    from konung2.story import QUESTS_DIR
    root_ = PROJECT_STORY / "qst"
    if not root_.is_dir():
        return False, "сюжет не экспортирован", {}
    with tempfile.TemporaryDirectory() as tmp_dir:
        sandbox = Path(tmp_dir) / "KONUNG2"
        shutil.copytree(QUESTS_DIR.parent, sandbox)
        for file in root_.glob("*.QST"):
            shutil.copy2(file, sandbox / "QUESTS" / file.name)
        done_flag = subprocess.run(
            [str(sandbox / "RESOURCE" / "M_QUEST.exe"), "konung2.qst",
             "-d_DEFINES.QST", "-l"],
            cwd=str(sandbox / "QUESTS"), capture_output=True, text=True,
            encoding="cp866", errors="replace",
            stdin=subprocess.DEVNULL, timeout=120)
        tail = (done_flag.stdout or "").strip().splitlines()[-3:]
        if done_flag.returncode != 0 or "Error" in (done_flag.stdout or ""):
            return False, "; ".join(tail), {}
        outcome = PROJECT_STORY / "QUESTS.RES"
        shutil.copy2(sandbox / "QUESTS" / "QUESTS.RES", outcome)
        # лог компиляции несёт нумерацию деревьев (имя -> номер) — она
        # нужна привязке диалога к юниту; кладём рядом с RES
        journal = sandbox / "QUESTS" / "QUESTS.LOG"
        if journal.is_file():
            shutil.copy2(journal, PROJECT_STORY / "QUESTS.LOG")
    return True, "; ".join(tail), {"res": str(outcome),
                                    "bytes": outcome.stat().st_size}


#: Маршруты чтения: (образец пути) -> обработчик. {n} — номер карты.
def api_dispatch_get(path_str: str, content_root) -> tuple[bool, str, dict]:
    parts_ = path_str.strip("/").split("/")   # editor api ...
    tail = parts_[2:]
    if tail == ["maps"]:
        return api_maps(content_root)
    if len(tail) == 2 and tail[0] == "maps":
        return api_map_state(int(tail[1]), content_root)
    if len(tail) == 3 and tail[0] == "maps":
        num_ = int(tail[1])
        if tail[2] == "terrain":
            return api_terrain(num_)
        if tail[2] == "cells":
            return api_cells(num_)
        if tail[2] == "pack":
            return api_pack_units(num_, content_root)
    if tail[:2] == ["catalog", "tiles"]:
        return editor_tiles_page(0, content_root)
    if tail[:2] == ["catalog", "objects"]:
        return editor_objects_page(0, content_root)
    if tail[:2] == ["catalog", "decor"]:
        return editor_decor_page(0, content_root)
    if tail[:2] == ["catalog", "items"]:
        return editor_items_page(content_root)
    if tail[:2] == ["catalog", "names"]:
        return editor_names_page()
    if len(tail) == 3 and tail[0] == "maps" and tail[2] == "village":
        return api_village(int(tail[1]), content_root)
    if tail[:2] == ["catalog", "bestiary"]:
        return editor_bestiary(content_root)
    if tail == ["build", "status"]:
        return api_build_status()
    if len(tail) == 2 and tail[0] == "play":
        # UI после сборки шлёт игрока в игру; собственно редирект
        # делает обработчик GET — здесь только валидация карты
        return api_play(int(tail[1]), content_root)
    if tail == ["history"]:
        return api_history()
    if tail == ["schema"]:
        return True, "схемы форм", {"schema": EDITOR_SCHEMA}
    if len(tail) == 2 and tail[0] == "schema":
        # подресурс, как зовёт UI: GET /schema/object, /schema/unit…
        schema = EDITOR_SCHEMA.get(tail[1])
        if schema is None:
            return False, f"нет схемы «{tail[1]}»", {
                "known": sorted(EDITOR_SCHEMA)}
        return True, tail[1], {"fields": schema}
    if len(tail) == 3 and tail[0] == "maps" and tail[2] == "validate":
        return api_validate(int(tail[1]), content_root)
    if tail == ["story"]:
        return api_story()
    if len(tail) == 3 and tail[:2] == ["story", "dialog"]:
        return api_story_dialog(unquote(tail[2]))
    if tail == ["worlds"]:
        return api_worlds()
    if len(tail) == 2 and tail[0] == "worlds":
        return api_world_meta(int(tail[1]))
    if len(tail) == 4 and tail[0] == "worlds" and tail[2] == "maps":
        return api_world_map(int(tail[1]), int(tail[3]))
    return False, f"нет такого пути: {path_str}", {}


def api_dispatch_get_paged(path_str: str, request: dict,
                           content_root) -> tuple[bool, str, dict]:
    """Каталоги со страницей из query string."""
    page_num = int((request.get("page") or ["0"])[0])
    # состав карты зависит от мира (выбор героя): ?world=N
    if path_str.endswith("/pack") and request.get("world"):
        parts_ = path_str.strip("/").split("/")
        return api_pack_units(int(parts_[-2]), content_root,
                              int(request["world"][0]))
    #: поселение тоже своё в каждом мире: должностные лица в GAME.<мир>
    #: разные, и клиент берёт запись мира своего героя
    if path_str.endswith("/village"):
        parts_ = path_str.strip("/").split("/")
        world_ = request.get("world")
        return api_village(int(parts_[-2]), content_root,
                           int(world_[0]) if world_ else None)
    if path_str.endswith("/catalog/tiles"):
        return editor_tiles_page(page_num, content_root)
    if path_str.endswith("/catalog/objects"):
        game_q = request.get("game")
        return editor_objects_page(page_num, content_root,
                                   game_q[0] if game_q else "canon")
    if path_str.endswith("/catalog/decor"):
        game_q = request.get("game")
        return editor_decor_page(page_num, content_root,
                                 game_q[0] if game_q else "canon")
    #: «играть отсюда»: клетка старта приезжает в query — /play/64?row=41&col=36
    parts_ = path_str.strip("/").split("/")
    if len(parts_) == 4 and parts_[2] == "play" and request.get("row"):
        return api_play(int(parts_[3]), content_root,
                        (int(request["row"][0]), int(request["col"][0])))
    return api_dispatch_get(path_str, content_root)


#: КАНОН ТОЛЬКО ДЛЯ ЧТЕНИЯ.
#:
#: project/maps — это распакованные карты ОБЕИХ игр, а не песочница: их
#: файлы обязаны оставаться байт в байт равными оригиналу (арбитр —
#: `KN2Map.pack(папка) == KN2Map.from_game(номер)`). Живые прогоны
#: редактора уже дважды пачкали канон незаметно: промахи кликов
#: наставили в Морской лагерь чужих тварей и объекты, а правка диалога
#: 27 испортила общий сюжет всей игры.
#:
#: Поэтому мутации разрешены только СВОИМ картам — тем, что создал сам
#: редактор (признак origin.editor в map.json). Канон правится через
#: свою карту: скопируйте нужное к себе или создайте новую.
def _editor_map(number: int) -> bool:
    folder = project_map_dir(number)
    if folder is None:
        return False
    file = folder / "map.json"
    if not file.is_file():
        return False
    try:
        document = json.loads(file.read_text(encoding="utf-8"))
    except ValueError:
        return False
    return bool((document.get("origin") or {}).get("editor"))


def _canon_protected(number: int) -> tuple[bool, str, dict] | None:
    """Отказ, если карта не наша. None — можно править."""
    if _editor_map(number):
        return None
    folder = project_map_dir(number)
    name_ = folder.name if folder else f"карта {number}"
    return (False,
            f"карта {number} ({name_}) — канон игры, её файлы держатся "
            f"байт в байт равными оригиналу. Правки идут только в свои "
            f"карты: создайте новую (POST /editor/api/maps) или "
            f"работайте с уже созданной.", {})


def api_dispatch_post(path_str: str, payload: dict,
                      content_root) -> tuple[bool, str, dict]:
    parts_ = path_str.strip("/").split("/")
    tail = parts_[2:]
    if tail == ["maps"]:
        #: {from: N} — снять СВОЮ копию с карты N. Единственный путь
        #: править канон: сами канонные файлы редактор не пишет никогда.
        #: Номер можно не задавать — возьмём первый свободный.
        if payload.get("from") is not None:
            return editor_map_copy(int(payload["from"]),
                                   int(payload.get("map") or _free_number()),
                                   str(payload.get("name") or ""))
        return editor_map_create(int(payload.get("map") or 0),
                                 str(payload.get("name") or "Карта"))
    if tail == ["build"]:
        return api_build_start(payload.get("maps") or [])
    if tail == ["undo"]:
        return api_undo()
    #: «новый» — не имя диалога, а действие: проверка идёт ДО разбора
    #: пути «story/dialog/<имя>», иначе новый диалог ушёл бы в правку
    #: диалога с именем «new».
    if tail == ["story", "dialog", "new"]:
        return api_story_dialog_new(payload, content_root)
    if len(tail) == 3 and tail[:2] == ["story", "dialog"]:
        return api_story_dialog_save(unquote(tail[2]), payload)
    if tail == ["story", "compile"]:
        return api_story_compile()
    if len(tail) == 3 and tail[0] == "worlds" and tail[2] == "build":
        return api_world_build(int(tail[1]))
    if len(tail) == 5 and tail[0] == "worlds" and tail[2] == "maps":
        world_, map_rec, layer_id = int(tail[1]), int(tail[3]), tail[4]
        if layer_id == "units":
            #: {add:{…}} — новый житель своим отрядом; без обёртки —
            #: правка существующего по индексу
            if payload.get("add") is not None:
                return editor_world_unit_add(world_, map_rec, payload["add"] or {})
            return api_world_unit_patch(world_, map_rec, payload)
        if layer_id == "parties":
            return api_world_party_patch(world_, map_rec, payload)
    if tail == ["redo"]:
        return api_redo()
    if len(tail) == 3 and tail[0] == "maps":
        num_ = int(tail[1])
        layer_id = tail[2]
        refusal = _canon_protected(num_)
        if refusal is not None:
            return refusal
        if layer_id == "terrain":
            patch_ = {k: payload[k] for k in ("lower", "upper", "light",
                                         "cells")
                    if k in payload}
            return editor_ground_save(num_, int(payload["row"]),
                                      int(payload["col"]), patch_)
        if layer_id == "water":
            patch_ = {k: payload[k] for k in ("row", "col", "value",
                                         "stream", "tile", "cells")
                    if k in payload}
            return editor_water_save(num_, patch_)
        if layer_id == "cells":
            patch_ = {k: v for k, v in payload.items()
                    if k not in ("row", "col")}
            return editor_cell_save(num_, int(payload.get("row") or 0),
                                    int(payload.get("col") or 0), patch_)
        if layer_id == "objects":
            if payload.get("patch"):
                return editor_object_move(num_, payload["patch"])
            return editor_object_add(num_, payload.get("add") or payload)
        if layer_id == "overlays":
            return editor_sprite_save(num_, payload)
        if layer_id == "exits":
            return editor_exit_save(num_, payload)
        if layer_id == "village":
            return editor_village_save(num_, payload)
        if layer_id == "warbands":
            if payload.get("patch") is not None:
                return editor_warband_patch(num_, payload)
            return editor_warband_add(num_, payload)
        if layer_id == "loot" and (payload.get("add_item") is not None
                               or payload.get("remove_item") is not None):
            return editor_loot_item(num_, payload)
        if layer_id == "units" and (payload.get("add_item") is not None
                                or payload.get("remove_item") is not None):
            return editor_unit_belt(num_, payload)
        if layer_id in ("units", "loot"):
            ok_, reply = editor_save(num_, layer_id.rstrip("s")
                                    if layer_id == "units" else "loot",
                                    payload.get("id"),
                                    payload.get("patch") or payload.get(
                                        "record") or {})
            return ok_, reply, {}
    return False, f"нет такого пути: {path_str}", {}


def api_dispatch_delete(path_str: str) -> tuple[bool, str, dict]:
    parts_ = path_str.strip("/").split("/")
    tail = parts_[2:]
    if len(tail) == 3 and tail[:2] == ["story", "dialog"]:
        return api_story_dialog_drop(unquote(tail[2]))
    if len(tail) == 4 and tail[0] == "maps":
        num_ = int(tail[1])
        layer_id, key_ = tail[2], tail[3]
        refusal = _canon_protected(num_)
        if refusal is not None:
            return refusal
        if layer_id == "objects":
            return editor_object_remove(num_, int(key_))
        if layer_id == "overlays":
            return editor_sprite_save(num_, {"slot": int(key_),
                                              "removed": True})
        if layer_id == "exits":
            return editor_exit_save(num_, {"index": int(key_),
                                            "removed": True})
        if layer_id == "units":
            return api_unit_delete(num_, key_)
        if layer_id == "loot":
            return api_loot_delete(num_, key_)
        if layer_id == "warbands":
            return api_warband_delete(num_, int(key_))
    return False, f"нет такого пути: {path_str}", {}


# Python не знает .opus, а без верного Content-Type <audio> может отказаться.
mimetypes.add_type("audio/ogg", ".opus")


def resolve_request(path: str, web_root: Path,
                    content_root: Path) -> Path | None:
    """Безопасно сопоставить URL с одним из двух доступных корней."""
    url_path = unquote(urlsplit(path).path)
    if url_path.startswith("/content/"):
        root = content_root.resolve()
        relative = url_path.removeprefix("/content/")
    else:
        root = web_root.resolve()
        relative = url_path.lstrip("/") or "index.html"

    raw = Path(relative)
    if raw.is_absolute() or ".." in raw.parts:
        return None
    candidate = (root / raw).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if candidate.is_dir():
        candidate = candidate / "index.html"
    return candidate if candidate.is_file() else None


class _Handler(BaseHTTPRequestHandler):
    server_version = "Knyaz2DevServer/0.1"
    #: Держим соединение. По умолчанию `BaseHTTPRequestHandler` отвечает
    #: HTTP/1.0 и закрывает сокет после каждого ответа, а вход на карту это
    #: шестьсот с лишним файлов — локально мерилось время установки соединений,
    #: а не наша очередь. Боевой сервер отдаёт по h2/h3, где соединение одно;
    #: с keep-alive локальный замер хотя бы сопоставим с ним.
    #: Требование HTTP/1.1 — точная длина тела в каждом ответе; она здесь есть
    #: в обеих ветках `_serve`, а `send_error` проставляет её сам.
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, web_root: Path, content_root: Path, **kwargs) -> None:
        self.web_root = web_root
        self.content_root = content_root
        super().__init__(*args, **kwargs)

    #: CORS: UI редактора живёт на чужом origin (Claude Design), сервер
    #: локальный — открываем всё.
    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.send_header("Access-Control-Allow-Methods",
                         "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _api_reply(self, ok_: bool, reply: str, data: dict) -> None:
        payload = json.dumps({"ok": ok_, "note": reply, **data},
                          ensure_ascii=False).encode("utf-8")
        self.send_response(200 if ok_ else 400)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        path_str = urlsplit(self.path).path
        if path_str.startswith("/editor/api/"):
            from urllib.parse import parse_qs
            request = parse_qs(urlsplit(self.path).query)
            try:
                ok_, reply, data = api_dispatch_get_paged(
                    path_str, request, self.content_root)
            except (ValueError, KeyError, TypeError, OSError) as trouble:
                ok_, reply, data = False, str(trouble), {}
            self._api_reply(ok_, reply, data)
            return
        self._serve(send_body=True)

    def do_DELETE(self) -> None:  # noqa: N802
        path_str = urlsplit(self.path).path
        if not path_str.startswith("/editor/api/"):
            self.send_error(404, "Not found")
            return
        try:
            snapshot = _journal_snapshot(path_str)
            ok_, reply, data = api_dispatch_delete(path_str)
            if ok_:
                _journal_push(snapshot)
        except (ValueError, KeyError, TypeError, OSError) as trouble:
            ok_, reply, data = False, str(trouble), {}
        self._api_reply(ok_, reply, data)

    def do_POST(self) -> None:  # noqa: N802
        """Редакторские ручки. Пока одна: /editor/unit — патч юнита в
        проектный слой; применится при следующей сборке пака."""
        path_str = urlsplit(self.path).path
        # ВХОДЯЩИЕ ФАЙЛЫ: сырое тело в .inbox/<имя> — канал доставки
        # наработок внешнего UI (Claude Design) в проект без ручного
        # скачивания. Имя чистится до последнего сегмента.
        if path_str.startswith("/editor/api/inbox/"):
            name_ = Path(unquote(path_str.rsplit("/", 1)[1])).name
            size = int(self.headers.get("Content-Length") or 0)
            if not 0 < size <= 4 * 1024 * 1024:
                self.send_error(400, "Bad length")
                return
            folder = REPOSITORY_ROOT / ".inbox"
            folder.mkdir(exist_ok=True)
            (folder / name_).write_bytes(self.rfile.read(size))
            self._api_reply(True, f"принят {name_}", {"bytes": size})
            return
        if path_str.startswith("/editor/api/"):
            size = int(self.headers.get("Content-Length") or 0)
            if not 0 <= size <= 262144:
                self.send_error(400, "Bad length")
                return
            try:
                payload = (json.loads(self.rfile.read(size).decode("utf-8"))
                        if size else {})
                # мутация карты? — снимок в журнал, ДО применения
                snapshot = _journal_snapshot(path_str)
                ok_, reply, data = api_dispatch_post(
                    path_str, payload, self.content_root)
                if ok_:
                    _journal_push(snapshot)
            except (ValueError, KeyError, TypeError, OSError) as trouble:
                ok_, reply, data = False, str(trouble), {}
            self._api_reply(ok_, reply, data)
            return
        if not path_str.startswith("/editor/"):
            self.send_error(404, "Not found")
            return
        layer_id = path_str.removeprefix("/editor/")
        size = int(self.headers.get("Content-Length") or 0)
        if not 0 < size <= 65536:
            self.send_error(400, "Bad length")
            return
        cell = {}
        try:
            payload = json.loads(self.rfile.read(size).decode("utf-8"))
            map_rec = int(payload.get("map") or 0)
            if layer_id == "quests":
                ok_, reply = editor_quests_compile()
            elif layer_id == "newmap":
                ok_, reply, cell = editor_map_create(
                    map_rec, str(payload.get("name") or f"Карта {map_rec}"))
            elif layer_id == "ground":
                ok_, reply, cell = editor_ground_save(
                    map_rec, int(payload["row"]), int(payload["col"]),
                    payload.get("patch") or {})
            elif layer_id == "objects":
                ok_, reply, cell = editor_objects_page(
                    int(payload.get("page") or 0), self.content_root)
            elif layer_id == "object":
                ok_, reply, cell = editor_object_add(
                    map_rec, payload.get("patch") or {})
            elif layer_id == "bestiary":
                ok_, reply, cell = editor_bestiary(self.content_root)
            elif layer_id == "warband":
                ok_, reply, cell = editor_warband_add(
                    map_rec, payload.get("patch") or {})
            elif layer_id == "sprite":
                ok_, reply, cell = editor_sprite_save(
                    map_rec, payload.get("patch") or {})
            elif layer_id == "water":
                ok_, reply, cell = editor_water_save(
                    map_rec, payload.get("patch") or {})
            elif layer_id == "tiles":
                ok_, reply, cell = editor_tiles_page(
                    int(payload.get("page") or 0),
                    self.content_root)
            elif layer_id == "cell":
                ok_, reply, cell = editor_cell_save(
                    map_rec, int(payload["row"]), int(payload["col"]),
                    payload.get("patch") or {})
            else:
                ok_, reply = editor_save(map_rec, layer_id,
                                        payload.get("unit") or payload.get("id"),
                                        payload["patch"])
        except (ValueError, KeyError, TypeError, OSError) as trouble:
            ok_, reply = False, str(trouble)
        code = 200 if ok_ else 400
        data = json.dumps({"ok": ok_, "note": reply, **cell},
                            ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_HEAD(self) -> None:  # noqa: N802
        self._serve(send_body=False)

    def _serve(self, send_body: bool) -> None:
        path = resolve_request(self.path, self.web_root, self.content_root)
        if path is None:
            self.send_error(404, "Not found")
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body = self._packed(path, content_type)
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", content_type)
        if body is None:
            self.send_header("Content-Length", str(path.stat().st_size))
        else:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if not send_body:
            return
        if body is not None:
            self.wfile.write(body)
            return
        with path.open("rb") as stream:
            self._copy(stream)

    #: Что жать. Картинки и звук уже сжаты своими форматами — их трогать
    #: незачем, а вот описания карт это текст из мелких чисел, и он ужимается
    #: примерно вдесятеро. Именно за него платит игрок при каждом переходе.
    PACKABLE = ("application/json", "text/", "application/javascript",
                "image/svg+xml")
    #: Мелочь жать дороже, чем отдать как есть.
    PACK_FROM = 1024

    def _packed(self, path: Path, content_type: str) -> bytes | None:
        """Сжатое тело, если клиент его примёт и файл того стоит."""
        if "gzip" not in self.headers.get("Accept-Encoding", ""):
            return None
        if not content_type.startswith(self.PACKABLE):
            return None
        if path.stat().st_size < self.PACK_FROM:
            return None
        return gzip.compress(path.read_bytes(), 6)

    def _copy(self, stream: BinaryIO) -> None:
        shutil.copyfileobj(stream, self.wfile)


def serve(host: str = "127.0.0.1", port: int = 8765,
          web_root: Path = DEFAULT_WEB_ROOT,
          content_root: Path = DEFAULT_CONTENT_ROOT) -> None:
    if not (web_root / "index.html").is_file():
        raise FileNotFoundError(f"нет web-приложения: {web_root}")
    if not (content_root / "manifest.json").is_file():
        raise FileNotFoundError(
            f"нет content pack: {content_root}; сначала выполните knyaz2-content build")

    def handler(*args, **kwargs):
        return _Handler(*args, web_root=web_root, content_root=content_root, **kwargs)

    server = ThreadingHTTPServer((host, port), handler)
    actual_host, actual_port = server.server_address[:2]
    print(f"Knyaz2 web: http://{actual_host}:{actual_port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="knyaz2-web")
    result.add_argument("--host", default="127.0.0.1")
    result.add_argument("--port", type=int, default=8765)
    result.add_argument("--web-root", type=Path, default=DEFAULT_WEB_ROOT)
    result.add_argument("--content", type=Path, default=DEFAULT_CONTENT_ROOT)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    serve(args.host, args.port, args.web_root.resolve(), args.content.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
