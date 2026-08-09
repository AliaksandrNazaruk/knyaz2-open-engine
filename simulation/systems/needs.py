# -*- coding: utf-8 -*-
"""Слой тела: голод, энергия, истощение, смерть."""
from __future__ import annotations

from ..config import NeedsConfig
from ..world_state import WorldState


def update(world: WorldState, cfg: NeedsConfig) -> list[str]:
    """Обновить тела всех живых. Возвращает список умерших на этом тике."""
    died: list[str] = []
    for actor in list(world.actors.values()):
        if not actor.alive:
            continue
        actor.hunger = min(cfg.max_value, actor.hunger + cfg.hunger_per_tick)
        actor.energy = max(0.0, actor.energy - cfg.energy_loss_per_tick)

        if actor.hunger >= cfg.starvation_threshold:
            actor.health = max(0.0, actor.health - cfg.starvation_damage)
        if actor.energy <= cfg.exhaustion_threshold:
            actor.health = max(0.0, actor.health - cfg.exhaustion_damage)

        if actor.health <= 0.0:
            actor.alive = False
            actor.current_intention = None
            died.append(actor.actor_id)
            # то, что нёс, падает на землю — предмет не должен исчезнуть
            for item in world.carried_by(actor.actor_id):
                item.owner_id = None
                item.position = actor.position
    return died
