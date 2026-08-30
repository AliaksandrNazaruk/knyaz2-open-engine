# -*- coding: utf-8 -*-
"""
Сверка бесцветных кадров юнитов со старой цветной выпечкой.

Переключать клиента на индексные листы можно только после того, как
доказано: цвет, подставленный к бесцветному кадру, даёт РОВНО ту же
картинку, что лежит в паке сейчас. Скрипт проходит все наборы тел и
снаряжения целиком, кадр в кадр, и печатает счёт.

Запуск:
    python tools/verify_indexed_units.py [content_build]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load_sheets(pack: Path, sheets: list[dict]) -> list:
    from PIL import Image
    out = []
    for sheet in sheets:
        path = pack / sheet["path"]
        out.append(Image.open(path).convert("RGBA") if path.is_file() else None)
    return out


def crop(sheets: list, frame: dict):
    sheet = sheets[frame["sheet"]] if frame.get("sheet") is not None else None
    if sheet is None:
        return None
    box = (frame["x"], frame["y"],
           frame["x"] + frame["width"], frame["y"] + frame["height"])
    return sheet.crop(box)


def palette_rows(pack: Path, entry: dict) -> list[list[tuple[int, int, int]]]:
    from PIL import Image
    picture = Image.open(pack / entry["path"]).convert("RGB")
    data = list(picture.getdata())
    width = picture.width
    return [data[row * width:(row + 1) * width] for row in range(picture.height)]


def main() -> int:
    pack = Path(sys.argv[1] if len(sys.argv) > 1 else "content_build")
    shared = json.loads((pack / "shared.json").read_text(encoding="utf-8"))
    hero = shared["hero"]
    plain = hero.get("plain_layers") or {}
    if not plain:
        print("в паке нет бесцветных слоёв — нечего сверять")
        return 1
    colour_sheets = load_sheets(pack, hero.get("sheets") or [])
    plain_sheets = load_sheets(pack, hero.get("plain_sheets") or [])
    palettes = {name: palette_rows(pack, entry)
                for name, entry in (shared.get("palettes") or {}).items()}
    if not palettes:
        print("в паке нет палитр")
        return 1

    checked = same = 0
    broken: list[str] = []

    def compare(colour_entry: dict, game: str, layer: int, palette_index: int,
                label: str) -> None:
        nonlocal checked, same
        source = plain.get(f"{game}:{layer}")
        if source is None:
            broken.append(f"{label}: нет бесцветного слоя {game}:{layer}")
            return
        table = palettes.get(game) or palettes["canon"]
        row = table[palette_index % len(table)]
        for record, frame in (colour_entry.get("frames") or {}).items():
            plain_frame = (source.get("frames") or {}).get(record)
            if plain_frame is None:
                broken.append(f"{label}: кадра {record} нет среди бесцветных")
                return
            want = crop(colour_sheets, frame)
            index_shot = crop(plain_sheets, plain_frame)
            if want is None or index_shot is None:
                broken.append(f"{label}: лист не читается")
                return
            painted = [(*row[px[0]], 255) if px[3] else (0, 0, 0, 0)
                       for px in index_shot.getdata()]
            checked += 1
            if painted == list(want.getdata()) and \
                    (frame.get("offset_x"), frame.get("offset_y")) == \
                    (plain_frame.get("offset_x"), plain_frame.get("offset_y")):
                same += 1
            else:
                broken.append(f"{label}: кадр {record} разошёлся")
                return

    for key, entry in (hero.get("body_layers") or {}).items():
        parts = key.split(":")
        if len(parts) == 3:
            game, body, palette_index = parts[0], int(parts[1]), int(parts[2])
        elif len(parts) == 2:
            game, body, palette_index = "canon", int(parts[0]), int(parts[1])
        else:
            continue
        layer = 0 if body == 0 else 0x30 + body
        compare(entry, game, layer, palette_index, f"тело {key}")

    for key, entry in (hero.get("equipment") or {}).items():
        if ":" not in key:
            continue
        layer, palette_index = (int(part) for part in key.split(":"))
        compare(entry, "canon", layer, palette_index, f"снаряжение {key}")

    print(f"сверено кадров: {checked}, совпало: {same}, наборов с бедой: "
          f"{len(broken)}")
    for line in broken[:20]:
        print("  ", line)
    return 0 if checked and not broken and same == checked else 1


if __name__ == "__main__":
    raise SystemExit(main())
