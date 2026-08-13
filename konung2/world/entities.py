# -*- coding: utf-8 -*-
"""Сущности мира: постройка, реквизит, клетка земли.

Смысл слоя — собрать в одном объекте то, что в файлах игры разложено по
четырём таблицам: кадры лежат в OBJECTS.RES, положение в записи карты,
пол и «крыльцо» в сетке `.KN2`, а правило освещения — в бите заголовка
ресурса. Редактор карт и моды должны видеть постройку целиком, а не
собирать её каждый раз заново.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .geometry import Bounds, Cell, GroundCell, Point

#: Части постройки в порядке отрисовки (VA 0x425AA8). Тень — не часть
#: картинки: она регистрируется спанами и затемняет фон отдельным проходом
#: (VA 0x43F260 -> 0x440788).
PART_ORDER = ("main", "walls", "roof")


@dataclass(frozen=True)
class Frame:
    """Один кадр сущности: геометрия и, если собран, файл картинки."""

    part: str
    width: int
    height: int
    offset_x: int
    offset_y: int
    asset: str | None = None


@dataclass(frozen=True)
class Lighting:
    """Как сущность ведёт себя при смене времени суток.

    ``main_static_palette`` — бит 0x04 байта hdr+0xFE. Развилка VA 0x425AED
    берёт для кадра main ИСХОДНУЮ палитру (``[0x58E300] + запись[+4]``, VA
    0x425B0C) вместо пересчитанной под сутки (VA 0x441393), которой рисуются
    стены и крыша. Интерьер постройки — это и есть кадр main, поэтому пол в
    доме никогда не темнеет. Бит стоит только у построек со стенами.
    """

    main_static_palette: bool = False
    lowers_depth_key: bool = False       # бит 0x08 того же байта


@dataclass(frozen=True)
class BuildingCells:
    """Клетки сетки, которыми постройка владеет.

    * ``footprint`` — все клетки с индексом этой постройки (биты 16..20).
      По ним прячется крыша, когда на клетку встаёт член отряда
      (VA 0x428282), и они шире пола: «крыльцо» у входа тоже сюда входит.
    * ``floor`` — из них те, что несут бит 15: пол интерьера. Игрок на такой
      клетке дополнительно рисуется полупрозрачной копией поверх всей сцены
      (отложенный список 0x866F5C, VA 0x428900) — иначе его закрыла бы стена.
    * ``routed`` — бит 21: юнит рисуется проходом содержимого постройки
      (классификатор VA 0x42846E), то есть между кадрами main и walls.
    """

    footprint: tuple[Cell, ...] = ()
    floor: tuple[Cell, ...] = ()
    routed: tuple[Cell, ...] = ()

    def __contains__(self, cell: object) -> bool:
        return cell in self.footprint


@dataclass
class Entity:
    """Общее у постройки и реквизита: где стоит и чем рисуется."""

    id: str
    record_slot: int
    resource_slot: int
    palette: int
    state: int
    position: Point
    bounds: Bounds
    frames: dict[str, Frame] = field(default_factory=dict)
    lighting: Lighting = field(default_factory=Lighting)

    @property
    def draw_origin(self) -> Point:
        return self.bounds.draw_origin(self.position)

    @property
    def sort_key(self) -> int:
        return self.bounds.sort_key(self.position)

    def frame(self, part: str) -> Frame | None:
        return self.frames.get(part)


@dataclass
class Prop(Entity):
    """Объект без стен: дерево, забор, колодец, мелочь у дороги.

    Клетки у него обычно пусты, но у пустой площадки под стройку они есть:
    сетка держит за ней «след» меткой «номер объекта + 1» (биты 16…20), и
    именно по ней движок открывает клетки достроенного (VA 0x43F178).
    """

    kind: str = "prop"
    cells: BuildingCells = field(default_factory=BuildingCells)


@dataclass
class Building(Entity):
    """Постройка: кадры main/walls/roof, свои клетки и правило света."""

    kind: str = "building"
    cells: BuildingCells = field(default_factory=BuildingCells)

    def hides_roof_for(self, cell: Cell) -> bool:
        """Крыша прячется, когда член отряда встал на клетку постройки."""
        return cell in self.cells.footprint

    def is_interior(self, cell: Cell) -> bool:
        """Клетка — пол интерьера (бит 15)."""
        return cell in self.cells.floor

    def routes_unit(self, cell: Cell) -> bool:
        """Юнит рисуется проходом содержимого, между main и walls (бит 21)."""
        return cell in self.cells.routed

    @property
    def interior_is_daylit(self) -> bool:
        return self.lighting.main_static_palette


@dataclass
class GroundTile:
    """Клетка земли: пара тайлов и локальный свет.

    ``light_mask`` — номер маски LIGHTS.RES (байт слоя 2 минус единица).
    Ненулевая маска means: движок рисует клетку проходом VA 0x43FD70, где
    красный и зелёный берутся из таблицы уровня «уровень канала + маска»,
    а синий не меняется вовсе. В content pack для такой клетки идёт разность
    с обычной клеткой (`glow`), которую клиент складывает с кадром.
    """

    cell: GroundCell
    lower_tile: int | None
    upper_tile: int | None
    light_mask: int | None = None
    asset: str | None = None
    glow: str | None = None

    @property
    def position(self) -> Point:
        return self.cell.origin()

    @property
    def lit(self) -> bool:
        return self.light_mask is not None
