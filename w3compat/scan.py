"""Read-only inventory and explicitly bounded compatibility diagnostics."""
from collections import Counter, defaultdict
import configparser
import hashlib
from pathlib import Path
import struct

from . import __version__
from .paths import OFFICIAL_DLC, game_root, is_link, reject_links, safe_relative, walk_files
from .script import analyze, decode

MAX_SCRIPT_BYTES = 8 * 1024 * 1024


def digest(data):
    return hashlib.sha256(data).hexdigest()


def mod_settings(path):
    if path is None:
        return {}
    reject_links(path)
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.read_string(decode(Path(path).read_bytes())[0])
    return {name.casefold(): dict(parser[name]) for name in parser.sections()}


def catalog(root, settings=None):
    root = game_root(root)
    settings = settings or {}
    owners, skipped = [], []
    for kind in ("Mods", "dlc"):
        folder = root / kind
        if not folder.is_dir():
            continue
        reject_links(folder)
        for directory in sorted(folder.iterdir()):
            if is_link(directory):
                skipped.append(f"{kind}/{directory.name}")
                continue
            if not directory.is_dir():
                continue
            name = directory.name
            inferred = name.lower().startswith("mod") if kind == "Mods" else name.lower() not in OFFICIAL_DLC and not name.startswith("~")
            configured = settings.get(name.casefold(), {}).get("enabled", "1") != "0"
            owners.append(dict(path=f"{kind}/{name}", name=name, kind=kind, active=inferred and configured,
                               priority=settings.get(name.casefold(), {}).get("priority")))
    return owners, skipped


