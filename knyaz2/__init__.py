"""Открытое, независимое от вывода ядро Knyaz2."""

from .core import HeadlessEngine
from .protocol import Command, CommandKind, EngineEvent, StepResult, WorldSnapshot

__all__ = [
    "Command",
    "CommandKind",
    "EngineEvent",
    "HeadlessEngine",
    "StepResult",
    "WorldSnapshot",
]

__version__ = "0.1.0"

