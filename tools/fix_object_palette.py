# -*- coding: utf-8 -*-
"""Починить палитру объектов в проектных картах, ничего не потеряв.

ЧТО СЛУЧИЛОСЬ. Палитра объекта в записи ``.KN2`` — это байтовое смещение в
блоке палитр (шаг 0x200), и движок читает его ДВОЙНЫМ СЛОВОМ целиком
(VA 0x43E7D8). Прежняя выгрузка проекта читала половину, и всё, что больше
0xFFFF, обрезалось: у деревьев Беглого вместо 116736 записано 51200, то
есть палитра 100 вместо 228. Оттого крона и выходила выбеленной, с красным
и синим крапом.

ПОЧЕМУ НЕ НУЖНА ПЕРЕВЫГРУЗКА. Правильное значение никуда не делось: рядом,
в поле ``raw`` той же записи, лежат её сырые байты целиком. Значит починка
чисто местная — пересчитать одно число из соседнего поля. Ни правки рук, ни
что-либо ещё в проекте не трогается.

ПРОВЕРКА ПЕРЕД ЗАПИСЬЮ. Трогаются только записи, где поле в точности равно
младшей половине сырого дворда. Всё остальное остаётся как есть, и если
находится расхождение другого рода — файл не переписывается вовсе.

    python tools/fix_object_palette.py            # показать, что будет
    python tools/fix_object_palette.py --write    # записать
"""
from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path

#: Где в записи объекта лежит палитра и какой у неё размер.
PALETTE_AT = 4
#: Шаг блока палитр: индекс = смещение // 0x200.
PALETTE_STRIDE = 0x200


def repair_records(records: list[dict]) -> tuple[int, list[str]]:
    """Починить записи на месте. Возвращает «сколько» и «что не так»."""
    fixed = 0
    trouble: list[str] = []
    for record in records:
        raw = record.get("raw")
        if not raw:
            continue
        try:
            data = bytes.fromhex(raw)
            full = struct.unpack_from("<I", data, PALETTE_AT)[0]
        except (ValueError, struct.error):
            trouble.append(f"слот {record.get('slot')}: raw не читается")
            continue
        current = record.get("kind")
        if current == full:
            continue
        if current != (full & 0xFFFF):
            # Не обрезание, а что-то иное — такую запись не трогаем.
            trouble.append(
                f"слот {record.get('slot')}: поле {current}, в байтах {full}")
            continue
        record["kind"] = full
        fixed += 1
    return fixed, trouble


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fix-object-palette")
    parser.add_argument("--project", type=Path, default=Path("project/maps"))
    parser.add_argument("--write", action="store_true",
                        help="записать изменения; без него только показ")
    args = parser.parse_args(argv)

    всего = 0
    задето = 0
    for path in sorted(args.project.glob("*/map.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        records = (document.get("objects") or {}).get("records") or []
        if not records:
            continue
        fixed, trouble = repair_records(records)
        if trouble:
            print(f"{path.parent.name}: НЕ ТРОГАЮ, странные записи:")
            for line in trouble[:5]:
                print(f"    {line}")
            continue
        if not fixed:
            continue
        всего += fixed
        задето += 1
        палитры = sorted({r["kind"] // PALETTE_STRIDE for r in records
                          if isinstance(r.get("kind"), int)})
        print(f"{path.parent.name}: починено {fixed}, палитры теперь "
              f"{палитры[:6]}{'…' if len(палитры) > 6 else ''}")
        if args.write:
            path.write_text(
                json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8", newline="\n")

    print(f"\nкарт задето {задето}, записей починено {всего}")
    if not args.write:
        print("это был показ; чтобы записать, добавьте --write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
