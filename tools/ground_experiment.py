# -*- coding: utf-8 -*-
"""Опыт: заменить клетки брусчатки в собранном паке на процедурные.

Каждая клетка рендерится по СВОИМ мировым координатам, поэтому рисунок
продолжается через границу клетки и швов не возникает. Форма ромба берётся
из альфы существующего ассета — геометрию сцены опыт не трогает.

    python tools/ground_experiment.py --pack content_build --map 19
    python tools/ground_experiment.py --restore          # вернуть как было
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import groundgen as G                                            # noqa: E402

#: Тайлы брусчатки Чёрного Бора (серо-зелёные, средний RGB 113/111/82).
COBBLE_TILES = {44, 45, 46}
GEN_DIR = "assets/ground/gen"

# Настройки утверждённого вида. Подбирались по кадру деревни и проверялись
# числами: каждая правка сравнивалась с предыдущей по среднему отклонению.
# Что сработало и что нет — важнее самих чисел:
#   усиление рельефа   отклонение 2.4 из 255 — незаметно;
#   косое солнце       4.0 — незаметно;
#   тени рельефа       0.16 — луч перескакивал камни, эффекта нет;
#   контраст высоты + длинные тени вместе — 6.4 и 28 % пикселей, видно.
# Отсюда правило: на камне в 15 экранных пикселей объём даёт НЕ освещение,
# а собственные тени рельефа, и работают они только при усиленной высоте.
HEIGHT_CONTRAST = 2.4       # фотография пологая: разводим макушки и швы
SUN_ELEVATION = 0.16        # солнце низко, иначе тени короче камня
SHADOW_STEPS = 12           # длина марша луча в пикселях = steps * step
SHADOW_STEP = 1.4
SHADOW_RELIEF = 26.0        # высота 1.0 считается таким числом пикселей
SHADOW_DEPTH = 0.65         # насколько тёмен полный подрез
STONE_STEEP = 16.0          # крутизна нормали для рассеянного света
STONE_GLOSS = 0.45
DIRT_TONE = (0.30, 0.25, 0.16)
JOINT_LEVEL = 0.46          # доля высоты, ниже которой шов заливает грязь


def photo_base(x, y, photo, dirt, *, scale, seed=5, wear=0.0, tone=(0.44, 0.43, 0.33),
               pad: int = 0):
    """Фотография как основа: её камни, наш износ, грязь и макро-вариация.

    ``pad`` — запас по краям для собственных теней рельефа: марш луча смотрит
    за границу клетки, поэтому поле считается шире и обрезается в конце.
    """
    # узор идёт по осям земли, а не экрана
    gx, gy = G.to_ground(x, y)
    rgb, height = photo.sample(gx, gy, scale)
    rgb = np.moveaxis(rgb, -1, 0)
    mean = rgb.mean(axis=(1, 2), keepdims=True)
    rgb = rgb * (np.array(tone)[:, None, None] ** 2.2 / np.maximum(mean, 1e-4))

    drgb, _ = dirt.sample(gx * 1.3, gy * 1.3, scale)
    drgb = np.moveaxis(drgb, -1, 0)
    dmean = drgb.mean(axis=(1, 2), keepdims=True)
    drgb = drgb * (np.array(DIRT_TONE)[:, None, None] ** 2.2 / np.maximum(dmean, 1e-4))

    wear = np.asarray(wear, dtype=np.float64)
    # Контраст высоты: у фотографии макушка и шов почти на одном уровне,
    # поэтому луч теней их не различает. Разводим — и тени появляются.
    relief_height = np.clip((height - 0.45) * HEIGHT_CONTRAST + 0.45, 0, 1)
    patch = G.fbm(gx, gy, 210.0, seed + 71, octaves=3)
    level = JOINT_LEVEL + 0.44 * wear + 0.26 * (patch - 0.45)
    blend = np.clip((level - relief_height) * 3.6, 0, 1)
    out = rgb * (1 - blend) + drgb * blend
    lit = relief_height * (1 - 0.5 * wear)
    out = out * G.shade_from_height(lit, relief=1.0 - 0.6 * blend,
                                    steep=STONE_STEEP, gloss=STONE_GLOSS)
    # Собственные тени рельефа: камень подрезает соседа. Это и есть объём —
    # ламберт с бликом на таком масштабе дают отклонение в пределах шума.
    shadow = G.self_shadow(lit, steps=SHADOW_STEPS, step=SHADOW_STEP,
                           relief=SHADOW_RELIEF, softness=1.0)
    out = out * ((1.0 - SHADOW_DEPTH) + SHADOW_DEPTH * shadow)
    macro = G.fbm(gx, gy, 430.0, seed + 91, octaves=3)
    out *= (0.86 + 0.30 * macro)
    out = np.clip(out, 0, 1) ** (1 / 2.2)
    return out[:, pad:out.shape[1] - pad, pad:out.shape[2] - pad] if pad else out


def cell_image(pack: Path, cell: dict, mask_cache: dict, photo, dirt, scale: float,
               layout: str = "photo", stone: float = 18.0):
    """Ромб клетки, отрисованный по её мировым координатам."""
    source = cell["asset"]
    if source not in mask_cache:
        with Image.open(pack / source) as image:
            mask_cache[source] = np.asarray(image.convert("RGBA"))[..., 3]
    alpha = mask_cache[source]
    h, w = alpha.shape
    pad = 10                                  # запас под марш теней
    y, x = np.mgrid[-pad:h + pad, -pad:w + pad].astype(np.float64)
    wx, wy = x + cell["x"], y + cell["y"]
    if layout == "voronoi":
        rgb = G.photo_cobblestone(wx, wy, photo, dirt=dirt, scale=scale, stone=stone)
        rgb = rgb[:, pad:rgb.shape[1] - pad, pad:rgb.shape[2] - pad]
    else:
        rgb = photo_base(wx, wy, photo, dirt, scale=scale, pad=pad)
    out = np.dstack([(np.moveaxis(rgb, 0, -1) * 255).astype(np.uint8), alpha])
    return Image.fromarray(out, "RGBA")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Процедурная брусчатка в готовом паке")
    parser.add_argument("--pack", type=Path, default=Path("content_build"))
    parser.add_argument("--map", type=int, default=19)
    parser.add_argument("--materials", type=Path, default=Path("project/materials"),
                        help="папка с наборами Color/Displacement (см. NOTICE.md)")
    parser.add_argument("--stones", default="PavingStones138")
    parser.add_argument("--dirt", default="Ground106")
    parser.add_argument("--scale", type=float, default=0.275,
                        help="во сколько раз пиксель фотографии мельче мирового")
    parser.add_argument("--layout", choices=("photo", "voronoi"), default="photo",
                        help="раскладка камней: с фотографии или своя (Вороной)")
    parser.add_argument("--stone", type=float, default=18.0,
                        help="размер камня для своей раскладки, в единицах земли")
    parser.add_argument("--sun", type=float, default=SUN_ELEVATION,
                        help="высота солнца: ниже — длиннее тени рельефа")
    parser.add_argument("--restore", action="store_true", help="вернуть исходные ассеты")
    args = parser.parse_args()

    map_path = args.pack / "maps" / str(args.map) / "map.json"
    document = json.loads(map_path.read_text(encoding="utf-8"))
    ground = document["terrain"]["ground"]

    if args.restore:
        restored = 0
        for cell in ground:
            original = cell.pop("asset_original", None)
            if original:
                cell["asset"] = original
                restored += 1
        map_path.write_text(json.dumps(document, ensure_ascii=False, sort_keys=True,
                                       indent=2) + "\n", encoding="utf-8", newline="\n")
        print(f"возвращено клеток: {restored}")
        return 0

    G.LIGHT_ELEVATION = args.sun          # солнце общее для нормали и теней
    photo = G.PhotoMaterial.load(str(args.materials), args.stones)
    dirt = G.PhotoMaterial.load(str(args.materials), args.dirt)
    (args.pack / GEN_DIR).mkdir(parents=True, exist_ok=True)

    masks: dict = {}
    touched = []
    for cell in ground:
        if cell["tiles"]["lower"] not in COBBLE_TILES or not cell.get("asset"):
            continue
        image = cell_image(args.pack, cell, masks, photo, dirt, args.scale,
                           layout=args.layout, stone=args.stone)
        relative = f"{GEN_DIR}/{cell['row']}_{cell['col']}.png"
        image.save(args.pack / relative)
        cell.setdefault("asset_original", cell["asset"])
        cell["asset"] = relative
        touched.append(relative)

    map_path.write_text(json.dumps(document, ensure_ascii=False, sort_keys=True,
                                   indent=2) + "\n", encoding="utf-8", newline="\n")

    # манифест должен остаться правдой: пересчитываем хэши тронутых файлов
    manifest_path = args.pack / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    known = {item["path"]: item for item in manifest["files"]}
    for relative in touched:
        path = args.pack / relative
        known[relative] = {"path": relative, "bytes": path.stat().st_size,
                           "sha256": sha256(path)}
    map_relative = f"maps/{args.map}/map.json"
    known[map_relative] = {"path": map_relative, "bytes": map_path.stat().st_size,
                           "sha256": sha256(map_path)}
    manifest["files"] = sorted(known.values(), key=lambda item: item["path"])
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                                        indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"заменено клеток: {len(touched)}, материал {args.stones}, "
          f"масштаб {args.scale}, раскладка {args.layout}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
