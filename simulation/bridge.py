# -*- coding: utf-8 -*-
"""
Мост к файлам игры: карта деревни и её обитатели становятся миром симуляции.

Проходимость. У клетки сетки .KN2 два слова. Младшее — ссылка на тайл или
объект, и по нему проходимость не читается: такие клетки составляют 39 % и
образуют шум, сквозь который не пройти и не посмотреть. Занятость даёт
**старшее слово**: ненулевые ``hi`` складываются в аккуратные ромбовидные
контуры — изометрические подошвы изб и частокола, всего около 7 % клеток.
Отсюда правило: клетка непроходима, если ``hi != 0``.

Проверено на Черном Бору: контуры совпадают с постройками, которые видно на
скриншотах игры. Вся зависимость собрана в ``passable_from_cell``.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from konung2.gamefile import GameWorld, T_UNITS            # noqa: E402
from konung2.kn2 import KN2Map                 # noqa: E402
from konung2.paths import BUILD_DIR, game_file             # noqa: E402

from .world_state import (ActorState, ItemState, ItemType, Position,  # noqa: E402
                          TerrainType, WorldState)

def passable_from_cell(lo: int, hi: int) -> bool:
    """Занятость клетки определяет старшее слово, а не ссылка на тайл."""
    return hi == 0


def terrain_from_map(kn2: KN2Map, rows: int, cols: int) -> list[list[TerrainType]]:
    grid: list[list[TerrainType]] = []
    for row in range(rows):
        line: list[TerrainType] = []
        for col in range(cols):
            lo, hi = kn2.cell(col, row)
            line.append(TerrainType.GROUND if passable_from_cell(lo, hi)
                        else TerrainType.OBSTACLE)
        grid.append(line)
    return grid


def _load_map(map_number: int) -> KN2Map:
    """Собранный мод приоритетнее: жители новой деревни есть только в нём."""
    built = Path(BUILD_DIR) / f'{map_number}.KN2'
    if built.exists():
        return KN2Map.from_file(str(built), map_number)
    return KN2Map.from_game(map_number)


def _load_world(index: int) -> GameWorld:
    built = Path(BUILD_DIR) / f'GAME.{index}'
    path = built if built.exists() else Path(game_file(f'GAME.{index}'))
    with open(path, 'rb') as f:
        return GameWorld(index, f.read())


def load_village(map_number: int = 32, world_index: int = 0, seed: int = 1,
                 rows: int = 190, cols: int = 80,
                 player_id: str = 'player') -> WorldState:
    """Собрать мир симуляции из карты и стартового состояния игры."""
    kn2 = _load_map(map_number)
    world = WorldState(tick=0, width=cols, height=rows,
                       terrain=terrain_from_map(kn2, rows, cols), random_seed=seed)

    game = _load_world(world_index)
    units = {r['slot']: r for r in T_UNITS.unpack(game.data)['records']}

    npc_positions: list[Position] = []
    for party in game.parties_on_map(map_number):
        for slot in game.party_units(party):
            rec = units.get(slot)
            if rec is None:
                continue
            pos = Position(int(rec.get('y', 0)), int(rec.get('x', 0)))
            if not world.is_passable(pos):
                pos = _nearest_ground(world, pos)
            npc_positions.append(pos)
            world.actors[f'npc_{slot}'] = ActorState(
                actor_id=f'npc_{slot}', position=pos,
                health=float(rec.get('hp', 1600)) / 16.0,
                hunger=0.0, energy=100.0,
                strength=10, agility=10)

    start = npc_positions[0] if npc_positions else Position(rows // 2, cols // 2)
    world.actors[player_id] = ActorState(
        actor_id=player_id,
        position=_nearest_ground(world, Position(start.row - 4, start.col)),
        is_player=True, strength=12, agility=12)
    return world


def _nearest_ground(world: WorldState, pos: Position) -> Position:
    if world.is_passable(pos) and world.actor_at(pos) is None:
        return pos
    for radius in range(1, 25):
        for dr in range(-radius, radius + 1):
            for dc in range(-radius, radius + 1):
                if max(abs(dr), abs(dc)) != radius:
                    continue
                cand = Position(pos.row + dr, pos.col + dc)
                if world.is_passable(cand) and world.actor_at(cand) is None:
                    return cand
    raise RuntimeError(f'рядом с {pos} нет свободной проходимой клетки')


def place_food(world: WorldState, near: Position, item_id: str = 'food_1',
               nutrition: float = 45.0) -> ItemState:
    spot = _nearest_ground(world, near)
    item = ItemState(item_id=item_id, item_type=ItemType.FOOD,
                     position=spot, nutrition=nutrition)
    world.items[item_id] = item
    return item


def place_food_in_sight(world: WorldState, actor_id: str, item_id: str = 'food_1',
                        nutrition: float = 45.0, min_distance: int = 3,
                        max_distance: int = 8) -> ItemState:
    """Положить еду туда, откуда персонаж её действительно увидит.

    За избой еда невидима, и житель о ней не узнает — это правильное
    поведение модели, но негодная постановка опыта.
    """
    from .config import DEFAULT_CONFIG
    from .systems.perception import compute

    view = compute(world, actor_id, DEFAULT_CONFIG.perception)
    origin = world.actors[actor_id].position
    candidates = [p for p in view.visible_positions
                  if world.is_passable(p) and world.actor_at(p) is None
                  and min_distance <= origin.chebyshev(p) <= max_distance]
    if not candidates:
        raise RuntimeError(f'{actor_id} не видит ни одной подходящей клетки для еды')
    spot = max(candidates, key=lambda p: (origin.chebyshev(p), -p.row, -p.col))
    item = ItemState(item_id=item_id, item_type=ItemType.FOOD,
                     position=spot, nutrition=nutrition)
    world.items[item_id] = item
    return item


def make_test_world(rows: int = 12, cols: int = 12, seed: int = 1,
                    walls: list[Position] | None = None) -> WorldState:
    """Маленький синтетический мир для тестов, без файлов игры."""
    terrain = [[TerrainType.GROUND] * cols for _ in range(rows)]
    for wall in walls or []:
        terrain[wall.row][wall.col] = TerrainType.OBSTACLE
    return WorldState(tick=0, width=cols, height=rows, terrain=terrain, random_seed=seed)
