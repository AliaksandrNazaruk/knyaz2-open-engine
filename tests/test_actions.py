# -*- coding: utf-8 -*-
"""Общий механизм действий: одни правила для игрока и NPC."""
from __future__ import annotations

import pytest

from simulation.bridge import make_test_world
from simulation.commands import EatIntent, GiveIntent, MoveIntent, TakeIntent
from simulation.config import DEFAULT_CONFIG
from simulation.action_resolver import resolve
from simulation.world_state import (ActorState, InvariantError, ItemState, ItemType,
                                    Position, check_invariants)


def world_with_two():
    world = make_test_world()
    world.actors['player'] = ActorState('player', Position(5, 5), is_player=True)
    world.actors['npc'] = ActorState('npc', Position(5, 7))
    world.items['food'] = ItemState('food', ItemType.FOOD, position=Position(5, 6))
    return world


@pytest.mark.parametrize('actor_id', ['player', 'npc'])
def test_take_works_the_same_for_everyone(actor_id: str) -> None:
    world = world_with_two()
    result = resolve(world, [TakeIntent(actor_id, 'food')], DEFAULT_CONFIG)
    assert not result.rejected
    assert world.items['food'].owner_id == actor_id
    assert world.items['food'].position is None
    check_invariants(world)


def test_take_requires_reach() -> None:
    world = world_with_two()
    world.actors['npc'].position = Position(0, 0)
    result = resolve(world, [TakeIntent('npc', 'food')], DEFAULT_CONFIG)
    assert result.rejected and 'далеко' in result.rejected[0].reason
    assert world.items['food'].position == Position(5, 6)


def test_item_is_never_in_two_places() -> None:
    world = world_with_two()
    resolve(world, [TakeIntent('player', 'food')], DEFAULT_CONFIG)
    world.items['food'].position = Position(1, 1)          # ломаем вручную
    with pytest.raises(InvariantError):
        check_invariants(world)


def test_eating_reduces_hunger_and_removes_item() -> None:
    world = world_with_two()
    world.actors['npc'].hunger = 80.0
    resolve(world, [TakeIntent('npc', 'food')], DEFAULT_CONFIG)
    resolve(world, [EatIntent('npc', 'food')], DEFAULT_CONFIG)
    assert 'food' not in world.items
    assert world.actors['npc'].hunger < 80.0


def test_give_transfers_ownership() -> None:
    world = world_with_two()
    world.actors['npc'].position = Position(5, 6)
    resolve(world, [TakeIntent('player', 'food')], DEFAULT_CONFIG)
    result = resolve(world, [GiveIntent('player', 'food', 'npc')], DEFAULT_CONFIG)
    assert not result.rejected
    assert world.items['food'].owner_id == 'npc'


def test_move_blocked_by_obstacle_and_by_actor() -> None:
    world = world_with_two()
    world.terrain[4][5] = world.terrain[4][5].__class__.OBSTACLE
    blocked = resolve(world, [MoveIntent('player', Position(4, 5))], DEFAULT_CONFIG)
    assert blocked.rejected
    world.actors['npc'].position = Position(5, 6)
    occupied = resolve(world, [MoveIntent('player', Position(5, 6))], DEFAULT_CONFIG)
    assert occupied.rejected
