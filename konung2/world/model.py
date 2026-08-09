# -*- coding: utf-8 -*-
"""Карта как мир: земля, постройки, реквизит и правила освещения.

`MapModel` собирается из файлов игры один раз и дальше отвечает на вопросы
по-человечески: какие постройки на карте, чем владеет каждая, проходима ли
клетка, светится ли клетка земли. На нём строятся сборщик content pack,
инструменты и будущий редактор — сырые таблицы `.KN2` и OBJECTS.RES дальше
этого модуля не идут.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Iterator

from ..graph import LIGHT_FROM_TICK, fixed_light_map, ground_cells
from ..grid import BUILT, GRID_COLS, GRID_ROWS, PASSABLE_MASK, SOLID
from ..kn2 import KN2Map, T_OBJECTS
from ..res import ObjectsRes
from .entities import (Building, BuildingCells, Entity, Frame, GroundTile,
                       Lighting, PART_ORDER, Prop)
from .geometry import Bounds, Cell, GroundCell, Point

#: Бит 22 клетки: юнит на ней блитится статичной палитрой (VA 0x425E81),
#: то есть в ауре света остаётся дневным, пока сцена затемнена.
BRIGHT_UNIT = 0x00400000
#: Бит 21: юнит рисуется проходом содержимого постройки (VA 0x42846E).
ROUTED_UNIT = 0x00200000


@dataclass(frozen=True)
class MapLighting:
    """Когда на карте включается локальный свет (VA 0x424FFA)."""

    from_tick: int = LIGHT_FROM_TICK
    always: bool = False


@dataclass
class Terrain:
    """Земля и её свойства, общие для всей карты."""

    tiles: list[GroundTile] = field(default_factory=list)
    blocked: tuple[Cell, ...] = ()
    #: Клетки с битом 0x4000 — «стена или постройка». По ним движок
    #: считает попадание зажигательной стрелы (VA 0x41FDD0) и обрывает
    #: траекторию выстрела (VA 0x414BA4). Это НЕ то же, что проходимость.
    solid: tuple[Cell, ...] = ()
    bright: tuple[Cell, ...] = ()

    def __iter__(self) -> Iterator[GroundTile]:
        return iter(self.tiles)

    @property
    def lit_tiles(self) -> list[GroundTile]:
        return [tile for tile in self.tiles if tile.lit]

    def passable(self, cell: Cell) -> bool:
        """Клетка свободна ⟺ младшие 12 бит пусты (VA 0x4414A7).

        Внутри построек эти биты нулевые — именно поэтому в дом можно войти.
        """
        return cell.valid and cell not in self._blocked_set

    @property
    def _blocked_set(self) -> set[Cell]:
        cached = getattr(self, "_blocked_cache", None)
        if cached is None:
            cached = set(self.blocked)
            object.__setattr__(self, "_blocked_cache", cached)
        return cached


@dataclass
class MapModel:
    """Одна локация целиком."""

    number: int
    terrain: Terrain = field(default_factory=Terrain)
    buildings: list[Building] = field(default_factory=list)
    props: list[Prop] = field(default_factory=list)
    lighting: MapLighting = field(default_factory=MapLighting)

    # ── сборка ────────────────────────────────────────────────────────────
    @classmethod
    def from_game(cls, number: int, objects: ObjectsRes | None = None) -> "MapModel":
        return cls.from_kn2(KN2Map.from_game(number), number, objects)

    @classmethod
    def from_kn2(cls, kn2: KN2Map, number: int,
                 objects: ObjectsRes | None = None) -> "MapModel":
        objects = objects or ObjectsRes.from_game()
        blocked, solid, bright, owned = _read_grid(kn2)
        model = cls(
            number=number,
            terrain=Terrain(tiles=_read_ground(kn2), blocked=blocked,
                            solid=solid, bright=bright),
            lighting=MapLighting(always=fixed_light_map(number)),
        )
        for record in T_OBJECTS.unpack(kn2.data)["records"]:
            entity = _read_entity(record, number, objects, owned)
            if isinstance(entity, Building):
                model.buildings.append(entity)
            elif entity is not None:
                model.props.append(entity)
        return model

    # ── запросы ───────────────────────────────────────────────────────────
    @property
    def entities(self) -> list[Entity]:
        return [*self.buildings, *self.props]

    def in_draw_order(self) -> list[Entity]:
        """Порядок отрисовки движка: по ключу глубины, затем по x и слоту."""
        return sorted(self.entities,
                      key=lambda e: (e.sort_key, e.draw_origin.x, e.record_slot))

    def building_at(self, cell: Cell) -> Building | None:
        """Постройка, которой принадлежит клетка (её крыша прячется)."""
        for building in self.buildings:
            if building.hides_roof_for(cell):
                return building
        return None

    def interior_at(self, cell: Cell) -> Building | None:
        """Постройка, внутри которой стоит клетка пола (бит 15)."""
        for building in self.buildings:
            if building.is_interior(cell):
                return building
        return None

    def passable(self, cell: Cell) -> bool:
        return self.terrain.passable(cell)

    def unit_is_daylit(self, cell: Cell) -> bool:
        """Бит 22: юнит на клетке рисуется статичной палитрой."""
        return cell in self._bright_set

    @property
    def _bright_set(self) -> set[Cell]:
        cached = getattr(self, "_bright_cache", None)
        if cached is None:
            cached = set(self.terrain.bright)
            object.__setattr__(self, "_bright_cache", cached)
        return cached


# ── чтение сырых таблиц ───────────────────────────────────────────────────

def _read_grid(kn2: KN2Map) -> tuple[tuple[Cell, ...], tuple[Cell, ...],
                                     tuple[Cell, ...],
                                     dict[int, dict[str, list[Cell]]]]:
    """Сетка: непроходимые и глухие клетки, «дневные» и владение постройками."""
    blocked: list[Cell] = []
    solid: list[Cell] = []
    bright: list[Cell] = []
    owned: dict[int, dict[str, list[Cell]]] = {}
    for row in range(GRID_ROWS):
        for col in range(GRID_COLS):
            low, high = kn2.cell(col, row)
            cell = Cell(row, col)
            if low & PASSABLE_MASK:
                blocked.append(cell)
            if low & SOLID:
                solid.append(cell)
            if high & (BRIGHT_UNIT >> 16):
                bright.append(cell)
            slot = (high & 0x1F) - 1
            if slot < 0:
                continue
            entry = owned.setdefault(slot, {"footprint": [], "floor": [], "routed": []})
            entry["footprint"].append(cell)
            if low & BUILT:
                entry["floor"].append(cell)
            if high & (ROUTED_UNIT >> 16):
                entry["routed"].append(cell)
    return tuple(blocked), tuple(solid), tuple(bright), owned


def _read_ground(kn2: KN2Map) -> list[GroundTile]:
    tiles = []
    for row, col, lower, upper, light in ground_cells(kn2, include_empty=True):
        if lower is None and upper is None:
            continue
        tiles.append(GroundTile(GroundCell(row, col), lower, upper, light))
    return tiles


def _read_frames(objects: ObjectsRes, resource_slot: int,
                 state: int) -> dict[str, Frame]:
    """Кадры сущности: геометрия и якоря, без распаковки пикселей.

    Порядок и состав — как у движка (VA 0x425AA8): кадр состояния (main),
    затем стены из hdr+0x08 и крыша из hdr+0x10, все с одним якорем. Тень —
    маска состояния со своим якорем (hdr+0xBC), она не картинка: движок
    затемняет по ней фон отдельным проходом.
    """
    states = objects.simple_frames(resource_slot)
    entry = next((item for item in states if item["state"] == state),
                 states[0] if states else None)
    if entry is None:
        return {}
    header = objects.simple_header(resource_slot) or {}
    frames: dict[str, Frame] = {}
    sources = [("main", entry["offset"], entry["dx"], entry["dy"])]
    for part in ("walls", "roof"):
        offset = int(header.get(part, -1))
        if offset > 0:
            sources.append((part, offset, entry["dx"], entry["dy"]))
    if entry.get("mask") is not None:
        sources.append(("shadow", entry["mask"], entry.get("mask_dx", 0),
                        entry.get("mask_dy", 0)))
    for part, offset, dx, dy in sources:
        size = objects.frame_size(resource_slot, offset)
        if size is None:
            continue
        frames[part] = Frame(part=part, width=size[0], height=size[1],
                             offset_x=dx, offset_y=dy)
    return frames


def _read_bounds(frames: dict[str, Frame], lighting: Lighting) -> Bounds:
    """Габариты сущности и её ключ глубины.

    Ключ считается по большей из высот main и walls (VA 0x426AFB) — крыша в
    него намеренно не входит; бит 0x08 байта hdr+0xFE понижает ключ на
    четверть высоты (VA 0x426B75): линия глубины идёт по подошве передней
    стены, поэтому юнит перед домом рисуется поверх него.
    """
    visible = [frame for name, frame in frames.items() if name != "shadow"]
    if not visible:
        return Bounds(0, 0, 0, 0, 0, 0)
    main = frames.get("main", visible[0])
    width = max(frame.width for frame in visible)
    height = max(frame.height for frame in visible)
    sort_height = max((frames[part].height for part in ("main", "walls")
                       if part in frames), default=height)
    bias = sort_height // 4 if lighting.lowers_depth_key else 0
    return Bounds(width=width, height=height,
                  offset_x=main.offset_x, offset_y=main.offset_y,
                  sort_height=sort_height, sort_bias=bias)


def _read_entity(record: dict, number: int, objects: ObjectsRes,
                 owned: dict[int, dict[str, list[Cell]]]) -> Entity | None:
    """Запись карты + заголовок ресурса -> постройка или реквизит."""
    # Пустая запись забита единичными битами целиком: поле палитры читается
    # двойным словом, поэтому «пусто» это и 0xFFFF, и 0xFFFFFFFF.
    if record.get("kind", 0xFFFF) in (0xFFFF, 0xFFFFFFFF):
        return None
    resource_slot = ObjectsRes.slot_of(record)
    if not 0 <= resource_slot < len(objects.entries):
        return None
    header = objects.simple_header(resource_slot)
    if header is None:
        return None
    # ПАЛИТРУ БЕРЁМ ИЗ СЫРЫХ БАЙТОВ. В промежуточном project/maps/*/map.json
    # поле `kind` запечено ещё старым чтением по половине слова, и там у
    # деревьев Беглого стоит 51200 вместо 116736 — палитра 100 вместо 228,
    # оттого крона и выходила выбеленной с цветным крапом. Запись целиком
    # лежит рядом в `raw`, и движок читает это поле ДВОЙНЫМ словом
    # (VA 0x43E7D8), подменяя ноль палитрой из заголовка ресурса.
    kind = int(record.get("kind", 0))
    raw = record.get("raw")
    if raw:
        try:
            kind = struct.unpack_from("<I", bytes.fromhex(raw), 4)[0]
        except (ValueError, struct.error):
            pass
    if kind in (0xFFFF, 0xFFFFFFFF):
        return None
    palette = kind // 512 or int(objects.simple_palette(resource_slot) or 0)
    record_slot = int(record["slot"])
    # Байт hdr+0xFE загрузчик кладёт в запись объекта (+0x22); бит 0x04 —
    # исходная палитра кадра main, бит 0x08 — понижение ключа глубины.
    group = int(header["group"])
    lighting = Lighting(main_static_palette=bool(group & 0x04),
                        lowers_depth_key=bool(group & 0x08))
    position = Point(int(record["pixel_x"]), int(record["pixel_y"]))
    state = int(record.get("state", 0))
    frames = _read_frames(objects, resource_slot, state)
    common = dict(
        id=f"legacy:{number}:{{kind}}:{record_slot}",
        record_slot=record_slot,
        resource_slot=resource_slot,
        palette=palette,
        state=state,
        position=position,
        bounds=_read_bounds(frames, lighting),
        frames=frames,
        lighting=lighting,
    )
    if header["walls"] == -1:
        common["id"] = common["id"].format(kind="prop")
        return Prop(**common)
    cells = owned.get(record_slot, {})
    common["id"] = common["id"].format(kind="building")
    return Building(**common, cells=BuildingCells(
        footprint=tuple(cells.get("footprint", ())),
        floor=tuple(cells.get("floor", ())),
        routed=tuple(cells.get("routed", ())),
    ))


__all__ = ["MapModel", "MapLighting", "Terrain", "Building", "Prop", "GroundTile",
           "BuildingCells", "Lighting", "Bounds", "Cell", "GroundCell", "Point",
           "PART_ORDER"]
