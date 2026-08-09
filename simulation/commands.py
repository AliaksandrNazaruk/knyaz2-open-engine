# -*- coding: utf-8 -*-
"""
Намерения — единственный способ что-либо изменить в мире.

И управление игрока, и система решений NPC порождают одни и те же намерения.
Различается только источник: у игрока — ввод, у NPC — оценка вариантов.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class Intent:
    actor_id: str


@dataclass(frozen=True)
class MoveIntent(Intent):
    """Шаг в соседнюю клетку. Маршрут строит система движения, не резолвер."""
    target: object          # Position


@dataclass(frozen=True)
class TakeIntent(Intent):
    item_id: str


@dataclass(frozen=True)
class DropIntent(Intent):
    item_id: str


@dataclass(frozen=True)
class EatIntent(Intent):
    item_id: str


@dataclass(frozen=True)
class GiveIntent(Intent):
    item_id: str
    target_actor_id: str


@dataclass(frozen=True)
class RestIntent(Intent):
    pass


@dataclass(frozen=True)
class WaitIntent(Intent):
    pass


class SpeechActType(Enum):
    GREETING = 0
    REQUEST_ITEM = 1
    OFFER_ITEM = 2
    WARN = 3
    THREATEN = 4
    ASK_LOCATION = 5
    ANSWER_LOCATION = 6


@dataclass(frozen=True)
class SpeakIntent(Intent):
    listener_id: str
    kind: SpeechActType
    subject_id: str | None = None


class ActionKind(Enum):
    MOVE = 0
    TAKE = 1
    DROP = 2
    EAT = 3
    GIVE = 4
    REST = 5
    WAIT = 6
    SPEAK = 7


@dataclass(frozen=True)
class ObservedAction:
    """Что именно наблюдатель мог увидеть. Без объяснений и оценок."""
    actor_id: str
    kind: ActionKind
    position: object                 # Position, где произошло
    item_id: str | None = None
    target_actor_id: str | None = None
    speech_kind: SpeechActType | None = None


@dataclass(frozen=True)
class RejectedIntent:
    intent: Intent
    reason: str
