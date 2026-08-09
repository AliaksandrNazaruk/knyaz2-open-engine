# -*- coding: utf-8 -*-
"""Снимок сцены прямо из content pack — без браузера.

Повторяет дневной порядок клиента: земля, оверлеи, затем сущности по ключу
глубины (main, стены, крыша). Нужен, чтобы сравнивать варианты земли
воспроизводимо, а не скриншотами.

    python tools/render_pack.py --at 2 --size 1100 620 --out scene.png
    python tools/render_pack.py --at 2 --original --out scene_before.png
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image


def load(pack: Path, number: int) -> dict:
    return json.loads((pack / "maps" / str(number) / "map.json").read_text(encoding="utf-8"))


def paste(canvas: Image.Image, pack: Path, relative: str, x: int, y: int, cache: dict) -> None:
    if not relative:
        return
    if relative not in cache:
        try:
            with Image.open(pack / relative) as image:
                cache[relative] = image.convert("RGBA")
        except OSError:
            cache[relative] = None
    sprite = cache[relative]
    if sprite is not None:
        canvas.alpha_composite(sprite, (x, y))


def render(pack: Path, document: dict, left: int, top: int, width: int, height: int,
           *, original: bool = False, roofs: bool = True) -> Image.Image:
    canvas = Image.new("RGBA", (width, height), (20, 19, 16, 255))
    cache: dict = {}
    right, bottom = left + width, top + height

    for cell in document["terrain"]["ground"]:
        x, y = cell["x"] - left, cell["y"] - top
        if x > width or y > height or x < -120 or y < -70:
            continue
        asset = cell.get("asset_original" if original else "asset") or cell.get("asset")
        paste(canvas, pack, asset, x, y, cache)

    for overlay in document["terrain"]["overlays"]:
        frame = overlay.get("frame")
        if not frame:
            continue
        x, y = overlay["position"]["x"] - left, overlay["position"]["y"] - top
        if x > width or y > height or x + frame["width"] < 0 or y + frame["height"] < 0:
            continue
        paste(canvas, pack, frame["asset"], x, y, cache)

    entities = sorted([*document["buildings"], *document["props"]],
                      key=lambda e: (e["bounds"]["sort_y"], e["bounds"]["draw_x"],
                                     e["record_slot"]))
    for entity in entities:
        frames = entity.get("frames") or {}
        bounds = entity["bounds"]
        if bounds["draw_x"] > right or bounds["draw_y"] > bottom or \
                bounds["draw_x"] + bounds["width"] < left or \
                bounds["draw_y"] + bounds["height"] < top:
            continue
        for part in ("main", "walls", "roof"):
            frame = frames.get(part)
            if not frame or (part == "roof" and not roofs):
                continue
            paste(canvas, pack, frame["asset"],
                  entity["position"]["x"] + frame["offset_x"] - left,
                  entity["position"]["y"] + frame["offset_y"] - top, cache)
    return canvas.convert("RGB")


def main() -> int:
    parser = argparse.ArgumentParser(description="Снимок сцены из пака")
    parser.add_argument("--pack", type=Path, default=Path("content_build"))
    parser.add_argument("--map", type=int, default=19)
    parser.add_argument("--at", type=int, help="центрировать на записи этого объекта")
    parser.add_argument("--center", type=int, nargs=2, help="центр в мировых пикселях")
    parser.add_argument("--size", type=int, nargs=2, default=(1100, 620))
    parser.add_argument("--original", action="store_true", help="земля до опыта")
    parser.add_argument("--no-roofs", action="store_true")
    parser.add_argument("--out", default="scene.png")
    args = parser.parse_args()

    document = load(args.pack, args.map)
    if args.at is not None:
        entity = next(e for e in [*document["buildings"], *document["props"]]
                      if e["record_slot"] == args.at)
        cx, cy = entity["position"]["x"], entity["position"]["y"] + 150
    elif args.center:
        cx, cy = args.center
    else:
        cx = sum(c["x"] for c in document["terrain"]["ground"]) // len(document["terrain"]["ground"])
        cy = sum(c["y"] for c in document["terrain"]["ground"]) // len(document["terrain"]["ground"])
    width, height = args.size
    image = render(args.pack, document, cx - width // 2, cy - height // 2, width, height,
                   original=args.original, roofs=not args.no_roofs)
    image.save(args.out)
    print(f"{args.out}: {width}x{height} вокруг ({cx}, {cy})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
