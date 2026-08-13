# -*- coding: utf-8 -*-
"""Бестиарий: всё о тварях, собранное из файлов игры.

Книга строится не из наших представлений, а из записей юнитов всех шести
миров `GAME.N` — по тем смещениям, что разобраны в `konung2/gamefile.py`, и с
формулами, снятыми с движка. Каждый столбец назван вместе с адресом, откуда
он взят, чтобы книгу можно было перепроверить.

Тварь от человека отличается ОБЛИКОМ (`+0xFC`): меньше шести — человек,
движок рисует его слоем `0x30 + облик`, иначе — целым набором кадров той же
породы (VA 0x424200, 0x4267B8). Тот же порог движок применяет и сам: обучение
в деревне считает работниками только тех, у кого облик меньше шести
(VA 0x4181E8).

    python tools/bestiary.py --md docs/BESTIARY.md
"""
from __future__ import annotations

import argparse
import collections
import io
import os
import struct
import sys

CREATURE_BODY_FROM = 6          # облик меньше шести — человек (0x4181E8)
BEAST_BIT = 0x40                # порода +0x1A: зверь (0x41B044)
DEAD_BIT = 0x80

#: ИМЯ ТВАРИ БЕРЁТСЯ ПО ПОРОДЕ, а не по облику. VA 0x43000C:
#:
#:     порода = юнит[+0x1A] & 0x7F
#:     если (юнит[+0x1A] & 0x40) и порода <= 0x53:
#:         имя = PTR_DAT_0045FAE0[порода]          # зверь
#:     иначе:
#:         имя = PTR_DAT_0046188C[юнит[+0xF0]] (+ «, роль» из 0x461B70[+0xF1])
#:
#: То есть таблица «ролей» одна на всех, а звериные имена лежат в её хвосте.
NAMES_VA = 0x45FAE0
NAME_LAST = 0x53


def worlds(root: str):
    sys.path.insert(0, root)
    from konung2.gamefile import T_PARTIES, T_UNITS, unit_stats
    from konung2.paths import game_file
    for number in range(6):
        try:
            blob = open(game_file(f"GAME.{number}"), "rb").read()
        except OSError:
            continue
        yield number, blob, T_PARTIES, T_UNITS, unit_stats


def names(root: str) -> dict[int, str]:
    """Имена по породе: указатели 0x45FAE0 + порода*4, строки в cp866."""
    sys.path.insert(0, root)
    from konung2.exetables import va_to_foff
    from konung2.paths import game_file
    blob = open(game_file("konung2.exe"), "rb").read()
    delta = NAMES_VA - va_to_foff(NAMES_VA)
    out: dict[int, str] = {}
    for breed in range(BEAST_BIT, NAME_LAST + 1):
        at = va_to_foff(NAMES_VA) + breed * 4
        pointer, = struct.unpack_from("<I", blob, at)
        file_at = pointer - delta
        if not (0 < file_at < len(blob)):
            continue
        end = blob.find(bytes([0]), file_at)
        text = blob[file_at:end].decode("cp866", "replace")
        if text:
            out[breed] = text
    return out


def collect(root: str):
    """Все твари всех миров: облик -> сведения."""
    book: dict[int, dict] = collections.defaultdict(lambda: {
        "count": 0, "maps": collections.Counter(), "levels": [], "health": [],
        "armour": [], "venom": [], "accuracy": [], "bodies": collections.Counter(),
        "palettes": collections.Counter(), "beast": 0, "worlds": set(),
        "characteristics": collections.defaultdict(list),
        "skills": collections.defaultdict(list), "hand": collections.Counter(),
    })
    for number, blob, parties, units, unit_stats in worlds(root):
        for squad in range(parties.count):
            at = parties.offset + squad * parties.size
            on_map, = struct.unpack_from("<H", blob, at + 8)
            first, = struct.unpack_from("<H", blob, at + 0x00)
            count = blob[at + 0x1C]
            for step in range(count):
                index = first + step
                if index >= units.count:
                    break
                record = blob[units.offset + index * units.size:][:units.size]
                if len(record) < units.size or not (record[0x1A] & BEAST_BIT):
                    continue
                if record[0x1A] & DEAD_BIT:
                    continue
                got = unit_stats(blob, index)
                row = book[record[0x1A] & 0x7F]
                row["count"] += 1
                row["maps"][on_map] += 1
                row["worlds"].add(number)
                row["levels"].append(got["level"])
                row["health"].append(got["health"])
                row["armour"].append(got["armour"])
                row["venom"].append(got["venom"])
                row["accuracy"].append(got["accuracy"])
                row["bodies"][got["body"]] += 1
                row["palettes"][got["palette"]] += 1
                row["hand"][got.get("equipment", {}).get("hand")] += 1
                if record[0x1A] & BEAST_BIT:
                    row["beast"] += 1
                for name, value in (got.get("characteristics") or {}).items():
                    row["characteristics"][name].append(value)
                for name, value in (got.get("skills") or {}).items():
                    if value:
                        row["skills"][name].append(value)
    return book


