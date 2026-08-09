"""Независимый от ввода и вывода фасад существующей симуляции."""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from simulation.commands import (DropIntent, EatIntent, GiveIntent, Intent, MoveIntent,
                                 RestIntent, SpeakIntent, SpeechActType, TakeIntent,
                                 WaitIntent)
from simulation.config import DEFAULT_CONFIG, SimulationConfig
from simulation.simulation_loop import Simulation
from simulation.world_state import Position, WorldState

from knyaz2.protocol import (Command, CommandKind, EngineEvent, StepResult,
                             WorldSnapshot)


class HeadlessEngine:
    """Единая точка входа для браузера, сервера и автоматических прогонов."""

    def __init__(self, simulation: Simulation) -> None:
        self.simulation = simulation

    @classmethod
    def from_world(cls, world: WorldState, cfg: SimulationConfig = DEFAULT_CONFIG,
                   check: bool = True) -> "HeadlessEngine":
        return cls(Simulation(world, cfg=cfg, check=check))

    @property
    def world(self) -> WorldState:
        return self.simulation.world

    def step(self, commands: Iterable[Command] = ()) -> StepResult:
        events: list[EngineEvent] = []
        controlled: set[str] = set()

        for command in commands:
            actor = self.world.actors.get(command.actor_id)
            if actor is None:
                events.append(_command_rejected(command, "персонажа не существует"))
                continue
            if not actor.is_player:
                events.append(_command_rejected(
                    command, "персонаж не управляется внешним адаптером"))
                continue
            if command.actor_id in controlled:
                events.append(_command_rejected(
                    command, "на один такт допустима одна команда персонажа"))
                continue
            try:
                intent = _intent_from_command(command)
            except (KeyError, TypeError, ValueError) as exc:
                events.append(_command_rejected(command, str(exc)))
                continue
            self.simulation.queue_player_intent(intent)
            controlled.add(command.actor_id)

        report = self.simulation.step()
        events.extend(_events_from_report(report))
        return StepResult(
            tick=self.world.tick,
            events=tuple(events),
            snapshot=self.snapshot(),
        )

    def snapshot(self) -> WorldSnapshot:
        return _snapshot(self.world)


def _intent_from_command(command: Command) -> Intent:
    payload = command.payload
    actor_id = command.actor_id

    if command.kind is CommandKind.MOVE:
        return MoveIntent(actor_id, Position(_integer(payload, "row"),
                                             _integer(payload, "col")))
    if command.kind is CommandKind.TAKE:
        return TakeIntent(actor_id, _string(payload, "item_id"))
    if command.kind is CommandKind.DROP:
        return DropIntent(actor_id, _string(payload, "item_id"))
    if command.kind is CommandKind.EAT:
        return EatIntent(actor_id, _string(payload, "item_id"))
    if command.kind is CommandKind.GIVE:
        return GiveIntent(actor_id, _string(payload, "item_id"),
                          _string(payload, "target_actor_id"))
    if command.kind is CommandKind.REST:
        return RestIntent(actor_id)
    if command.kind is CommandKind.WAIT:
        return WaitIntent(actor_id)
    if command.kind is CommandKind.SPEAK:
        speech_name = _string(payload, "speech_kind").upper()
        try:
            speech_kind = SpeechActType[speech_name]
        except KeyError as exc:
            raise ValueError(f"неизвестный speech_kind: {speech_name.lower()}") from exc
        subject_id = payload.get("subject_id")
        if subject_id is not None and not isinstance(subject_id, str):
            raise TypeError("subject_id должен быть строкой или null")
        return SpeakIntent(actor_id, _string(payload, "listener_id"),
                           speech_kind, subject_id)
    raise ValueError(f"неподдерживаемая команда: {command.kind.value}")


def _integer(payload: Mapping[str, Any], key: str) -> int:
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{key} должен быть целым числом")
    return value


def _string(payload: Mapping[str, Any], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str) or not value:
        raise TypeError(f"{key} должен быть непустой строкой")
    return value


def _command_rejected(command: Command, reason: str) -> EngineEvent:
    payload: dict[str, Any] = {"command": command.kind.value, "reason": reason}
    if command.request_id is not None:
        payload["request_id"] = command.request_id
    return EngineEvent("command.rejected", command.actor_id, payload)


def _events_from_report(report: Any) -> list[EngineEvent]:
    events: list[EngineEvent] = []
    for action in report.applied:
        position = action.position
        payload: dict[str, Any] = {
            "row": position.row,
            "col": position.col,
        }
        if action.item_id is not None:
            payload["item_id"] = action.item_id
        if action.target_actor_id is not None:
            payload["target_actor_id"] = action.target_actor_id
        if action.speech_kind is not None:
            payload["speech_kind"] = action.speech_kind.name.lower()
        events.append(EngineEvent(
            f"action.{action.kind.name.lower()}", action.actor_id, payload))

    for reason in report.rejected:
        events.append(EngineEvent("action.rejected", payload={"reason": reason}))
    for actor_id in report.died:
        events.append(EngineEvent("actor.died", actor_id))
    for description in report.relation_log:
        events.append(EngineEvent(
            "relationship.changed", payload={"description": description}))
    return events


def _snapshot(world: WorldState) -> WorldSnapshot:
    actors: list[Mapping[str, Any]] = []
    for actor_id in sorted(world.actors):
        actor = world.actors[actor_id]
        actors.append({
            "actor_id": actor.actor_id,
            "row": actor.position.row,
            "col": actor.position.col,
            "health": actor.health,
            "energy": actor.energy,
            "hunger": actor.hunger,
            "alive": actor.alive,
            "is_player": actor.is_player,
            "intention": actor.current_intention,
            "relationships": {
                other_id: {
                    "trust": relation.trust,
                    "fear": relation.fear,
                    "hostility": relation.hostility,
                }
                for other_id, relation in sorted(actor.relationships.items())
            },
        })

    items: list[Mapping[str, Any]] = []
    for item_id in sorted(world.items):
        item = world.items[item_id]
        items.append({
            "item_id": item.item_id,
            "item_type": item.item_type.name.lower(),
            "row": item.position.row if item.position is not None else None,
            "col": item.position.col if item.position is not None else None,
            "owner_id": item.owner_id,
        })

    return WorldSnapshot(
        tick=world.tick,
        width=world.width,
        height=world.height,
        actors=tuple(actors),
        items=tuple(items),
    )

