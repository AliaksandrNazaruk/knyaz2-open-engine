"""Разбор путей Figma из блобов .fig в обычный SVG.

Векторная геометрия в файле лежит отдельно от узлов: у узла есть
`fillGeometry` / `strokeGeometry` со ссылкой `commandsBlob`, а сами команды —
в массиве `blobs` того же сообщения.

ФОРМАТ КОМАНД. Байт-команда, за ней столько пар float32, сколько ей нужно:

    0  замкнуть контур          нет точек
    1  перевести перо           1 точка
    2  отрезок                  1 точка
    3  квадратичная кривая      2 точки
    4  кубическая кривая        3 точки

Проверено на простых фигурах: блоб ромба-разделителя даёт (0,5) (5,0)
(10,5) (5,10), что совпадает с его размером 10x10 в макете.

ЗАЧЕМ. Часть облика рисует не CSS, а сама Figma: у рамок стоит обводка
кистью, и её край рваный. Повторить это стилями нельзя, но обводка уже
посчитана и лежит здесь — значит SVG можно собрать локально, без выгрузки
картинок из Figma и без обращений к её API.
"""

from __future__ import annotations

import struct

#: сколько точек забирает каждая команда
POINTS = {0: 0, 1: 1, 2: 1, 3: 2, 4: 3}
#: как команда называется в SVG
LETTER = {0: 'Z', 1: 'M', 2: 'L', 3: 'Q', 4: 'C'}


def parse(blob: bytes) -> list[tuple[int, list[tuple[float, float]]]]:
    """Список команд: (код, точки)."""
    out: list[tuple[int, list[tuple[float, float]]]] = []
    at = 0
    size = len(blob)
    while at < size:
        code = blob[at]
        at += 1
        if code not in POINTS:
            raise ValueError(f'неизвестная команда {code} на смещении {at - 1}')
        points = []
        for _ in range(POINTS[code]):
            if at + 8 > size:
                raise ValueError('точка не помещается в блоб')
            x, y = struct.unpack_from('<2f', blob, at)
            at += 8
            points.append((x, y))
        out.append((code, points))
    return out


def _num(value: float) -> str:
    text = f'{value:.3f}'.rstrip('0').rstrip('.')
    return text if text not in ('', '-0') else '0'


def to_d(commands) -> str:
    """Команды в атрибут `d` для <path>."""
    parts = []
    for code, points in commands:
        parts.append(LETTER[code])
        for x, y in points:
            parts.append(f'{_num(x)} {_num(y)}')
    return ' '.join(parts)


def bounds(commands):
    """Габариты пути — нужны, чтобы выставить viewBox."""
    xs, ys = [], []
    for _, points in commands:
        for x, y in points:
            xs.append(x)
            ys.append(y)
    if not xs:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(xs), min(ys), max(xs), max(ys))


def to_svg(commands, fill: str = '#000', pad: float = 0.0,
           winding: str = 'nonzero') -> str:
    """Готовый самостоятельный SVG с одним контуром."""
    left, top, right, bottom = bounds(commands)
    left, top = left - pad, top - pad
    width = (right - left) + pad
    height = (bottom - top) + pad
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{_num(left)} {_num(top)} {_num(width)} {_num(height)}" '
        f'width="{_num(width)}" height="{_num(height)}">'
        f'<path d="{to_d(commands)}" fill="{fill}" fill-rule="{winding}"/>'
        f'</svg>'
    )