def scan(root, settings_path=None, expected_cr2w=164, expected_strings=164):
    root = game_root(root)
    owners, skipped = catalog(root, mod_settings(settings_path))
    findings, scripts, formats = [], [], []
    overrides = defaultdict(list)
    file_count = 0

    def finding(code, path, detail, severity="warning", **extra):
        findings.append(dict(code=code, severity=severity, path=path, detail=detail, **extra))

    for path in skipped:
        finding("linked_directory_skipped", path, "Link/reparse-point directory was not traversed; coverage is incomplete")
    for owner in owners:
        if not owner["active"]:
            continue
        owner_path = safe_relative(root, owner["path"])
        if "sss" in owner["name"].casefold():
            finding("talent_tree_review", owner["path"], "SSS-named mod detected. Old talent-tree integration needs a specific adapter; the tool does not disable it.")
        for path in walk_files(owner_path):
            file_count += 1
            relative = path.relative_to(root).as_posix()
            suffix = path.suffix.lower()
            try:
                if suffix == ".ws":
                    if tuple(relative.split("/")[2:4]) != ("content", "scripts"):
                        finding("non_loaded_script_skipped", relative, "Example/tool script outside content/scripts; excluded from engine-script analysis", "info")
                        continue
                    safe_relative(root, relative, writable=True)
                    if path.stat().st_size > MAX_SCRIPT_BYTES:
                        finding("script_too_large", relative, "Script exceeds the 8 MiB inspection limit", "error")
                        continue
                    data = path.read_bytes()
                    row = dict(path=relative, sha256=digest(data), bytes=len(data))
                    scripts.append(row)
                    key = "/".join(relative.split("/")[4:]).casefold()
                    overrides[key].append(relative)
                    try:
                        candidate, edits, warnings = analyze(data)
                        row["edits"] = edits
                        row["candidate_sha256"] = digest(candidate)
                        for warning in warnings:
                            warning = dict(warning)
                            code = warning.pop("code")
                            reason = warning.pop("reason")
                            finding(code, relative, reason, **warning)
                        if edits:
                            finding("reserved_identifier_fixable", relative, "Unambiguous function parameter/local declaration and references can be renamed", edits=len(edits))
                        for critical in ("characterMenu.ws", "PlayerAbilityManager.ws", "playerWitcher.ws", "inventoryComponent.ws"):
                            if path.name.casefold() == critical.casefold():
                                finding("critical_override_review", relative, "Core character/inventory override detected. Compilation does not validate inventory, talents or menu behavior.", "info")
                    except (ValueError, UnicodeError) as exc:
                        row["edits"] = []
                        finding("script_analysis_blocked", relative, str(exc), "error")
                elif suffix == ".w3strings":
                    with path.open("rb") as stream:
                        header = stream.read(8)
                    if len(header) != 8 or header[:4] != b"RTSW":
                        finding("invalid_strings_header", relative, "Unrecognized localization header", "error")
                    else:
                        version = struct.unpack_from("<I", header, 4)[0]
                        formats.append(dict(path=relative, kind="w3strings", version=version))
                        if version != expected_strings:
                            finding("strings_format_review", relative, f"Header version {version}; reference expectation {expected_strings}. Conversion is not implemented in v0.1.")
                elif suffix == ".bundle":
                    with path.open("rb") as stream:
                        header = stream.read(32)
                    if len(header) < 22 or header[:8] != b"POTATO70":
                        finding("bundle_header_unknown", relative, "Bundle header is unsupported; packed resources are not inspected")
                    else:
                        formats.append(dict(path=relative, kind="bundle", version=struct.unpack_from("<H", header, 20)[0]))
                        finding("packed_resources_uninspected", relative, "Bundle index/payload is not decoded in v0.1. Packed script/XML/CR2W/UI compatibility is outside scan coverage.", "info")
                else:
                    with path.open("rb") as stream:
                        header = stream.read(8)
                    if len(header) == 8 and header[:4] == b"CR2W":
                        version = struct.unpack_from("<I", header, 4)[0]
                        formats.append(dict(path=relative, kind="cr2w", version=version))
                        if version != expected_cr2w:
                            finding("cr2w_format_review", relative, f"Header version {version}; reference expectation {expected_cr2w}. A mismatch alone does not prove failure; recooking is not implemented.")
            except (OSError, ValueError) as exc:
                detail = (exc.strerror or "Filesystem inspection failed") if isinstance(exc, OSError) else str(exc)
                finding("file_uninspected", relative, type(exc).__name__ + ": " + detail, "error")

    duplicate_rows = []
    for key, paths in sorted(overrides.items()):
        if len(paths) < 2:
            continue
        values = {row["path"]: row["sha256"] for row in scripts if row["path"] in paths}
        identical = len(set(values.values())) == 1
        merged = any("mergedfiles" in p.split("/")[1].casefold() for p in paths)
        duplicate_rows.append(dict(script=key, paths=paths, identical=identical, merged_output_present=merged))
        finding("duplicate_script_override", paths[0], "Multiple active loose scripts share an engine path; this tool does not decide load order or verify a merge.", "info" if identical else "warning", paths=paths, merged_output_present=merged)
    active = [owner for owner in owners if owner["active"]]
    return dict(schema_version=1, tool_version=__version__, target="Witcher 3 5.x",
                expectations=dict(cr2w=expected_cr2w, w3strings=expected_strings),
                coverage=dict(loose_scripts=True, loose_resource_headers=True, packed_payloads=False,
                              native_script_rebase=False, save_data=False, runtime_test=False,
                              activation="mods.settings + folder names" if settings_path else "folder names only; enabled/priority settings were not read"),
                owners=owners, scripts=scripts, formats=formats, duplicate_scripts=duplicate_rows,
                findings=findings, summary=dict(active_mods=sum(o["kind"] == "Mods" for o in active),
                    active_custom_dlc=sum(o["kind"] == "dlc" for o in active), files_inspected=file_count,
                    scripts_inspected=len(scripts), fixable_files=sum(bool(row.get("edits")) for row in scripts),
                    findings_by_severity=dict(Counter(f["severity"] for f in findings))))


def markdown(report):
    lines = ["# Witcher 3 compatibility scan", "", f"Tool: {report['tool_version']} | Target: {report['target']}", "",
             "A clean scan does not establish game compatibility. Launch the game and verify menus and an existing save separately.", "",
             "## Coverage", "", "```json", __import__("json").dumps(report["coverage"], indent=2), "```", "",
             "## Summary", "", "```json", __import__("json").dumps(report["summary"], indent=2), "```", "",
             "## Findings", "", "| Severity | Code | Relative path | Detail |", "| --- | --- | --- | --- |"]
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ")
    for row in report["findings"]:
        lines.append("| " + " | ".join(cell(row[k]) for k in ("severity", "code", "path", "detail")) + " |")
    if not report["findings"]:
        lines.extend(["", "No findings within the documented scan coverage."])
    return "\n".join(lines) + "\n"
