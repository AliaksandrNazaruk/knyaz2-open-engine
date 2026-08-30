# -*- coding: utf-8 -*-
"""
Перенос карты из «Продолжения легенды» в проект.

Один вызов делает всё, что раньше делалось руками: обрезает карту под наш
формат, раскладывает её в ``project/maps/``, называет по донорской таблице,
измеряет кромку и место прибытия, прописывает выходы и заносит карту в
``project/index.json``.

ЧИСЛА ЗАМЕРЯЮТСЯ, А НЕ НАЗНАЧАЮТСЯ:

  прибытие   ближайшая к середине застройки ПРОХОДИМАЯ клетка (проходимость
             по движку — младшие 12 бит нижнего слова нулевые, VA 0x43DFA9);
             середина берётся по всем объектам карты
  номер      150 + номер у донора: номера 1..54 заняты нашими картами,
             100..146 — записями отрядов в GAME.<мир>, свободно с 147

Выходы отсюда НЕ пишутся: они настоящие, лежат в GAME.<мир> донора, и берёт
их сборщик. Ключ `origin` — то, по чему он понимает, чью таблицу читать.

Что НЕ делается и делается отдельно: клетка на карте мира и значок. Их
называет ``project/locations.json`` — там же, где имя на глобальной, чтобы
«где стоит» и «как называется» не разошлись.

Запуск:
    python tools/donor_import.py <номер карты у донора> [ещё номера…]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from konung2 import donor
from konung2.graph import cell_position
from konung2.kn2 import GRID_H, GRID_W, KN2Map

#: Насколько сдвигается номер при переносе (см. docs/MERGE_SPEC.md).
NUMBER_SHIFT = 150

TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "",
    "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}


def slug(name: str) -> str:
    out = "".join(TRANSLIT.get(letter, letter) for letter in name.lower())
    out = re.sub(r"[^a-z0-9]+", "_", out).strip("_")
    return out or "map"


def passable(kn2: KN2Map, x: int, y: int) -> bool:
    """Пройдёт ли отряд по клетке — то же правило, что у модели карты.

    Непроходимость это младшие 12 бит младшего слова: 0x0FFF стена, 0x4FFF
    край карты. Проходимы 0x0000 (земля) и 0x8000 (пол постройки).

    Здесь была ошибка, стоившая криво поставленного прибытия: сравнивалось
    с 0xFFFF, а пустая клетка у нас 0x4FFF, и «проходимой» выходила любая
    непустая — в том числе стена. У донорских карт до перевода проходимости
    (konung2/donor.py) это давало вообще все занятые клетки подряд.
    """
    return not (kn2.cell(x, y)[0] & 0x0FFF)


def measure(kn2: KN2Map) -> dict:
    """Кромка проходимой части и место прибытия — по самой карте."""
    free = [(y, x) for y in range(GRID_H) for x in range(GRID_W)
            if passable(kn2, x, y)]
    if not free:
        raise SystemExit("на карте нет ни одной проходимой клетки")
    rows = [row for row, _ in free]
    cols = [col for _, col in free]
    objects = [entry for entry in kn2.objects()
               if entry.get("sprite", -1) > 0 and entry["pixel_x"] != 0xFFFF]
    if objects:
        centre_x = sum(entry["pixel_x"] for entry in objects) / len(objects)
        centre_y = sum(entry["pixel_y"] for entry in objects) / len(objects)
        arrival = min(free, key=lambda place: (
            (cell_position(*place)[0] - centre_x) ** 2 +
            (cell_position(*place)[1] - centre_y) ** 2))
    else:
        arrival = free[len(free) // 2]
    return {"row_min": min(rows), "row_max": max(rows),
            "col_min": min(cols), "col_max": max(cols),
            "free": len(free), "objects": len(objects),
            "arrival": {"row": arrival[0], "col": arrival[1]}}


def import_map(number: int, names: list[str]) -> dict:
    ours = NUMBER_SHIFT + number
    name = names[number] if number < len(names) else ""
    if not name or name == "???":
        name = f"Карта {number} («Продолжение легенды»)"
    data, lost = donor.map_data(number)
    if lost:
        print(f"  ВНИМАНИЕ: у карты {number} занято {lost} лишних зон, "
              f"обрезка их теряет")
    kn2 = KN2Map(ours, data)
    edge = measure(kn2)

    directory = ROOT / "project" / "maps" / f"{ours}_{slug(name)}"
    kn2.unpack(str(directory))
    document = json.loads((directory / "map.json").read_text(encoding="utf-8"))
    document["map_number"] = ours
    document["name"] = name
    document["source"] = (f"Продолжение легенды, карта {number} «{name}» "
                          f"(номер = {NUMBER_SHIFT} + {number})")
    # ОТКУДА КАРТА. По этой записи сборщик понимает, в чьём GAME.<мир>
    # искать жителей: у перенесённой карты они лежат у донора и под его
    # номером, а не под нашим. Без неё деревня приезжает пустой.
    document["origin"] = {"game": donor.LEGEND_NAME, "map": number}
    # ВЫХОДЫ ЗДЕСЬ БОЛЬШЕ НЕ СОЧИНЯЮТСЯ. Пока запись выхода донора не была
    # разобрана, сюда писались четыре полосы по кромке — заведомая подделка:
    # в настоящей таблице у Холмогорья выходов три, и один из них идёт лишь
    # до 87-го столбца, а у Дубков есть дверь в пещеру, которой полосы не
    # знают вовсе. Теперь сборщик берёт настоящие из GAME.<мир> донора.
    document.pop("exits", None)
    (directory / "map.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"карта {number} «{name}» -> наша {ours}, {directory.name}")
    print(f"  проходимых клеток {edge['free']}, объектов {edge['objects']}, "
          f"кромка строки {edge['row_min']}..{edge['row_max']}, "
          f"столбцы {edge['col_min']}..{edge['col_max']}")
    print(f"  прибытие: строка {edge['arrival']['row']}, "
          f"столбец {edge['arrival']['col']}")
    return {"map": ours, "name": name, "dir": f"maps/{directory.name}",
            "source": document["source"], "arrival": edge["arrival"]}


def register(entries: list[dict]) -> None:
    path = ROOT / "project" / "index.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    by_number = {record["map"]: record for record in document["maps"]}
    for entry in entries:
        by_number[entry["map"]] = {key: entry[key]
                                   for key in ("map", "name", "dir", "source")}
    document["maps"] = [by_number[key] for key in sorted(by_number)]
    path.write_text(json.dumps(document, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    print(f"project/index.json: карт всего {len(document['maps'])}")


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    if not donor.available():
        raise SystemExit(f"донор недоступен: нет {donor.DONOR_EXE}")
    names = donor.DonorExe.load().location_names()
    entries = [import_map(int(argument), names) for argument in sys.argv[1:]]
    register(entries)
    print("\nв project/locations.json допишите клетку и значок:")
    for entry in entries:
        print(f'  {{"number": {entry["map"]}, "name": "{entry["name"]}", '
              f'"cell": [?, ?], "marker": {{"sprite": 256, "dx": 0, "dy": 0}}, '
              f'"arrival": {{"row": {entry["arrival"]["row"]}, '
              f'"col": {entry["arrival"]["col"]}}}}}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
