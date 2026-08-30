# -*- coding: utf-8 -*-
"""
`KONUNG2/voices.res` — озвучка: реплики диалогов и приветствия спутников.

Устройство (загрузчик VA 0x43C228, проигрыватель VA 0x42D9FC):

    +0x0000  6000 x 8  таблица {u32 off; u32 size}
    +0xBB80  данные    сырой PCM s16le, моно

В отличие от SOUNDS.RES смещения здесь **абсолютные**: проигрыватель сикает
`FUN_00443211(файл, off, 0)` без прибавки размера таблицы, и минимальное
смещение занятой записи равно ровно 48000. Записи лежат вплотную, конец
последней совпадает с размером файла байт в байт.

Кто на что ссылается:

* записи 1…1215 — реплики диалогов. Номер реплики хранится ПЕРВЫМ полем
  записи фразы QUESTS.RES (``konung2.quests.Dialogs.phrase(i)['voice']``,
  таблица фраз в памяти 0x642790); 0 — фраза не озвучена. Играется при
  входе в узел разговора (VA 0x436478).
* записи 5500…5529 — приветствия: по пять на актёра,
  ``5500 + актёр*5 + rand()%5`` (актёр — байт unit+0xFC). Спутник
  здоровается раз в 1024 тика (VA 0x438A00, маска 0x3FF).

Частота воспроизведения — 22050 Гц плюс личная поправка ГОЛОСА говорящего
(байт unit+0xF2) из текстового файла ``KONUNG2/_VOICES`` — см.
``konung2.sounds.voice_rates``. Сам файл записан на базовой частоте, поэтому
WAV по умолчанию сохраняется в 22050; частота-аргумент нужна, чтобы получить
звучание конкретного персонажа.
"""
from __future__ import annotations

import os
import struct
import wave

from .paths import game_file

VOICE_ENTRIES = 6000
VOICE_TABLE_SIZE = VOICE_ENTRIES * 8          # 48000: проверка абсолютных смещений
VOICE_RATE, VOICE_CHANNELS, SAMPLE_WIDTH = 22050, 1, 2

#: Приветствия спутников (VA 0x438A00: ``rand%5 + актёр*5 + 0x157C``).
GREETING_BASE = 5500
GREETINGS_PER_ACTOR = 5
GREETING_PERIOD_TICKS = 1024                  # маска 0x3FF на счётчике тиков


def greeting_index(actor: int, variant: int) -> int:
    """Номер записи приветствия: пять вариантов на актёра."""
    return GREETING_BASE + actor * GREETINGS_PER_ACTOR + variant % GREETINGS_PER_ACTOR


class VoicesRes:
    """Каталог voices.res и выемка реплик."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.entries: list[tuple[int, int] | None] = []
        for index in range(VOICE_ENTRIES):
            offset, size = struct.unpack_from('<2I', data, index * 8)
            # пустые места забиты нулями; односемпловых записей не бывает
            self.entries.append((offset, size) if size > 1 else None)

    #: Разобранные voices.res по игре: файл на полгигабайта, и читать его
    #: заново на каждый вопрос слишком дорого.
    _LOADED: dict[str, 'VoicesRes'] = {}

    @classmethod
    def from_game(cls, profile=None) -> 'VoicesRes':
        """Голоса своей игры.

        У «Продолжения легенды» файл СВОЙ (703 МБ против наших 469) и
        нумерация тоже своя — под общий номер у него лежит другая реплика.
        Развести их обязательно, иначе персонаж заговорит чужими словами.
        """
        from .profile import CANON
        profile = profile or CANON
        if profile.name not in cls._LOADED:
            path = os.path.join(profile.directory, 'KONUNG2', 'voices.res')
            if not os.path.isfile(path):
                path = game_file(r'KONUNG2\voices.res')
            with open(path, 'rb') as stream:
                cls._LOADED[profile.name] = cls(stream.read())
        return cls._LOADED[profile.name]

    def used(self) -> list[int]:
        """Номера занятых записей (в оригинале их 1245)."""
        return [i for i, entry in enumerate(self.entries) if entry]

    def pcm(self, index: int) -> bytes | None:
        """Сырой PCM реплики (s16le, моно, базовая частота 22050)."""
        entry = self.entries[index]
        if entry is None:
            return None
        offset, size = entry
        return self.data[offset:offset + size]

    def duration(self, index: int, rate: int = VOICE_RATE) -> float | None:
        entry = self.entries[index]
        if entry is None:
            return None
        return entry[1] / (rate * VOICE_CHANNELS * SAMPLE_WIDTH)

    def save_wav(self, index: int, path, rate: int = VOICE_RATE) -> bool:
        """Реплика в WAV; rate — частота голоса говорящего, если нужна."""
        pcm = self.pcm(index)
        if pcm is None:
            return False
        with wave.open(str(path), 'wb') as out:
            out.setnchannels(VOICE_CHANNELS)
            out.setsampwidth(SAMPLE_WIDTH)
            out.setframerate(rate)
            out.writeframes(pcm)
        return True
