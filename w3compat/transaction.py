"""Preview first, rederive candidates, back up all targets, journal every write."""
from contextlib import contextmanager
from datetime import datetime, timezone
import difflib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import uuid

from . import __version__
from .paths import SafetyError, game_root, output_directory, reject_links, safe_relative
from .scan import MAX_SCRIPT_BYTES, digest, markdown, scan
from .script import analyze, decode


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def atomic_write(path, data, mode=None):
    reject_links(path)
    fd, name = tempfile.mkstemp(prefix=".w3compat-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def read_manifest(directory, filename, kind):
    directory = reject_links(directory)
    path = safe_relative(directory, filename)
    if path.stat().st_size > 16 * 1024 * 1024:
        raise SafetyError("Manifest is too large")
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("schema_version") != 1 or document.get("kind") != kind or document.get("tool_version") != __version__:
        raise SafetyError("Unsupported manifest kind, schema or tool version")
    rows = document.get("files")
    if not isinstance(rows, list) or len(rows) > 10000:
        raise SafetyError("Invalid manifest file list")
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            raise SafetyError("Invalid file record")
        key = row["path"].casefold()
        if key in seen:
            raise SafetyError("Duplicate manifest target")
        seen.add(key)
        for field in ("before_sha256", "after_sha256"):
            if not isinstance(row.get(field), str) or not re.fullmatch(r"[0-9a-f]{64}", row[field]):
                raise SafetyError("Invalid SHA-256 in manifest")
        if row["before_sha256"] == row["after_sha256"]:
            raise SafetyError("Manifest contains a no-op target")
    return document


def windows_process_names():
    """Use Toolhelp rather than tasklist/WMI, which can fail in restricted hosts."""
    import ctypes
    from ctypes import wintypes

    class ProcessEntry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260)]

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    api.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    for method in (api.Process32FirstW, api.Process32NextW):
        method.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
        method.restype = wintypes.BOOL
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    handle = api.CreateToolhelp32Snapshot(2, 0)
    if handle in (None, ctypes.c_void_p(-1).value):
        raise SafetyError("Could not inspect Windows processes; mutation blocked")
    try:
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        if not api.Process32FirstW(handle, ctypes.byref(entry)):
            raise SafetyError("Could not read Windows process inventory; mutation blocked")
        names = []
        while True:
            names.append(entry.szExeFile.casefold())
            if not api.Process32NextW(handle, ctypes.byref(entry)):
                if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
                    raise SafetyError("Incomplete Windows process inventory; mutation blocked")
                break
        return names
    finally:
        api.CloseHandle(handle)


def require_game_closed():
    if os.name == "nt":
        names = windows_process_names()
    elif sys.platform.startswith("linux"):
        names = []
        for path in Path("/proc").glob("[0-9]*/comm"):
            try:
                names.append(path.read_text().strip().casefold())
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise SafetyError("Could not inspect Linux processes; mutation blocked") from exc
    else:
        raise SafetyError("Mutation process guard supports Windows/Linux only")
    if not names:
        raise SafetyError("Empty process inventory; mutation blocked")
    if any(name.startswith("witcher3") for name in names):
        raise SafetyError("Witcher 3 is running; apply/rollback is blocked")


@contextmanager
def operation_lock(root):
    path = reject_links(root / ".w3compat.lock")
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    stream = os.fdopen(fd, "r+b")
    try:
        if os.name == "nt":
            import msvcrt
            if path.stat().st_size == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise SafetyError("Another w3compat operation holds this game root") from exc
        else:
            import fcntl
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise SafetyError("Another w3compat operation holds this game root") from exc
        yield
    finally:
        # OS locks are released on close/crash. Keep the lock file to avoid
        # races from deleting and recreating a different inode.
        stream.close()


