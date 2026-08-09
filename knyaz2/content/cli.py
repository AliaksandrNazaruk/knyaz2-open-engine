"""Командная строка сборки и проверки content pack."""
from __future__ import annotations

import argparse
from pathlib import Path

from .builder import build_content_pack, verify_content_pack


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="knyaz2-content")
    commands = result.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="собрать content pack")
    build.add_argument("--map", dest="maps", type=int, action="append", required=True,
                       help="номер карты; параметр можно повторять")
    build.add_argument("--output", type=Path, default=Path("content_build"))
    build.add_argument("--project", type=Path, default=Path("project"))
    build.add_argument("--content-id", default="konung2-base")

    verify = commands.add_parser("verify", help="проверить хэши и структуру")
    verify.add_argument("path", type=Path)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "build":
        manifest = build_content_pack(args.maps, args.output, args.project,
                                      content_id=args.content_id)
        total = sum(item.bytes for item in manifest.files)
        print(f"content pack: {args.output.resolve()}")
        print(f"карты: {len(manifest.maps)}, файлы: {len(manifest.files)}, байт: {total}")
        return 0

    errors = verify_content_pack(args.path)
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print(f"OK: {args.path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

