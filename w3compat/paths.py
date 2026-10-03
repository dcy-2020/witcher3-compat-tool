"""Bound file operations to mod-owned scripts; reject links and junctions."""
import os
from pathlib import Path, PurePosixPath
import stat


class SafetyError(ValueError):
    pass


OFFICIAL_DLC = {"bob", "ep1", *(f"dlc{i}" for i in range(1, 17))}


def is_link(path):
    info = path.lstat()
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def reject_links(path):
    path = Path(os.path.abspath(path))
    for item in (path, *path.parents):
        if item.exists() or item.is_symlink():
            if is_link(item):
                raise SafetyError(f"Symbolic link or reparse point is unsupported: {item.name}")
    return path


def game_root(path):
    root = reject_links(path)
    if not root.is_dir() or not any((root / name).is_dir() for name in ("Mods", "dlc")):
        raise SafetyError("Game root must contain Mods or dlc")
    return root


def safe_relative(root, relative, writable=False):
    if not isinstance(relative, str) or "\\" in relative or ":" in relative:
        raise SafetyError("Expected a portable relative path")
    parts = PurePosixPath(relative).parts
    if not parts or PurePosixPath(relative).is_absolute() or any(p in (".", "..") for p in parts) or "/".join(parts) != relative:
        raise SafetyError("Unsafe or non-canonical relative path")
    path = reject_links(root.joinpath(*parts))
    if writable:
        if len(parts) < 5 or parts[0] not in ("Mods", "dlc") or parts[2:4] != ("content", "scripts") or not relative.lower().endswith(".ws"):
            raise SafetyError("Only mod-owned content/scripts/*.ws targets may be written")
        name = parts[1].lower()
        if parts[0] == "Mods" and not name.startswith("mod"):
            raise SafetyError("Inactive or non-mod directory is not writable")
        if parts[0] == "dlc" and (name in OFFICIAL_DLC or name.startswith("~")):
            raise SafetyError("Official or inactive DLC is not writable")
    return path


def walk_files(directory):
    reject_links(directory)
    for current, dirs, files in os.walk(directory, followlinks=False):
        base = Path(current)
        dirs[:] = sorted(d for d in dirs if not is_link(base / d))
        for name in sorted(files):
            path = base / name
            if not is_link(path):
                yield path


def output_directory(path, root):
    path = reject_links(path)
    # Output cannot be staged where the engine consumes mods/native content.
    for name in ("Mods", "dlc", "content", "bin"):
        forbidden = root / name
        if path == forbidden or forbidden in path.parents:
            raise SafetyError("Output must be outside engine-loaded directories")
    return path
