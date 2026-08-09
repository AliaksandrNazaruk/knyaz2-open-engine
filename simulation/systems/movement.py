# -*- coding: utf-8 -*-
"""Поиск пути по сетке (A*). Возвращает шаги, а не телепортацию."""
from __future__ import annotations

import heapq

from ..world_state import Position, WorldState

STRAIGHT, DIAGONAL = 10, 14


def _cost(a: Position, b: Position) -> int:
    return DIAGONAL if a.row != b.row and a.col != b.col else STRAIGHT


def _heuristic(a: Position, b: Position) -> int:
    dr, dc = abs(a.row - b.row), abs(a.col - b.col)
    return STRAIGHT * (dr + dc) + (DIAGONAL - 2 * STRAIGHT) * min(dr, dc)


def find_path(world: WorldState, start: Position, goal: Position,
              ignore_actors: bool = False, limit: int = 20000) -> list[Position]:
    """Путь без стартовой клетки. Пустой список — цель недостижима."""
    if start == goal:
        return []
    blocked: set[Position] = set()
    if not ignore_actors:
        blocked = {a.position for a in world.living_actors() if a.position != start}

    open_heap: list[tuple[int, int, Position]] = [(_heuristic(start, goal), 0, start)]
    came: dict[Position, Position] = {}
    best: dict[Position, int] = {start: 0}
    visited = 0

    while open_heap:
        _, g, current = heapq.heappop(open_heap)
        if current == goal:
            path = [current]
            while path[-1] != start:
                path.append(came[path[-1]])
            path.reverse()
            return path[1:]
        if g > best.get(current, 1 << 30):
            continue
        visited += 1
        if visited > limit:
            break
        for nxt in current.neighbours():
            if not world.is_passable(nxt):
                continue
            if nxt in blocked and nxt != goal:
                continue
            ng = g + _cost(current, nxt)
            if ng < best.get(nxt, 1 << 30):
                best[nxt] = ng
                came[nxt] = current
                heapq.heappush(open_heap, (ng + _heuristic(nxt, goal), ng, nxt))
    return []


def step_towards(world: WorldState, start: Position, goal: Position) -> Position | None:
    """Первая клетка пути или None, если идти некуда."""
    path = find_path(world, start, goal)
    return path[0] if path else None


def nearest_free_neighbour(world: WorldState, target: Position,
                           frm: Position) -> Position | None:
    """Ближайшая к frm проходимая клетка рядом с target."""
    options = [p for p in target.neighbours()
               if world.is_passable(p) and world.actor_at(p) is None]
    if world.is_passable(target) and world.actor_at(target) is None:
        options.append(target)
    if not options:
        return None
    return min(options, key=lambda p: (p.chebyshev(frm), p.row, p.col))
