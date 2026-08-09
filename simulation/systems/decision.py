# -*- coding: utf-8 -*-
"""
Выбор действия NPC: оценка вариантов, а не маршрут и не конечный автомат.

Система получает только восприятие и личную память персонажа. Полное
состояние мира ей недоступно — карту читает лишь система движения, и только
для клеток, куда персонаж и так собрался идти.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from ..commands import (EatIntent, Intent, MoveIntent, RestIntent, SpeakIntent,
                        SpeechActType, TakeIntent, WaitIntent)
from ..config import SimulationConfig
from ..world_state import ActorState, FactType, ItemType, Position, WorldState
from . import movement
from .perception import Perception


@dataclass
class Option:
    name: str
    score: float
    intent: Intent
    why: str = ''


@dataclass
class Decision:
    chosen: Option | None
    options: list[Option] = field(default_factory=list)

    def explain(self) -> str:
        rows = [f'выбрано: {self.chosen.name} ({self.chosen.score:.1f}) — {self.chosen.why}'
                if self.chosen else 'выбрано: ничего']
        for opt in sorted(self.options, key=lambda o: -o.score):
            if self.chosen is None or opt is not self.chosen:
                rows.append(f'  {opt.name}: {opt.score:.1f} — {opt.why}')
        return '\n'.join(rows)


def _carried_food(world: WorldState, actor: ActorState):
    return [i for i in world.carried_by(actor.actor_id) if i.item_type is ItemType.FOOD]


def _remembered_food(actor: ActorState) -> list[tuple[str, Position, float]]:
    out = []
    for fact in actor.knowledge.by_type(FactType.ITEM_AT):
        pos = fact.value
        if isinstance(pos, Position):
            out.append((fact.subject_id, pos, fact.confidence))
    return out


def _threat(actor: ActorState, view: Perception, cfg: SimulationConfig) -> str | None:
    """Кого персонаж сейчас видит и при этом боится или считает враждебным."""
    rel_cfg = cfg.relationships
    worst, worst_score = None, 0
    for other_id in view.visible_actor_ids:
        if other_id == actor.actor_id:
            continue
        rel = actor.relationships.get(other_id)
        if rel is None:
            continue
        score = max(rel.fear, rel.hostility)
        if score >= rel_cfg.fear_threshold and score > worst_score:
            worst, worst_score = other_id, score
    return worst


def decide(world: WorldState, actor_id: str, view: Perception,
           cfg: SimulationConfig) -> Decision:
    actor = world.actors[actor_id]
    if not actor.alive:
        return Decision(None)

    d = cfg.decision
    options: list[Option] = []

    # съесть то, что в руках
    food = _carried_food(world, actor)
    if food:
        options.append(Option('поесть', actor.hunger * 2.0,
                              EatIntent(actor_id, food[0].item_id),
                              f'голод {actor.hunger:.0f}, еда в руках'))

    # взять еду рядом
    for item_id in sorted(view.visible_item_ids):
        item = world.items.get(item_id)
        if item is None or item.position is None or item.item_type is not ItemType.FOOD:
            continue
        if actor.position.chebyshev(item.position) <= cfg.reach:
            options.append(Option('взять еду', actor.hunger + 20.0,
                                  TakeIntent(actor_id, item_id),
                                  f'еда в соседней клетке {item.position}'))
            break

    # пойти к еде, которую помню
    if actor.hunger >= d.hunger_search_threshold:
        for item_id, pos, confidence in sorted(_remembered_food(actor)):
            spot = movement.nearest_free_neighbour(world, pos, actor.position)
            if spot is None:
                continue
            step = movement.step_towards(world, actor.position, spot)
            if step is None:
                continue
            distance = actor.position.chebyshev(pos)
            score = actor.hunger + 10.0 * confidence - distance * 0.5
            options.append(Option('идти к еде', score, MoveIntent(actor_id, step),
                                  f'помню еду {item_id} в {pos}, уверенность {confidence:.2f}, '
                                  f'до неё {distance} клеток'))
            break

    # отойти от того, кого боится
    threat_id = _threat(actor, view, cfg)
    if threat_id is not None:
        threat_pos = world.actors[threat_id].position
        distance = actor.position.chebyshev(threat_pos)
        if distance <= d.fear_avoid_distance:
            away = max(
                (p for p in actor.position.neighbours()
                 if world.is_passable(p) and world.actor_at(p) is None),
                key=lambda p: (p.chebyshev(threat_pos), p.row, p.col), default=None)
            if away is not None:
                rel = actor.relation_to(threat_id)
                options.append(Option('отойти', 40.0 + max(rel.fear, rel.hostility) * 0.5,
                                      MoveIntent(actor_id, away),
                                      f'{threat_id} рядом ({distance}), '
                                      f'страх {rel.fear}, враждебность {rel.hostility}'))

    # попросить еду у того, у кого она есть
    if actor.hunger >= d.hunger_search_threshold and not food:
        for fact in actor.knowledge.by_type(FactType.ITEM_TAKEN_BY):
            holder = fact.value
            if not isinstance(holder, str) or holder == actor_id:
                continue
            if holder not in view.visible_actor_ids:
                continue
            rel = actor.relation_to(holder)
            if rel.hostility >= cfg.relationships.hostile_threshold:
                continue
            options.append(Option('попросить еду', actor.hunger * 0.8 + rel.trust * 0.2,
                                  SpeakIntent(actor_id, holder, SpeechActType.REQUEST_ITEM,
                                              fact.subject_id),
                                  f'у {holder} есть {fact.subject_id}, доверие {rel.trust}'))
            break

    # отдохнуть
    if actor.energy <= d.rest_energy_threshold:
        options.append(Option('отдохнуть', (d.rest_energy_threshold - actor.energy) * 2.0,
                              RestIntent(actor_id), f'энергия {actor.energy:.0f}'))

    options.append(Option('ждать', 1.0, WaitIntent(actor_id), 'ничего не требуется'))

    best = max(o.score for o in options)
    top = [o for o in options if best - o.score <= d.tie_epsilon]
    if len(top) == 1:
        chosen = top[0]
    else:
        rng = random.Random(f'{world.random_seed}|{world.tick}|{actor_id}')
        chosen = rng.choice(sorted(top, key=lambda o: o.name))
    return Decision(chosen, options)
