"""Версионированный манифест content pack."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


CONTENT_SCHEMA_VERSION = "0.1"


@dataclass(frozen=True, slots=True)
class PackedFile:
    path: str
    bytes: int
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "bytes": self.bytes, "sha256": self.sha256}

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "PackedFile":
        return cls(path=str(raw["path"]), bytes=int(raw["bytes"]),
                   sha256=str(raw["sha256"]))


@dataclass(frozen=True, slots=True)
class ContentMap:
    map_id: str
    legacy_number: int
    name: str
    path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.map_id,
            "legacy_number": self.legacy_number,
            "name": self.name,
            "path": self.path,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ContentMap":
        return cls(map_id=str(raw["id"]), legacy_number=int(raw["legacy_number"]),
                   name=str(raw["name"]), path=str(raw["path"]))


@dataclass(frozen=True, slots=True)
class ContentManifest:
    content_id: str
    maps: tuple[ContentMap, ...]
    files: tuple[PackedFile, ...]
    schema_version: str = CONTENT_SCHEMA_VERSION
    #: С какой карты начинается игра. Стартовых клеток в данных ШЕСТЬ — по
    #: одной на мир GAME.0…GAME.5, — и брать надо ту, чей мир нулевой: весь
    #: пак собран из GAME.0. Без этого клиент начинал с первой карты по
    #: номеру, то есть с Дворца Повелителя.
    start_map: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "content_id": self.content_id,
            "start_map": self.start_map,
            "maps": [item.to_dict() for item in self.maps],
            "files": [item.to_dict() for item in self.files],
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ContentManifest":
        version = str(raw.get("schema_version", ""))
        if version != CONTENT_SCHEMA_VERSION:
            raise ValueError(
                f"версия content pack {version!r}, поддерживается {CONTENT_SCHEMA_VERSION!r}")
        maps = raw.get("maps")
        files = raw.get("files")
        if not isinstance(maps, list) or not isinstance(files, list):
            raise ValueError("maps и files должны быть массивами")
        return cls(
            content_id=str(raw["content_id"]),
            maps=tuple(ContentMap.from_dict(item) for item in maps),
            files=tuple(PackedFile.from_dict(item) for item in files),
            schema_version=version,
        )

