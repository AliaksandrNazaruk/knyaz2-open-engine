"""Выемка оригинальных спрайтов движения из HEROES.RES как эталона для ротоскопа.

    python tools/extract_ref_anim.py [--unit 0] [--blocks 0,1,6,7]

Складывает все 54 слоя экипировки в один кадр, выравнивает по ТОЧКЕ НОГ и пишет
tools/refanim/<блок>_<направление>_<кадр>.png плюс ref.json с габаритами.
"""
import json, os, sys
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from konung2.heroes import HeroesRes, LAYER_COUNT, DIRECTION_STEPS
from konung2.graph import read_palettes

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "refanim")
os.makedirs(OUT, exist_ok=True)
DIRNAMES = ["W", "NW", "N", "NE", "E", "SE", "S", "SW"]
BLOCKNAMES = {0: "stand", 1: "walk", 6: "idle", 7: "run"}

argv = sys.argv[1:]
blocks = [0, 1, 6, 7]
if "--blocks" in argv:
    blocks = [int(x) for x in argv[argv.index("--blocks") + 1].split(",")]
# Слой 0 — тело. Склейка ВСЕХ 54 слотов даёт кашу: в записи лежат все варианты
# экипировки сразу, движок рисует лишь надетые. Для ротоскопа нужно тело.
layers = [0]
if "--layers" in argv:
    spec = argv[argv.index("--layers") + 1]
    layers = list(range(LAYER_COUNT)) if spec == "all" else [int(x) for x in spec.split(",")]

hr = HeroesRes.from_game()
pal = read_palettes()[0]

CANV, AX, AY = 320, 160, 250          # холст и точка ног на нём
meta = {"canvas": CANV, "anchor": [AX, AY], "dirs": DIRNAMES,
        "direction_steps": list(DIRECTION_STEPS), "blocks": {}}

for kind in blocks:
    per_dir = {}
    for d in range(8):
        frames = hr.animation(kind, d)
        saved = []
        for fi, rec in enumerate(frames):
            img = Image.new("RGBA", (CANV, CANV), (0, 0, 0, 0))
            drew = 0
            for layer in layers:
                sp, dx, dy = hr.decode_layer(rec, layer=layer, palette=pal)
                if sp is None:
                    continue
                lay = Image.frombytes("RGBA", (sp.width, sp.height),
                                      bytes(b for px in sp.pixels for b in px))
                img.alpha_composite(lay, (AX + dx, AY + dy))
                drew += 1
            bb = img.getbbox()
            if bb is None:
                continue
            name = "%s_%s_%02d.png" % (BLOCKNAMES.get(kind, "b%d" % kind), DIRNAMES[d], fi)
            img.save(os.path.join(OUT, name))
            saved.append(dict(file=name, rec=rec, layers=drew,
                              bbox=[bb[0] - AX, bb[1] - AY, bb[2] - AX, bb[3] - AY]))
        per_dir[DIRNAMES[d]] = dict(count=len(frames), frames=saved)
        if saved:
            hs = [-f["bbox"][1] for f in saved]
            ws = [f["bbox"][2] - f["bbox"][0] for f in saved]
            below = [f["bbox"][3] for f in saved]
            print("блок %d %-2s: кадров %2d, слоёв %d, высота над ногами %d..%d px, "
                  "ширина %d..%d, ниже ног %d..%d"
                  % (kind, DIRNAMES[d], len(frames), saved[0]["layers"],
                     min(hs), max(hs), min(ws), max(ws), min(below), max(below)))
    meta["blocks"][BLOCKNAMES.get(kind, "b%d" % kind)] = per_dir

json.dump(meta, open(os.path.join(OUT, "ref.json"), "w"), ensure_ascii=False, indent=1)
print("\nзаписано в", OUT)
