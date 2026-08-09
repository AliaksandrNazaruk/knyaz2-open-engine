# -*- coding: utf-8 -*-
"""
Извлечь графику из ресурсов игры в PNG.

    python tools\\res_extract.py palettes            # 256 палитр одной картинкой
    python tools\\res_extract.py objects 0 3         # спрайты записей OBJECTS.RES 0..3
    python tools\\res_extract.py scan GRAPH.RES 16   # найти спрайты в файле (16-битные)

Спрайты ищутся перебором с проверкой по таблице длин строк из заголовка —
ложные срабатывания практически исключены. Палитра для 8-битных спрайтов
берётся из GRAPH.RES; нужный номер подбирается ключом --pal.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from konung2.res import read_palettes, decode_rle, scan_sprites, ObjectsRes
from konung2.paths import game_file, ROOT

OUT = os.path.join(ROOT, 'gfx')
os.makedirs(OUT, exist_ok=True)


def pal_arg(default=0):
    for a in sys.argv:
        if a.startswith('--pal='):
            return int(a.split('=')[1])
    return default


def cmd_palettes():
    from PIL import Image
    pals = read_palettes()
    img = Image.new('RGB', (256, 256))
    px = img.load()
    for p in range(256):
        for i in range(256):
            px[i, p] = pals[p][i]
    path = os.path.join(OUT, 'palettes.png')
    img.resize((768, 768), Image.NEAREST).save(path)
    print(f"256 палитр (строка = палитра) -> {path}")


def cmd_objects(first, last):
    pals = read_palettes()
    pal = pals[pal_arg(0)]
    o = ObjectsRes.from_game()
    total = 0
    for i in range(first, last + 1):
        rec = o.record(i)
        if rec is None:
            continue
        d = os.path.join(OUT, f'objects_{i:03d}')
        os.makedirs(d, exist_ok=True)
        sprites = scan_sprites(rec, mode=8, limit=400)
        for k, s in enumerate(sprites):
            sp = decode_rle(rec, s['offset'], pal, 8)
            if sp:
                sp.save(os.path.join(d, f"{k:03d}_{s['width']}x{s['height']}.png"))
        print(f"  запись {i}: спрайтов {len(sprites)} -> gfx/objects_{i:03d}/")
        total += len(sprites)
    print(f"всего извлечено {total}")


def cmd_scan(name, mode):
    pals = read_palettes()
    pal = pals[pal_arg(0)]
    with open(game_file(name), 'rb') as f:
        data = f.read()
    sprites = scan_sprites(data, mode=mode, limit=500)
    d = os.path.join(OUT, os.path.splitext(name)[0].lower())
    os.makedirs(d, exist_ok=True)
    for k, s in enumerate(sprites):
        sp = decode_rle(data, s['offset'], pal, mode)
        if sp:
            sp.save(os.path.join(d, f"{k:04d}_{s['width']}x{s['height']}.png"))
    print(f"{name}: найдено спрайтов {len(sprites)} -> gfx/{os.path.basename(d)}/")


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'palettes'
    if cmd == 'palettes':
        cmd_palettes()
    elif cmd == 'objects':
        cmd_objects(int(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) > 3 else int(sys.argv[2]))
    elif cmd == 'scan':
        cmd_scan(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 8)
    else:
        print(__doc__)
