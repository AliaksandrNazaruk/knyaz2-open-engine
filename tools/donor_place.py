# -*- coding: utf-8 -*-
"""
Расставить донорские локации на общей карте мира.

Клетки НЕ придумываются: они берутся с самой карты мира донора и
переносятся сдвигом, замеренным по картинкам (``konung2/donor.py``,
DONOR_WORLD_AT). Значок — свой у каждой локации, из её же записи.

Сажается только то, до чего игрок дойдёт: клетка должна быть сушей, лежать
на том же куске суши, что Борье, и быть свободной. Всё остальное
перечисляется с причиной — локация на нарисованном море или на отрезанном
острове это не мелочь оформления, а место, куда нельзя попасть.

Запуск:
    python tools/donor_place.py            # показать, что получится
    python tools/donor_place.py --write    # перенести карты и записать реестр
"""
from __future__ import annotations

import json
import sys
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from konung2 import donor
from konung2 import worldmap as canon
from konung2.interf import InterfRes

sys.path.insert(0, str(ROOT / "tools"))
import donor_import                                        # noqa: E402

#: Запасной значок, если у локации своего нет или его нет в нашей INTERF.RES.
FALLBACK_MARKER = 256


def mainland(document: dict) -> set[tuple[int, int]]:
    """Кусок суши, на котором стоит Борье."""
    rows, cols, walk = document["rows"], document["cols"], document["walk"]
    row0, col0 = document["canon_at"]
    land = lambda row, col: bool(walk[row][col] & canon.MASK_LAND)  # noqa: E731
    grid = canon.grid()
    home = [(r + row0, c + col0) for r in range(canon.ROWS)
            for c in range(canon.COLS) if grid[r][c] & 0xFF == 33][0]
    seen = {home}
    queue = deque([home])
    while queue:
        row, col = queue.popleft()
        for drow in (-1, 0, 1):
            for dcol in (-1, 0, 1):
                r, c = row + drow, col + dcol
                if ((drow or dcol) and 0 <= r < rows and 0 <= c < cols
                        and (r, c) not in seen and land(r, c)):
                    seen.add((r, c))
                    queue.append((r, c))
    return seen


def main() -> int:
    write = "--write" in sys.argv
    if not donor.available():
        raise SystemExit(f"донор недоступен: нет {donor.DONOR_EXE}")

    document = json.loads(
        (ROOT / "project" / "worldmap" / "world.json").read_text("utf-8"))
    reachable = mainland(document)
    rows, cols, walk = document["rows"], document["cols"], document["walk"]

    grid = canon.grid()
    row0, col0 = document["canon_at"]
    taken = {(r + row0, c + col0): grid[r][c] & 0xFF
             for r in range(canon.ROWS) for c in range(canon.COLS)
             if grid[r][c] & 0xFF}

    exe = donor.DonorExe.load()
    names = exe.location_names()
    places = donor.world_locations()
    have = set(donor.map_numbers())
    interf = InterfRes.from_game()
    shared_rows = range(10, 24)
    shared_cols = range(22, 32)

    good, skipped = [], []
    for location in sorted(places):
        row, col = places[location]
        name = names[location] if location < len(names) else ""
        why = None
        if location not in have:
            why = "нет файла карты"
        elif not (0 <= row < rows and 0 <= col < cols):
            why = "клетка вне общей карты"
        elif not walk[row][col] & canon.MASK_LAND:
            why = "клетка на нарисованном море"
        elif (row, col) in taken:
            why = f"клетку занимает наша локация {taken[(row, col)]}"
        elif (row, col) not in reachable:
            why = "отрезана от материка: пешком не дойти"
        if why:
            skipped.append((location, name, (row, col), why))
            continue
        sprite = donor.world_marker(location)
        if not sprite or interf.frame_size(sprite) is None:
            sprite = FALLBACK_MARKER
        good.append({"location": location, "name": name, "cell": [row, col],
                     "sprite": sprite,
                     "shared": row in shared_rows and col in shared_cols})

    print(f"сажаем: {len(good)}, пропускаем: {len(skipped)}\n")
    print(f"{'лок':>4} {'название':<28} {'клетка':>9} {'значок':>7}  где")
    for entry in good:
        where = "ОБЩАЯ ПОЛОСА" if entry["shared"] else "своя земля"
        print(f"{entry['location']:>4} {entry['name']:<28} "
              f"{str(tuple(entry['cell'])):>9} {entry['sprite']:>7}  {where}")
    print(f"\nпропущены:")
    for location, name, place, why in skipped:
        print(f"{location:>4} {name:<28} {str(place):>9}  {why}")

    if not write:
        print("\n(показ без записи; чтобы перенести — --write)")
        return 0

    records, entries = [], []
    for entry in good:
        record = donor_import.import_map(entry["location"], names)
        records.append(record)
        entries.append({
            "number": record["map"],
            "name": entry["name"],
            "source": record["source"],
            "cell": entry["cell"],
            "cell_comment": (
                "Снято с карты мира донора и перенесено сдвигом "
                f"{donor.DONOR_WORLD_AT}, замеренным по картинкам."),
            "marker": {"sprite": entry["sprite"], "dx": 0, "dy": 0},
            "marker_comment": "Значок из записи локации донора (+0x08).",
            "arrival": record["arrival"],
            "arrival_comment": "Замерено tools/donor_import.py по самой карте.",
            "shared_strip": entry["shared"],
        })
    donor_import.register(records)

    # Реестр локаций: свои записи заменяем, чужие не трогаем.
    path = ROOT / "project" / "locations.json"
    registry = json.loads(path.read_text(encoding="utf-8"))
    by_number = {int(item["number"]): item for item in registry["locations"]}
    for entry in entries:
        by_number[entry["number"]] = entry
    registry["locations"] = [by_number[key] for key in sorted(by_number)]
    path.write_text(json.dumps(registry, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    print(f"\nproject/locations.json: локаций {len(registry['locations'])}")
    return entries


if __name__ == "__main__":
    result = main()
    raise SystemExit(0 if not isinstance(result, int) else result)
