"""Порождает HTML и CSS экрана прямо из .fig — без ручного переписывания.

ЗАЧЕМ ИМЕННО ГЕНЕРАТОР. Прежний способ — прочитать число глазами и набрать
его в стилях — раз за разом давал ошибки не там, где данных не хватало, а
там, где я подставлял своё: фон, прозрачность, режим смешивания. Поэтому
шага «перепечатать значение» здесь нет вовсе: всё, что попадает в вывод,
берётся из узла.

ЧЕГО ГЕНЕРАТОР НЕ ДЕЛАЕТ. Он не догадывается. Любое свойство, которое он не
умеет разложить, попадает в отчёт `--report` списком, а не заменяется чем-то
похожим. Пустая строка отчёта означает, что экран перенесён целиком.

ЕДИНИЦЫ. Всё пишется как `calc(N * var(--px))`, где `--px` — один пиксель
макета. Кадр масштабируется целиком, поэтому пропорции не плывут.

ПРИМЕР

    python tools/figgen.py "Game UI.fig" --node 1221:41387 \\
        --out knyaz2/web/static/gen --name loadgame --report
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import figdump   # noqa: E402
import figpath   # noqa: E402
import figsvg    # noqa: E402

#: свойства, которые генератор умеет; всё прочее уходит в отчёт
KNOWN = {
    'guid', 'parentIndex', 'phase', 'type', 'name', 'visible', 'opacity',
    'transform', 'size', 'symbolData', 'derivedSymbolData',
    'derivedSymbolDataLayoutVersion', 'editInfo', 'userFacingVersion',
    'fillPaints', 'strokePaints', 'strokeWeight', 'strokeAlign', 'strokeJoin',
    'cornerRadius', 'rectangleTopLeftCornerRadius',
    'rectangleTopRightCornerRadius', 'rectangleBottomLeftCornerRadius',
    'rectangleBottomRightCornerRadius', 'rectangleCornerRadiiIndependent',
    'effects', 'fillGeometry', 'strokeGeometry', 'strokeBrushGuid',
    'stackMode', 'stackSpacing', 'stackPaddingRight', 'stackPaddingBottom',
    'stackHorizontalPadding', 'stackVerticalPadding',
    'stackPrimaryAlignItems', 'stackCounterAlignItems',
    'stackPrimarySizing', 'stackCounterSizing', 'stackChildAlignSelf',
    'stackPositioning', 'stackChildPrimaryGrow', 'stackReverseZIndex',
    'fontName', 'fontSize', 'lineHeight', 'letterSpacing', 'textData',
    'derivedTextData', 'leadingTrim', 'textAlignHorizontal',
    'textAlignVertical', 'textAutoResize', 'textTracking',
    'horizontalConstraint', 'verticalConstraint', 'frameMaskDisabled',
    'styleIdForFill', 'styleIdForText', 'styleIdForStroke',
    'blendMode', 'mask', 'handleMirroring',
    'componentPropRefs', 'componentPropAssignments', 'componentPropDefs',
    'variantPropSpecs',
}

#: типы, чья форма задаётся контуром, а не рамкой со скруглением
VECTORISH = {'VECTOR', 'BOOLEAN_OPERATION', 'STAR', 'REGULAR_POLYGON', 'LINE'}

ALIGN = {'MIN': 'flex-start', 'CENTER': 'center', 'MAX': 'flex-end',
         'SPACE_BETWEEN': 'space-between', 'SPACE_EVENLY': 'space-evenly'}

#: режимы наложения Figma -> CSS. Без них слой «стекла» с белым градиентом
#: в режиме умножения (он ЗАТЕМНЯЕТ) рисовался белилами поверх панели.
#: LINEAR_BURN и PASS_THROUGH точных пар в CSS не имеют: первый ближе к
#: умножению, второй означает «как у родителя», то есть обычный.
BLEND = {
    'MULTIPLY': 'multiply', 'SCREEN': 'screen', 'OVERLAY': 'overlay',
    'DARKEN': 'darken', 'LIGHTEN': 'lighten', 'COLOR_DODGE': 'color-dodge',
    'COLOR_BURN': 'color-burn', 'HARD_LIGHT': 'hard-light',
    'SOFT_LIGHT': 'soft-light', 'DIFFERENCE': 'difference',
    'EXCLUSION': 'exclusion', 'HUE': 'hue', 'SATURATION': 'saturation',
    'COLOR': 'color', 'LUMINOSITY': 'luminosity',
    'LINEAR_BURN': 'multiply',
}


def px(value: float) -> str:
    """Число в единицах макета."""
    if not value:
        return '0'
    text = f'{value:g}'
    return f'calc({text} * var(--px))'


def colour(paint: dict) -> str | None:
    """Сплошной цвет заливки как CSS."""
    if paint.get('type') != 'SOLID' or paint.get('visible') is False:
        return None
    c = paint.get('color') or {}
    r, g, b = (round(c.get(k, 0) * 255) for k in 'rgb')
    alpha = c.get('a', 1.0) * paint.get('opacity', 1.0)
    if alpha >= 0.999:
        return f'#{r:02X}{g:02X}{b:02X}'
    return f'rgba({r}, {g}, {b}, {alpha:.3f})'


def gradient(paint: dict, size: dict | None = None) -> str | None:
    """Градиент как CSS.

    Матрица краски переводит нормированные координаты узла в координату
    вдоль градиента: t = m00*u + m01*v + m02. Направление в пикселях —
    (m00/ширина, m01/высота); раньше угол был зашит как 90deg, и подложка
    нижней панели с вуалью прокрутки лежали повёрнутыми на бок. Позиции
    стопов перекладываются на проекцию рамки узла (как их растягивает CSS).
    """
    kind = paint.get('type') or ''
    if not kind.startswith('GRADIENT') or paint.get('visible') is False:
        return None
    matrix = paint.get('transform') or {}
    m00 = matrix.get('m00', 1.0)
    m01 = matrix.get('m01', 0.0)
    m02 = matrix.get('m02', 0.0)
    box = size or {}
    dx = m00 / (box.get('x') or 1.0)
    dy = m01 / (box.get('y') or 1.0)
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        angle, t_min, t_max = 90.0, 0.0, 1.0
    else:
        import math
        angle = math.degrees(math.atan2(dx, -dy)) % 360
        corners = [m00 * u + m01 * v + m02 for u in (0, 1) for v in (0, 1)]
        t_min, t_max = min(corners), max(corners)
        if t_max - t_min < 1e-9:
            t_min, t_max = 0.0, 1.0
    stops = []
    for stop in paint.get('stops') or []:
        c = stop.get('color') or {}
        r, g, b = (round(c.get(k, 0) * 255) for k in 'rgb')
        alpha = c.get('a', 1.0)
        spot = (stop.get('position', 0) - t_min) / (t_max - t_min)
        stops.append(f'rgba({r}, {g}, {b}, {alpha:.3f}) {spot * 100:g}%')
    if not stops:
        return None
    body = ', '.join(stops)
    if kind == 'GRADIENT_RADIAL':
        return f'radial-gradient(circle, {body})'
    return f'linear-gradient({angle:g}deg, {body})'


def image_name(paint: dict) -> str | None:
    raw = (paint.get('image') or {}).get('hash')
    return bytes(raw).hex() if raw else None



def resized(node: dict, grow: tuple[float, float]) -> dict:
    """Подгоняет ребёнка компонента под изменённый размер экземпляра.

    Дети хранят геометрию в координатах ИСХОДНОГО компонента. Если
    экземпляр другого размера, Figma разносит разницу по привязкам каждого
    ребёнка. `derivedSymbolData` даёт только пересчитанный размер, но не
    положение, поэтому положение считаем здесь — иначе рамка выделения
    уезжает на сотни точек в сторону.

    Пересчёт нужен ТОЛЬКО на границе экземпляра: глубже дети лежат внутри
    уже подогнанных родителей.
    """
    if grow == (0.0, 0.0):
        return node
    transform = dict(node.get('transform') or {})
    size = dict(node.get('size') or {})
    out = dict(node)
    for axis, delta in zip('xy', grow):
        if not delta:
            continue
        key = 'm02' if axis == 'x' else 'm12'
        kind = node.get('horizontalConstraint' if axis == 'x'
                        else 'verticalConstraint')
        start = transform.get(key, 0.0)
        length = size.get(axis, 0.0) or 0.0
        if kind == 'MAX':
            transform[key] = start + delta
        elif kind == 'CENTER':
            transform[key] = start + delta / 2
        elif kind == 'STRETCH':
            size[axis] = length + delta
        elif kind == 'SCALE':
            # доля от прежней ширины сохраняется
            was = length + 0.0
            transform[key] = start * (1 + delta / (was or 1))
            size[axis] = length * (1 + delta / (was or 1))
        # MIN — ничего не двигаем
    out['transform'] = transform
    out['size'] = size
    return out


def baked(data: bytes, filt: dict) -> bytes:
    """Правки тона Figma поверх PNG: приближение её ползунков.

    Формулы стандартные (стопы экспозиции, линейный контраст вокруг
    середины, колокол весов для теней/светов, сдвиг каналов для теплоты),
    сочность — через насыщенность. Это перенос СЕМАНТИКИ движка, как
    радиус размытия = две сигмы; сверяется с рендером макета.
    """
    import io as _io
    import numpy as np
    from PIL import Image
    im = Image.open(_io.BytesIO(data)).convert('RGB')
    v = np.asarray(im).astype(np.float32) / 255.0

    exposure = filt.get('exposure', 0.0) or 0.0
    if exposure:
        v *= 2.0 ** exposure
    contrast = filt.get('contrast', 0.0) or 0.0
    if contrast:
        v = (v - 0.5) * (1.0 + contrast) + 0.5
    shadows = filt.get('shadows', 0.0) or 0.0
    highlights = filt.get('highlights', 0.0) or 0.0
    if shadows or highlights:
        lum = v.mean(axis=2, keepdims=True)
        weight_dark = np.clip(1.0 - lum, 0.0, 1.0) ** 2
        weight_light = np.clip(lum, 0.0, 1.0) ** 2
        v += shadows * weight_dark * lum          # тянет тёмное
        v += highlights * weight_light * (1.0 - lum)  # тянет светлое
    temperature = filt.get('temperature', 0.0) or 0.0
    if temperature:
        v[..., 0] += temperature * 0.08
        v[..., 2] -= temperature * 0.08
    tint = filt.get('tint', 0.0) or 0.0
    if tint:
        v[..., 1] += tint * 0.08
    v = np.clip(v, 0.0, 1.0)
    vibrance = filt.get('vibrance', 0.0) or 0.0
    if vibrance:
        grey = v.mean(axis=2, keepdims=True)
        v = grey + (v - grey) * (1.0 + vibrance)
        v = np.clip(v, 0.0, 1.0)
    grain = filt.get('_grain')
    if grain:
        # Зерно Figma (эффект GRAIN): крапинки цвета эффекта, размер
        # частицы = radius, сила = альфа цвета, свой seed. CSS его не
        # умеет, поэтому крупа запекается в саму текстуру.
        cell = max(1, int(round(grain.get('radius', 1.0) or 1.0)))
        c = grain.get('color') or {}
        strength = c.get('a', 0.25)
        rng = np.random.RandomState(int(grain.get('seed', 0)) & 0x7FFFFFFF)
        gh = -(-v.shape[0] // cell)   # потолок, чтобы поле покрыло всё
        gw = -(-v.shape[1] // cell)
        field = rng.rand(gh, gw).astype(np.float32) * strength
        field = np.kron(field, np.ones((cell, cell), dtype=np.float32))
        field = field[:v.shape[0], :v.shape[1], None]
        tone = np.array([c.get('r', 0.0), c.get('g', 0.0), c.get('b', 0.0)],
                        dtype=np.float32)
        v = v * (1.0 - field) + tone * field
        v = np.clip(v, 0.0, 1.0)
    out = Image.fromarray((v * 255.0 + 0.5).astype('uint8'))
    buf = _io.BytesIO()
    out.save(buf, 'PNG')
    return buf.getvalue()


class Generator:
    def __init__(self, fig: Path, out: Path, name: str):
        self.fig = fig
        self.out = out
        self.name = name
        self.nodes = figdump.load_nodes(fig)
        self.by_id = {figdump.node_id(n): n for n in self.nodes}
        self.kids = figdump._children_map(self.nodes)
        self.blobs = None
        self.rules: list[str] = []
        self.assets: dict[str, str] = {}
        self.unknown: dict[str, int] = {}
        #: узлы-заглушки внешней библиотеки — дорисовываются растром
        self.blanks: list[dict] = []
        self.counter = 0
        (out / 'assets').mkdir(parents=True, exist_ok=True)

    # ---- ресурсы ---------------------------------------------------------

    def save_image(self, digest: str, filt: dict | None = None) -> str | None:
        """Картинку из архива — в папку вывода, вернуть путь для CSS.

        `filt` — paintFilter краски: правки тона Figma (экспозиция,
        контраст, тени/света, теплота, сочность) запекаются в сам PNG.
        Без этого миниатюры сейвов были насыщенно-оранжевыми, а в макете
        они бледная тёплая гравюра (тени -1, света +1, сочность -0.5).
        """
        grain = (filt or {}).get('_grain')
        filt = {k: v for k, v in (filt or {}).items()
                if k != '_grain' and abs(v or 0) > 1e-4}
        if grain:
            c = grain.get('color') or {}
            filt['_grain'] = grain
            filt['_gkey'] = (grain.get('seed', 0) or 0) \
                + (grain.get('radius', 0) or 0) * 1000 \
                + c.get('a', 0) * 7
        tag = ''
        if filt:
            import hashlib
            fkey = ','.join(f'{k}={filt[k]:.4f}' for k in sorted(filt)
                            if not isinstance(filt[k], dict))
            tag = '_' + hashlib.sha1(fkey.encode()).hexdigest()[:6]
        key = digest + tag
        if key in self.assets:
            return self.assets[key]
        with zipfile.ZipFile(self.fig) as archive:
            inside = f'images/{digest}'
            if inside not in archive.namelist():
                return None
            data = archive.read(inside)
        rel = f'assets/{digest[:12]}{tag}.png'
        if filt:
            data = baked(data, filt)
        (self.out / rel).write_bytes(data)
        self.assets[key] = rel
        return rel

    def image_css(self, paint: dict, box: dict | None,
                  grain: dict | None = None) -> str | None:
        """Слой background для картинки-краски: кроп, черепица, заливка.

        Матрица краски отображает нормированный бокс узла в кусок картинки:
        видимая область начинается в (m02, m12) и занимает (m00, m11) её
        доли. Раньше всё рисовалось «top left / cover», и у миниатюр
        пропадал авторский кроп, а черепичная текстура растягивалась.
        """
        digest = image_name(paint)
        if not digest:
            return None
        filt = dict(paint.get('paintFilter') or {})
        if grain:
            filt['_grain'] = grain
        rel = self.save_image(digest, filt)
        if not rel:
            return None
        box = box or {}
        w = box.get('x', 0) or 0
        h = box.get('y', 0) or 0
        if paint.get('imageScaleMode') == 'TILE':
            scale = paint.get('scale', 1.0) or 1.0
            tile_w = (paint.get('originalImageWidth') or 0) * scale
            tile_h = (paint.get('originalImageHeight') or 0) * scale
            if tile_w and tile_h:
                return (f'url("{rel}") 0 0 / {px(tile_w)} {px(tile_h)} repeat')
            return f'url("{rel}") 0 0 repeat'
        matrix = paint.get('transform') or {}
        m00 = matrix.get('m00', 1.0) or 1e-6
        m11 = matrix.get('m11', 1.0) or 1e-6
        m02 = matrix.get('m02', 0.0)
        m12 = matrix.get('m12', 0.0)
        plain = (abs(m00 - 1) < 1e-4 and abs(m11 - 1) < 1e-4
                 and abs(m02) < 1e-4 and abs(m12) < 1e-4)
        if plain or not (w and h):
            return f'url("{rel}") center / cover no-repeat'
        return (f'url("{rel}") {px(-m02 / m00 * w)} {px(-m12 / m11 * h)} / '
                f'{100 / m00:g}% {100 / m11:g}% no-repeat')

    def save_shape(self, node: dict, only: str):
        """Контур узла в SVG и его габарит (left, top, w, h).

        В имени файла участвует номер блоба: один и тот же узел в разных
        экземплярах несёт РАЗНУЮ пересчитанную геометрию (слот 126 и слот
        86), и без номера второй экземпляр затирал файл первого.
        """
        if self.blobs is None:
            self.blobs = figsvg.load_blobs(self.fig)
        try:
            svg = figsvg.build_svg(node, self.blobs, mask=True, only=only)
        except SystemExit:
            return None
        paths = figsvg.node_paths(node, self.blobs).get(only) or []
        if not paths:
            return None
        boxes = [figpath.bounds(cmds) for cmds, _ in paths]
        left = min(b[0] for b in boxes)
        top = min(b[1] for b in boxes)
        right = max(b[2] for b in boxes)
        bottom = max(b[3] for b in boxes)
        tag = 'edge' if only == 'strokeGeometry' else 'body'
        blob = (node.get(only) or [{}])[0].get('commandsBlob', 0)
        rel = f'assets/{figdump.node_id(node).replace(":", "_")}_{tag}{blob}.svg'
        (self.out / rel).write_text(svg, encoding='utf-8')
        return rel, (left, top, right - left, bottom - top)

    def shape_layer(self, css_class: str, node: dict, only: str,
                    pseudo: str, paints_key: str) -> None:
        """Слой-маска по настоящему контуру узла.

        Векторы и рваные кромки рисуются не коробкой div, а своей
        геометрией: SVG-силуэт становится маской псевдоэлемента, положенного
        точно по габариту путей (обводка выходит за размер узла — стрелка
        слота без этого превращалась в размытое пятно, а контур рамки
        выделения не рисовался вовсе).
        """
        got = self.save_shape(node, only)
        if got is None:
            return
        rel, (left, top, width, height) = got
        fill = None
        node_grain = next((e for e in node.get('effects') or []
                           if e.get('type') == 'GRAIN'
                           and e.get('visible') is not False), None)
        for paint in node.get(paints_key) or []:
            if image_name(paint):
                fill = self.image_css(paint, {'x': width, 'y': height},
                                      node_grain)
                if fill:
                    break
                continue
            fill = gradient(paint, node.get('size')) or colour(paint)
            if fill:
                break
        if fill is None:
            return
        spot = f'url("{rel}") 0 0 / 100% 100% no-repeat'
        self.rules.append(
            f'.{css_class}{pseudo} {{ content: ""; position: absolute; '
            f'left: {px(left)}; top: {px(top)}; '
            f'width: {px(width)}; height: {px(height)}; '
            f'background: {fill}; '
            f'-webkit-mask: {spot}; mask: {spot}; }}')

    # ---- разбор одного узла ---------------------------------------------

    def note_unknown(self, node: dict) -> None:
        for key in node:
            if key not in KNOWN:
                self.unknown[key] = self.unknown.get(key, 0) + 1

    def painted(self, node: dict, key: str) -> list:
        """Краски узла с раскрытием общего стиля.

        Figma умеет держать заливку в общем стиле («Text color/Primary»),
        и тогда у самого узла список красок пуст, а рядом лежит ссылка
        styleIdForFill. Узел-стиль хранится в том же файле, поэтому просто
        берём краски оттуда — иначе элемент оставался бесцветным.
        """
        # ПУСТОЙ СПИСОК — не то же самое, что отсутствие поля: он значит,
        # что заливку у узла сняли осознанно, и подставлять цвет стиля
        # нельзя (иначе диалог торговца заливался лишним цветом).
        if key in node:
            return node[key] or []
        ref = node.get('styleIdForFill' if key == 'fillPaints'
                       else 'styleIdForStroke')
        guid = (ref or {}).get('guid') or {}
        holder = self.by_id.get(f"{guid.get('sessionID')}:{guid.get('localID')}")
        return (holder or {}).get(key) or []

    def style_of(self, node: dict, inside_stack: bool,
                 is_root: bool = False,
                 parent_size: dict | None = None) -> list[str]:
        out: list[str] = []
        transform = node.get('transform') or {}
        size = node.get('size') or {}

        # «Absolute в авто-раскладке»: подложки пилюль и слотов помечены
        # stackPositioning=ABSOLUTE — они не участвуют в потоке. Как флекс-
        # дети они выталкивали текст за край пилюли (12+56+32 при ширине 56)
        # и сдвигали содержимое слота вниз.
        if inside_stack and node.get('stackPositioning') == 'ABSOLUTE':
            inside_stack = False

        if is_root:
            # координаты корня — это его место на холсте Figma, странице они
            # не нужны: экран начинается с нуля
            out.append('position: relative')
            if size.get('x') is not None:
                out.append(f'width: {px(size["x"])}')
            if size.get('y') is not None:
                out.append(f'height: {px(size["y"])}')
        elif not inside_stack:
            # Геометрия в файле уже окончательная: кадр статичный, ничего не
            # пересчитывается. Привязки к краям родителя (STRETCH и прочие)
            # тут не нужны — они для изменения размеров, и попытка их
            # применить раздувала подложки на пол-экрана.
            out.append('position: absolute')
            # МАТРИЦА ЦЕЛИКОМ: отражения И повороты. Сдвиг (m02, m12) — это
            # место ЛЕВОГО ВЕРХНЕГО угла системы координат узла, поэтому он
            # уходит в translate, а линейная часть — в matrix() вокруг
            # origin 0 0. Отражённая рамка выделения тянется влево от своего
            # сдвига; стрелка слота хранится повёрнутой на 90 градусов
            # (44x67 в коробке 67x44) — читая одни знаки диагонали, я рисовал
            # её лежачей коробкой, и вместо шеврона выходило пятно.
            m00 = transform.get('m00', 1.0)
            m01 = transform.get('m01', 0.0)
            m10 = transform.get('m10', 0.0)
            m11 = transform.get('m11', 1.0)
            plain = (abs(m00 - 1) < 1e-6 and abs(m01) < 1e-6
                     and abs(m10) < 1e-6 and abs(m11 - 1) < 1e-6)
            if plain:
                out.append(f'left: {px(transform.get("m02", 0))}')
                out.append(f'top: {px(transform.get("m12", 0))}')
            else:
                out.append('left: 0')
                out.append('top: 0')
                out.append('transform-origin: 0 0')
                out.append(f'transform: translate({px(transform.get("m02", 0))}, '
                           f'{px(transform.get("m12", 0))}) '
                           f'matrix({m00:g}, {m10:g}, {m01:g}, {m11:g}, 0, 0)')
            if size.get('x') is not None:
                out.append(f'width: {px(size["x"])}')
            if size.get('y') is not None:
                out.append(f'height: {px(size["y"])}')
        else:
            # Внутри авто-раскладки место распределяет флекс, но размер свой.
            # `relative` обязателен: без него абсолютно расположенные потомки
            # цепляются не к своему элементу, а к дальнему предку, и слоты
            # налезали друг на друга.
            out.append('position: relative')
            out.append('flex: none')
            if size.get('x') is not None:
                out.append(f'width: {px(size["x"])}')
            if size.get('y') is not None:
                out.append(f'height: {px(size["y"])}')

        if node.get('visible') is False:
            out.append('display: none')
        if (node.get('opacity') or 1.0) < 0.999:
            out.append(f'opacity: {node["opacity"]:g}')
        blend = BLEND.get(node.get('blendMode'))
        if blend:
            out.append(f'mix-blend-mode: {blend}')
        elif node.get('blendMode') not in (None, 'NORMAL', 'PASS_THROUGH'):
            tag = f"режим наложения {node['blendMode']}"
            self.unknown[tag] = self.unknown.get(tag, 0) + 1

        # авто-раскладка -> flex
        if node.get('stackMode') in ('HORIZONTAL', 'VERTICAL'):
            out.append('display: flex')
            if node['stackMode'] == 'VERTICAL':
                out.append('flex-direction: column')
            if node.get('stackSpacing'):
                out.append(f'gap: {px(node["stackSpacing"])}')
            primary = ALIGN.get(node.get('stackPrimaryAlignItems'))
            counter = ALIGN.get(node.get('stackCounterAlignItems'))
            if primary:
                out.append(f'justify-content: {primary}')
            if counter:
                out.append(f'align-items: {counter}')
            top = node.get('stackVerticalPadding') or 0
            left = node.get('stackHorizontalPadding') or 0
            right = node.get('stackPaddingRight', left) or 0
            bottom = node.get('stackPaddingBottom', top) or 0
            if any((top, left, right, bottom)):
                out.append(f'padding: {px(top)} {px(right)} {px(bottom)} {px(left)}')

        # Обрезка содержимого. У Figma-кадра она включена по умолчанию, а
        # выключенная записана как frameMaskDisabled=True. В этом макете
        # обрезают только корень и рамка «Image» — она и кадрирует
        # миниатюру 164x118 в окошко слота.
        if (node.get('type') in ('FRAME', 'SYMBOL', 'INSTANCE')
                and not node.get('frameMaskDisabled')):
            out.append('overflow: hidden')

        # скругление
        radius = node.get('cornerRadius')
        if node.get('rectangleCornerRadiiIndependent'):
            corners = [node.get(f'rectangle{c}CornerRadius', 0) or 0
                       for c in ('TopLeft', 'TopRight', 'BottomRight', 'BottomLeft')]
            if any(corners):
                out.append('border-radius: ' + ' '.join(px(c) for c in corners))
        elif radius:
            out.append(f'border-radius: {px(radius)}')

        # заливка
        layers, colours = [], []
        node_grain = next((e for e in node.get('effects') or []
                           if e.get('type') == 'GRAIN'
                           and e.get('visible') is not False), None)
        for paint in self.painted(node, 'fillPaints'):
            if image_name(paint):
                spot = self.image_css(paint, size, node_grain)
                if spot:
                    layers.append(spot)
                continue
            grad = gradient(paint, size)
            if grad:
                layers.append(grad)
                continue
            solid = colour(paint)
            if solid:
                colours.append(solid)
        if node.get('type') == 'TEXT':
            if colours:
                out.append(f'color: {colours[0]}')
        elif node.get('fillGeometry') and (node.get('type') in VECTORISH or any(image_name(p) for p in node.get('fillPaints') or [])):
            pass  # нарисует слой-маска по контуру (shape_layer)
        else:
            if layers:
                out.append('background: ' + ', '.join(layers))
            if colours:
                out.append(f'background-color: {colours[0]}')

        # обводка: кисть и векторы — слоем-маской (shape_layer), текст —
        # контуром букв, остальное — рамкой
        weight = node.get('strokeWeight') or 0
        if node.get('strokeGeometry') and node.get('strokePaints') and (
                node.get('strokeBrushGuid') or node.get('type') in VECTORISH):
            pass
        elif weight and self.painted(node, 'strokePaints'):
            stroke = next((colour(p) for p in self.painted(node, 'strokePaints')
                           if colour(p)), None)
            if stroke and node.get('type') == 'TEXT':
                # у текста strokePaints красит контур букв, а не рамку
                # коробки; рамка ещё и съедала бокс при border-box
                out.append(f'-webkit-text-stroke: {px(weight)} {stroke}')
                out.append('paint-order: stroke fill')
            elif stroke:
                out.append(f'border: {px(weight)} solid {stroke}')

        # эффекты
        shadows, filters, backdrop = [], [], []
        for effect in node.get('effects') or []:
            if effect.get('visible') is False:
                continue
            kind = effect.get('type')
            c = effect.get('color') or {}
            rgba = (f'rgba({round(c.get("r",0)*255)}, {round(c.get("g",0)*255)}, '
                    f'{round(c.get("b",0)*255)}, {c.get("a",1):.2f})')
            off = effect.get('offset') or {}
            if kind == 'DROP_SHADOW':
                spot = (f'{px(off.get("x",0))} {px(off.get("y",0))} '
                        f'{px(effect.get("radius", 0))} {rgba}')
                if node.get('type') == 'TEXT':
                    # у текста тень лежит на буквах, а не на коробке
                    out.append(f'text-shadow: {spot}')
                else:
                    shadows.append(spot)
            elif kind == 'INNER_SHADOW':
                shadows.append(f'inset {px(off.get("x",0))} {px(off.get("y",0))} '
                               f'{px(effect.get("radius",0))} {rgba}')
            # Радиус размытия Figma — это ~двойная сигма Гаусса, а CSS
            # blur() принимает саму сигму: без деления пополам шеврон у
            # выделенного слота расплывался в бесформенное пятно (сверено с
            # рендером макета).
            elif kind == 'BACKGROUND_BLUR':
                backdrop.append(f'blur({px((effect.get("radius", 0)) / 2)})')
            elif kind == 'FOREGROUND_BLUR':
                filters.append(f'blur({px((effect.get("radius", 0)) / 2)})')
            # GRAIN и NOISE средствами CSS не воспроизводятся — в отчёт
            elif kind in ('GRAIN', 'NOISE'):
                self.unknown[f'эффект {kind}'] = self.unknown.get(f'эффект {kind}', 0) + 1
        if shadows:
            out.append('box-shadow: ' + ', '.join(shadows))
        if filters:
            out.append('filter: ' + ' '.join(filters))
        if backdrop:
            out.append('backdrop-filter: ' + ' '.join(backdrop))

        # текст
        if node.get('type') == 'TEXT':
            font = node.get('fontName') or {}
            family = font.get('family')
            if family:
                out.append(f'font-family: "{family}", serif')
            style = (font.get('style') or '').lower()
            out.append('font-weight: ' + ('700' if 'bold' in style else '400'))
            if node.get('fontSize'):
                out.append(f'font-size: {px(node["fontSize"])}')
            line = node.get('lineHeight') or {}
            if line.get('units') == 'RAW' and line.get('value'):
                out.append(f'line-height: {line["value"]:.3f}')
            if node.get('leadingTrim') == 'CAP_HEIGHT':
                out.append('text-box: trim-both cap alphabetic')
            spacing = node.get('letterSpacing') or {}
            if spacing.get('value'):
                unit = 'em' if spacing.get('units') == 'PERCENT' else 'px'
                amount = (spacing['value'] / 100) if unit == 'em' else spacing['value']
                out.append(f'letter-spacing: {amount:g}{unit}')
            align = node.get('textAlignHorizontal')
            if align:
                out.append(f'text-align: {align.lower()}')
            # ширина по содержимому означает строку без переносов
            if node.get('textAutoResize') == 'WIDTH_AND_HEIGHT':
                out.append('white-space: pre')
            vertical = node.get('textAlignVertical')
            if vertical == 'CENTER':
                out.append('display: flex')
                out.append('align-items: center')
                if align == 'CENTER':
                    out.append('justify-content: center')
        return out

    # ---- обход -----------------------------------------------------------

    def walk(self, node: dict, patches: dict, prefix: tuple,
             inside_stack: bool, depth: int,
             parent_size: dict | None = None,
             grow: tuple[float, float] = (0.0, 0.0),
             z: int | None = None,
             props: dict | None = None,
             isolated: bool = False) -> str:
        key = prefix + (figdump.node_id(node),)
        patch = patches.get(key)
        if patch:
            node = {**node, **{k: v for k, v in patch.items()
                               if k in ('textData', 'visible', 'size',
                                        'transform', 'fillGeometry',
                                        'strokeGeometry', 'stackPositioning',
                                        'componentPropAssignments',
                                        # состояние может подменять сами
                                        # краски: у выделенного слота та же
                                        # текстура без затемнения, кромка
                                        # высветлена (+0.25 экспозиции)
                                        'fillPaints', 'strokePaints',
                                        'opacity', 'effects',
                                        'cornerRadius',
                                        'rectangleCornerRadiiIndependent',
                                        'rectangleTopLeftCornerRadius',
                                        'rectangleTopRightCornerRadius',
                                        'rectangleBottomLeftCornerRadius',
                                        'rectangleBottomRightCornerRadius')}}
        # Свойство компонента, привязанное к полю слоя: так ужатые слоты
        # выключают строку подсказок (булево 1225:1 -> VISIBLE у «Hotkeys»).
        for ref in node.get('componentPropRefs') or []:
            def_id = ref.get('defID') or {}
            def_key = f"{def_id.get('sessionID')}:{def_id.get('localID')}"
            if props and def_key in props:
                field = ref.get('componentPropNodeField')
                if field == 'VISIBLE':
                    node = {**node, 'visible': props[def_key]}
                else:
                    tag = f'свойство компонента {field}'
                    self.unknown[tag] = self.unknown.get(tag, 0) + 1
        if node.get('visible') is False:
            return ''
        # Узел-маска не рисуется: в Figma он обрезает соседей, а не красит
        # собой. Его форму навешиваем на родителя (см. mask_of ниже).
        if node.get('mask'):
            return ''
        # ЗАТЕМНЯЮЩИЙ РЕЖИМ ВНУТРИ ИЗОЛИРОВАННОЙ ГРУППЫ. У предка стоит
        # размытие фона (или фильтр), а в CSS это отрезает группу от того,
        # что под ней: умножение считается уже не с панелью, а с пустотой,
        # и «стекло» ложится белой пеленой вместо лёгкого затемнения.
        # Ни один порядок слоёв этого не чинит — таково правило CSS.
        # Меньшее зло: слой не рисуем и честно пишем в отчёт.
        if isolated and node.get('blendMode') in (
                'MULTIPLY', 'DARKEN', 'COLOR_BURN', 'LINEAR_BURN'):
            tag = f"слой {node.get('blendMode')} внутри изолированной группы"
            self.unknown[tag] = self.unknown.get(tag, 0) + 1
            return ''

        self.note_unknown(node)

        self.counter += 1
        css_class = f'{self.name}-{self.counter}'
        rules = self.style_of(node, inside_stack, is_root=(depth == 0),
                              parent_size=parent_size)
        if z is not None:
            rules.append(f'z-index: {z}')
        if rules:
            self.rules.append(f'.{css_class} {{ ' + '; '.join(rules) + '; }')
        if node.get('fillGeometry') and (node.get('type') in VECTORISH or any(image_name(p) for p in node.get('fillPaints') or [])):
            self.shape_layer(css_class, node, 'fillGeometry', '::before',
                             'fillPaints')
        if node.get('strokeGeometry') and node.get('strokePaints') and (
                node.get('strokeBrushGuid')
                or node.get('type') in VECTORISH):
            self.shape_layer(css_class, node, 'strokeGeometry', '::after',
                             'strokePaints')

        source, child_prefix = node, prefix
        child_grow = (0.0, 0.0)
        child_props = props
        if node.get('type') == 'INSTANCE':
            # значения свойств, выставленные этому экземпляру
            assigned = node.get('componentPropAssignments') or []
            if assigned:
                child_props = dict(props or {})
                for item in assigned:
                    def_id = item.get('defID') or {}
                    value = (item.get('value') or {}).get('boolValue')
                    if value is not None:
                        child_props[
                            f"{def_id.get('sessionID')}:{def_id.get('localID')}"
                        ] = value
            for path, item in figdump._overrides(node).items():
                # Запись могла уже появиться от derivedSymbolData внешнего
                # экземпляра — тогда setdefault выбрасывал правку ЦЕЛИКОМ, и
                # пилюля печатала базовый «SPACE» вместо «ESC». Сливаем по
                # полям; внешний экземпляр главнее, поэтому setdefault. Хранить
                # item по ссылке нельзя: дальше его дополнили бы геометрией и
                # испортили разобранный файл для соседних экземпляров.
                spot = patches.setdefault(key + path, {})
                for field, value in item.items():
                    spot.setdefault(field, value)
            # пересчитанная под этот экземпляр геометрия детей
            for item in node.get('derivedSymbolData') or []:
                path = tuple(f"{g.get('sessionID')}:{g.get('localID')}"
                             for g in (item.get('guidPath') or {}).get('guids') or [])
                if not path:
                    continue
                spot = patches.setdefault(key + path, {})
                for field in ('size', 'transform', 'fillGeometry',
                              'strokeGeometry'):
                    if field in item:
                        spot.setdefault(field, item[field])
            symbol = (patch or {}).get('overriddenSymbolID') \
                or (node.get('symbolData') or {}).get('symbolID')
            target = self.by_id.get(
                f"{symbol.get('sessionID')}:{symbol.get('localID')}") if symbol else None
            if target is None:
                self.blanks.append({'class': css_class,
                                    'node': figdump.node_id(node),
                                    'name': node.get('name')})
                return f'<div class="{css_class}"></div>'
            source, child_prefix = target, key
            here = node.get('size') or {}
            there = target.get('size') or {}
            child_grow = ((here.get('x', 0) or 0) - (there.get('x', 0) or 0),
                          (here.get('y', 0) or 0) - (there.get('y', 0) or 0))

        if node.get('type') == 'TEXT':
            text = ((node.get('textData') or {}).get('characters') or '')
            safe = (text.replace('&', '&amp;').replace('<', '&lt;')
                        .replace('>', '&gt;'))
            return f'<div class="{css_class}">{safe}</div>'

        stack = node.get('stackMode') in ('HORIZONTAL', 'VERTICAL')
        kids = self.kids.get(figdump.node_id(source), [])
        # Булева операция рисуется СВОИМ контуром, а её дети — только
        # операнды: в Figma они не отображаются. Раньше генератор рисовал и
        # результат, и операнды, и светлые прямоугольники-заготовки лезли
        # поверх кнопок и панелей белыми плашками.
        if node.get('type') == 'BOOLEAN_OPERATION':
            kids = []
        # Пустой узел из внешней библиотеки: Figma кладёт в .fig только
        # заглушку символа (размер есть, детей и красок нет), поэтому фоны
        # и логотипы приезжали дырами. Помечаем — их дорисует figfill.py,
        # снимая растр через мост прямо из открытого файла.
        if (not kids and not node.get('fillPaints')
                and not node.get('fillGeometry')
                and node.get('type') in ('INSTANCE', 'FRAME')
                and (node.get('size') or {}).get('x')):
            self.blanks.append({'class': css_class,
                                'node': figdump.node_id(node),
                                'name': node.get('name')})
        # Если среди детей есть маска — родитель по ней и обрезается.
        # Маска с градиентной заливкой (вуаль прокрутки) переносится как
        # настоящая mask-image: клип давал жёсткий срез там, где макет
        # плавно гасит последний слот.
        veil = next((k for k in kids if k.get('mask')), None)
        if veil is not None:
            # узел-маска берётся из символа сырым — правки экземпляра
            # (пересчитанный размер и рваный контур) лежат в patches
            veil_patch = patches.get(child_prefix + (figdump.node_id(veil),))
            if veil_patch:
                veil = {**veil, **{k: v for k, v in veil_patch.items()
                                   if k in ('size', 'transform',
                                            'fillGeometry')}}
            box = veil.get('size') or {}
            spot = veil.get('transform') or {}
            grad = next((gradient(p, box) for p in veil.get('fillPaints') or []
                         if gradient(p, box)), None)
            shape = (None if grad else
                     self.save_shape(veil, 'fillGeometry')
                     if veil.get('fillGeometry') else None)
            if shape is not None:
                # маска с формой (рваная бумага миниатюр): силуэт её
                # контура вместо жёсткого прямоугольного клипа
                rel, (gl, gt, gw, gh) = shape
                place = (f'{px(spot.get("m02", 0) + gl)} '
                         f'{px(spot.get("m12", 0) + gt)} / '
                         f'{px(gw)} {px(gh)} no-repeat')
                self.rules.append(
                    f'.{css_class} {{ -webkit-mask: url("{rel}") {place}; '
                    f'mask: url("{rel}") {place}; }}')
            elif grad:
                place = (f'{px(spot.get("m02", 0))} {px(spot.get("m12", 0))} / '
                         f'{px(box.get("x", 0))} {px(box.get("y", 0))} no-repeat')
                # mask-clip по умолчанию режет отрисовку по границе
                # элемента — стрелка слота и вынос рамки выделения пропадали.
                # Вуаль Figma шире кадра и ничего не режет: no-clip.
                self.rules.append(
                    f'.{css_class} {{ -webkit-mask: {grad} {place}; '
                    f'mask: {grad} {place}; mask-clip: no-clip; }}')
            else:
                self.rules.append(
                    f'.{css_class} {{ clip-path: inset('
                    f'{px(spot.get("m12", 0))} '
                    f'calc(100% - {px((spot.get("m02", 0)) + (box.get("x", 0)))}) '
                    f'calc(100% - {px((spot.get("m12", 0)) + (box.get("y", 0)))}) '
                    f'{px(spot.get("m02", 0))}); }}')
        # У стека Figma может стоять «первый сверху» (stackReverseZIndex);
        # DOM красит наоборот, поэтому раздаём z-index по убыванию — иначе
        # подложка слота, став absolute, закрасила бы текст.
        # группа становится изолированной для потомков, если у неё есть
        # размытие фона, фильтр или собственная прозрачность
        kid_isolated = isolated or (node.get('opacity') or 1.0) < 0.999 or any(
            e.get('type') in ('BACKGROUND_BLUR', 'FOREGROUND_BLUR')
            and e.get('visible') is not False
            for e in node.get('effects') or [])
        reverse = bool(node.get('stackReverseZIndex'))
        inner = ''.join(self.walk(kid, patches, child_prefix, stack,
                                  depth + 1, node.get('size'), child_grow,
                                  z=(len(kids) - i if reverse else None),
                                  props=child_props, isolated=kid_isolated)
                        for i, kid in enumerate(kids))
        title = (node.get('name') or '').replace('"', "'")
        return f'<div class="{css_class}" data-name="{title}">{inner}</div>'

    def run(self, root: str) -> None:
        node = self.by_id.get(root)
        if node is None:
            raise SystemExit(f'нет такого узла: {root}')
        patches = figdump._overrides(node) if node.get('type') == 'INSTANCE' else {}
        body = self.walk(node, patches, (), False, 0)
        size = node.get('size') or {}
        width = size.get('x', 1920)

        css = ['/* Порождено tools/figgen.py из .fig — вручную не править. */',
               # кадр вписывается в окно целиком: по ширине это 100vw, по
               # высоте — ширина, пересчитанная через соотношение сторон.
               # Коэффициент был перевёрнут (56.25vh вместо 177.78vh), и
               # весь экран рисовался втрое мельче.
               f'.{self.name}-root {{ position: relative; overflow: hidden; '
               f'--px: calc(min(100vw, {(width/size.get("y",1080))*100:g}vh)'
               f' / {width:g}); }}',
               '.' + self.name + '-root div { box-sizing: border-box; margin: 0; }',
               *self.rules]
        # Атомарно: сверка может снимать страницу ровно в момент записи,
        # и полуготовый файл даёт ложный «регресс» вместо настоящего числа.
        def put(name: str, text: str) -> None:
            spare = self.out / (name + '.tmp')
            spare.write_text(text, encoding='utf-8')
            spare.replace(self.out / name)

        # НЕТ ФОНОВОГО СЛОЯ. У части кадров фон существует только в облаке:
        # в выгруженном .fig слоя нет вовсе, и экран выходит на голой
        # подложке. Помечаем — figfill подставит извлечённую сцену, и это
        # будет видно как заимствование, а не выдано за данные макета.
        # Скрытый полноэкранный слой тоже считается фоном: дизайнер его
        # выключил намеренно (экран загрузки в макете тёмный), и подмена
        # сценой была бы отсебятиной.
        wide = [k for k in self.kids.get(root, [])
                if (k.get('size') or {}).get('x', 0) >= width * 0.95
                and (k.get('size') or {}).get('y', 0) >= (size.get('y') or 1080) * 0.95]
        if not node.get('fillPaints') and not wide:
            self.blanks.append({'class': f'{self.name}-root',
                                'node': root, 'name': 'фон кадра',
                                'scene': True})

        put(f'{self.name}.css', '\n'.join(css))
        put(f'{self.name}.html', f'<div class="{self.name}-root">{body}</div>')
        # Список заглушек переписываем ВСЕГДА, а пустой — удаляем: иначе
        # вчерашняя пометка переживает пересборку, и figfill подставляет
        # фон экрану, которому он уже не нужен.
        spec = self.out / f'{self.name}.blanks.json'
        if self.blanks:
            import json as _json
            put(f'{self.name}.blanks.json',
                _json.dumps(self.blanks, ensure_ascii=False, indent=1))
        elif spec.exists():
            spec.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('fig', type=Path)
    parser.add_argument('--node', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--report', action='store_true',
                        help='показать, чего генератор не сумел разложить')
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    gen = Generator(args.fig, args.out, args.name)
    gen.run(args.node)
    print(f'узлов: {gen.counter}, правил: {len(gen.rules)}, '
          f'картинок: {len(gen.assets)}')
    if args.report:
        if gen.unknown:
            print('\nНЕ РАЗЛОЖЕНО (ничем не подменялось):')
            for key, count in sorted(gen.unknown.items(), key=lambda kv: -kv[1]):
                print(f'   {key:34} {count}')
        else:
            print('\nвсё разложено')


if __name__ == '__main__':
    main()
