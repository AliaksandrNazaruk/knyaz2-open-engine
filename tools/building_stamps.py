# -*- coding: utf-8 -*-
"""Штампы построек: какие клетки авторы размечали под каждым зданием.

ЗАЧЕМ. Поставить дом в редакторе мало: сам по себе объект — картинка.
Твёрдость стен, «внутри дома» и снятие крыши держатся не на записи
объекта, а на КЛЕТКАХ карты (konung2/world/model.py:_read_grid):

* старшие биты 0..4 клетки — НОМЕР ЗАПИСИ постройки плюс один; такие
  клетки и есть её footprint;
* младшие 0..11 (0xFFF) — глушь: ими выложены стены;
* бит 0x8000 (BUILT) — пол постройки;
* старший 0x20 — «внутренняя» (юнит виден только при активном объекте).

Пока эти клетки не размечены, герой ходит сквозь дом, а крыша не
снимается никогда: движок помечает крышу к сокрытию по клеткам, на
которых стоит отряд (VA 0x428253), и без footprint дом «пустой».

ОТКУДА БЕРЁМ. Не выдумываем, а снимаем с канона: у каждой родной карты
клетки под домами уже размечены авторами. Для каждой пары «гнездо
OBJECTS.RES + состояние» собираем все встречи по всем картам проекта и
берём САМУЮ ЧАСТУЮ разметку — она и есть штамп.

Разметки одного дома на разных картах иногда отличаются (автор подрезал
угол под соседний забор), поэтому берём моду, а не первую встречу; в
сводке видно, насколько вид устойчив.

    python tools/building_stamps.py [--out knyaz2/data/building_stamps.json]
"""
from __future__ import annotations

import io
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from konung2.grid import BUILT, PASSABLE_MASK, SOLID          # noqa: E402
from konung2.kn2 import GRID_H, GRID_W, KN2Map, T_OBJECTS     # noqa: E402

КОРЕНЬ = Path(__file__).resolve().parents[1]
ПО_УМОЛЧАНИЮ = КОРЕНЬ / "knyaz2" / "data" / "building_stamps.json"
#: ТОЛЬКО СТРУКТУРНЫЕ БИТЫ. Сверх номера постройки старшие биты несут
#: 0x20 «внутренняя», 0x40 дневной свет и 0x80 upoff. Свет — свойство
#: КАРТЫ (её освещения), а не дома: одна и та же изба на светлой и
#: тёмной карте даёт разные слова, и штамп «расходился» у 14 встреч из
#: 15. upoff финальный движок не читает вовсе. Берём «внутреннюю».
ХИ_МАСКА = 0x20


