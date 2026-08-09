# -*- coding: utf-8 -*-
"""Упаковка кадров в листы — так же, как ресурсы устроены в самой игре.

Движок НЕ держит кадры отдельными файлами. Каждый ``.RES`` он читает одним
куском в одну арену и обращается к спрайтам через таблицу смещений:

    HEROES.RES (VA 0x43C2E8)   размер файла -> одно выделение -> таблица
                               смещений 0x49C0 байт на 1399 записей ->
                               цикл дочитывания кусков подряд, указатели
                               складываются в таблицу 0x84694C
    INTERF.RES (VA 0x43026C)   u32 размер -> 8000 байт таблицы
                               1000×{смещение, палитра} -> данные
    GRAPH.RES                  палитры, затем такая же таблица тайлов

Здесь то же самое в браузерном виде: кадры набора кладутся на общий ЛИСТ
(атлас), а вместо смещения в арене кадр получает прямоугольник на листе.
Клиент тянет один файл вместо тысяч и рисует куском из него.

Раскладка простая, полками: кадры сортируются по высоте и укладываются
рядами. Спрайты игры примерно одного роста (самый большой 134×126), так что
плотность выходит высокой, а код остаётся проверяемым.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

#: Предел стороны листа. Больше 4096 брать нельзя: часть видеокарт такие
#: холсты не берёт, а движок и подавно оперировал кусками поменьше.
SHEET_LIMIT = 4096
#: Зазор между кадрами, чтобы сглаживание не тянуло соседний пиксель.
PADDING = 1


class Sheet:
    """Один лист: холст и уложенные на него кадры."""

    def __init__(self, name: str, limit: int = SHEET_LIMIT) -> None:
        self.name = name
        self.limit = limit
        self.image = None
        self.width = 0
        self.height = 0
        self._x = 0
        self._y = 0
        self._row = 0

    def fits(self, width: int, height: int) -> bool:
        """Влезет ли кадр — с переходом на новую полку, если нужно."""
        if width + PADDING > self.limit:
            return False
        if self._x + width + PADDING <= self.limit:
            return self._y + height + PADDING <= self.limit
        return self._y + self._row + height + PADDING <= self.limit

    def place(self, sprite) -> tuple[int, int]:
        """Положить кадр и вернуть его угол на листе.

        Спрайты игры приходят своим типом (``konung2.res.Sprite``), а не
        картинкой PIL, поэтому перед укладкой их надо обратить в картинку —
        у них для этого есть ``to_image``.
        """
        from PIL import Image

        if hasattr(sprite, "to_image"):
            sprite = sprite.to_image()
        width, height = sprite.width, sprite.height
        if self._x + width + PADDING > self.limit:
            self._y += self._row + PADDING
            self._x = 0
            self._row = 0
        x, y = self._x, self._y
        self._x += width + PADDING
        self._row = max(self._row, height)
        self.width = max(self.width, x + width)
        self.height = max(self.height, y + height)
        if self.image is None:
            self.image = Image.new("RGBA", (self.limit, self.limit), (0, 0, 0, 0))
        self.image.paste(sprite, (x, y))
        return x, y

    def save(self, root: Path, relative: Path) -> dict[str, Any]:
        """Обрезать лист по занятому и записать — по возможности с палитрой.

        Спрайты игры ВОСЬМИБИТНЫЕ: в ресурсе лежат номера цветов, а палитра
        подставляется перед блиттером. Поэтому на листе, собранном из кадров
        ОДНОЙ палитры, цветов не больше двухсот пятидесяти шести — и его
        можно записать индексированным PNG без единой потери. Выходит вдвое
        с лишним легче полноцветного, а браузер разворачивает его сам.
        """
        from PIL import Image

        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        cropped = self.image.crop((0, 0, self.width, self.height))
        indexed = _to_indexed(cropped)
        if indexed is not None:
            indexed.save(str(target), optimize=True, transparency=0)
        else:
            cropped.save(str(target))
        return {"path": relative.as_posix(),
                "width": cropped.width, "height": cropped.height,
                "indexed": indexed is not None}


class AtlasWriter:
    """Складывает кадры набора на листы и отдаёт их описание."""

    def __init__(self, root: Path, folder: Path, name: str,
                 limit: int = SHEET_LIMIT) -> None:
        self.root = root
        self.folder = folder
        self.name = name
        self.limit = limit
        self.sheets: list[Sheet] = []
        #: по листу на палитру — иначе цветов станет больше двухсот пятидесяти
        #: шести и лист придётся писать полноцветным
        self._byPalette: dict[Any, Sheet] = {}

    def add(self, sprite, palette: Any = None) -> dict[str, Any]:
        """Положить кадр и вернуть, где он лежит.

        ``palette`` — ключ палитры кадра. Кадры разных палитр на один лист
        не кладутся: так лист остаётся в пределах 256 цветов и пишется
        индексированным PNG без потерь, как и хранит их сама игра.
        """
        if sprite is None:
            return {}
        current = self._byPalette.get(palette)
        if current is None or not current.fits(sprite.width, sprite.height):
            current = Sheet(f"{self.name}_{len(self.sheets)}", self.limit)
            self.sheets.append(current)
            self._byPalette[palette] = current
        x, y = current.place(sprite)
        return {"sheet": self.sheets.index(current),
                "x": x, "y": y,
                "width": sprite.width, "height": sprite.height}

    def flush(self) -> list[dict[str, Any]]:
        """Записать листы на диск и вернуть их описания."""
        out = []
        for index, sheet in enumerate(self.sheets):
            relative = self.folder / f"{self.name}_{index}.png"
            out.append(sheet.save(self.root, relative))
        return out


def pack(root: Path, folder: Path, name: str,
         frames: Iterable[tuple[Any, Any]],
         limit: int = SHEET_LIMIT) -> tuple[list[dict[str, Any]], dict[Any, dict]]:
    """Упаковать набор кадров.

    ``frames`` — пары «ключ, картинка». Возвращает список листов и таблицу
    «ключ -> где лежит», то есть ровно то же, чем в движке служит таблица
    смещений рядом с ареной.
    """
    writer = AtlasWriter(root, folder, name, limit)
    where: dict[Any, dict] = {}
    for key, sprite in frames:
        if sprite is None:
            continue
        where[key] = writer.add(sprite)
    return writer.flush(), where


def _to_indexed(image):
    """Перевести картинку в палитру ТОЧНО, без квантования.

    Возвращает None, если цветов больше двухсот пятидесяти шести: тогда
    лист остаётся полноцветным, и это честно видно в его описании.
    """
    from PIL import Image

    colours = image.getcolors(maxcolors=256)
    if colours is None:
        return None
    values = [colour for _, colour in colours]
    clear = [c for c in values if c[3] == 0]
    order = (clear[:1] if clear else [(0, 0, 0, 0)])
    order += [c for c in values if c[3] != 0]
    if len(order) > 256:
        return None
    table = {colour: index for index, colour in enumerate(order)}
    indexed = Image.new("P", image.size)
    indexed.putdata([table[colour] for colour in image.getdata()])
    flat: list[int] = []
    for colour in order:
        flat += [colour[0], colour[1], colour[2]]
    flat += [0] * (768 - len(flat))
    indexed.putpalette(flat)
    return indexed
