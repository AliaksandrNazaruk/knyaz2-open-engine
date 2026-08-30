# -*- coding: utf-8 -*-
"""GAME.N -> project/worlds/N/*.json: миры как исходники (EDITOR_VISION E2).

Авторы собирали миры текстом (86 исходников GAMERES -> M_UNIT -> GAME.N);
мы возвращаем миру исходниковую форму — JSON по карте, диффабельный и
редактируемый. Читалки полей давно живут в gamefile.py — здесь только
раскладка по файлам.

Раскладка экспорта:

    project/worlds/<N>/meta.json      герой, стартовая карта, счётчики
    project/worlds/<N>/maps/<M>.json  отряды, юниты, кучи, выходы,
                                      события и поселение карты M
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import struct

from .gamefile import (WORLD_COUNT, _game_bytes, all_exits, ground_items,
                       hero_stats, map_events, map_exits, map_parties,
                       map_units, player_party, village)
from .paths import game_file

#: Куда кладётся СОБРАННЫЙ мир (наш M_UNIT): gamefile._game_bytes читает
#: его приоритетно, и вся сборка пака видит правленый мир одной точкой.
WORLDS_BUILD = Path(__file__).resolve().parents[1] / "project" / "worlds" / "build"


def world_map_numbers(world: int) -> list[int]:
    """Карты, где у мира есть хоть что-то: отряды или выходы."""
    import struct
    numbers: set[int] = set()
    data, layout = _game_bytes(world)
    start, tally, stride = layout["parties"]
    for band in range(tally):
        record = data[start + band * stride:][:stride]
        map_rec = struct.unpack_from("<H", record, 0x08)[0]
        if 0 < map_rec < 0xFF:
            numbers.add(map_rec)
    for exit_rec in all_exits(world):
        map_rec = exit_rec.get("map")
        if isinstance(map_rec, int) and 0 < map_rec < 0xFF:
            numbers.add(map_rec)
    return sorted(numbers)


def export_map(world: int, number: int) -> dict:
    """Содержимое одной карты мира — всё, что о ней знает GAME.N.

    Отрядам и юнитам добавляется ``raw`` — hex сырой записи: сборщик
    мира (build_world) берёт его основой и кладёт разобранные поля
    ПОВЕРХ, как binrec.pack, — неразобранные байты записи не теряются,
    а нетронутый экспорт собирается байт-в-байт.
    """
    data, layout = _game_bytes(world)
    bands_at, _, band_stride = layout["parties"]
    units_at, _, unit_stride = layout["units"]
    bands = map_parties(number, world)
    for band in bands:
        # сторона отряда РАВНА его слоту (0x71E56C + сторона * 0x100)
        slot = int(band["side"])
        band["slot"] = slot
        start = bands_at + slot * band_stride
        band["raw"] = data[start:start + band_stride].hex()
    units = map_units(number, world)
    for unit in units:
        start = units_at + int(unit["index"]) * unit_stride
        unit["raw"] = data[start:start + unit_stride].hex()
    return {
        "map": number,
        "parties": bands,
        "units": units,
        "loot": ground_items(number, world),
        "exits": map_exits(number, world),
        "events": map_events(number, world),
        "village": village(number, world),
    }


def export_world(world: int, out_dir: str | Path) -> dict:
    """Разложить мир по файлам. Возвращает мету с описью."""
    root = Path(out_dir) / str(world)
    (root / "maps").mkdir(parents=True, exist_ok=True)
    maps = world_map_numbers(world)
    counters = {}
    for number in maps:
        document = export_map(world, number)
        counters[str(number)] = {
            "parties": len(document["parties"]),
            "units": len(document["units"]),
            "loot": len(document["loot"]),
            "exits": len(document["exits"]),
            "village": document["village"] is not None,
        }
        (root / "maps" / f"{number}.json").write_text(
            json.dumps(document, ensure_ascii=False, indent=1),
            encoding="utf-8")
    # стартовая карта мира — слово +0x08 записи отряда №0 (отряда игрока)
    import struct
    data, layout = _game_bytes(world)
    bands_start = layout["parties"][0]
    starting = struct.unpack_from("<H", data, bands_start + 0x08)[0]
    meta = {
        "world": world,
        "hero": hero_stats(world),
        "player_party": player_party(world),
        "start_map": starting,
        "maps": counters,
    }
    (root / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


#: ═══ СБОРКА МИРА (наш M_UNIT) ═══════════════════════════════════════════
#:
#: project/worlds/<N>/maps/*.json -> GAME.<N> в project/worlds/build/.
#: Основа — ОРИГИНАЛЬНЫЙ файл игры (нетронутые области: глобальная
#: карта, вещи, счётчики — сохраняются как есть); поверх кладутся записи
#: отрядов и юнитов: raw записи, а на него — разобранные поля из JSON.
#: Нетронутый экспорт по построению собирается байт-в-байт.
#:
#: Смещения полей — те же, что у читалок gamefile.py (unit_stats,
#: map_parties, spawn_zone): писатель и читатель делят одну карту байт.

from .progress import CHARACTERISTICS, SKILLS


def _write_party(record: bytearray, band: dict) -> None:
    struc = struct
    if "first_unit" in band:
        struc.pack_into("<H", record, 0x00, int(band["first_unit"]))
    if "map" in band:
        struc.pack_into("<H", record, 0x08, int(band["map"] or 0))
    if "count" in band:
        record[0x1C] = int(band["count"]) & 0xFF
    zone = band.get("zone") or {}
    # ряды зоны — u16, СТОЛБЦЫ — БАЙТЫ: их соседи 0x15/0x17 заняты
    # столбцами roam (гуляния пород 0x54/0x55) — u16-запись их затирала,
    # round-trip поймал 219 затёртых байтов
    for key, off in (("row_from", 0x0C), ("row_to", 0x10)):
        if key in zone:
            struc.pack_into("<H", record, off, int(zone[key]) & 0xFFFF)
    for key, off in (("col_from", 0x14), ("col_to", 0x16)):
        if key in zone:
            record[off] = int(zone[key]) & 0xFF
    if "flags" in zone:
        record[0x1E] = int(zone["flags"]) & 0xFF
    if "war_flags" in band:
        record[0x1F] = int(band["war_flags"]) & 0xFF
    if "enemy_side" in band:
        record[0x06] = int(band["enemy_side"]) & 0xFF
    if "fighting" in band:
        record[0x1D] = 1 if band["fighting"] else 0


def _write_unit(record: bytearray, unit: dict) -> None:
    struc = struct
    #: ИМЯ И ПРОЗВИЩЕ — НОМЕРА В ТАБЛИЦАХ EXE, а не строки: самой строки
    #: в GAME.<мир> нет вовсе (0xF0 — таблица имён, 0xF1 — прозвищ, см.
    #: gamefile.map_units и _npc_nickname). Без них добавленный
    #: редактором житель обречён зваться так же, как запись, с которой
    #: он снят: поставишь пятерых — выйдет пять тёзок.
    #: Тварей это не касается: у пород 0x41…0x53 имя берётся из таблицы
    #: пород по самому байту породы, и байты имени там не смотрят.
    raw_bytes = (("row", 0x12), ("col", 0x14), ("pose", 0x17),
             ("direction", 0x18), ("breed", 0x1A), ("side", 0x1B),
             ("accuracy", 0x1F), ("breed_counter", 0xEE),
             ("face", 0xEF), ("name_id", 0xF0), ("nick_id", 0xF1),
             ("dialog", 0xF2), ("level", 0xF3),
             ("armour", 0xF4), ("venom", 0xF6), ("body", 0xFC))
    for key, off in raw_bytes:
        if key in unit:
            record[off] = int(unit[key]) & 0xFF
    if "speed" in unit:
        struc.pack_into("<b", record, 0x1D, int(unit["speed"]))
    if "health" in unit:
        struc.pack_into("<h", record, 0x4E, int(unit["health"]))
    if "money" in unit:
        struc.pack_into("<i", record, 0x26, int(unit["money"]))
    if "experience" in unit:
        struc.pack_into("<i", record, 0x22, int(unit["experience"]))
    if "next_level" in unit:
        struc.pack_into("<i", record, 0x2A, int(unit["next_level"]))
    if "free_xp" in unit:
        struc.pack_into("<h", record, 0x48, int(unit["free_xp"]))
    if "palette" in unit:
        # в записи лежит БАЙТОВОЕ СМЕЩЕНИЕ палитры: номер * 512
        struc.pack_into("<i", record, 0x2E, int(unit["palette"]) * 512)
    for name, base in (("characteristics", 0xC0), ("current", 0xCC)):
        block = unit.get(name)
        if isinstance(block, dict):
            for stride, stat in enumerate(CHARACTERISTICS):
                if stat in block:
                    record[base + stride] = int(block[stat]) & 0xFF
    skills = unit.get("skills")
    if isinstance(skills, dict):
        # экспорт пишет только ненулевые: отсутствующее имя — ноль
        for stride, skill in enumerate(SKILLS):
            record[0xD2 + stride] = int(skills.get(skill) or 0) & 0xFF


def build_world(world: int, src_dir: str | Path,
                out_dir: str | Path | None = None) -> Path:
    """Собрать GAME.<world> из исходников мира. Возвращает путь."""
    sources = Path(src_dir) / str(world) / "maps"
    if not sources.is_dir():
        raise FileNotFoundError(f"нет исходников мира {world}: {sources}")
    with open(game_file(f"GAME.{world}"), "rb") as stream:
        data = bytearray(stream.read())
    _, layout = _game_bytes(world)
    bands_at, band_count, band_stride = layout["parties"]
    units_at, unit_count, unit_stride = layout["units"]
    for file in sorted(sources.glob("*.json")):
        document = json.loads(file.read_text(encoding="utf-8"))
        for band in document.get("parties") or []:
            slot = int(band.get("slot", band.get("side", -1)))
            if not 0 <= slot < band_count:
                raise ValueError(f"{file.name}: слот отряда {slot} "
                                 f"вне таблицы из {band_count}")
            start = bands_at + slot * band_stride
            record = bytearray(bytes.fromhex(band["raw"])
                               if band.get("raw")
                               else data[start:start + band_stride])
            band.setdefault("map", document.get("map"))
            _write_party(record, band)
            data[start:start + band_stride] = record
        for unit in document.get("units") or []:
            number = int(unit["index"])
            if not 0 <= number < unit_count:
                raise ValueError(f"{file.name}: юнит {number} вне "
                                 f"таблицы из {unit_count}")
            start = units_at + number * unit_stride
            record = bytearray(bytes.fromhex(unit["raw"])
                               if unit.get("raw")
                               else data[start:start + unit_stride])
            _write_unit(record, unit)
            data[start:start + unit_stride] = record
    exit_rec = Path(out_dir) if out_dir is not None else WORLDS_BUILD
    exit_rec.mkdir(parents=True, exist_ok=True)
    world_file = exit_rec / f"GAME.{world}"
    world_file.write_bytes(bytes(data))
    return world_file


def main(argv: list[str] | None = None) -> int:
    parsed = argparse.ArgumentParser(prog="konung2-worlds")
    parsed.add_argument("--out", type=Path,
                        default=Path("project") / "worlds")
    parsed.add_argument("--world", type=int, action="append",
                        help="номер мира; можно повторять (все — если нет)")
    parsed.add_argument("--build", action="store_true",
                        help="собрать GAME.N из исходников (в --out/build)")
    args = parsed.parse_args(argv)
    worlds = args.world or list(range(WORLD_COUNT))
    for world in worlds:
        if args.build:
            file = build_world(world, args.out)
            print(f"мир {world}: собран {file}")
        else:
            meta = export_world(world, args.out)
            print(f"мир {world}: карт {len(meta['maps'])}, "
                  f"старт {meta['start_map']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
