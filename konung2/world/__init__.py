# -*- coding: utf-8 -*-
"""Доменный слой: мир «Князя 2» сущностями, а не таблицами.

    from konung2.world import MapModel

    world = MapModel.from_game(19)
    for building in world.buildings:
        print(building.id, building.bounds.width, len(building.cells.floor),
              building.interior_is_daylit)

Ниже этого слоя лежат кодеки (`konung2.kn2`, `konung2.res`, `konung2.graph`),
выше — сборщик content pack, инструменты и редактор карт. Правила поведения
(что прячет крышу, что не темнеет ночью, где проходимо) описаны на сущностях
и снабжены ссылками на код движка.
"""
from .entities import (Building, BuildingCells, Entity, Frame, GroundTile,
                       Lighting, PART_ORDER, Prop)
from .geometry import (Bounds, Cell, GroundCell, Point, cell_at_point,
                       ground_at_cell, ground_at_point)
from .model import MapLighting, MapModel, Terrain

__all__ = [
    "MapModel", "MapLighting", "Terrain",
    "Building", "BuildingCells", "Entity", "Frame", "GroundTile", "Lighting",
    "Prop", "PART_ORDER",
    "Bounds", "Cell", "GroundCell", "Point",
    "cell_at_point", "ground_at_cell", "ground_at_point",
]
