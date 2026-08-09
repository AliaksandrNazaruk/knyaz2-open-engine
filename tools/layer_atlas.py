"""Разбор слоёв экипировки в кадре HEROES.RES: что в каком слоте лежит.

    python tools/layer_atlas.py [--block 0] [--dir SE] [--frame 0]

Рисует контактный лист: каждый непустой слой отдельно, с номером и габаритами
относительно ТОЧКИ НОГ. По нему видно, где тело, где доспех, где меч и щит.
"""
import os, sys
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from konung2.heroes import HeroesRes, LAYER_COUNT
from konung2.graph import read_palettes

argv = sys.argv[1:]
def opt(n, d):
    return argv[argv.index(n) + 1] if n in argv else d
BLOCK = int(opt("--block", "0"))
DIRS = ["W", "NW", "N", "NE", "E", "SE", "S", "SW"]
DIR = opt("--dir", "SE")
FRAME = int(opt("--frame", "0"))
OUT = os.path.join(ROOT, "tools", "refanim")
os.makedirs(OUT, exist_ok=True)

hr = HeroesRes.from_game()
pal = read_palettes()[0]
rec = hr.animation(BLOCK, DIRS.index(DIR))[FRAME]
print("блок %d, направление %s, кадр %d -> запись %d" % (BLOCK, DIR, FRAME, rec))

W, H, AX, AY = 120, 150, 60, 120
found = []
for L in range(LAYER_COUNT):
    sp, dx, dy = hr.decode_layer(rec, layer=L, palette=pal)
    if sp is None:
        continue
    im = Image.frombytes("RGBA", (sp.width, sp.height),
                         bytes(b for px in sp.pixels for b in px))
    found.append((L, im, dx, dy))
print("непустых слоёв: %d" % len(found))

COLS = 9
rows = (len(found) + COLS - 1) // COLS
S = 1
sheet = Image.new("RGB", (COLS * W * S, rows * (H * S + 16)), (30, 30, 34))
dr = ImageDraw.Draw(sheet)
for k, (L, im, dx, dy) in enumerate(found):
    cx, cy = (k % COLS) * W * S, (k // COLS) * (H * S + 16) + 16
    cell = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    cell.alpha_composite(im, (AX + dx, AY + dy))
    b = Image.new("RGB", (W, H), (30, 30, 34))
    b.paste(cell.convert("RGB"), (0, 0), cell)
    sheet.paste(b.resize((W * S, H * S), Image.NEAREST), (cx, cy))
    dr.line([(cx, cy + AY * S), (cx + W * S, cy + AY * S)], fill=(70, 70, 80))
    dr.line([(cx + AX * S, cy), (cx + AX * S, cy + H * S)], fill=(70, 70, 80))
    dr.text((cx + 3, cy - 14), "%d  %dx%d" % (L, im.width, im.height), fill=(230, 230, 235))
p = os.path.join(OUT, "layers_%d_%s.png" % (BLOCK, DIR))
sheet.save(p)
print("лист:", p, sheet.size)
print()
print("%5s %8s %8s   %s" % ("слой", "размер", "низ", "смещение от ног (dx,dy)"))
for L, im, dx, dy in found:
    print("%5d %8s %8d   %d, %d" % (L, "%dx%d" % (im.width, im.height),
                                    dy + im.height, dx, dy))
