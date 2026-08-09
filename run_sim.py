# -*- coding: utf-8 -*-
"""
Запуск симуляции на настоящей карте деревни.

    python run_sim.py                 1000 тиков, сводка в конце
    python run_sim.py --ticks 200 --watch 20     показывать карту каждые 20 тиков
    python run_sim.py --synthetic     без файлов игры, на тестовой площадке
    python run_sim.py --seed 5        другой жребий

Управление игроком здесь не интерактивное: сценарий задаёт его намерения,
чтобы можно было наблюдать, как один и тот же механизм действий работает
для игрока и для жителя.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from simulation import Simulation                              # noqa: E402
from simulation.bridge import load_village, make_test_world, place_food_in_sight  # noqa: E402
from simulation.commands import TakeIntent                     # noqa: E402
from simulation.debug import LEGEND, describe_actor, render_map  # noqa: E402
from simulation.world_state import ActorState, ItemState, ItemType, Position  # noqa: E402


def build_world(synthetic: bool, seed: int):
    if synthetic:
        world = make_test_world(rows=30, cols=40, seed=seed)
        world.actors['npc_1'] = ActorState('npc_1', Position(15, 8), hunger=45.0)
        world.actors['player'] = ActorState('player', Position(15, 20), is_player=True)
        world.items['food_1'] = ItemState('food_1', ItemType.FOOD,
                                          position=Position(15, 14), nutrition=45.0)
        return world

    world = load_village(map_number=32, world_index=0, seed=seed)
    npc = next((a for a in world.actors.values() if not a.is_player), None)
    if npc is None:
        sys.exit('на карте 32 нет жителей — соберите мод с --residents 1')
    npc.hunger = 45.0
    place_food_in_sight(world, npc.actor_id)
    return world


def main() -> None:
    ap = argparse.ArgumentParser(description='Симуляция автономного жителя')
    ap.add_argument('--ticks', type=int, default=1000)
    ap.add_argument('--watch', type=int, default=0, help='печатать карту каждые N тиков')
    ap.add_argument('--synthetic', action='store_true', help='не читать файлы игры')
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--steal-at', type=int, default=-1,
                    help='на этом тике игрок забирает еду (проверка свидетельства)')
    ap.add_argument('--respawn', type=int, default=120,
                    help='подкладывать еду каждые N тиков (0 — не подкладывать)')
    a = ap.parse_args()

    world = build_world(a.synthetic, a.seed)
    sim = Simulation(world)
    npc_id = next(x.actor_id for x in world.actors.values() if not x.is_player)
    print(f'мир: {world.width}x{world.height}, житель {npc_id}, seed {a.seed}')
    print(LEGEND)

    meals = 0
    for i in range(a.ticks):
        npc_alive = sim.world.actors[npc_id].alive
        if a.respawn and npc_alive and i % a.respawn == 0 and not sim.world.items:
            try:
                place_food_in_sight(sim.world, npc_id, item_id=f'food_{meals + 2}')
                meals += 1
            except RuntimeError:
                pass                       # некуда положить — житель сам справится
        if i == a.steal_at:
            food = next((f for f in sim.world.items.values() if f.position), None)
            if food is not None:
                sim.queue_player_intent(TakeIntent('player', food.item_id))
        report = sim.step()
        if report.relation_log:
            for line in report.relation_log:
                print(f'[тик {report.tick}] {line}')
        if a.watch and i % a.watch == 0:
            npc = sim.world.actors[npc_id]
            print(f'\n--- тик {report.tick} --- голод {npc.hunger:.0f}, '
                  f'энергия {npc.energy:.0f}, намерение {npc.current_intention}')
            print(render_map(sim, npc_id, top=max(0, npc.position.row - 8),
                             left=max(0, npc.position.col - 20), rows=17, cols=52))

    print('\n' + describe_actor(sim, npc_id))
    alive = [a_.actor_id for a_ in sim.world.living_actors()]
    print(f'\nтиков: {sim.world.tick}, живы: {alive}, '
          f'предметов на карте: {len(sim.world.items)}')


if __name__ == '__main__':
    main()
