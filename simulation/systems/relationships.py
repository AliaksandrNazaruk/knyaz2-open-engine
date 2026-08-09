# -*- coding: utf-8 -*-
"""
Отношения меняются только от того, что персонаж сам наблюдал.

Правила универсальны: нет ни одного условия вида «если это игрок» или
«если сюжет дошёл до такой-то стадии». Взял еду на глазах у голодного —
доверие упало, независимо от того, кто взял.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..commands import ActionKind, ObservedAction, SpeechActType
from ..config import RelationshipConfig, SimulationConfig
from ..world_state import ItemType, WorldState


@dataclass(frozen=True)
class RelationChange:
    observer_id: str
    subject_id: str
    trust: int = 0
    fear: int = 0
    hostility: int = 0
    reason: str = ''


def _clamp(value: int, cfg: RelationshipConfig) -> int:
    return max(cfg.min_value, min(cfg.max_value, value))


def evaluate(world: WorldState, observer_id: str,
             observed: list[ObservedAction], cfg: SimulationConfig) -> list[RelationChange]:
    """Что наблюдение меняет в отношении наблюдателя к действующему лицу."""
    rc = cfg.relationships
    observer = world.actors.get(observer_id)
    changes: list[RelationChange] = []
    if observer is None or not observer.alive:
        return changes

    hungry = observer.hunger >= cfg.decision.hunger_search_threshold
    for action in observed:
        if action.actor_id == observer_id:
            continue
        subject = action.actor_id

        if action.kind is ActionKind.TAKE and action.item_id:
            item = world.items.get(action.item_id)
            if item is None or item.item_type is not ItemType.FOOD:
                continue
            weight = rc.hungry_multiplier if hungry else 1.0
            changes.append(RelationChange(
                observer_id, subject,
                trust=int(rc.take_seen_trust * weight),
                hostility=int(rc.take_seen_hostility * weight),
                reason=f'на глазах забрал {action.item_id}'
                       + (' при том, что наблюдатель голоден' if hungry else '')))

        elif action.kind is ActionKind.GIVE and action.target_actor_id == observer_id:
            changes.append(RelationChange(
                observer_id, subject, trust=rc.give_trust, hostility=rc.give_hostility,
                reason=f'передал {action.item_id}'))

        elif action.kind is ActionKind.SPEAK and action.target_actor_id == observer_id:
            if action.speech_kind is SpeechActType.THREATEN:
                changes.append(RelationChange(observer_id, subject, fear=rc.threat_fear,
                                              hostility=rc.take_seen_hostility,
                                              reason='угрожал'))
            elif action.speech_kind is SpeechActType.GREETING:
                changes.append(RelationChange(observer_id, subject, trust=1,
                                              reason='поздоровался'))
    return changes


def apply(world: WorldState, changes: list[RelationChange],
          cfg: SimulationConfig) -> list[str]:
    rc = cfg.relationships
    log: list[str] = []
    for ch in changes:
        observer = world.actors.get(ch.observer_id)
        if observer is None:
            continue
        rel = observer.relation_to(ch.subject_id)
        rel.trust = _clamp(rel.trust + ch.trust, rc)
        rel.fear = _clamp(rel.fear + ch.fear, rc)
        rel.hostility = _clamp(rel.hostility + ch.hostility, rc)
        log.append(f'{ch.observer_id} об {ch.subject_id}: '
                   f'доверие {ch.trust:+d}, страх {ch.fear:+d}, враждебность {ch.hostility:+d} '
                   f'— {ch.reason}')
    return log
