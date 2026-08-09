"""Проверка позы экипировкой: садятся ли игровые доспех, меч и щит на наш спрайт.

    python tools/fit_equipment.py [--shots tools/mixamo_shots] [--block 0]
            [--armor 24] [--sword 1] [--shield 28]

Слои HEROES.RES выровнены по ТОЧКЕ НОГ, наши кадры — тоже (центр кадра). Значит
накладываются один в один, без подгонки. Если поза совпадает с игровой, доспех
ляжет на грудь, меч в руку, щит на предплечье.
"""
import json, os, sys
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from konung2.heroes import HeroesRes
from konung2.graph import read_palettes

argv = sys.argv[1:]
def opt(n, d):
    return argv[argv.index(n) + 1] if n in argv else d
SHOTS = opt("--shots", os.path.join(ROOT, "tools", "mixamo_shots"))
BLOCK = int(opt("--block", "0"))
FRAME = int(opt("--frame", "0"))
GEAR = [("доспех", int(opt("--armor", "24"))),
        ("меч", int(opt("--sword", "1"))),
        ("щит", int(opt("--shield", "28")))]
DIRS = ["W", "NW", "N", "NE", "E", "SE", "S", "SW"]

DIRS0 = ["W", "NW", "N", "NE", "E", "SE", "S", "SW"]
PREFIX = None
for p in ("iso_", "mx_"):
    if os.path.exists(os.path.join(SHOTS, p + "SE.png")):
        PREFIX = p
        break
assert PREFIX, "в %s нет кадров iso_*.png или mx_*.png" % SHOTS
RES = Image.open(os.path.join(SHOTS, PREFIX + "SE.png")).size[0]
PXU = 46.01
mp = os.path.join(SHOTS, "iso.json")
if os.path.exists(mp):
    PXU = json.load(open(mp, encoding="utf-8")).get("px_per_unit", PXU)
AX = AY = RES // 2                      # точка ног — центр кадра
print("наши кадры %s*.png %dx%d, якорь (%d,%d), %.2f px на единицу"
      % (PREFIX, RES, RES, AX, AY, PXU))

hr = HeroesRes.from_game()
pal = read_palettes()[0]

def layer(rec, L):
    sp, dx, dy = hr.decode_layer(rec, layer=L, palette=pal)
    if sp is None:
        return None
    return (Image.frombytes("RGBA", (sp.width, sp.height),
                            bytes(b for px in sp.pixels for b in px)), dx, dy)

S = 2
CW, CH = RES * S, RES * S
sheet = Image.new("RGB", (CW * len(DIRS), CH * 3 + 60), (28, 28, 32))
dr = ImageDraw.Draw(sheet)
rows = ["наш спрайт", "наш спрайт + игровая экипировка", "игровое тело + та же экипировка"]

for di, d in enumerate(DIRS):
    rec = hr.animation(BLOCK, di)[FRAME]
    ours = Image.open(os.path.join(SHOTS, "%s%s.png" % (PREFIX, d))).convert("RGBA")

    gear = Image.new("RGBA", (RES, RES), (0, 0, 0, 0))
    for _, L in GEAR:
        got = layer(rec, L)
        if got:
            im, dx, dy = got
            gear.alpha_composite(im, (AX + dx, AY + dy))

    body = Image.new("RGBA", (RES, RES), (0, 0, 0, 0))
    got = layer(rec, 0)
    if got:
        im, dx, dy = got
        body.alpha_composite(im, (AX + dx, AY + dy))

    combo = ours.copy(); combo.alpha_composite(gear)
    orig = body.copy(); orig.alpha_composite(gear)

    for ri, im in enumerate((ours, combo, orig)):
        b = Image.new("RGB", (RES, RES), (28, 28, 32))
        b.paste(im.convert("RGB"), (0, 0), im)
        sheet.paste(b.resize((CW, CH), Image.NEAREST), (di * CW, 20 + ri * (CH + 20)))
    dr.text((di * CW + 6, 4), d, fill=(235, 235, 235))

for ri, t in enumerate(rows):
    dr.text((6, 20 + ri * (CH + 20) + CH + 3), t, fill=(200, 205, 215))
out = os.path.join(ROOT, "tools", "refanim", "equipment_check.png")
sheet.save(out)
print("лист:", out, sheet.size)
print("слои:", ", ".join("%s=%d" % (n, L) for n, L in GEAR))
