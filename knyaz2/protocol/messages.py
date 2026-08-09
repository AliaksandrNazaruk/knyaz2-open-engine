"""JSON-совместимый протокол headless-ядра.

В сообщениях намеренно нет объектов рендера, файловых путей и классов
симуляции. Эта граница одинакова для прямого вызова, WebSocket и Web Worker.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


PROTOCOL_VERSION = "0.1"


class ProtocolError(ValueError):
    """Внешнее сообщение не соответствует текущей версии протокола."""


class CommandKind(str, Enum):
    MOVE = "move"
    TAKE = "take"
    DROP = "drop"
    EAT = "eat"
    GIVE = "give"
    REST = "rest"
    WAIT = "wait"
    SPEAK = "speak"


@dataclass(frozen=True, slots=True)
class Command:
    """Одна команда внешнего управляющего адаптера."""

    kind: CommandKind
    actor_id: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    request_id: str | None = None

    def __post_init__(self) -> None:
        if not self.actor_id:
            raise ProtocolError("actor_id не может быть пустым")

    @classmethod
    def move(cls, actor_id: str, row: int, col: int,
             request_id: str | None = None) -> "Command":
        return cls(CommandKind.MOVE, actor_id, {"row": row, "col": col}, request_id)

    @classmethod
    def wait(cls, actor_id: str, request_id: str | None = None) -> "Command":
        return cls(CommandKind.WAIT, actor_id, request_id=request_id)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Command":
        try:
            kind = CommandKind(str(raw["kind"]))
        except (KeyError, ValueError, TypeError) as exc:
            raise ProtocolError(f"некорректная команда: {exc}") from exc

        actor_id = raw.get("actor_id")
        if not isinstance(actor_id, str) or not actor_id:
            raise ProtocolError("actor_id должен быть непустой строкой")

        payload = raw.get("payload", {})
        if not isinstance(payload, Mapping):
            raise ProtocolError("payload команды должен быть объектом")
        request_id = raw.get("request_id")
        if request_id is not None and not isinstance(request_id, str):
            raise ProtocolError("request_id должен быть строкой или null")
        return cls(kind, actor_id, dict(payload), request_id)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "kind": self.kind.value,
            "actor_id": self.actor_id,
            "payload": dict(self.payload),
        }
        if self.request_id is not None:
            result["request_id"] = self.request_id
        return result


@dataclass(frozen=True, slots=True)
class EngineEvent:
    """Факт, опубликованный ядром после обработки такта."""

    kind: str
    actor_id: str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"kind": self.kind, "payload": dict(self.payload)}
        if self.actor_id is not None:
            result["actor_id"] = self.actor_id
        return result


@dataclass(frozen=True, slots=True)
class WorldSnapshot:
    """Полное динамическое состояние, достаточное для первого адаптера."""

    tick: int
    width: int
    height: int
    actors: tuple[Mapping[str, Any], ...]
    items: tuple[Mapping[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "tick": self.tick,
            "width": self.width,
            "height": self.height,
            "actors": [dict(actor) for actor in self.actors],
            "items": [dict(item) for item in self.items],
        }


@dataclass(frozen=True, slots=True)
class StepResult:
    """Результат одного атомарного шага ядра."""

    tick: int
    events: tuple[EngineEvent, ...]
    snapshot: WorldSnapshot
    protocol_version: str = PROTOCOL_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "tick": self.tick,
            "events": [event.to_dict() for event in self.events],
            "snapshot": self.snapshot.to_dict(),
        }