def stage(root, destination, settings_path=None):
    root = game_root(root)
    destination = output_directory(destination, root)
    if destination.exists():
        raise SafetyError("Stage destination already exists; choose a new directory")
    report = scan(root, settings_path)
    rows, diff = [], []
    for entry in report["scripts"]:
        if not entry.get("edits"):
            continue
        path = safe_relative(root, entry["path"], writable=True)
        original = path.read_bytes()
        if digest(original) != entry["sha256"]:
            raise SafetyError("Script changed during scan: " + entry["path"])
        candidate, edits, warnings = analyze(original)
        if warnings or not edits:
            raise SafetyError("Candidate is no longer reproducible")
        rows.append(dict(path=entry["path"], before_sha256=digest(original),
                         after_sha256=digest(candidate), edits=edits))
        before_text = decode(original)[0].splitlines(keepends=True)
        after_text = decode(candidate)[0].splitlines(keepends=True)
        diff.extend(difflib.unified_diff(before_text, after_text, fromfile=entry["path"], tofile=entry["path"] + " (candidate)"))
    destination.mkdir(parents=True, exist_ok=False)
    for row in rows:
        original = safe_relative(root, row["path"], writable=True).read_bytes()
        if digest(original) != row["before_sha256"]:
            raise SafetyError("Script changed while staging: " + row["path"])
        candidate = analyze(original)[0]
        for folder, content in (("original", original), ("candidate", candidate)):
            path = safe_relative(destination / folder, row["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    manifest = dict(schema_version=1, tool_version=__version__, kind="stage", rules=["function_local_set_map"], files=rows)
    (destination / "plan.json").write_bytes(json_bytes(manifest))
    (destination / "scan.json").write_bytes(json_bytes(report))
    (destination / "scan.md").write_text(markdown(report), encoding="utf-8", newline="\n")
    (destination / "preview.diff").write_text("".join(diff), encoding="utf-8", newline="")
    return dict(staged_files=len(rows), stage=str(destination), preview=str(destination / "preview.diff"))


def _writable_file(path):
    if not path.is_file() or path.stat().st_size > MAX_SCRIPT_BYTES:
        raise SafetyError("Missing, invalid or oversized target: " + path.name)
    info = path.stat()
    if not info.st_mode & stat.S_IWUSR or getattr(info, "st_file_attributes", 0) & 1:
        raise SafetyError("Read-only target is not changed: " + path.name)
    return stat.S_IMODE(info.st_mode)


def apply(root, staged, backup_parent):
    root = game_root(root)
    staged = output_directory(staged, root)
    backup_parent = output_directory(backup_parent, root)
    plan = read_manifest(staged, "plan.json", "stage")
    if not plan["files"]:
        return dict(applied_files=0, status="no_changes")
    require_game_closed()
    with operation_lock(root):
        prepared = []
        for row in plan["files"]:
            target = safe_relative(root, row["path"], writable=True)
            mode = _writable_file(target)
            original = target.read_bytes()
            saved = safe_relative(staged / "original", row["path"]).read_bytes()
            candidate = safe_relative(staged / "candidate", row["path"]).read_bytes()
            if digest(original) != row["before_sha256"] or original != saved or digest(candidate) != row["after_sha256"]:
                raise SafetyError("Source/stage hash mismatch: " + row["path"])
            regenerated, edits, warnings = analyze(original)
            if warnings or not edits or regenerated != candidate:
                raise SafetyError("Staged candidate is not the exact output of the supported rule")
            prepared.append((row, target, original, candidate, mode))
        transaction = backup_parent / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
        transaction.mkdir(parents=True, exist_ok=False)
        for row, target, original, candidate, mode in prepared:
            saved = safe_relative(transaction / "original", row["path"])
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, saved)
            if saved.read_bytes() != original:
                raise SafetyError("Backup verification failed before mutation")
        journal = dict(schema_version=1, tool_version=__version__, kind="transaction", status="prepared", files=plan["files"], applied=[], rolled_back=[])
        journal_path = transaction / "transaction.json"
        atomic_write(journal_path, json_bytes(journal))
        try:
            require_game_closed()
            for row, target, original, candidate, mode in prepared:
                if target.read_bytes() != original:
                    raise SafetyError("Target changed before write: " + row["path"])
                atomic_write(target, candidate, mode)
                if digest(target.read_bytes()) != row["after_sha256"]:
                    raise SafetyError("Post-write verification failed")
                journal["applied"].append(row["path"])
                atomic_write(journal_path, json_bytes(journal))
            journal["status"] = "committed"
        except Exception:
            # Recover only states whose exact bytes we know. An external edit
            # is preserved; the journal then supports explicit rollback later.
            recovered = True
            for row, target, original, candidate, mode in reversed(prepared):
                try:
                    current = target.read_bytes()
                    if current == candidate:
                        atomic_write(target, original, mode)
                    elif current != original:
                        recovered = False
                except OSError:
                    recovered = False
            journal["status"] = "aborted_restored" if recovered else "failed_partial"
            atomic_write(journal_path, json_bytes(journal))
            raise SafetyError("Apply failed; recovery status " + journal["status"] + "; journal: " + str(journal_path)) from None
        atomic_write(journal_path, json_bytes(journal))
        return dict(applied_files=len(prepared), status="committed", transaction=str(transaction))


def rollback(root, transaction, do_apply=False):
    root = game_root(root)
    transaction = output_directory(transaction, root)
    journal = read_manifest(transaction, "transaction.json", "transaction")
    if journal.get("status") not in ("prepared", "committed", "failed_partial", "aborted_restored", "rolling_back", "rolled_back"):
        raise SafetyError("Unsupported transaction state")

    def prepare():
        rows = []
        for row in journal["files"]:
            target = safe_relative(root, row["path"], writable=True)
            if not target.is_file():
                raise SafetyError("Rollback target is missing")
            original = safe_relative(transaction / "original", row["path"]).read_bytes()
            if digest(original) != row["before_sha256"]:
                raise SafetyError("Rollback backup hash mismatch")
            current = target.read_bytes()
            current_digest = digest(current)
            if current_digest not in (row["before_sha256"], row["after_sha256"]):
                raise SafetyError("Rollback would overwrite an external edit: " + row["path"])
            if current_digest == row["after_sha256"]:
                rows.append((row, target, original, _writable_file(target)))
        return rows

    if not do_apply:
        rows = prepare()
        return dict(status="dry_run", files_to_restore=len(rows), transaction=str(transaction))
    require_game_closed()
    with operation_lock(root):
        rows = prepare()
        journal["status"] = "rolling_back"
        atomic_write(transaction / "transaction.json", json_bytes(journal))
        for row, target, original, mode in rows:
            if digest(target.read_bytes()) != row["after_sha256"]:
                raise SafetyError("Rollback target changed before write")
            atomic_write(target, original, mode)
            if digest(target.read_bytes()) != row["before_sha256"]:
                raise SafetyError("Rollback post-write verification failed")
            journal.setdefault("rolled_back", []).append(row["path"])
            atomic_write(transaction / "transaction.json", json_bytes(journal))
        journal["status"] = "rolled_back"
        atomic_write(transaction / "transaction.json", json_bytes(journal))
        return dict(status="rolled_back", restored_files=len(rows), transaction=str(transaction))
