# -*- coding: utf-8 -*-
"""
Инструменты разработчика: объяснение решений и текстовый вид карты.

Всё здесь — только для наблюдателя. Персонаж этими данными не пользуется:
он видит лишь то, что дала система восприятия, и помнит лишь то, что запомнил.
"""
from __future__ import annotations

from .simulation_loop import Simulation
from .systems.perception import Perception
from .world_state import FactType, Position, TerrainType


def describe_actor(sim: Simulation, actor_id: str) -> str:
    world = sim.world
    actor = world.actors[actor_id]
    view: Perception = sim.perception_of(actor_id)
    lines = [
        f'=== {actor_id} (тик {world.tick}) ===',
        f'позиция {actor.position}, жив: {actor.alive}',
        f'здоровье {actor.health:.0f}, голод {actor.hunger:.0f}, энергия {actor.energy:.0f}',
        f'намерение: {actor.current_intention}',
        f'видит персонажей: {sorted(view.visible_actor_ids - {actor_id}) or "никого"}',
        f'видит предметов: {sorted(view.visible_item_ids) or "нет"}',
        f'несёт: {[i.item_id for i in world.carried_by(actor_id)] or "ничего"}',
    ]

    known = []
    for fact in actor.knowledge.facts.values():
        known.append(f'{fact.fact_type.name} {fact.subject_id} = {fact.value} '
                     f'(тик {fact.observed_tick}, уверенность {fact.confidence:.2f})')
    lines.append('знает: ' + ('; '.join(sorted(known)) if known else 'ничего'))

    for other_id, rel in sorted(actor.relationships.items()):
        lines.append(f'отношение к {other_id}: доверие {rel.trust}, '
                     f'страх {rel.fear}, враждебность {rel.hostility}')

    report = sim.last_report
    if report and actor_id in report.decisions:
        lines.append('оценка вариантов:')
        lines.append(report.decisions[actor_id].explain())
    return '\n'.join(lines)


def render_map(sim: Simulation, actor_id: str | None = None,
               top: int = 0, left: int = 0, rows: int = 24, cols: int = 60) -> str:
    """Текстовая карта. Радиус зрения показывается только как подсказка автору."""
    world = sim.world
    view = sim.perception_of(actor_id) if actor_id else None
    known_food: set[Position] = set()
    if actor_id:
        actor = world.actors[actor_id]
        for fact in actor.knowledge.by_type(FactType.ITEM_AT):
            if isinstance(fact.value, Position):
                known_food.add(fact.value)

    out = []
    for row in range(top, min(top + rows, world.height)):
        line = ''
        for col in range(left, min(left + cols, world.width)):
            pos = Position(row, col)
            actor = world.actor_at(pos)
            items = world.items_at(pos)
            if actor is not None:
                line += '@' if actor.is_player else 'N'
            elif items:
                line += '*'
            elif pos in known_food:
                line += '?'
            elif world.terrain_at(pos) is TerrainType.OBSTACLE:
                line += '#'
            elif view is not None and pos in view.visible_positions:
                line += '.'
            else:
                line += ' '
        out.append(line)
    return '\n'.join(out)


LEGEND = '@ игрок   N житель   * предмет   ? помнит еду   # препятствие   . в поле зрения'
