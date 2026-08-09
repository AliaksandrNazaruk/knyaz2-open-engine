"""Подложка-эталон для браузерного ротоскопа.

    python tools/build_ref_payload.py

Кладёт tools/webanim/refpayload.json: по одной горизонтальной полосе на
(блок × направление), кадры выровнены по ТОЧКЕ НОГ, плюс параметры игровой камеры.
"""
import base64, io, json, os, sys
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from konung2.heroes import HeroesRes
from konung2.graph import read_palettes

OUT = os.path.join(ROOT, "tools", "webanim")
os.makedirs(OUT, exist_ok=True)
DIRS = ["W", "NW", "N", "NE", "E", "SE", "S", "SW"]
BLOCKS = {"stand": 0, "walk": 1, "idle": 6, "run": 7}
# азимут камеры на направление спрайта — замерено, см. tools/render_iso.py
AZ = {"SE": 0, "E": 315, "NE": 270, "N": 225, "NW": 180, "W": 135, "SW": 90, "S": 45}
TILT = 33.4849            # asin(tan(atan(16/29)))
PX_PER_UNIT = 46.01

W, H, AX, AY = 120, 150, 60, 120          # окно кадра и якорь внутри него
CANV, CX, CY = 320, 160, 250

hr = HeroesRes.from_game()
pal = read_palettes()[0]

# Слои экипировки: доспех, меч, щит. По ним при позировании видно, куда должна
# прийти кисть — по одному силуэту тела это не прочитать. Номера слотов — из
# tools/layer_atlas.py, там же можно подобрать другие.
GEAR = [24, 1, 28]
import sys as _s
if "--gear" in _s.argv:
    GEAR = [int(x) for x in _s.argv[_s.argv.index("--gear") + 1].split(",")]

def frame(rec, layers=(0,)):
    img = Image.new("RGBA", (CANV, CANV), (0, 0, 0, 0))
    for L in layers:
        sp, dx, dy = hr.decode_layer(rec, layer=L, palette=pal)
        if sp is None:
            continue
        img.alpha_composite(Image.frombytes("RGBA", (sp.width, sp.height),
                            bytes(b for px in sp.pixels for b in px)), (CX + dx, CY + dy))
    return img.crop((CX - AX, CY - AY, CX - AX + W, CY - AY + H))

def b64png(im):
    buf = io.BytesIO()
    # RGBA квантуется только Fast Octree; альфа при этом сохраняется
    im.quantize(colors=200, method=Image.FASTOCTREE).save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")

payload = dict(window=dict(w=W, h=H, ax=AX, ay=AY), az=AZ, tilt=TILT,
               px_per_unit=PX_PER_UNIT, dirs=DIRS, gear_layers=GEAR, blocks={})
total = 0
for bname, kind in BLOCKS.items():
    n = len(hr.animation(kind, 0))
    strips, gear = {}, {}
    for d, dn in enumerate(DIRS):
        recs = hr.animation(kind, d)
        s1 = Image.new("RGBA", (W * len(recs), H), (0, 0, 0, 0))
        s2 = Image.new("RGBA", (W * len(recs), H), (0, 0, 0, 0))
        for i, rec in enumerate(recs):
            s1.paste(frame(rec), (i * W, 0))
            s2.paste(frame(rec, GEAR), (i * W, 0))
        strips[dn] = b64png(s1)
        gear[dn] = b64png(s2)
        total += len(strips[dn]) + len(gear[dn])
    payload["blocks"][bname] = dict(frames=n, strips=strips, gear=gear)
    print("%-6s %2d кадров x 8 направлений" % (bname, n))

p = os.path.join(OUT, "refpayload.json")
json.dump(payload, open(p, "w"), separators=(",", ":"))
print("\nзаписано %s  %.2f MB" % (p, os.path.getsize(p) / 1024 / 1024))
