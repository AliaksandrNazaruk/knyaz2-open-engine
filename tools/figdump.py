"""Читает выгруженный из Figma файл .fig и печатает раскладку экрана.

ЗАЧЕМ. Figma MCP отдаёт те же числа, но на Starter-плане быстро упирается в
лимит вызовов, а экранов интерфейса больше сотни. Файл .fig лежит на диске
целиком, поэтому координаты, шрифты и цвета берутся из него без обращений к
сети и без ограничений.

ЧТО ВНУТРИ .fig. Это zip: `canvas.fig` (сам документ), `images/` и
`meta.json`. Документ начинается с метки `fig-kiwi`, дальше два куска:
описание формата (сжато deflate) и данные (сжаты zstd — старые файлы жали
deflate, в свежих zstd). Оба разбираются по описанию kiwi, см. figkiwi.py.

ПРИМЕРЫ

    python tools/figdump.py "Game UI.fig" --node 961:16456
    python tools/figdump.py "Game UI.fig" --node 961:16456 --depth 3
    python tools/figdump.py "Game UI.fig" --find "Options menu point"
    python tools/figdump.py "Game UI.fig" --node 1228:43012 --style

Разбор занимает секунды, поэтому результат кладётся рядом с файлом в
`<имя>.nodes.pkl` и при следующем запуске берётся оттуда.
"""

from __future__ import annotations

import argparse
import pickle
import struct
import sys
import zipfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import figkiwi  # noqa: E402


def _chunks(blob: bytes):
    """Два куска после метки: описание формата и данные."""
    if blob[:8] != b'fig-kiwi':
        raise ValueError('это не canvas.fig: нет метки fig-kiwi')
    at = 12                                   # 8 метка + 4 версия
    out = []
    while at + 4 <= len(blob):
        size = struct.unpack_from('<I', blob, at)[0]
        at += 4
        piece = blob[at:at + size]
        at += size
        out.append(piece)
        if len(out) == 2:
            break
    return out


def _unpack(piece: bytes) -> bytes:
    """Кусок сжат либо deflate, либо zstd — смотрим по первым байтам."""
    if piece[:4] == b'\x28\xb5\x2f\xfd':
        import zstandard
        return zstandard.ZstdDecompressor().decompress(piece,
                                                       max_output_size=1 << 30)
    return zlib.decompress(piece, -15)


def load_nodes(fig_path: Path, refresh: bool = False) -> list[dict]:
    """Список узлов документа. Результат кэшируется рядом с файлом."""
    cache = fig_path.with_suffix('.nodes.pkl')
    if cache.is_file() and not refresh \
            and cache.stat().st_mtime >= fig_path.stat().st_mtime:
        with cache.open('rb') as stream:
            return pickle.load(stream)

    with zipfile.ZipFile(fig_path) as archive:
        blob = archive.read('canvas.fig')
    schema_raw, doc_raw = (_unpack(piece) for piece in _chunks(blob))

    defs = figkiwi.parse_schema(schema_raw)
    decoder = figkiwi.Decoder(defs)
    reader = figkiwi.Reader(doc_raw)
    message = defs[decoder.index['Message']]

    # Нужен только массив узлов; всё, что идёт после него, не разбираем.
    nodes: list[dict] = []
    while True:
        field_id = reader.varuint()
        if field_id == 0:
            break
        field = message.by_id.get(field_id)
        if field is None:
            break
        value = decoder.field(reader, field)
        if field.name == 'nodeChanges':
            nodes = value
            break

    with cache.open('wb') as stream:
        pickle.dump(nodes, stream)
    return nodes


def node_id(node: dict) -> str:
    guid = node.get('guid') or {}
    return f"{guid.get('sessionID')}:{guid.get('localID')}"


def _children_map(nodes: list[dict]) -> dict[str, list[dict]]:
    """Дети каждого узла в порядке, который задаёт parentIndex.position."""
    out: dict[str, list[dict]] = {}
    for node in nodes:
        parent = (node.get('parentIndex') or {}).get('guid')
        if not parent:
            continue
        key = f"{parent.get('sessionID')}:{parent.get('localID')}"
        out.setdefault(key, []).append(node)
    for kids in out.values():
        kids.sort(key=lambda n: (n.get('parentIndex') or {}).get('position') or '')
    return out


def _rect(node: dict) -> tuple[float, float, float, float]:
    transform = node.get('transform') or {}
    size = node.get('size') or {}
    return (transform.get('m02', 0.0), transform.get('m12', 0.0),
            size.get('x', 0.0), size.get('y', 0.0))


def _num(value: float) -> str:
    return f'{value:g}'


def _colour(paints) -> str:
    """Первая сплошная заливка как #RRGGBB (плюс альфа, если не единица)."""
    for paint in paints or []:
        if paint.get('type') != 'SOLID' or paint.get('visible') is False:
            continue
        colour = paint.get('color') or {}
        red, green, blue = (round(colour.get(k, 0) * 255) for k in 'rgb')
        alpha = colour.get('a', 1.0)
        text = f'#{red:02X}{green:02X}{blue:02X}'
        return text if alpha >= 0.999 else f'{text} a={alpha:.2f}'
    return ''


