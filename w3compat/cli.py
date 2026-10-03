import argparse
import json
from pathlib import Path
import sys

from . import __version__
from .paths import SafetyError, game_root, output_directory
from .scan import markdown, scan
from .transaction import apply, json_bytes, rollback, stage


def main(argv=None):
    parser = argparse.ArgumentParser(prog="w3compat", description="Limited Witcher 3 5.x scanner and reversible reserved-name repair")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("scan", "stage", "apply", "rollback"):
        command = commands.add_parser(name)
        command.add_argument("--game-root", required=True, type=Path)
        if name in ("scan", "stage"):
            command.add_argument("--mod-settings", type=Path, help="Optional mods.settings; folder names alone do not prove activation")
            command.add_argument("--out", required=True, type=Path, help="New output directory outside engine-loaded folders")
        if name == "scan":
            command.add_argument("--expected-cr2w", type=int, default=164)
            command.add_argument("--expected-strings", type=int, default=164)
        if name == "apply":
            command.add_argument("--stage", required=True, type=Path)
            command.add_argument("--backup-dir", required=True, type=Path)
        if name == "rollback":
            command.add_argument("--transaction", required=True, type=Path)
            command.add_argument("--apply", action="store_true", help="Restore bytes; default validates and previews only")
    args = parser.parse_args(argv)
    try:
        root = game_root(args.game_root)
        if args.command == "scan":
            destination = output_directory(args.out, root)
            if destination.exists():
                raise SafetyError("Output already exists; choose a new directory")
            report = scan(root, args.mod_settings, args.expected_cr2w, args.expected_strings)
            destination.mkdir(parents=True, exist_ok=False)
            (destination / "scan.json").write_bytes(json_bytes(report))
            (destination / "scan.md").write_text(markdown(report), encoding="utf-8", newline="\n")
            result = dict(report= str(destination / "scan.md"), **report["summary"])
        elif args.command == "stage":
            result = stage(root, args.out, args.mod_settings)
        elif args.command == "apply":
            result = apply(root, args.stage, args.backup_dir)
        else:
            result = rollback(root, args.transaction, args.apply)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print("w3compat: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
