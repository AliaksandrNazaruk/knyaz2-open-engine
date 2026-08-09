# -*- coding: utf-8 -*-
"""
Каталог мира: все тайлы земли и все объекты игры с превью и таблицами.

    python tools\\catalog.py            # полный каталог
    python tools\\catalog.py --tiles    # только тайлы

Складывает в ``catalog/``: JSON-таблицы, превью каждого элемента и
контактные листы для быстрого просмотра, плюс ``index.html``.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PIL import Image                                        # noqa: E402

from konung2.graph import GraphRes, TILE_SLOTS               # noqa: E402
from konung2.paths import ROOT                               # noqa: E402
from konung2.res import ObjectsRes, read_palettes            # noqa: E402

OUT = os.path.join(ROOT, 'catalog')
THUMB = 160                     # длинная сторона превью
SHEET_COLS = 10


def _thumb(sprite, limit=THUMB):
    img = sprite.to_image()
    if max(img.width, img.height) > limit:
        k = limit / max(img.width, img.height)
        img = img.resize((max(1, int(img.width * k)), max(1, int(img.height * k))),
                         Image.LANCZOS)
    return img


def _sheet(images, path, cols=SHEET_COLS, cell=(THUMB + 8, THUMB + 8)):
    if not images:
        return
    rows = (len(images) + cols - 1) // cols
    sheet = Image.new('RGBA', (cols * cell[0], rows * cell[1]), (24, 26, 32, 255))
    for k, img in enumerate(images):
        x = (k % cols) * cell[0] + (cell[0] - img.width) // 2
        y = (k // cols) * cell[1] + (cell[1] - img.height) // 2
        sheet.alpha_composite(img.convert('RGBA'), (x, y))
    sheet.save(path)


def tiles_catalog():
    """Все тайлы земли: превью, палитра, размеры."""
    graph = GraphRes.from_game()
    os.makedirs(os.path.join(OUT, 'tiles'), exist_ok=True)
    records, thumbs = [], []
    for index in range(TILE_SLOTS):
        entry = graph.tile_entry(index)
        sprite = graph.decode_tile(index)
        if entry is None or sprite is None:
            continue
        img = _thumb(sprite)
        img.save(os.path.join(OUT, 'tiles', f'{index:03}.png'))
        thumbs.append(img)
        records.append({'index': index, 'offset': entry[0],
                        'palette': entry[1] // 512,
                        'width': sprite.width, 'height': sprite.height})
        if index % 100 == 0:
            print(f'  тайлы: {index}', flush=True)
    _sheet(thumbs, os.path.join(OUT, 'tiles_sheet.png'), cell=(126, 78))
    with open(os.path.join(OUT, 'tiles.json'), 'w', encoding='utf-8') as f:
        json.dump(records, f, ensure_ascii=False, indent=1)
    print(f'тайлов: {len(records)}')
    return records


def objects_catalog():
    """Все объекты OBJECTS.RES: превью, палитра, части, состояния."""
    res = ObjectsRes.from_game()
    palettes = read_palettes()
    os.makedirs(os.path.join(OUT, 'objects'), exist_ok=True)
    records, thumbs = [], []
    for slot in range(len(res.entries)):
        if res.entries[slot] is None:
            continue
        if slot < 30:
            sprite = res.decode_frame(slot, 0, palettes[0])
            header, frames = None, []
        else:
            header = res.simple_header(slot)
            frames = res.simple_frames(slot)
            index = header['kind'] // 512 if header else 0
            palette = palettes[index] if index < len(palettes) else palettes[0]
            sprite, dx, dy = res.decode_building(slot, palette)
        if sprite is None:
            continue
        img = _thumb(sprite)
        img.save(os.path.join(OUT, 'objects', f'{slot:03}.png'))
        thumbs.append(img)
        rec = {'slot': slot, 'sprite_field': slot - 30,
               'size': res.entries[slot][1],
               'width': sprite.width, 'height': sprite.height}
        if header:
            rec.update({'palette': header['kind'] // 512,
                        'anchor': [dx, dy],
                        'walls': header['walls'] > 0,
                        'roof': header['roof'] > 0,
                        'states': [f['state'] for f in frames],
                        'group': header['group']})
        records.append(rec)
        if len(records) % 50 == 0:
            print(f'  объекты: слот {slot}, готово {len(records)}', flush=True)
    _sheet(thumbs, os.path.join(OUT, 'objects_sheet.png'))
    with open(os.path.join(OUT, 'objects.json'), 'w', encoding='utf-8') as f:
        json.dump(records, f, ensure_ascii=False, indent=1)
    print(f'объектов: {len(records)}')
    return records


def cells_catalog():
    """Сводка по клеткам сетки: какие значения встречаются на всех картах."""
    import collections

    from konung2.grid import cells as grid_cells
    from konung2.kn2 import KN2Map
    from konung2.paths import GAME_DIR

    numbers = sorted(int(f[:-4]) for f in os.listdir(GAME_DIR)
                     if f.upper().endswith('.KN2') and f[:-4].isdigit())
    stat = collections.Counter()
    total = 0
    for n in numbers:
        for _, _, v in grid_cells(KN2Map.from_game(n)):
            key = (v['built'], bool(v['unit']), tuple(v['flags']))
            stat[key] += 1
            total += 1
    records = [{'built': b, 'unit': u, 'flags': list(f), 'count': c}
               for (b, u, f), c in stat.most_common()]
    with open(os.path.join(OUT, 'cells.json'), 'w', encoding='utf-8') as f:
        json.dump({'maps': len(numbers), 'used_cells': total,
                   'kinds': records}, f, ensure_ascii=False, indent=1)
    print(f'клеток занятых: {total} на {len(numbers)} картах, '
          f'сочетаний признаков: {len(records)}')
    return records


def write_index(tiles, objects):
    rows_t = '\n'.join(
        f'<figure><img src="tiles/{r["index"]:03}.png" loading="lazy">'
        f'<figcaption>{r["index"]} · пал {r["palette"]}</figcaption></figure>'
        for r in tiles)
    rows_o = '\n'.join(
        f'<figure><img src="objects/{r["slot"]:03}.png" loading="lazy">'
        f'<figcaption>слот {r["slot"]} · поле {r["sprite_field"]}'
        f'{" · пал " + str(r["palette"]) if "palette" in r else ""}'
        f'{" · крыша" if r.get("roof") else ""}</figcaption></figure>'
        for r in objects)
    html = f"""<!doctype html><meta charset="utf-8"><title>Каталог мира «Князь 2»</title>
<style>
 body{{background:#16181e;color:#d8dae0;font:14px system-ui;margin:24px}}
 h1{{font-size:20px}} h2{{margin-top:32px;font-size:17px}}
 .grid{{display:flex;flex-wrap:wrap;gap:10px}}
 figure{{margin:0;background:#1e2129;padding:6px;border-radius:6px;text-align:center}}
 figcaption{{font-size:11px;color:#9aa0ad;margin-top:4px}}
 img{{display:block;max-width:170px;height:auto}}
</style>
<h1>Каталог мира «Князь 2: Кровь Титанов»</h1>
<p>Тайлов земли: {len(tiles)}. Объектов: {len(objects)}.
Слот объекта = поле <code>sprite</code> записи карты + 30.</p>
<h2>Тайлы земли</h2><div class="grid">{rows_t}</div>
<h2>Объекты</h2><div class="grid">{rows_o}</div>
"""
    with open(os.path.join(OUT, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(html)


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    only_tiles = '--tiles' in sys.argv
    tiles = tiles_catalog()
    objects = [] if only_tiles else objects_catalog()
    cells_catalog()
    write_index(tiles, objects)
    print(f'каталог: {OUT}')
