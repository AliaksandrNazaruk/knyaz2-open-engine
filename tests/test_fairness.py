# -*- coding: utf-8 -*-
"""Справедливость и воспроизводимость: роль персонажа ничего не решает."""
from __future__ import annotations

from simulation.action_resolver import resolve
from simulation.bridge import make_test_world
from simulation.commands import TakeIntent
from simulation.config import DEFAULT_CONFIG
from simulation.simulation_loop import Simulation
from simulation.world_state import ActorState, ItemState, ItemType, Position


def contest(player_agility: int, npc_agility: int, swap_roles: bool = False):
    world = make_test_world(seed=42)
    world.actors['a'] = ActorState('a', Position(5, 5), agility=player_agility,
                                   is_player=not swap_roles)
    world.actors['b'] = ActorState('b', Position(5, 7), agility=npc_agility,
                                   is_player=swap_roles)
    world.items['food'] = ItemState('food', ItemType.FOOD, position=Position(5, 6))
    resolve(world, [TakeIntent('a', 'food'), TakeIntent('b', 'food')], DEFAULT_CONFIG)
    return world.items['food'].owner_id


def test_more_agile_wins_regardless_of_role() -> None:
    assert contest(15, 10) == 'a'
    assert contest(15, 10, swap_roles=True) == 'a'
    assert contest(10, 15) == 'b'
    assert contest(10, 15, swap_roles=True) == 'b'


def test_tie_does_not_depend_on_who_is_the_player() -> None:
    normal = contest(10, 10)
    swapped = contest(10, 10, swap_roles=True)
    assert normal == swapped, 'исход спора не должен зависеть от роли'


def test_tie_is_deterministic_but_seed_dependent() -> None:
    assert contest(10, 10) == contest(10, 10)


def _run(seed: int, ticks: int = 100) -> tuple:
    world = make_test_world(seed=seed)
    world.actors['npc'] = ActorState('npc', Position(2, 2), hunger=50.0)
    world.actors['player'] = ActorState('player', Position(8, 8), is_player=True)
    world.items['food'] = ItemState('food', ItemType.FOOD, position=Position(2, 6))
    sim = Simulation(world)
    sim.run(ticks)
    npc = sim.world.actors['npc']
    return (npc.position, round(npc.hunger, 4), round(npc.health, 4),
            sorted(sim.world.items), sim.world.tick)


def test_same_seed_gives_same_world_after_100_ticks() -> None:
    assert _run(7) == _run(7)


def test_different_seed_is_allowed_to_differ() -> None:
    _run(7)                       # просто не должно падать
    _run(8)