def span(values) -> str:
    if not values:
        return "—"
    low, high = min(values), max(values)
    return str(low) if low == high else f"{low}…{high}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bestiary")
    parser.add_argument("--root", default=".")
    parser.add_argument("--md")
    args = parser.parse_args(argv)

    book = collect(args.root)
    titles = names(args.root)
    sys.path.insert(0, args.root)
    try:
        from konung2.gamefile import location_names
        got = location_names()
        места = (got if isinstance(got, dict)
                 else {n: name for n, name in enumerate(got)})
    except Exception:
        места = {}

    print(f"пород тварей: {len(book)}, всего записей: "
          f"{sum(row['count'] for row in book.values())}")
    if not args.md:
        for breed in sorted(book):
            row = book[breed]
            print(f"  {titles.get(breed, '?'):<20} порода {breed:#04x}: "
                  f"{row['count']:>4} шт, карт {len(row['maps']):>2}, "
                  f"уровни {span(row['levels'])}, отрава {span(row['venom'])}")
        return 0

    lines = [
        "# Бестиарий: твари по записям игры", "",
        "Собрано `tools/bestiary.py` из всех шести миров `GAME.N`. Тварь от "
        "человека отличается ОБЛИКОМ `+0xFC`: меньше шести — человек, движок "
        "рисует его слоем `0x30 + облик`, иначе — целым набором кадров "
        "(VA 0x424200, 0x4267B8). Тот же порог движок применяет сам — "
        "обучение в деревне считает работниками только облик меньше шести "
        "(VA 0x4181E8).", "",
        "Столбцы и откуда они взяты:", "",
        "| столбец | поле записи | адрес |",
        "|---|---|---|",
        "| уровень | `+0xF3` | 0x413138 |",
        "| здоровье | `+0x4E` | 0x41C494 |",
        "| броня | `+0xF4` | 0x41A414 |",
        "| отрава | `+0xF6` | 0x41A7D0, 0x41BB10 |",
        "| точность | `+0x1F` | 0x41FDD0 |",
        "| зверь | `+0x1A` бит 0x40 | 0x41B044 |",
        "| облик | `+0xFC` | 0x424200 |",
        "| палитра | `+0x2E` делить на 512 | 0x425DB4 |", "",
        f"Всего обликов: **{len(book)}**, записей тварей: "
        f"**{sum(row['count'] for row in book.values())}**.", "",
        "## Сводка", "",
        "| тварь | порода | сколько | уровень | броня | отрава | "
        "точность | карт |", "|---|---|---|---|---|---|---|---|",
    ]
    for breed in sorted(book):
        row = book[breed]
        lines.append(
            f"| **{titles.get(breed, '?')}** | {breed:#04x} | {row['count']} | "
            f"{span(row['levels'])} | {span(row['armour'])} | "
            f"{span(row['venom'])} | {span(row['accuracy'])} | "
            f"{len(row['maps'])} |")
    lines += ["", "## Подробно", ""]
    for breed in sorted(book):
        row = book[breed]
        карты = ", ".join(
            f"{места.get(m, m)} ({c})" if места else f"{m} ({c})"
            for m, c in row["maps"].most_common(10))
        lines += [f"### {titles.get(breed, '?')} (порода {breed:#04x})", "",
                  f"* записей: **{row['count']}**, из них зверей "
                  f"(бит 0x40): {row['beast']}",
                  f"* миры: {sorted(row['worlds'])}",
                  f"* уровень {span(row['levels'])}, здоровье "
                  f"{span(row['health'])}, броня {span(row['armour'])}, "
                  f"отрава {span(row['venom'])}, точность "
                  f"{span(row['accuracy'])}",
                  f"* облики: {', '.join(str(b) for b, _ in row['bodies'].most_common(4))}; "
                  f"палитры: {', '.join(str(p) for p, _ in row['palettes'].most_common(6))}",
                  f"* обитание: {карты}"]
        if row["characteristics"]:
            свод = ", ".join(f"{name} {span(values)}"
                             for name, values in row["characteristics"].items())
            lines.append(f"* характеристики: {свод}")
        if row["skills"]:
            свод = ", ".join(f"{name} {span(values)}"
                             for name, values in sorted(row["skills"].items()))
            lines.append(f"* навыки: {свод}")
        lines.append("")
    io.open(os.path.join(args.root, args.md), "w", encoding="utf-8").write(
        "\n".join(lines) + "\n")
    print(f"книга: {args.md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
