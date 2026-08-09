# -*- coding: utf-8 -*-
"""Публичная граница ядра не зависит от конкретного адаптера."""
from __future__ import annotations

import json
import unittest

from knyaz2.core import HeadlessEngine
from knyaz2.protocol import Command, CommandKind, ProtocolError
from simulation.bridge import make_test_world
from simulation.world_state import ActorState, Position


class ProtocolTest(unittest.TestCase):
    def test_command_round_trip(self) -> None:
        original = Command.move("hero", 4, 7, request_id="click-1")
        restored = Command.from_dict(original.to_dict())
        self.assertEqual(restored, original)
        self.assertEqual(restored.kind, CommandKind.MOVE)

    def test_invalid_payload_is_rejected_without_stopping_tick(self) -> None:
        world = make_test_world()
        world.actors["hero"] = ActorState("hero", Position(4, 4), is_player=True)
        engine = HeadlessEngine.from_world(world)
        bad = Command(CommandKind.MOVE, "hero", {"row": "4", "col": 5})

        result = engine.step([bad])

        self.assertEqual(result.tick, 1)
        self.assertEqual(engine.world.actors["hero"].position, Position(4, 4))
        self.assertTrue(any(event.kind == "command.rejected" for event in result.events))

    def test_wire_command_requires_string_actor_id(self) -> None:
        with self.assertRaises(ProtocolError):
            Command.from_dict({"kind": "wait", "actor_id": 7})


class HeadlessEngineTest(unittest.TestCase):
    def make_engine(self) -> HeadlessEngine:
        world = make_test_world(seed=17)
        world.actors["hero"] = ActorState("hero", Position(4, 4), is_player=True)
        world.actors["npc"] = ActorState("npc", Position(8, 8))
        return HeadlessEngine.from_world(world)

    def test_move_command_changes_world_and_emits_json_event(self) -> None:
        engine = self.make_engine()

        result = engine.step([Command.move("hero", 4, 5)])

        self.assertEqual(engine.world.actors["hero"].position, Position(4, 5))
        self.assertEqual(result.snapshot.tick, 1)
        self.assertTrue(any(event.kind == "action.move" and event.actor_id == "hero"
                            for event in result.events))
        json.dumps(result.to_dict(), ensure_ascii=False)

    def test_adapter_cannot_take_control_of_npc(self) -> None:
        engine = self.make_engine()

        result = engine.step([Command.move("npc", 8, 9, request_id="bad-control")])

        rejected = [event for event in result.events if event.kind == "command.rejected"]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0].payload["request_id"], "bad-control")

    def test_same_seed_and_commands_produce_same_public_result(self) -> None:
        first = self.make_engine().step([Command.wait("hero")]).to_dict()
        second = self.make_engine().step([Command.wait("hero")]).to_dict()
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
