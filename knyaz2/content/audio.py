# -*- coding: utf-8 -*-
"""Экспорт звука в content pack: Opus-файлы, канон правил, блок карты.

Три пласта — ровно те, что стримит движок (docs/AUDIO_AUDIT.md §6):

    assets/sfx/NNN.opus          эффекты и голоса юнитов, моно 48 kbps
    assets/audio/track_NN.opus   музыкальные петли, стерео 96 kbps
    assets/voices/NNNN.opus      реплики диалогов, моно 32 kbps

Голоса кодируются НА БАЗОВОЙ частоте 22050: личный питч голоса (файл
_VOICES) — это скорость воспроизведения, клиент умножает playbackRate,
как движок подставляет WAVEFORMATEX говорящего.

Перекодировка инкрементальна: реестры assets/audio.json и assets/voices.json
хранят sha256 исходного PCM, совпал — файл не трогаем (а при сборке в чистый
stage готовый файл переносится из прежнего пака). Каждый закодированный файл
тут же проверяется числами: длительность Opus против PCM с допуском 2 %.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Iterable

from konung2 import sounds
from konung2.gamefile import map_units
from konung2.graph import fixed_light_map
from konung2.sounds import (MUSIC_SLOTS, SoundsRes, audio_format, map_track,
                           music_slots)
from konung2.voices import VOICE_CHANNELS, VOICE_RATE, VoicesRes

#: Битрейты по пластам (kbps): выбраны в docs/AUDIO_PLAN.md.
SFX_KBPS, MUSIC_KBPS, VOICE_KBPS = 48, 96, 32
#: Допуск расхождения длительности Opus против исходного PCM.
DURATION_TOLERANCE = 0.02

SFX_DIR = Path("assets") / "sfx"
TRACK_DIR = Path("assets") / "audio"
VOICE_DIR = Path("assets") / "voices"
AUDIO_INDEX = Path("assets") / "audio.json"
VOICE_INDEX = Path("assets") / "voices.json"

_FFMPEG: str | None = None


class AudioExportError(RuntimeError):
    pass


def _ffmpeg() -> str:
    global _FFMPEG
    if _FFMPEG is None:
        import imageio_ffmpeg
        _FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
    return _FFMPEG


def _opus_seconds(path: Path) -> float:
    """Длительность готового файла — по контейнеру, без полного декода."""
    import av
    with av.open(str(path)) as container:
        if container.duration is not None:
            return container.duration / 1_000_000
        stream = container.streams.audio[0]
        if stream.duration is not None:
            return float(stream.duration * stream.time_base)
        total = 0
        for frame in container.decode(stream):
            total += frame.samples
        return total / stream.rate


def encode_opus(pcm: bytes, rate: int, channels: int, kbps: int,
                destination: Path) -> float:
    """PCM s16le -> Opus; возвращает длительность, сверенную с исходником."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        _ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "s16le", "-ar", str(rate), "-ac", str(channels), "-i", "pipe:0",
        "-c:a", "libopus", "-b:a", f"{kbps}k", "-vbr", "on",
        str(destination),
    ]
    result = subprocess.run(command, input=pcm, capture_output=True)
    if result.returncode:
        raise AudioExportError(
            f"ffmpeg не закодировал {destination.name}: "
            f"{result.stderr.decode('utf-8', 'replace').strip()}")
    expected = len(pcm) / (rate * channels * 2)
    actual = _opus_seconds(destination)
    if abs(actual - expected) > max(0.05, expected * DURATION_TOLERANCE):
        raise AudioExportError(
            f"{destination.name}: длительность {actual:.2f} c "
            f"против PCM {expected:.2f} c")
    return expected


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_registry(*paths: Path) -> dict[str, Any]:
    for path in paths:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
    return {}


def _write_json(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2)
    path.write_text(text + "\n", encoding="utf-8", newline="\n")


def _reusable(entry: Any, digest: str, target: Path,
              previous_root: Path | None, relative: Path) -> bool:
    """Готов ли файл: реестр сошёлся по sha и сам файл существует."""
    if not isinstance(entry, dict) or entry.get("pcm_sha") != digest:
        return False
    if target.is_file():
        return True
    if previous_root is not None:
        source = previous_root / relative
        if source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            return True
    return False


def _encode_batch(jobs: list[tuple[str, bytes, int, int, int, Path]],
                  registry: dict[str, Any]) -> None:
    """Кодирование пачкой: subprocess не держит GIL, потоки дают кратно."""
    def run(job):
        key, pcm, rate, channels, kbps, destination = job
        seconds = encode_opus(pcm, rate, channels, kbps, destination)
        return key, {
            "path": str(destination).replace("\\", "/"),
            "seconds": round(seconds, 2),
            "pcm_sha": _sha256(pcm),
        }

    if not jobs:
        return
    with ThreadPoolExecutor(max_workers=min(8, len(jobs))) as pool:
        for key, entry in pool.map(run, jobs):
            registry[key] = entry


