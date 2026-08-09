# -*- coding: utf-8 -*-
"""
Правила действий: предусловия и последствия.

Правила ничего не знают о том, кто именно действует — игрок или NPC.
Проверка вида ``if actor.is_player`` здесь запрещена.
"""
from __future__ import annotations

from .commands import (ActionKind, DropIntent, EatIntent, GiveIntent, Intent, MoveIntent,
                       ObservedAction, RestIntent, SpeakIntent, TakeIntent, WaitIntent)
from .config import SimulationConfig
from .world_state import ItemType, Position, WorldState


def _actor_ok(world: WorldState, actor_id: str) -> str | None:
    actor = world.actors.get(actor_id)
    if actor is None:
        return 'персонажа не существует'
    if not actor.alive:
        return 'персонаж мёртв'
    return None


def check(world: WorldState, intent: Intent, cfg: SimulationConfig) -> str | None:
    """Вернуть причину отказа или None, если действие допустимо."""
    problem = _actor_ok(world, intent.actor_id)
    if problem:
        return problem
    actor = world.actors[intent.actor_id]

    if isinstance(intent, MoveIntent):
        target: Position = intent.target            # type: ignore[assignment]
        if actor.position.chebyshev(target) != 1:
            return 'шаг только в соседнюю клетку'
        if not world.is_passable(target):
            return 'клетка непроходима'
        occupant = world.actor_at(target)
        if occupant is not None and occupant.actor_id != actor.actor_id:
            return 'клетка занята'
        return None

    if isinstance(intent, (TakeIntent, EatIntent, DropIntent, GiveIntent)):
        item = world.items.get(getattr(intent, 'item_id'))
        if item is None:
            return 'предмета не существует'

        if isinstance(intent, TakeIntent):
            if item.owner_id == actor.actor_id:
                return 'предмет уже у персонажа'
            if item.owner_id is not None:
                return 'предмет у другого персонажа'
            if item.position is None or actor.position.chebyshev(item.position) > cfg.reach:
                return 'предмет слишком далеко'
            return None

        if isinstance(intent, DropIntent):
            if item.owner_id != actor.actor_id:
                return 'предмет не у персонажа'
            return None

        if isinstance(intent, EatIntent):
            if item.item_type is not ItemType.FOOD:
                return 'предмет несъедобен'
            if item.owner_id != actor.actor_id:
                return 'предмет не в руках'
            return None

        if isinstance(intent, GiveIntent):
            if item.owner_id != actor.actor_id:
                return 'предмет не у персонажа'
            other = world.actors.get(intent.target_actor_id)
            if other is None or not other.alive:
                return 'получателя нет'
            if actor.position.chebyshev(other.position) > cfg.reach:
                return 'получатель слишком далеко'
            return None

    if isinstance(intent, SpeakIntent):
        other = world.actors.get(intent.listener_id)
        if other is None or not other.alive:
            return 'собеседника нет'
        if actor.position.chebyshev(other.position) > cfg.perception.sight_radius:
            return 'собеседник слишком далеко'
        return None

    if isinstance(intent, (RestIntent, WaitIntent)):
        return None

    return 'неизвестное намерение'


def apply(world: WorldState, intent: Intent, cfg: SimulationConfig) -> ObservedAction:
    """Изменить мир и вернуть то, что мог бы увидеть свидетель."""
    actor = world.actors[intent.actor_id]

    if isinstance(intent, MoveIntent):
        actor.position = intent.target            # type: ignore[assignment]
        return ObservedAction(actor.actor_id, ActionKind.MOVE, actor.position)

    if isinstance(intent, TakeIntent):
        item = world.items[intent.item_id]
        where = item.position
        item.position = None
        item.owner_id = actor.actor_id
        return ObservedAction(actor.actor_id, ActionKind.TAKE, where, item_id=item.item_id)

    if isinstance(intent, DropIntent):
        item = world.items[intent.item_id]
        item.owner_id = None
        item.position = actor.position
        return ObservedAction(actor.actor_id, ActionKind.DROP, actor.position,
                              item_id=item.item_id)

    if isinstance(intent, EatIntent):
        item = world.items.pop(intent.item_id)
        needs = cfg.needs
        actor.hunger = max(0.0, actor.hunger - item.nutrition)
        actor.energy = min(needs.max_value, actor.energy + item.nutrition * 0.25)
        return ObservedAction(actor.actor_id, ActionKind.EAT, actor.position,
                              item_id=item.item_id)

    if isinstance(intent, GiveIntent):
        item = world.items[intent.item_id]
        item.owner_id = intent.target_actor_id
        item.position = None
        return ObservedAction(actor.actor_id, ActionKind.GIVE, actor.position,
                              item_id=item.item_id,
                              target_actor_id=intent.target_actor_id)

    if isinstance(intent, RestIntent):
        needs = cfg.needs
        actor.energy = min(needs.max_value, actor.energy + needs.energy_regain_when_resting)
        return ObservedAction(actor.actor_id, ActionKind.REST, actor.position)

    if isinstance(intent, SpeakIntent):
        return ObservedAction(actor.actor_id, ActionKind.SPEAK, actor.position,
                              item_id=intent.subject_id,
                              target_actor_id=intent.listener_id,
                              speech_kind=intent.kind)

    return ObservedAction(actor.actor_id, ActionKind.WAIT, actor.position)


def contested_resource(intent: Intent) -> str | None:
    """Ключ ресурса, за который спорят: клетка или предмет."""
    if isinstance(intent, MoveIntent):
        return f'cell:{intent.target}'
    if isinstance(intent, (TakeIntent, EatIntent)):
        return f'item:{getattr(intent, "item_id")}'
    return None
