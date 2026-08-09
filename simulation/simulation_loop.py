# -*- coding: utf-8 -*-
"""
Такт симуляции: сначала все читают состояние начала тика, потом всё применяется.

Ни один персонаж не получает преимущества от порядка обхода списка: решения
принимаются по снимку, а споры за клетку или предмет разрешаются отдельно.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .action_resolver import ResolutionResult, resolve
from .commands import Intent, ObservedAction
from .config import DEFAULT_CONFIG, SimulationConfig
from .systems import decision, knowledge, needs, perception, relationships
from .world_state import WorldState, check_invariants


@dataclass
class TickReport:
    """Что произошло за тик — только для отладки, логика это не читает."""
    tick: int
    applied: list[ObservedAction] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    decisions: dict[str, decision.Decision] = field(default_factory=dict)
    relation_log: list[str] = field(default_factory=list)
    died: list[str] = field(default_factory=list)


class Simulation:
    """Мир и его правила. Игрок задаёт намерение снаружи, NPC — сам."""

    def __init__(self, world: WorldState, cfg: SimulationConfig = DEFAULT_CONFIG,
                 check: bool = True) -> None:
        self.world = world
        self.cfg = cfg
        self.check = check
        self.paused = False
        self.pending_player_intents: dict[str, Intent] = {}
        self.last_report: TickReport | None = None
        self._perception: dict[str, perception.Perception] = {}

    # --- ввод игрока ----------------------------------------------------
    def queue_player_intent(self, intent: Intent) -> None:
        """Обработчик клавиатуры не меняет мир — он только ставит намерение."""
        self.pending_player_intents[intent.actor_id] = intent

    def perception_of(self, actor_id: str) -> perception.Perception:
        return self._perception.get(actor_id, perception.Perception())

    # --- один такт ------------------------------------------------------
    def step(self) -> TickReport:
        world = self.world
        report = TickReport(tick=world.tick)

        # 1-2. тело
        report.died = needs.update(world, self.cfg.needs)

        # 3. снимок: всё, что дальше читают системы, берётся отсюда
        snapshot = world.snapshot()

        # 4. восприятие и память
        self._perception = {}
        for actor in list(snapshot.living_actors()):
            view = perception.compute(snapshot, actor.actor_id, self.cfg.perception)
            self._perception[actor.actor_id] = view
            knowledge.update(world, actor.actor_id, view, [], self.cfg.perception)

        # 5-7. намерения: у игрока — от управления, у NPC — от оценки вариантов
        intents: list[Intent] = []
        for actor in list(snapshot.living_actors()):
            if actor.is_player:
                intent = self.pending_player_intents.pop(actor.actor_id, None)
                if intent is not None:
                    intents.append(intent)
                    world.actors[actor.actor_id].current_intention = type(intent).__name__
                continue
            view = self._perception[actor.actor_id]
            result = decision.decide(snapshot, actor.actor_id, view, self.cfg)
            report.decisions[actor.actor_id] = result
            if result.chosen is not None:
                intents.append(result.chosen.intent)
                world.actors[actor.actor_id].current_intention = result.chosen.name

        # 8-10. проверка, разрешение споров, применение
        resolution: ResolutionResult = resolve(world, intents, self.cfg)
        report.applied = resolution.applied
        report.rejected = [f'{type(r.intent).__name__}({r.intent.actor_id}): {r.reason}'
                           for r in resolution.rejected]

        # 11. что увидели — то и меняет знания и отношения
        for actor in list(world.living_actors()):
            view = self._perception.get(actor.actor_id)
            if view is None:
                continue
            seen = perception.filter_actions(view, resolution.applied)
            if not seen:
                continue
            knowledge.update(world, actor.actor_id, view, seen, self.cfg.perception)
            changes = relationships.evaluate(world, actor.actor_id, seen, self.cfg)
            report.relation_log.extend(relationships.apply(world, changes, self.cfg))

        # 12-13. инварианты и время
        if self.check:
            check_invariants(world)
        world.tick += 1
        self.last_report = report
        return report

    def run(self, ticks: int) -> list[TickReport]:
        return [self.step() for _ in range(ticks)]
