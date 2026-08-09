# -*- coding: utf-8 -*-
"""
Общий исполнитель действий для всех персонажей.

Разрешение конфликтов не смотрит на роль участника: выигрывает более ловкий,
при равенстве — детерминированный жребий от seed мира, номера тика и спорного
ресурса. Порядок обхода списка персонажей на исход не влияет.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from . import rules
from .commands import Intent, ObservedAction, RejectedIntent
from .config import SimulationConfig
from .world_state import WorldState


@dataclass
class ResolutionResult:
    applied: list[ObservedAction] = field(default_factory=list)
    rejected: list[RejectedIntent] = field(default_factory=list)


def _tiebreak(world: WorldState, resource: str, contenders: list[str]) -> str:
    """Жребий, не зависящий ни от порядка, ни от роли участников."""
    rng = random.Random(f'{world.random_seed}|{world.tick}|{resource}')
    return rng.choice(sorted(contenders))


def resolve(world: WorldState, intents: list[Intent], cfg: SimulationConfig) -> ResolutionResult:
    result = ResolutionResult()

    # 1. предусловия — на состоянии начала тика
    valid: list[Intent] = []
    for intent in intents:
        reason = rules.check(world, intent, cfg)
        if reason is None:
            valid.append(intent)
        else:
            result.rejected.append(RejectedIntent(intent, reason))

    # 2. конфликты за один и тот же ресурс
    by_resource: dict[str, list[Intent]] = {}
    for intent in valid:
        key = rules.contested_resource(intent)
        if key is not None:
            by_resource.setdefault(key, []).append(intent)

    losers: set[int] = set()
    for resource, competing in by_resource.items():
        if len(competing) < 2:
            continue
        best = max(world.actors[i.actor_id].agility for i in competing)
        top = [i for i in competing if world.actors[i.actor_id].agility == best]
        if len(top) == 1:
            winner = top[0]
        else:
            winner_id = _tiebreak(world, resource, [i.actor_id for i in top])
            winner = next(i for i in top if i.actor_id == winner_id)
        for intent in competing:
            if intent is not winner:
                losers.add(id(intent))
                result.rejected.append(RejectedIntent(intent, f'проиграл спор за {resource}'))

    # 3. применение; предусловия перепроверяются, потому что мир уже менялся
    for intent in valid:
        if id(intent) in losers:
            continue
        reason = rules.check(world, intent, cfg)
        if reason is not None:
            result.rejected.append(RejectedIntent(intent, f'условие исчезло: {reason}'))
            continue
        result.applied.append(rules.apply(world, intent, cfg))

    return result