def describe(node: dict, style: bool) -> str:
    """Короткая подпись узла: геометрия, а для текста ещё шрифт и цвет."""
    x, y, width, height = _rect(node)
    parts = [f'x={_num(x)} y={_num(y)} {_num(width)}x{_num(height)}']

    if node.get('visible') is False:
        parts.append('СКРЫТ')

    if node.get('stackMode') in ('HORIZONTAL', 'VERTICAL'):
        gap = node.get('stackSpacing')
        parts.append('стек ' + ('строкой' if node['stackMode'] == 'HORIZONTAL'
                                else 'столбцом')
                     + (f' зазор {_num(gap)}' if gap else ''))

    if node.get('type') == 'TEXT':
        font = node.get('fontName') or {}
        size = node.get('fontSize')
        parts.append(f"{font.get('family','?')} {font.get('style','')} {_num(size or 0)}")
        line = node.get('lineHeight') or {}
        if line.get('units') == 'RAW':
            parts.append(f"межстрочный {line.get('value'):.2f}")
        if node.get('leadingTrim') == 'CAP_HEIGHT':
            parts.append('обрезка по cap-height')
        spacing = node.get('letterSpacing') or {}
        if spacing.get('value'):
            parts.append(f"трекинг {_num(spacing['value'])}{'%' if spacing.get('units')=='PERCENT' else ''}")

    if style or node.get('type') == 'TEXT':
        colour = _colour(node.get('fillPaints'))
        if colour:
            parts.append(colour)

    if node.get('type') == 'TEXT':
        text = ((node.get('textData') or {}).get('characters') or '').strip()
        if text:
            short = text if len(text) <= 60 else text[:57] + '…'
            parts.append(f'«{short}»')

    return '  '.join(parts)


def _overrides(node: dict) -> dict[tuple, dict]:
    """Переопределения экземпляра, разложенные по пути внутри компонента.

    У INSTANCE своих детей нет: содержимое лежит в компоненте (SYMBOL), а
    экземпляр хранит только правки — свой текст, скрытые слои. Ключ — путь
    из guid-ов от корня компонента до изменённого узла.
    """
    out: dict[tuple, dict] = {}
    for item in (node.get('symbolData') or {}).get('symbolOverrides') or []:
        path = tuple(f"{g.get('sessionID')}:{g.get('localID')}"
                     for g in (item.get('guidPath') or {}).get('guids') or [])
        if path:
            out[path] = item
    return out


def walk(nodes: list[dict], root: str, depth: int, style: bool) -> None:
    kids = _children_map(nodes)
    by_id = {node_id(n): n for n in nodes}
    start = by_id.get(root)
    if start is None:
        raise SystemExit(f'нет такого узла: {root}')

    # Правки экземпляров собираем по ходу обхода в один словарь с полным
    # путём от корня. Путь наращивается ТОЛЬКО на вложенных экземплярах:
    # внутри одного компонента Figma адресует узел его собственным guid-ом,
    # а не цепочкой всех родителей.
    patches: dict[tuple, dict] = {}

    def show(node: dict, level: int, prefix: tuple) -> None:
        key = prefix + (node_id(node),)
        patch = patches.get(key)
        shown = node
        if patch:
            shown = {**node, **{k: v for k, v in patch.items()
                                if k in ('textData', 'visible', 'size')}}
        pad = '  ' * level
        mark = '  <- правка' if patch else ''
        print(f"{pad}{node_id(shown):<12} {shown.get('type','?'):<18} "
              f"{shown.get('name','') or '':<26} {describe(shown, style)}{mark}")
        if level >= depth or shown.get('visible') is False:
            return

        source, child_prefix = node, prefix
        if node.get('type') == 'INSTANCE':
            for path, item in _overrides(node).items():
                patches.setdefault(key + path, item)
            # Экземпляру могли ПОДМЕНИТЬ компонент (overriddenSymbolID) —
            # так в макете одна и та же строка настройки показывает то
            # список, то ползунок, то две клавиши. Без этого показывался бы
            # исходный вариант, а не тот, что стоит на экране.
            symbol = (patch or {}).get('overriddenSymbolID')                 or (node.get('symbolData') or {}).get('symbolID')
            if not symbol:
                return
            target = by_id.get(f"{symbol.get('sessionID')}:{symbol.get('localID')}")
            if target is None:
                return
            source, child_prefix = target, key

        for kid in kids.get(node_id(source), []):
            show(kid, level + 1, child_prefix)

    show(start, 0, ())


def find(nodes: list[dict], needle: str) -> None:
    low = needle.lower()
    for node in nodes:
        name = node.get('name') or ''
        if low in name.lower():
            x, y, width, height = _rect(node)
            print(f"{node_id(node):<12} {node.get('type','?'):<18} {name:<32} "
                  f"x={_num(x)} y={_num(y)} {_num(width)}x{_num(height)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('fig', type=Path, help='файл .fig, выгруженный из Figma')
    parser.add_argument('--node', help='узел вида 961:16456')
    parser.add_argument('--find', help='искать узлы по части имени')
    parser.add_argument('--depth', type=int, default=2, help='глубина обхода')
    parser.add_argument('--style', action='store_true', help='показывать цвета заливки')
    parser.add_argument('--refresh', action='store_true', help='перечитать файл, не брать кэш')
    args = parser.parse_args()

    # Консоль Windows по умолчанию в cp1251 и роняет вывод на первом же
    # символе вне неё (стрелки, кавычки-ёлочки).
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except AttributeError:
        pass

    nodes = load_nodes(args.fig, refresh=args.refresh)
    if args.find:
        find(nodes, args.find)
    elif args.node:
        walk(nodes, args.node, args.depth, args.style)
    else:
        print(f'узлов в файле: {len(nodes)}')
        print('укажите --node или --find')


if __name__ == '__main__':
    main()
