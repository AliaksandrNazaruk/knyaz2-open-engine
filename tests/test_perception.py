# -*- coding: utf-8 -*-
"""Восприятие и память: NPC знает только то, что видел."""
from __future__ import annotations

from simulation.bridge import make_test_world
from simulation.config import DEFAULT_CONFIG
from simulation.simulation_loop import Simulation
from simulation.systems import perception
from simulation.world_state import (ActorState, FactType, ItemState, ItemType, Position,
                                    TerrainType)


def test_sight_is_limited_by_radius() -> None:
    world = make_test_world(rows=40, cols=40)
    world.actors['npc'] = ActorState('npc', Position(20, 20))
    world.items['far'] = ItemState('far', ItemType.FOOD, position=Position(20, 35))
    view = perception.compute(world, 'npc', DEFAULT_CONFIG.perception)
    assert 'far' not in view.visible_item_ids


def test_obstacle_blocks_sight() -> None:
    world = make_test_world(rows=20, cols=20)
    for row in range(0, 20):
        world.terrain[row][10] = TerrainType.OBSTACLE
    world.actors['npc'] = ActorState('npc', Position(10, 8))
    world.items['behind'] = ItemState('behind', ItemType.FOOD, position=Position(10, 12))
    view = perception.compute(world, 'npc', DEFAULT_CONFIG.perception)
    assert 'behind' not in view.visible_item_ids


def test_npc_does_not_target_unseen_food() -> None:
    """Еда вне поля зрения не должна стать целью: её просто нет в памяти."""
    world = make_test_world(rows=40, cols=40)
    world.actors['npc'] = ActorState('npc', Position(20, 20), hunger=70.0)
    world.items['far'] = ItemState('far', ItemType.FOOD, position=Position(20, 38))
    sim = Simulation(world)
    sim.run(3)
    npc = sim.world.actors['npc']
    assert not npc.knowledge.by_type(FactType.ITEM_AT)
    assert npc.position.chebyshev(Position(20, 38)) >= 17


def test_memory_survives_losing_sight() -> None:
    world = make_test_world(rows=30, cols=30)
    world.actors['npc'] = ActorState('npc', Position(10, 10), hunger=0.0)
    world.items['food'] = ItemState('food', ItemType.FOOD, position=Position(10, 14))
    sim = Simulation(world)
    sim.step()
    remembered = sim.world.actors['npc'].knowledge.get(FactType.ITEM_AT, 'food')
    assert remembered is not None and remembered.value == Position(10, 14)

    # уносим еду далеко, пока NPC не смотрит — знание должно остаться прежним
    sim.world.items['food'].position = Position(28, 28)
    sim.world.actors['npc'].position = Position(0, 0)
    sim.step()
    stale = sim.world.actors['npc'].knowledge.get(FactType.ITEM_AT, 'food')
    assert stale is not None and stale.value == Position(10, 14)