def export_pack_audio(root: Path, previous: Path | None = None,
                      slots: Iterable[int] | None = None) -> dict[str, Any]:
    """Эффекты, музыка и канон правил; возвращает базу для блоков карт.

    ЗВУК ДВУХ ИГР — ДВА РАЗНЫХ НАБОРА ПОД ОДНИМИ НОМЕРАМИ, ровно как
    графика. Замер по `SOUNDS.RES`: общих номеров 376, и **ни один** не
    совпал байт в байт; у десяти совпала длина — и в них различается 98–99%
    байт, то есть та же длительность при другом звуке (сжатие с постоянным
    потоком). Своих у канона 118, у донора 306. Поэтому его набор едет в пак
    рядом, под ключом ``legend:<слот>`` и файлами с приставкой ``legend_``.

    slots — ограничение для тестов; по умолчанию все занятые слоты.
    """
    from konung2 import donor

    old = _load_registry(root / AUDIO_INDEX,
                         *([previous / AUDIO_INDEX] if previous else []))
    old_slots = old.get("slots", {})
    registry: dict[str, Any] = {}
    jobs: list[tuple[str, bytes, int, int, int, Path]] = []
    occupied: dict[str, set[int]] = {}

    def collect(res: SoundsRes, prefix: str) -> None:
        # ЧЬИ СЛОТЫ МУЗЫКАЛЬНЫЕ. Формат задаёт место вызова в движке, а не
        # номер: у канона музыку заводят слотами 20…30, у донора 28…39.
        # Пока набор брался канонный, его музыка распаковывалась как моно
        # 22050 (вчетверо медленнее), а его эффекты — как стерео 44100 и
        # превращались в обрывки по 0.11…0.37 с.
        game = "legend" if prefix else None
        music_of = music_slots(game)
        mine = [i for i, e in enumerate(res.entries) if e and e[1] > 1]
        wanted = (mine if slots is None
                  else [s for s in mine if s in set(slots)])
        occupied[prefix or "canon"] = set(wanted)
        for slot in wanted:
            music = slot in music_of
            name = (f"{prefix}track_{slot:03}.opus" if music
                    else f"{prefix}{slot:03}.opus")
            relative = (TRACK_DIR if music else SFX_DIR) / name
            pcm = res.pcm(slot)
            digest = _sha256(pcm)
            rate, channels = audio_format(slot, game)
            key = f"legend:{slot}" if prefix else str(slot)
            entry = old_slots.get(key)
            if _reusable(entry, digest, root / relative, previous, relative):
                registry[key] = entry
                continue
            kbps = MUSIC_KBPS if music else SFX_KBPS
            jobs.append((key, pcm, rate, channels, kbps, root / relative))

    collect(SoundsRes.from_game(), "")
    if donor.available():
        try:
            collect(SoundsRes(Path(donor.donor_file("sounds.res")).read_bytes()),
                    "legend_")
        except OSError:
            pass
    _encode_batch(jobs, registry)
    for key, entry in registry.items():        # пути в реестре — относительные
        slot = int(key.split(":")[-1])
        own = music_slots("legend" if key.startswith("legend:") else None)
        entry["path"] = str((TRACK_DIR if slot in own else SFX_DIR)
                            / Path(entry["path"]).name).replace("\\", "/")

    document = {
        "encoder": {"codec": "libopus",
                    "sfx_kbps": SFX_KBPS, "music_kbps": MUSIC_KBPS,
                    "voice_kbps": VOICE_KBPS},
        "rules": sounds.rules(),
        "slots": registry,
    }
    _write_json(root / AUDIO_INDEX, document)

    tracks = [{"slot": slot,
               "path": registry[str(slot)]["path"],
               "seconds": registry[str(slot)]["seconds"]}
              for slot in sorted(MUSIC_SLOTS) if str(slot) in registry]
    legend_tracks = [{"slot": slot,
                      "path": registry[f"legend:{slot}"]["path"],
                      "seconds": registry[f"legend:{slot}"]["seconds"]}
                     for slot in sorted(music_slots("legend"))
                     if f"legend:{slot}" in registry]
    return {"index": str(AUDIO_INDEX).replace("\\", "/"),
            "tracks": tracks, "legend_tracks": legend_tracks,
            "occupied": occupied.get("canon", set()),
            "legend_occupied": occupied.get("legend_", set())}


