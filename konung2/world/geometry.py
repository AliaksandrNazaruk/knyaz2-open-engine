# -*- coding: utf-8 -*-
"""Две решётки мира и переходы между ними.

В «Князе 2» их именно две, и путать их нельзя — на этом уже терялись часы:

* **клетка сетки** (`Cell`) — 160 столбцов × 256 строк, кирпич 58 × 16.
  На ней живут проходимость, постройки и юниты (`konung2.grid`).
* **клетка земли** (`GroundCell`) — 80 столбцов × 160 строк, ромб 114 × 64.
  На ней живут тайлы и маска локального света (`konung2.graph`).

Земляная решётка ровно вдвое крупнее по обеим осям, но начала координат у
них не совпадают, поэтому сравнивать `(row, col)` двух решёток напрямую
НЕЛЬЗЯ. Единственный надёжный путь — через пиксели, для этого здесь
`ground_at_point`.

Все формулы сняты с движка, ссылки на адреса стоят у каждой.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..graph import TILE_HEIGHT, TILE_ODD_SHIFT, TILE_STEP_X, TILE_STEP_Y, TILE_WIDTH
from ..grid import CELL_H, CELL_W, GRID_COLS, GRID_ROWS

GROUND_ROWS, GROUND_COLS = 160, 80


@dataclass(frozen=True)
class Point:
    """Точка в мировых пикселях карты."""

    x: int
    y: int

    def moved(self, dx: int, dy: int) -> "Point":
        return Point(self.x + dx, self.y + dy)


@dataclass(frozen=True)
class Cell:
    """Клетка сетки: проходимость, постройки, юниты."""

    row: int
    col: int

    @property
    def valid(self) -> bool:
        return 0 <= self.row < GRID_ROWS and 0 <= self.col < GRID_COLS

    def anchor(self) -> Point:
        """Точка ног юнита, стоящего в клетке (VA 0x43B974)."""
        return Point(self.col * CELL_W + (29 if self.row & 1 else CELL_W),
                     self.row * CELL_H + CELL_H)


@dataclass(frozen=True)
class GroundCell:
    """Клетка земли: пара тайлов и маска локального света."""

    row: int
    col: int

    @property
    def valid(self) -> bool:
        return 0 <= self.row < GROUND_ROWS and 0 <= self.col < GROUND_COLS

    def origin(self) -> Point:
        """Левый верхний угол ромба (VA 0x42502C, 0x425047, 0x42504E)."""
        return Point(self.col * TILE_STEP_X + (TILE_ODD_SHIFT if self.row & 1 else 0),
                     self.row * TILE_STEP_Y)

    def center(self) -> Point:
        origin = self.origin()
        return Point(origin.x + TILE_WIDTH // 2, origin.y + TILE_HEIGHT // 2)


def cell_at_point(point: Point) -> Cell:
    """Клетка сетки по мировой точке (VA 0x43B9B0).

    Разбор целиком живёт в :func:`konung2.grid.pixel_to_cell` — там же
    ромбическая поправка и клемпы; здесь только обёртка в ``Cell``.
    """
    from ..grid import pixel_to_cell
    return Cell(*pixel_to_cell(point.x, point.y))


def ground_at_point(point: Point) -> GroundCell | None:
    """Клетка земли, чей ромб накрывает точку.

    Обратная к :meth:`GroundCell.origin`: ромбы уложены со сдвигом нечётных
    рядов, поэтому подходящих строк всегда две, и выбирается та, для которой
    точка лежит внутри ромба (|dx|/57 + |dy|/32 <= 1).
    """
    base = int(point.y) // TILE_STEP_Y
    for row in (base, base - 1, base + 1):
        if not 0 <= row < GROUND_ROWS:
            continue
        shift = TILE_ODD_SHIFT if row & 1 else 0
        col = (int(point.x) - shift) // TILE_STEP_X
        for candidate in (col, col - 1, col + 1):
            if not 0 <= candidate < GROUND_COLS:
                continue
            cell = GroundCell(row, candidate)
            center = cell.center()
            dx = abs(point.x - center.x) / (TILE_WIDTH / 2)
            dy = abs(point.y - center.y) / (TILE_HEIGHT / 2)
            if dx + dy <= 1.0:
                return cell
    return None


def ground_at_cell(cell: Cell) -> GroundCell | None:
    """Клетка земли под клеткой сетки — только через пиксели."""
    return ground_at_point(cell.anchor())


@dataclass(frozen=True)
class Bounds:
    """Габариты кадра сущности и её ключ глубины.

    ``sort_height`` — большая из высот кадров main и walls (VA 0x426AFB),
    крыша в ключ намеренно не входит; ``sort_bias`` — понижение ключа на
    четверть высоты для построек с битом 0x08 байта hdr+0xFE (VA 0x426B75):
    линия глубины проходит по подошве передней стены.
    """

    width: int
    height: int
    offset_x: int
    offset_y: int
    sort_height: int
    sort_bias: int = 0

    def draw_origin(self, position: Point) -> Point:
        return Point(position.x + self.offset_x, position.y + self.offset_y)

    def sort_key(self, position: Point) -> int:
        return position.y + self.offset_y + self.sort_height - self.sort_bias