def якорная_клетка(record: dict) -> tuple[int, int]:
    """Клетка, в которой стоит объект: пиксели записи по сетке 58x16."""
    x, y = int(record.get("pixel_x") or 0), int(record.get("pixel_y") or 0)
    row = max(0, (y - 16) // 16)
    col = max(0, (x - (29 if row % 2 else 58)) // 58)
    return row, col


#: Насколько широко смотрим вокруг постройки: стены авторы красят ВНЕ её
#: клеток (у стены старших битов постройки нет), и без запаса штамп
#: остался бы без стен вовсе.
ЗАПАС = 1
#: Клетка попадает в штамп, если так размечено у большинства встреч.
СОГЛАСИЕ = 0.6


def игра_карты(folder: Path) -> str:
    """«canon» или «legend»: у игр СВОЙ OBJECTS.RES, и гнездо 47 у них —
    разные постройки. Без игры в ключе штамп одной лёг бы на другую."""
    from konung2 import donor
    try:
        origin = (json.loads((folder / "map.json").read_text(encoding="utf-8"))
                  .get("origin") or {}).get("game")
    except (OSError, ValueError):
        origin = None
    return "legend" if origin == donor.LEGEND_NAME else "canon"


def случаи_карты(folder: Path, number: int) -> dict:
    """Встречи построек на карте: {(гнездо, состояние): [разметка, …]}.

    Разметка — окрестность объекта: для каждой клетки вокруг его якоря
    берём структурные биты (глушь/NoFly/пол), «внутреннюю» и признак
    «клетка принадлежит этой постройке». Стены в него входят именно
    потому, что смотрим шире собственных клеток.
    """
    kn2 = KN2Map.pack(str(folder), number)
    игра = игра_карты(folder)
    owned: dict[int, list] = defaultdict(list)
    for row in range(GRID_H):
        for col in range(GRID_W):
            low, high = kn2.cell(col, row)
            slot = (high & 0x1F) - 1
            if slot >= 0:
                owned[slot].append((row, col))
    out: dict[tuple, list] = {}
    for record in T_OBJECTS.unpack(kn2.data)["records"]:
        cells = owned.get(int(record["slot"]))
        if not cells:
            continue
        nest = int(record.get("sprite") or 0) + 30
        state = int(record.get("state") or 0)
        row0, col0 = якорная_клетка(record)
        mine = set(cells)
        #: БЕРЁМ СВОИ КЛЕТКИ И ГЛУШЬ ВПЛОТНУЮ К НИМ. Стены у постройки
        #: своих битов не несут (номер стоит только на полу и входе),
        #: поэтому одними «своими» штамп остался бы без стен. Но и всё
        #: подряд вокруг брать нельзя: в запас попадают чужой забор и
        #: соседняя изба, и редактор ставил бы их вместе с домом.
        интерес = set(mine)
        for row, col in cells:
            for dr in range(-ЗАПАС, ЗАПАС + 1):
                for dc in range(-ЗАПАС, ЗАПАС + 1):
                    сосед = (row + dr, col + dc)
                    if not (0 <= сосед[0] < GRID_H and 0 <= сосед[1] < GRID_W):
                        continue
                    low, _ = kn2.cell(сосед[1], сосед[0])
                    if (low & PASSABLE_MASK) == PASSABLE_MASK:
                        интерес.add(сосед)
        #: ВЫРАВНИВАЕМ ПО СЛЕДУ ДОМА, А НЕ ПО ПИКСЕЛЯМ ЗАПИСИ. Пиксельная
        #: точка объекта на клетку не ложится: у разных встреч одного дома
        #: она попадает то в одну клетку, то в соседнюю, и «одинаковые»
        #: разметки расходились на шаг — согласия не набиралось ни у
        #: одной клетки нутра. Началом штампа берём угол СВОИХ клеток, а
        #: смещение якоря до него запоминаем отдельно: по нему редактор и
        #: положит штамп относительно поставленного объекта.
        начР, начС = min(row for row, _ in cells), min(col for _, col in cells)
        плитка = {}
        for row, col in интерес:
            low, high = kn2.cell(col, row)
            плитка[(row - начР, col - начС)] = (
                low & (PASSABLE_MASK | SOLID | BUILT),
                high & ХИ_МАСКА,
                (row, col) in mine)
        out.setdefault((игра, nest, state), []).append(
            {"плитка": плитка, "якорь": (row0 - начР, col0 - начС)})
    return out


def образец(случаи: list[dict]) -> dict | None:
    """Самая полно размеченная встреча постройки — она и есть штамп.

    СОГЛАСИЕ БОЛЬШИНСТВА ЗДЕСЬ НЕ РАБОТАЕТ, и это свойство данных, а не
    беда способа: одну и ту же избу авторы обводили по-разному — где
    полный пол с «внутренними» клетками, где три клетки у порога. Голоса
    по каждой клетке расходятся, и общего у пятнадцати встреч остаются
    почти одни стены — дом без нутра и без пола.
    Берём ЦЕЛЬНЫЙ экземпляр: тот, где своих клеток больше всего. Это
    разметка живого авторского дома, а не усреднённая тень.
    """
    if not случаи:
        return None
    #: НЕ САМЫЙ БОЛЬШОЙ, А СРЕДИННЫЙ. Максимум ловит слипшийся случай:
    #: у дома 72 нашёлся экземпляр на 196 клеток — его номер носил ещё и
    #: соседний двор, и штамп вышел бы с чужим забором. Медиана берёт
    #: обычный дом.
    порядок = sorted(случаи,
                     key=lambda с: sum(1 for з in с["плитка"].values() if з[2]))
    return порядок[len(порядок) // 2]


def клетки_образца(случай: dict) -> list[dict]:
    out = []
    for (dr, dc), (low, high, own) in sorted(случай["плитка"].items()):
        if not (low or high or own):
            continue                      # чистая земля — не разметка
        out.append({"dr": dr, "dc": dc, "low": low, "high": high,
                    "own": bool(own)})
    return out


def собрать(project: Path) -> dict:
    встречи: dict[tuple, list] = defaultdict(list)
    карт = 0
    for folder in sorted(project.glob("*_*")):
        if not (folder / "map.json").is_file():
            continue
        try:
            number = int(folder.name.split("_")[0])
            свои = случаи_карты(folder, number)
        except (ValueError, OSError, KeyError):
            continue
        карт += 1
        for ключ, список in свои.items():
            встречи[ключ].extend(список)
    таблица = {}
    for (игра, nest, state), случаи in sorted(встречи.items()):
        лучший = образец(случаи)
        клетки = клетки_образца(лучший) if лучший else []
        if not клетки:
            continue
        стен = sum(1 for c in клетки if (c["low"] & PASSABLE_MASK) == PASSABLE_MASK)
        нутро = sum(1 for c in клетки if c["high"] & 0x20)
        дверь = sum(1 for c in клетки if c["own"] and not c["high"] & 0x20
                    and (c["low"] & PASSABLE_MASK) != PASSABLE_MASK)
        #: якорь берём У ТОГО ЖЕ экземпляра, с которого снят штамп: чужое
        #: смещение сдвинуло бы дом на клетку от собственных стен
        якР, якС = лучший["якорь"]
        таблица[f"{игра}:{nest}:{state}"] = {
            "cells": клетки, "seen": len(случаи),
            "anchor": [якР, якС],
            "walls": стен, "inner": нутро, "door": дверь,
        }
    добавлено = размножить(таблица)
    return {"maps": карт, "stamps": таблица, "twins": добавлено}


def размножить(таблица: dict) -> int:
    """Отдать штамп постройкам-БЛИЗНЕЦАМ той же геометрии.

    Авторы размечали клетки не под каждым домом: из 57 канонных построек
    со стенами и крышей обведены 30. Остальные — это те же срубы в другой
    фазе или другой раскраске: спрайт у них тот же по размеру и
    смещениям, а значит и клетки ложатся так же. Берём штамп близнеца, а
    не выдумываем свой; пометка `from` говорит, чей он.
    """
    from json import loads
    паспорт = (КОРЕНЬ / "content_build" / "assets" / "objects" / "index.json")
    if not паспорт.is_file():
        return 0
    записи = loads(паспорт.read_text(encoding="utf-8"))
    геометрия: dict[tuple, list] = defaultdict(list)
    строение: dict[tuple, tuple] = {}
    for ключ, з in записи.items():
        игра, слот, _пал, сост = ключ.split(":")
        игра = "legend" if игра != "canon" else "canon"
        слои = tuple(sorted((з.get("layers") or {}).keys()))
        if "walls" not in слои or "roof" not in слои:
            continue                     # не постройка: в неё не войти
        место = (игра, int(слот), int(сост))
        размер = (игра, з["width"], з["height"], з["offset_x"], з["offset_y"])
        строение.setdefault(место, размер)
        геометрия[размер].append(место)
    добавлено = 0
    for место, размер in строение.items():
        игра, слот, сост = место
        имя = f"{игра}:{слот}:{сост}"
        if имя in таблица:
            continue
        for сосед in геометрия[размер]:
            чужое = f"{сосед[0]}:{сосед[1]}:{сосед[2]}"
            if чужое in таблица and not таблица[чужое].get("from"):
                таблица[имя] = {**таблица[чужое], "from": чужое}
                добавлено += 1
                break
    return добавлено


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    выход = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv \
        else ПО_УМОЛЧАНИЮ
    итог = собрать(КОРЕНЬ / "project" / "maps")
    выход.parent.mkdir(parents=True, exist_ok=True)
    выход.write_text(json.dumps(итог, ensure_ascii=False, indent=1),
                     encoding="utf-8")
    print(f"карт прочитано: {итог['maps']}, штампов: {len(итог['stamps'])} "
          f"(из них по близнецу: {итог.get('twins', 0)})")
    print(f"записано: {выход}")
