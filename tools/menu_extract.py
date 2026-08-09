# -*- coding: utf-8 -*-
"""Разобрать MENU.RES — ресурс стартового меню оригинала — в файлы для веба.

    python tools\\menu_extract.py

Формат снят с самого файла и сходится байт в байт (3 428 670 = сумма блоков):

    +0x000000  картинка 1024x768   фон главного меню
    +0x18240C  картинка 1024x768   фон окна «Настройки»
    +0x304814  спрайт 13x13        значок-галочка настроек
    +0x304970  12 x 308x285        шесть пунктов меню, по две плиты на пункт

Все блоки — обычный спрайт ``u16 w; u16 h; u16 строки[h]; RLE``, но в
ШЕСТНАДЦАТИБИТНОМ варианте (X1R5G5B5 прямо в данных, палитра не нужна) —
тот же кодек, что у GRAPH.RES при mode=16.

Плита пункта — это holst 308x285 во всю высоту списка, а текст лежит на своей
строке: ПРОДОЛЖИТЬ ИГРУ на 0, СОХРАНИТЬ на 51, ЗАГРУЗИТЬ на 100, НОВАЯ ИГРА
на 151, НАСТРОЙКИ на 199, ВЫХОД на 250. Первая плита пары — золотая (курсор
на пункте), вторая — серебряная (обычное состояние). Движку достаточно
нарисовать плиту в одной и той же точке экрана, поэтому раскладка списка
целиком лежит в самих спрайтах — её и забираем в items.json.

Фон плиты непрозрачный (кусок тёмного проёма), а нам нужно положить пункты
поверх видео, поэтому альфа собирается ПО ЯРКОСТИ: гистограмма плиты строго
двугорбая (фон 0..31, буквы 48..191), порог с мягким скатом 28..68 режет её
без бахромы. Цвет букв восстанавливается обратной смесью с фоном плиты.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from konung2.paths import read_game
from konung2.res import decode_rle, scan_sprites

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'knyaz2', 'web', 'static', 'menu')

#: Порядок пунктов в файле совпадает с порядком на экране.
ITEMS = [
    ('continue', 'ПРОДОЛЖИТЬ ИГРУ'),
    ('save',     'СОХРАНИТЬ ИГРУ'),
    ('load',     'ЗАГРУЗИТЬ ИГРУ'),
    ('new',      'НОВАЯ ИГРА'),
    ('options',  'НАСТРОЙКИ'),
    ('exit',     'ВЫХОД'),
]

PLATE = (308, 285)
KEY_LOW, KEY_HIGH = 28, 68       # скат альфы по яркости
BACKDROP = (18, 16, 15)          # средний цвет фона плиты — для обратной смеси


def key_out(image):
    """Вырезать буквы: альфа по яркости, цвет — без примеси тёмного фона."""
    from PIL import Image
    source = image.convert('RGB')
    width, height = source.size
    pixels = list(source.getdata())
    out = []
    for r, g, b in pixels:
        lum = (r * 299 + g * 587 + b * 114) // 1000
        if lum <= KEY_LOW:
            out.append((0, 0, 0, 0))
            continue
        alpha = 255 if lum >= KEY_HIGH else round((lum - KEY_LOW) * 255 / (KEY_HIGH - KEY_LOW))
        share = alpha / 255
        clean = tuple(min(255, max(0, round((c - back * (1 - share)) / share)))
                      for c, back in zip((r, g, b), BACKDROP))
        out.append(clean + (alpha,))
    result = Image.new('RGBA', (width, height))
    result.putdata(out)
    return result


def main():
    os.makedirs(OUT, exist_ok=True)
    data = read_game('MENU.RES')
    sprites = scan_sprites(data, mode=16, start=0)
    sizes = [(s['width'], s['height']) for s in sprites]
    expected = [(1024, 768), (1024, 768), (13, 13)] + [PLATE] * 12
    if sizes != expected:
        raise SystemExit(f'MENU.RES разобрался не так, как ожидалось: {sizes}')

    for index, name in ((0, 'bg-main.jpg'), (1, 'bg-options.jpg')):
        picture = decode_rle(data, sprites[index]['offset'], mode=16).to_image()
        picture.convert('RGB').save(os.path.join(OUT, name), quality=88)
        print(f'фон -> menu/{name}')

    manifest = []
    for number, (slug, caption) in enumerate(ITEMS):
        hot, idle = sprites[3 + number * 2], sprites[4 + number * 2]
        band = None
        for state, sprite in (('hot', hot), ('idle', idle)):
            plate = decode_rle(data, sprite['offset'], mode=16).to_image()
            if band is None:
                band = plate.getchannel('A').getbbox()          # строка текста внутри плиты
            letters = key_out(plate.crop((0, band[1], PLATE[0], band[3])))
            letters.save(os.path.join(OUT, f'item-{slug}-{state}.png'))
        manifest.append({'slug': slug, 'caption': caption,
                         'top': band[1], 'height': band[3] - band[1]})
        print(f'пункт {caption}: строки {band[1]}..{band[3]} -> item-{slug}-*.png')

    mark = decode_rle(data, sprites[2]['offset'], mode=16).to_image()
    mark.save(os.path.join(OUT, 'mark.png'))

    with open(os.path.join(OUT, 'items.json'), 'w', encoding='utf-8') as stream:
        json.dump({'plate': {'width': PLATE[0], 'height': PLATE[1]}, 'items': manifest},
                  stream, ensure_ascii=False, indent=2)
    print(f'раскладка списка -> menu/items.json')


if __name__ == '__main__':
    main()
