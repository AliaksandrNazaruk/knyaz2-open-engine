# -*- coding: utf-8 -*-
"""
Восприятие: единственный канал, по которому персонаж узнаёт о мире.

Полное состояние мира читает только эта система. Всё, что получает система
решений, проходит через ``Perception`` и личную память.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..commands import ObservedAction
from ..config import PerceptionConfig
from ..world_state import Position, WorldState


@dataclass
class Perception:
    visible_positions: set[Position] = field(default_factory=set)
    visible_actor_ids: set[str] = field(default_factory=set)
    visible_item_ids: set[str] = field(default_factory=set)
    observed_actions: list[ObservedAction] = field(default_factory=list)


def _line_of_sight(world: WorldState, a: Position, b: Position) -> bool:
    """Брезенхэм по клеткам: препятствие на пути закрывает обзор."""
    r0, c0, r1, c1 = a.row, a.col, b.row, b.col
    dr, dc = abs(r1 - r0), abs(c1 - c0)
    sr = 1 if r0 < r1 else -1
    sc = 1 if c0 < c1 else -1
    err = dr - dc
    while (r0, c0) != (r1, c1):
        e2 = 2 * err
        if e2 > -dc:
            err -= dc
            r0 += sr
        if e2 < dr:
            err += dr
            c0 += sc
        if (r0, c0) == (r1, c1):
            break
        if world.blocks_sight(Position(r0, c0)):
            return False
    return True


def compute(world: WorldState, actor_id: str, cfg: PerceptionConfig) -> Perception:
    actor = world.actors[actor_id]
    view = Perception()
    if not actor.alive:
        return view

    radius = cfg.sight_radius
    for dr in range(-radius, radius + 1):
        for dc in range(-radius, radius + 1):
            pos = Position(actor.position.row + dr, actor.position.col + dc)
            if actor.position.chebyshev(pos) > radius:
                continue
            if world.terrain_at(pos).name == 'VOID':
                continue
            if _line_of_sight(world, actor.position, pos):
                view.visible_positions.add(pos)

    for other in world.actors.values():
        if other.alive and other.position in view.visible_positions:
            view.visible_actor_ids.add(other.actor_id)
    for item in world.items.values():
        if item.position is not None and item.position in view.visible_positions:
            view.visible_item_ids.add(item.item_id)
        elif item.owner_id is not None and item.owner_id in view.visible_actor_ids:
            view.visible_item_ids.add(item.item_id)
    return view


def filter_actions(view: Perception, actions: list[ObservedAction]) -> list[ObservedAction]:
    """Оставить только те действия, которые попали в поле зрения."""
    return [a for a in actions if a.position in view.visible_positions]
