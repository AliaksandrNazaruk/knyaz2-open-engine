# -*- coding: utf-8 -*-
"""
Перезаписать `grid.txt` перенесённых карт по исправленному переводу клеток.

Зачем: прежний перевод резал номер постройки по пяти битам и сдвигал флаги
вниз, и постройка 38 (0xE6) становилась постройкой 6 (0x66). На Кирингхольме
так теряли клетки 29 построек из 58, в Тиграте 21 из 47 — а без клеток крыша
не прячется и юнит рисуется поверх дома. Теперь переводится только младшее
слово (проходимость), а старшее остаётся донорским и читается его раскладкой
(`konung2.world.model.LEGEND_CELLS`).

Трогается РОВНО `grid.txt`: `map.json` перенесённых карт правился руками
(точки прибытия, убранные сочинённые полосы), и переносить их заново нельзя.

    python tools/regrid_donor.py [--dry]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from konung2 import donor  # noqa: E402
from konung2.kn2 import GRID_H, GRID_W, KN2Map  # noqa: E402

HEAD = ("# сетка карты: 256 строк по 160 клеток, формат LO:HI (hex)\n"
        "# LO=4FFF — пустая клетка (0xFFF в младших битах = непроходимо)\n")


def grid_text(kn2: KN2Map) -> str:
    lines = []
    for row in range(GRID_H):
        lines.append(" ".join(f"{lo:04X}:{hi:04X}"
                              for lo, hi in (kn2.cell(col, row)
                                             for col in range(GRID_W))))
    return HEAD + "\n".join(lines) + "\n"


def main() -> int:
    dry = "--dry" in sys.argv
    changed = same = 0
    widest = []
    for folder in sorted((ROOT / "project" / "maps").iterdir()):
        document = folder / "map.json"
        if not document.is_file():
            continue
        origin = (json.loads(document.read_text(encoding="utf-8"))
                  .get("origin") or {})
        if origin.get("game") != donor.LEGEND_NAME:
            continue
        his = int(origin["map"])
        data, _ = donor.map_data(his)
        fresh = grid_text(KN2Map(int(re.match(r"^(\d+)_", folder.name)[1]), data))
        target = folder / "grid.txt"
        was = target.read_text(encoding="utf-8") if target.is_file() else ""
        # сколько построек карта вообще может назвать: шесть бит против пяти
        numbers = {int(token.split(":")[1], 16) & donor.DONOR_CELL_OBJECT
                   for line in fresh.splitlines() if not line.startswith("#")
                   for token in line.split()}
        numbers.discard(0)
        if max(numbers, default=0) > 31:
            widest.append((folder.name, len(numbers), max(numbers)))
        if fresh == was:
            same += 1
            continue
        changed += 1
        if not dry:
            target.write_text(fresh, encoding="utf-8")
    print(f"сеток переписано: {changed}, совпало: {same}")
    print(f"карт, где номер постройки не влезал в пять бит: {len(widest)}")
    for name, count, top in widest[:10]:
        print(f"   {name}: номеров {count}, наибольший {top}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
