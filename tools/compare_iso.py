"""Наложение нашего изометрического рендера на оригинальный спрайт.

    python tools/compare_iso.py [--block 0] [--frame 0]

Совмещает по ТОЧКЕ НОГ, печатает рост/ширину/совпадение силуэтов и рисует
tools/isoshots/overlay.png: оригинал синим, наш рендер оранжевым, совпадение белым.
"""
import json, os, sys
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from konung2.heroes import HeroesRes
from konung2.graph import read_palettes

SHOTS = os.path.join(ROOT, "tools", "isoshots")
meta = json.load(open(os.path.join(SHOTS, "iso.json")))
R = meta["res"]
AX = AY = R // 2
DIRS = ["W", "NW", "N", "NE", "E", "SE", "S", "SW"]
argv = sys.argv[1:]
BLOCK = int(argv[argv.index("--block") + 1]) if "--block" in argv else 0
FRAME = int(argv[argv.index("--frame") + 1]) if "--frame" in argv else 0

hr = HeroesRes.from_game()
pal = read_palettes()[0]

def sprite_rgba(d):
    rec = hr.animation(BLOCK, d)[FRAME]
    img = Image.new("RGBA", (R, R), (0, 0, 0, 0))
    sp, dx, dy = hr.decode_layer(rec, layer=0, palette=pal)
    img.alpha_composite(Image.frombytes("RGBA", (sp.width, sp.height),
                        bytes(b for px in sp.pixels for b in px)), (AX + dx, AY + dy))
    return img

def stats(mask):
    ys, xs = np.where(mask)
    if not len(ys):
        return None
    return dict(top=AY - ys.min(), bottom=ys.max() - AY,
                left=AX - xs.min(), right=xs.max() - AX, w=xs.max() - xs.min() + 1)

print("совмещение по точке ног, %d px на мировую единицу, наклон камеры %.2f°"
      % (meta["px_per_unit"], meta["tilt"]))
print("%-4s | %-26s | %-26s | %s" % ("дир", "оригинал: верх/низ/шир", "наш: верх/низ/шир", "IoU"))
sheet = Image.new("RGB", (8 * R, R + 22), (28, 28, 32))
rows = []
for i, d in enumerate(DIRS):
    orig = sprite_rgba(i)
    ours = Image.open(os.path.join(SHOTS, "iso_%s.png" % d)).convert("RGBA")
    mo = np.asarray(orig)[:, :, 3] > 8
    mu = np.asarray(ours)[:, :, 3] > 8
    so, su = stats(mo), stats(mu)
    inter = (mo & mu).sum()
    union = (mo | mu).sum()
    iou = inter / union if union else 0
    rows.append((d, so, su, iou))
    print("%-4s | %8d %8d %8d | %8d %8d %8d | %.3f"
          % (d, so["top"], so["bottom"], so["w"], su["top"], su["bottom"], su["w"], iou))
    rgb = np.zeros((R, R, 3), np.uint8)
    rgb[..., 2] = np.where(mo, 235, 28)
    rgb[..., 0] = np.where(mu, 235, 28)
    rgb[..., 1] = np.where(mo & mu, 235, 28)
    im = Image.fromarray(rgb)
    sheet.paste(im, (i * R, 20))
sheet.save(os.path.join(SHOTS, "overlay.png"))

ho = [r[1]["top"] for r in rows]
hu = [r[2]["top"] for r in rows]
print("\nрост над точкой ног: оригинал %d..%d, наш %d..%d" % (min(ho), max(ho), min(hu), max(hu)))
print("средний коэффициент роста наш/оригинал: %.3f" % (np.mean(hu) / np.mean(ho)))
print("рекомендуемый --px для совпадения роста: %.2f"
      % (meta["px_per_unit"] * np.mean(ho) / np.mean(hu)))
print("средний IoU: %.3f" % np.mean([r[3] for r in rows]))
print("overlay.png записан")
