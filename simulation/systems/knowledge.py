# -*- coding: utf-8 -*-
"""
Память персонажа. Хранит воспринятое, а не объективную истину.

Знание может устареть: предмет унесли, пока NPC не смотрел. Именно поэтому
NPC способен ошибаться — он идёт к тому месту, которое помнит, а не к тому,
где предмет находится на самом деле.
"""
from __future__ import annotations

from ..commands import ActionKind, ObservedAction
from ..config import PerceptionConfig
from ..world_state import FactType, KnownFact, Position, WorldState
from .perception import Perception


def update(world: WorldState, actor_id: str, view: Perception,
           observed: list[ObservedAction], cfg: PerceptionConfig) -> None:
    actor = world.actors[actor_id]
    know = actor.knowledge
    tick = world.tick

    # то, что видно прямо сейчас
    for item_id in view.visible_item_ids:
        item = world.items.get(item_id)
        if item is None:
            continue
        if item.position is not None:
            know.remember(KnownFact(FactType.ITEM_AT, item_id, item.position, tick, 1.0))
            know.forget(FactType.ITEM_TAKEN_BY, item_id)
            know.forget(FactType.ITEM_ABSENT, item_id)   # нашёлся — прежний вывод неверен
        elif item.owner_id is not None:
            know.remember(KnownFact(FactType.ITEM_TAKEN_BY, item_id, item.owner_id, tick, 1.0))
            know.forget(FactType.ITEM_AT, item_id)

    for other_id in view.visible_actor_ids:
        if other_id == actor_id:
            continue
        know.remember(KnownFact(FactType.ACTOR_AT, other_id,
                                world.actors[other_id].position, tick, 1.0))

    # опровержение: помню предмет в клетке, вижу клетку, предмета там нет
    for fact in list(know.by_type(FactType.ITEM_AT)):
        pos: Position = fact.value            # type: ignore[assignment]
        if pos not in view.visible_positions:
            continue
        item = world.items.get(fact.subject_id)
        if item is None or item.position != pos:
            know.forget(FactType.ITEM_AT, fact.subject_id)
            know.remember(KnownFact(FactType.ITEM_ABSENT, fact.subject_id, pos, tick, 1.0))

    # наблюдение чужих действий уточняет знание о предметах
    for action in observed:
        if action.actor_id == actor_id or action.item_id is None:
            continue
        if action.kind is ActionKind.TAKE:
            know.remember(KnownFact(FactType.ITEM_TAKEN_BY, action.item_id,
                                    action.actor_id, tick, 1.0))
            know.forget(FactType.ITEM_AT, action.item_id)
        elif action.kind is ActionKind.DROP:
            know.remember(KnownFact(FactType.ITEM_AT, action.item_id,
                                    action.position, tick, 1.0))
            know.forget(FactType.ITEM_TAKEN_BY, action.item_id)
        elif action.kind is ActionKind.GIVE and action.target_actor_id:
            know.remember(KnownFact(FactType.ITEM_TAKEN_BY, action.item_id,
                                    action.target_actor_id, tick, 1.0))
        elif action.kind is ActionKind.EAT:
            know.forget(FactType.ITEM_AT, action.item_id)
            know.forget(FactType.ITEM_TAKEN_BY, action.item_id)

    _decay(know, tick, cfg)


def _decay(know, tick: int, cfg: PerceptionConfig) -> None:
    """Старое знание теряет уверенность и в конце концов забывается."""
    for key, fact in list(know.facts.items()):
        age = tick - fact.observed_tick
        if age <= 0:
            continue
        confidence = max(0.0, 1.0 - age / cfg.memory_ttl_ticks)
        if confidence <= 0.0:
            del know.facts[key]
        elif confidence != fact.confidence:
            know.facts[key] = KnownFact(fact.fact_type, fact.subject_id, fact.value,
                                        fact.observed_tick, confidence)
