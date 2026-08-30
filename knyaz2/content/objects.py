# -*- coding: utf-8 -*-
"""
Каталог объектов для пака: канон и его продолжение.

Правило то же, что у карты мира: КАНОН ВЛАДЕЕТ НАЧАЛОМ, ПРОЕКТ ПРОДОЛЖЕНИЕМ.
Гнёзда 30..509 всегда наши, 510..587 берутся у «Продолжения легенды».
Границы не назначены, а замерены: у нас годные гнёзда идут подряд с 30 по
509 без дыр, у донора — с 30 по 587, и того, чего нет у него, у нас нет.

Гнёзда, которые есть у обоих, берутся ТОЛЬКО У НАС. Донор перерисовал 154
из них в свой сезон (те же kind, count и group, другие walls, roof и size);
взять их значило бы посадить лето посреди осени. Ввозятся ровно те 78, у
которых нашего варианта не существует.

Донорские объекты приезжают в СВОЁМ сезоне — иначе никак, другого их вида
нет. Для пустынных построек это и правильно: пустыня не бывает осенней.
"""
from __future__ import annotations

from typing import Any

from konung2 import donor
from konung2.res import ObjectsRes


class MergedObjects:
    """Два каталога под одним номером гнезда.

    Не наследник и не «прозрачная обёртка»: перечислены ровно те способы,
    которыми каталог пользуются сборщик и модель карты. Понадобится новый —
    он упадёт с AttributeError здесь, а не тихо возьмёт данные не из того
    файла.
    """

    def __init__(self, canon: ObjectsRes, extension: ObjectsRes,
                 last_canon_slot: int = donor.CANON_LAST_SLOT,
                 extra_slots: tuple[int, ...] = donor.DONOR_CREATURE_SLOTS) -> None:
        self.canon = canon
        self.extension = extension
        self.last_canon_slot = last_canon_slot
        # ГНЁЗДА НИЖЕ ГРАНИЦЫ, КОТОРЫЕ ВСЁ РАВНО БЕРУТСЯ У ДОНОРА. Твари
        # живут в первых тридцати записях того же каталога, и две из них
        # (23 и 24) есть только у него — у нас там пусто.
        self.extra_slots = frozenset(extra_slots)
        # `entries` наружу нужен только длиной и проверкой на None, поэтому
        # склеиваем списки: за каноном идут донорские гнёзда.
        self.entries = [
            canon.entries[slot] if slot <= last_canon_slot
            and slot not in self.extra_slots
            else (extension.entries[slot]
                  if slot < len(extension.entries) else None)
            for slot in range(max(len(canon.entries), len(extension.entries)))
        ]

    def _owner(self, slot: int) -> ObjectsRes:
        if slot in self.extra_slots:
            return self.extension
        return self.canon if slot <= self.last_canon_slot else self.extension

    def simple_header(self, slot: int):
        return self._owner(slot).simple_header(slot)

    def simple_palette(self, slot: int):
        return self._owner(slot).simple_palette(slot)

    def simple_frames(self, slot: int):
        return self._owner(slot).simple_frames(slot)

    def simple_parts(self, slot: int):
        return self._owner(slot).simple_parts(slot)

    def frame_size(self, slot: int, offset: int = 0):
        return self._owner(slot).frame_size(slot, offset)

    def decode_building(self, slot: int, palette=None, state: int = 0,
                        show_roof: bool = True):
        return self._owner(slot).decode_building(
            slot, palette=palette, state=state, show_roof=show_roof)

    def decode_building_layers(self, slot: int, palette=None, state: int = 0):
        return self._owner(slot).decode_building_layers(
            slot, palette=palette, state=state)

    def decode_shadow(self, slot: int, state: int = 0):
        return self._owner(slot).decode_shadow(slot, state=state)


def catalogue(with_extension: bool = True) -> Any:
    """Каталог для сборки пака: с продолжением, если донор на месте."""
    canon = ObjectsRes.from_game()
    if not with_extension or not donor.available():
        return canon
    return MergedObjects(canon, donor.objects())


def missing_slots(catalogue_object: Any, slots) -> list[int]:
    """Какие из этих гнёзд каталог не знает.

    Нужно, чтобы объект не пропадал с карты МОЛЧА. Сейчас и сборщик, и
    модель карты на неизвестном гнезде просто возвращают None, и постройки
    нет — ни ошибки, ни следа. На наших 52 картах не теряется ни одного
    объекта, поэтому потеря это всегда неисправность, а не норма.
    """
    out = []
    for slot in sorted(set(slots)):
        if not 0 <= slot < len(catalogue_object.entries):
            out.append(slot)
        elif catalogue_object.entries[slot] is None:
            out.append(slot)
        elif catalogue_object.simple_header(slot) is None:
            out.append(slot)
    return out
