import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from w3compat.paths import SafetyError, safe_relative
from w3compat.scan import digest
from w3compat.transaction import apply, atomic_write, require_game_closed, rollback, stage


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.root = self.base / "Game"
        self.source = self.root / "Mods/modExample/content/scripts/local/example.ws"
        self.source.parent.mkdir(parents=True)
        self.original = b"function Toggle(set:bool) { enabled=set; }\r\n"
        self.source.write_bytes(self.original)
        self.stage = self.base / "stage"
        self.backups = self.base / "transactions"

    def tearDown(self):
        self.temporary.cleanup()

    def prepare(self):
        return stage(self.root, self.stage)

    def commit(self):
        self.prepare()
        with patch("w3compat.transaction.require_game_closed"):
            return apply(self.root, self.stage, self.backups)

    def test_stage_is_read_only_and_no_overwrite(self):
        result = self.prepare()
        self.assertEqual(result["staged_files"], 1)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertIn("+function Toggle(w3compatSet", (self.stage / "preview.diff").read_text())
        with self.assertRaises(SafetyError):
            self.prepare()

    def test_apply_and_exact_rollback(self):
        result = self.commit()
        self.assertEqual(result["status"], "committed")
        self.assertNotEqual(self.source.read_bytes(), self.original)
        transaction = Path(result["transaction"])
        preview = rollback(self.root, transaction)
        self.assertEqual(preview["status"], "dry_run")
        self.assertNotEqual(self.source.read_bytes(), self.original)
        with patch("w3compat.transaction.require_game_closed"):
            restored = rollback(self.root, transaction, True)
        self.assertEqual(restored["restored_files"], 1)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(rollback(self.root, transaction)["files_to_restore"], 0)

    def test_source_drift_blocks_apply(self):
        self.prepare()
        self.source.write_bytes(self.original + b"// external\n")
        with patch("w3compat.transaction.require_game_closed"), self.assertRaises(SafetyError):
            apply(self.root, self.stage, self.backups)
        self.assertFalse(self.backups.exists())

    def test_recomputed_candidate_blocks_tamper_even_with_matching_hash(self):
        self.prepare()
        plan_path = self.stage / "plan.json"
        plan = json.loads(plan_path.read_text())
        candidate = self.stage / "candidate" / plan["files"][0]["path"]
        malicious = candidate.read_bytes() + b"function UnrelatedChange() {}"
        candidate.write_bytes(malicious)
        plan["files"][0]["after_sha256"] = digest(malicious)
        plan_path.write_text(json.dumps(plan))
        with patch("w3compat.transaction.require_game_closed"), self.assertRaises(SafetyError):
            apply(self.root, self.stage, self.backups)
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_rollback_preserves_external_edits(self):
        result = self.commit()
        self.source.write_bytes(b"function ExternalEdit() {}")
        with self.assertRaises(SafetyError):
            rollback(self.root, Path(result["transaction"]), True)
        self.assertEqual(self.source.read_bytes(), b"function ExternalEdit() {}")

    def test_backup_tamper_blocks_rollback(self):
        result = self.commit()
        saved = Path(result["transaction"]) / "original/Mods/modExample/content/scripts/local/example.ws"
        saved.write_bytes(b"bad backup")
        with self.assertRaises(SafetyError):
            rollback(self.root, Path(result["transaction"]))

    def test_paths_native_saves_traversal_rejected(self):
        for relative in ("../outside.ws", "/outside.ws", "Mods/modExample/../../outside.ws", "C:/file.ws", "Mods\\modExample\\file.ws", "content/content0/scripts/example.ws", "Mods/~modExample/content/scripts/example.ws", "dlc/ep1/content/scripts/example.ws", "Mods/modExample/content/scripts/example.sav"):
            with self.subTest(relative=relative), self.assertRaises(SafetyError):
                safe_relative(self.root, relative, writable=True)

    def test_stage_inside_mods_rejected(self):
        with self.assertRaises(SafetyError):
            stage(self.root, self.root / "Mods/modExample/stage")

    def test_readonly_file_rejected(self):
        self.prepare()
        self.source.chmod(0o444)
        try:
            with patch("w3compat.transaction.require_game_closed"), self.assertRaises(SafetyError):
                apply(self.root, self.stage, self.backups)
        finally:
            self.source.chmod(0o644)

    def test_running_game_blocks_apply(self):
        self.prepare()
        with patch("w3compat.transaction.require_game_closed", side_effect=SafetyError("running")), self.assertRaises(SafetyError):
            apply(self.root, self.stage, self.backups)
        self.assertEqual(self.source.read_bytes(), self.original)

    @unittest.skipUnless(os.name == "nt", "Windows process guard")
    def test_windows_game_name_detection(self):
        with patch("w3compat.transaction.windows_process_names", return_value=["other.exe", "witcher3.exe"]), self.assertRaises(SafetyError):
            require_game_closed()
        with patch("w3compat.transaction.windows_process_names", return_value=["other.exe"]):
            require_game_closed()

    @unittest.skipUnless(os.name == "nt", "Windows process guard")
    def test_process_inventory_failure_stops_mutation(self):
        with patch("w3compat.transaction.windows_process_names", side_effect=SafetyError("failed")), self.assertRaises(SafetyError):
            require_game_closed()
        with patch("w3compat.transaction.windows_process_names", return_value=[]), self.assertRaises(SafetyError):
            require_game_closed()

    def test_failed_second_write_restores_first(self):
        second = self.source.with_name("second.ws")
        second.write_bytes(self.original)
        self.prepare()

        def injected(path, data, mode=None):
            if path == second and b"w3compatSet" in data:
                raise OSError("injected write failure")
            return atomic_write(path, data, mode)

        with patch("w3compat.transaction.require_game_closed"), patch("w3compat.transaction.atomic_write", side_effect=injected), self.assertRaises(SafetyError):
            apply(self.root, self.stage, self.backups)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(second.read_bytes(), self.original)
        journals = list(self.backups.glob("*/transaction.json"))
        self.assertEqual(json.loads(journals[0].read_text())["status"], "aborted_restored")

    def test_interrupted_apply_can_rollback_from_prepared_journal(self):
        result = self.commit()
        transaction = Path(result["transaction"])
        journal_path = transaction / "transaction.json"
        journal = json.loads(journal_path.read_text())
        journal["status"], journal["applied"] = "prepared", []
        journal_path.write_text(json.dumps(journal))
        with patch("w3compat.transaction.require_game_closed"):
            rollback(self.root, transaction, True)
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_duplicate_manifest_target_is_rejected(self):
        self.prepare()
        path = self.stage / "plan.json"
        plan = json.loads(path.read_text())
        plan["files"].append(dict(plan["files"][0]))
        path.write_text(json.dumps(plan))
        with self.assertRaises(SafetyError):
            apply(self.root, self.stage, self.backups)

    def test_symlink_target_is_rejected(self):
        target = self.base / "external.ws"
        target.write_bytes(self.original)
        link = self.source.with_name("linked.ws")
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest("Creating symlinks requires additional Windows privileges")
        with self.assertRaises(SafetyError):
            safe_relative(self.root, link.relative_to(self.root).as_posix(), writable=True)


if __name__ == "__main__":
    unittest.main()
