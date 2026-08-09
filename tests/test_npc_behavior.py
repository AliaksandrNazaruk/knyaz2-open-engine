# -*- coding: utf-8 -*-
"""Автономность, ошибка из-за устаревшей памяти и реакция на свидетельство."""
from __future__ import annotations

from simulation.bridge import make_test_world
from simulation.commands import TakeIntent
from simulation.simulation_loop import Simulation
from simulation.world_state import (ActorState, FactType, ItemState, ItemType, Position)


def test_npc_feeds_itself_without_player() -> None:
    """Голод -> заметил еду -> дошёл -> взял -> съел -> голод упал."""
    world = make_test_world(rows=20, cols=20)
    world.actors['npc'] = ActorState('npc', Position(10, 10), hunger=60.0)
    world.items['food'] = ItemState('food', ItemType.FOOD,
                                    position=Position(10, 16), nutrition=40.0)
    sim = Simulation(world)
    start_hunger = world.actors['npc'].hunger
    sim.run(40)
    npc = sim.world.actors['npc']
    assert 'food' not in sim.world.items, 'еда должна быть съедена'
    assert npc.hunger < start_hunger
    assert npc.alive


def test_npc_walks_to_remembered_place_and_fixes_memory() -> None:
    """Еду унесли незаметно: NPC идёт к старому месту и исправляет память."""
    world = make_test_world(rows=40, cols=40)
    world.actors['npc'] = ActorState('npc', Position(10, 4), hunger=55.0)
    world.items['food'] = ItemState('food', ItemType.FOOD, position=Position(10, 10))
    sim = Simulation(world)
    sim.step()
    assert sim.world.actors['npc'].knowledge.get(FactType.ITEM_AT, 'food') is not None

    # уносим далеко за радиус зрения, иначе NPC честно заметит еду на новом месте
    sim.world.items['food'].position = Position(38, 38)
    for _ in range(30):
        sim.step()
        if sim.world.actors['npc'].knowledge.get(FactType.ITEM_ABSENT, 'food'):
            break
    npc = sim.world.actors['npc']
    assert npc.knowledge.get(FactType.ITEM_AT, 'food') is None, 'старое знание должно исчезнуть'
    assert npc.knowledge.get(FactType.ITEM_ABSENT, 'food') is not None


def _witness_world(distance: int):
    world = make_test_world(rows=40, cols=40)
    world.actors['npc'] = ActorState('npc', Position(10, 10), hunger=60.0)
    world.actors['player'] = ActorState('player', Position(10, 10 + distance),
                                        is_player=True)
    world.items['food'] = ItemState('food', ItemType.FOOD,
                                    position=Position(10, 10 + distance + 1))
    return world


def test_trust_drops_when_player_takes_food_in_sight() -> None:
    sim = Simulation(_witness_world(3))
    sim.step()                                    # NPC осмотрелся
    sim.queue_player_intent(TakeIntent('player', 'food'))
    sim.step()
    rel = sim.world.actors['npc'].relation_to('player')
    assert rel.trust < 0, 'на глазах забрал еду у голодного — доверие должно упасть'
    assert rel.hostility > 0


def test_no_witness_means_no_relation_change() -> None:
    sim = Simulation(_witness_world(25))          # игрок далеко за радиусом зрения
    sim.step()
    sim.queue_player_intent(TakeIntent('player', 'food'))
    sim.step()
    rel = sim.world.actors['npc'].relation_to('player')
    assert (rel.trust, rel.fear, rel.hostility) == (0, 0, 0)


def test_hostile_npc_keeps_distance() -> None:
    world = make_test_world(rows=20, cols=20)
    world.actors['npc'] = ActorState('npc', Position(10, 10), hunger=0.0)
    world.actors['player'] = ActorState('player', Position(10, 12), is_player=True)
    npc = world.actors['npc']
    npc.relation_to('player').fear = 80
    sim = Simulation(world)
    before = npc.position.chebyshev(world.actors['player'].position)
    sim.run(4)
    after = sim.world.actors['npc'].position.chebyshev(sim.world.actors['player'].position)
    assert after > before, 'испуганный житель должен отойти'
