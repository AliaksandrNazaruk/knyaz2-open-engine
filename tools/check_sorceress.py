# -*- coding: utf-8 -*-
"""Проверка собранного пака: волшебница на месте и её кадры сходятся.

    python tools/check_sorceress.py [пак]

Смотрит ровно то, на что слепы тесты сборщика: попал ли свой набор в
shared.json, лежит ли рядом лист, ссылаются ли кадры на него и стоит ли
юнит на карте 63 с поднятым битом твари.
"""
import json
import struct
import sys
from pathlib import Path

BODY = "200"
MAP = "63"
POSES = ("stand", "walk", "attack", "hit", "death_1", "rise")
BEAST_BIT = 0x40


def png_size(path: Path):
    with open(path, "rb") as stream:
        head = stream.read(24)
    return struct.unpack(">II", head[16:24])


def main() -> int:
    pack = Path(sys.argv[1] if len(sys.argv) > 1 else "content_build")
    bad = []
    shared = json.loads((pack / "shared.json").read_text(encoding="utf-8"))
    creatures = shared.get("creatures") or {}
    sheets = creatures.get("sheets") or []
    sets = creatures.get("sets") or {}

    own = sets.get(BODY)
    if not own:
        print("НЕТ набора тела %s в shared.json" % BODY)
        return 1
    palette, poses = sorted(own.items())[0]
    print("набор: тело %s, масть %s, поз %d" % (BODY, palette, len(poses)))

    for pose in POSES:
        directions = poses.get(pose)
        if not directions:
            bad.append("нет позы %s" % pose)
            continue
        if len(directions) != 8:
            bad.append("поза %s: %d направлений вместо 8" % (pose, len(directions)))
        counts = [len(d) for d in directions]
        if min(counts) == 0:
            bad.append("поза %s: пустое направление" % pose)
        print("   %-8s направлений %d, кадров %s" % (pose, len(directions), counts[0]))

    used = {frame["sheet"] for directions in poses.values()
            for frames in directions for frame in frames}
    if len(used) != 1:
        bad.append("кадры ссылаются на разные листы: %s" % sorted(used))
    number = sorted(used)[0]
    sheet = sheets[number]
    print("лист %d: %s %dx%d" % (number, sheet["path"], sheet["width"], sheet["height"]))
    image = pack / sheet["path"]
    if not image.is_file():
        bad.append("листа нет на диске: %s" % image)
    else:
        width, height = png_size(image)
        if (width, height) != (sheet["width"], sheet["height"]):
            bad.append("размер листа %dx%d, а в описи %dx%d"
                       % (width, height, sheet["width"], sheet["height"]))
        # каждый кадр должен целиком помещаться на лист
        for pose, directions in poses.items():
            for j, frames in enumerate(directions):
                for k, frame in enumerate(frames):
                    if (frame["x"] + frame["width"] > width
                            or frame["y"] + frame["height"] > height):
                        bad.append("%s[%d][%d] выходит за лист" % (pose, j, k))

    # канон не пострадал
    canon = [b for b in sets if b != BODY]
    print("канонных тел рядом: %d" % len(canon))
    if len(canon) < 20:
        bad.append("канонных наборов стало мало: %d" % len(canon))

    document = json.loads((pack / "maps" / MAP / "map.json").read_text(encoding="utf-8"))
    units = [u for u in (document.get("units") or []) if str(u.get("body")) == BODY]
    if not units:
        bad.append("на карте %s нет юнита с телом %s" % (MAP, BODY))
    for unit in units:
        breed = unit.get("breed", 0)
        print("юнит: %s тело %s масть %s порода 0x%02X клетка %s"
              % (unit.get("name"), unit.get("body"), unit.get("palette"), breed, unit.get("cell")))
        if not breed & BEAST_BIT:
            bad.append("у юнита не поднят бит твари 0x40 — клиент нарисует его слоями человека")
        if str(unit.get("palette")) not in own:
            bad.append("масть юнита %s, а набор есть только для %s"
                       % (unit.get("palette"), sorted(own)))

    # опись пака должна знать про лист
    manifest = json.loads((pack / "manifest.json").read_text(encoding="utf-8"))
    files = manifest.get("files") or {}
    if isinstance(files, dict):
        known = sheet["path"] in files
    else:
        known = any(entry.get("path") == sheet["path"] for entry in files)
    if not known:
        bad.append("листа нет в manifest.json — verify его не проверит")
    else:
        print("лист записан в manifest.json")

    print()
    if bad:
        print("НЕ СОШЛОСЬ (%d):" % len(bad))
        for line in bad:
            print("   " + line)
        return 1
    print("всё сошлось")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
