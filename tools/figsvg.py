"""Собирает SVG формы узла Figma прямо из .fig — без выгрузки картинок.

ЗАЧЕМ. У рамок в макете обводка нарисована кистью, поэтому край рваный.
Стилями это не повторить, а выгружать каждый такой элемент картинкой —
долго (в файле 141 разная форма с кистью). Но Figma уже посчитала контур и
положила его в файл: у узла есть `fillGeometry` / `strokeGeometry`, а сами
команды — в массиве `blobs`. Отсюда SVG собирается локально и сколько
угодно раз.

ВАЖНО ПРО РАСТЯЖЕНИЕ. Формы нарисованы на своём размере (например 256x256),
а в макете растянуты на всю ширину строки. Поэтому SVG пишется с
`preserveAspectRatio="none"`: в CSS его можно тянуть как угодно, и край
поведёт себя ровно как в Figma.

ПРИМЕРЫ

    python tools/figsvg.py "Game UI.fig" --node 711:6945 --out shape.svg
    python tools/figsvg.py "Game UI.fig" --node 711:6945 --out mask.svg --mask
"""

from __future__ import annotations

import argparse
import pickle
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import figdump   # noqa: E402
import figkiwi   # noqa: E402
import figpath   # noqa: E402


def load_blobs(fig_path: Path, refresh: bool = False) -> list[bytes]:
    """Массив путей документа. Кэшируется рядом с файлом.

    Счётчик массива узлов в файле занижен (заявлено меньше, чем записано),
    поэтому границу ищем перебором: читаем узлы по одному и проверяем, с
    какой позиции поток читается как поле `blobs`.
    """
    cache = fig_path.with_suffix('.blobs.pkl')
    if cache.is_file() and not refresh \
            and cache.stat().st_mtime >= fig_path.stat().st_mtime:
        with cache.open('rb') as stream:
            return pickle.load(stream)

    with zipfile.ZipFile(fig_path) as archive:
        raw = archive.read('canvas.fig')
    schema_raw, doc_raw = (figdump._unpack(piece)
                           for piece in figdump._chunks(raw))
    defs = figkiwi.parse_schema(schema_raw)
    decoder = figkiwi.Decoder(defs)
    message = defs[decoder.index['Message']]
    node_def = defs[decoder.index['NodeChange']]
    blob_def = defs[decoder.index['Blob']]
    blobs_field = next(f for f in message.fields if f.name == 'blobs')

    reader = figkiwi.Reader(doc_raw)
    while True:
        field = message.by_id[reader.varuint()]
        if field.name == 'nodeChanges':
            break
        decoder.field(reader, field)

    reader.varuint()                       # заявленная длина, ей верить нельзя
    marks = []
    while True:
        save = reader.at
        try:
            decoder.compound(reader, node_def)
        except Exception:
            reader.at = save
            break
        marks.append(reader.at)

    for position in reversed(marks[-500:]):
        probe = figkiwi.Reader(doc_raw)
        probe.at = position
        try:
            if probe.varuint() != blobs_field.value:
                continue
            count = probe.varuint()
            if not (0 < count < 500000):
                continue
            out = []
            for _ in range(count):
                item = decoder.compound(probe, blob_def)
                data = item.get('bytes')
                out.append(bytes(data) if isinstance(data, list) else data)
        except Exception:
            continue
        with cache.open('wb') as stream:
            pickle.dump(out, stream)
        return out

    raise SystemExit('не нашли начало массива путей')


def node_paths(node: dict, blobs: list[bytes]) -> dict[str, list]:
    """Команды заливки и обводки узла."""
    out: dict[str, list] = {}
    for key in ('fillGeometry', 'strokeGeometry'):
        for entry in node.get(key) or []:
            index = entry.get('commandsBlob')
            if index is None or index >= len(blobs):
                continue
            try:
                out.setdefault(key, []).append(
                    (figpath.parse(blobs[index]),
                     entry.get('windingRule', 'NONZERO').lower()))
            except ValueError:
                continue
    return out


def build_svg(node: dict, blobs: list[bytes], mask: bool,
              only: str | None = None) -> str:
    """SVG формы узла: заливка и обводка одним файлом.

    `mask=True` красит всё белым — такой файл годится как CSS-маска, и
    панель принимает рваный силуэт вместо прямоугольника.
    """
    paths = node_paths(node, blobs)
    if only:
        paths = {k: v for k, v in paths.items() if k == only}
    size = node.get('size') or {}
    width = size.get('x', 0.0) or 0.0
    height = size.get('y', 0.0) or 0.0

    pieces = []
    for key in ('fillGeometry', 'strokeGeometry'):
        for commands, winding in paths.get(key, []):
            colour = '#fff' if mask else ('#000' if key == 'fillGeometry' else '#222')
            pieces.append(f'<path d="{figpath.to_d(commands)}" fill="{colour}" '
                          f'fill-rule="{winding}"/>')
    if not pieces:
        raise SystemExit('у этого узла нет векторной геометрии')

    # Габарит берём по самим путям: обводка выходит за размер узла.
    lefts, tops, rights, bottoms = [], [], [], []
    for key in paths:
        for commands, _ in paths[key]:
            left, top, right, bottom = figpath.bounds(commands)
            lefts.append(left); tops.append(top)
            rights.append(right); bottoms.append(bottom)
    left, top = min(lefts), min(tops)
    right, bottom = max(rights), max(bottoms)
    view_w, view_h = right - left, bottom - top

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{left:g} {top:g} {view_w:g} {view_h:g}" '
        f'width="{view_w:g}" height="{view_h:g}" '
        f'preserveAspectRatio="none">{"".join(pieces)}</svg>'
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('fig', type=Path)
    parser.add_argument('--node', required=True, help='узел вида 711:6945')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--mask', action='store_true',
                        help='всё белым — файл для CSS-маски')
    parser.add_argument('--only', choices=('fillGeometry', 'strokeGeometry'),
                        help='взять только заливку или только обводку')
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    nodes = figdump.load_nodes(args.fig)
    by_id = {figdump.node_id(n): n for n in nodes}
    node = by_id.get(args.node)
    if node is None:
        raise SystemExit(f'нет такого узла: {args.node}')

    blobs = load_blobs(args.fig)
    svg = build_svg(node, blobs, args.mask, args.only)
    args.out.write_text(svg, encoding='utf-8')
    print(f'{args.out}: {len(svg)} байт')


if __name__ == '__main__':
    main()