def export_voice_lines(root: Path, previous: Path | None = None,
                       lines: Iterable[int] | None = None) -> dict[str, Any]:
    """Реплики диалогов и приветствия — по файлу на запись.

    ГОЛОСА ОБЕИХ ИГР. У «Продолжения легенды» свой ``voices.res`` и своя
    нумерация: под общим номером у него лежит другая реплика, и все 1215
    наших номеров попадают в его диапазон. Поэтому его записи уезжают в
    проектный участок (``donor.PROJECT_VOICE_BASE``) — туда же, куда их
    уводит разбор разговоров, и клиент получает уже готовый номер.
    """
    from konung2 import donor
    from konung2.profile import CANON, LEGEND
    old = _load_registry(root / VOICE_INDEX,
                         *([previous / VOICE_INDEX] if previous else []))
    old_lines = old.get("lines", {})

    sources = [(CANON, 0)]
    if donor.available():
        sources.append((LEGEND, donor.PROJECT_VOICE_BASE))

    registry: dict[str, Any] = {}
    jobs = []
    picked = None if lines is None else set(lines)
    for profile, shift in sources:
        res = VoicesRes.from_game(profile)
        for index in res.used():
            number = index + shift
            if picked is not None and number not in picked:
                continue
            relative = VOICE_DIR / f"{number:04}.opus"
            pcm = res.pcm(index)
            digest = _sha256(pcm)
            entry = old_lines.get(str(number))
            if _reusable(entry, digest, root / relative, previous, relative):
                registry[str(number)] = entry
                continue
            jobs.append((str(number), pcm, VOICE_RATE, VOICE_CHANNELS,
                         VOICE_KBPS, root / relative))
    _encode_batch(jobs, registry)
    for entry in registry.values():
        entry["path"] = str(VOICE_DIR / Path(entry["path"]).name).replace("\\", "/")

    document = {"base_rate": VOICE_RATE, "lines": registry}
    _write_json(root / VOICE_INDEX, document)
    return document


def _legend_flag(native: int) -> bool:
    """Бит признаков локации донора; нет донора — считаем, что не стоит."""
    from konung2 import donor
    if not donor.available():
        return False
    try:
        return donor.location_track_flag(native)
    except OSError:
        return False


def map_audio_block(number: int, base: dict[str, Any],
                    game: str | None = None,
                    native: int | None = None,
                    village: bool = False) -> dict[str, Any]:
    """Блок ``audio`` документа карты: трек, амбиент и предзагрузка.

    Повторяет загрузчик карты (VA 0x43DF48): амбиент — занятые слоты
    восьмёрки карты, предзагрузка — те же слоты плюс восьмёрки зверей всех
    записей динамики среди юнитов карты и принудительные записи 14 и 15.
    Деление день/ночь — правило амбиента из 0x438A00; в «пещерах» (карты с
    фиксированным светом, таблица 0x4617B0) оно выключено.
    """
    # ЧЕЙ ЗВУК И ПО ЧЬЕМУ НОМЕРУ. Восьмёрка амбиента — арифметика от номера
    # карты (база + (номер−1)·шаг), поэтому донорской карте нужен ЕГО номер:
    # по нашему 155 она брала бы чужую восьмёрку. Набор звуков тоже его.
    legend = game == "legend"
    occupied: set[int] = (base.get("legend_occupied") or set()) if legend \
        else base["occupied"]
    own = native if (legend and native) else number
    # БАЗА ВОСЬМЁРКИ ТОЖЕ СВОЯ У КАЖДОЙ ИГРЫ: канон 256, донор 300. Пока
    # бралась канонная, его карты озвучивались слотами на 44 раньше своих —
    # чужими вскриками вместо своего гомона.
    eight = [slot for slot in sounds.ambient_slots(own, game) if slot in occupied]
    night_from = (sounds.ambient_slots(own, game).start
                  + sounds.AMBIENT_NIGHT_OFFSET)
    cave = bool(fixed_light_map(number))

    records = set(sounds.PRELOAD_FORCED_RECORDS)
    try:
        for resident in map_units(number):
            breed = int(resident.get("breed", 0) or 0)
            if breed & 0x40:
                records.add(breed & 0x3F)
    except (OSError, ValueError, IndexError):
        pass
    preload = set(eight)
    for record in sorted(records):
        preload.update(slot for slot in sounds.creature_preload_slots(record)
                       if slot in occupied)

    return {
        # ЧЕЙ НАБОР ЗВУКОВ БРАТЬ. Клиент ищет слот сперва под этой
        # приставкой (`legend:<слот>`), и только потом среди канонных.
        **({"game": "legend"} if legend else {}),
        # Правило выбора трека — СВОЁ У КАЖДОЙ ИГРЫ: канон 0x437F48, донор
        # 0x43BC94. Раньше к донорской карте применялось канонное, и оно
        # выдавало номер из канонного музыкального диапазона — а в его наборе
        # под этим номером лежит звуковой эффект. Отсюда «музыка зависает»:
        # карта 169 просила трек 24, а в донорском банке это 0.23 секунды,
        # закольцованные навсегда.
        "map_track": map_track(own, game, village, _legend_flag(own)
                               if legend else False),
        "tracks": (base.get("legend_tracks") or base["tracks"]) if legend
                  else base["tracks"],
        "index": base["index"],
        "ambient": {
            "day": [slot for slot in eight if slot < night_from],
            "night": [slot for slot in eight if slot >= night_from],
            "cave": cave,
        },
        "preload": sorted(preload),
    }
