import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from contextlib import redirect_stdout

from w3compat.cli import main
from w3compat.scan import markdown, scan


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.root = self.base / "Game"
        self.owner = self.root / "Mods/modExample/content"
        self.owner.mkdir(parents=True)

    def tearDown(self):
        self.temporary.cleanup()

    def write_script(self, name, data=b"function F(set:bool) { value=set; }"):
        path = self.root / f"Mods/{name}/content/scripts/local/example.ws"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_inactive_and_configured_disabled_mods_are_excluded(self):
        self.write_script("modExample")
        self.write_script("~modInactive")
        settings = self.base / "mods.settings"
        settings.write_text("[modExample]\nEnabled=0\nPriority=10\n")
        report = scan(self.root, settings)
        self.assertEqual(report["summary"]["active_mods"], 0)
        self.assertFalse(report["scripts"])

    def test_duplicate_distinct_scripts_and_merged_output(self):
        self.write_script("modExample")
        self.write_script("mod0000_MergedFiles", b"function F(set:bool) { other=set; }")
        report = scan(self.root)
        duplicate = report["duplicate_scripts"][0]
        self.assertFalse(duplicate["identical"])
        self.assertTrue(duplicate["merged_output_present"])

    def test_resource_header_and_packed_coverage_are_explicit(self):
        (self.owner / "en.w3strings").write_bytes(b"RTSW" + struct.pack("<I", 162))
        (self.owner / "entity.w2ent").write_bytes(b"CR2W" + struct.pack("<I", 163))
        bundle = bytearray(32)
        bundle[:8] = b"POTATO70"
        struct.pack_into("<H", bundle, 20, 5)
        (self.owner / "example.bundle").write_bytes(bundle)
        report = scan(self.root)
        codes = {row["code"] for row in report["findings"]}
        self.assertTrue({"strings_format_review", "cr2w_format_review", "packed_resources_uninspected"} <= codes)
        self.assertFalse(report["coverage"]["packed_payloads"])

    def test_bad_script_is_diagnostic_not_a_crash(self):
        self.write_script("modExample", b"function F() {")
        report = scan(self.root)
        self.assertEqual(report["summary"]["fixable_files"], 0)
        self.assertTrue(any(row["code"] == "script_analysis_blocked" for row in report["findings"]))

    def test_official_dlc_and_native_scripts_are_not_inspected(self):
        self.write_script("modExample")
        for relative in ("dlc/ep1/content/scripts/local/example.ws", "content/content0/scripts/local/example.ws"):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"function F(set:bool) {}")
        self.assertEqual(len(scan(self.root)["scripts"]), 1)

    def test_custom_dlc_without_dlc_prefix_is_supported(self):
        path = self.root / "dlc/ExampleCustom/content/scripts/local/example.ws"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"function F(map:int) {}")
        self.assertEqual(scan(self.root)["summary"]["active_custom_dlc"], 1)

    def test_bundled_example_script_is_not_a_compatibility_error(self):
        path = self.owner.parent / "example/main.ws"
        path.parent.mkdir()
        path.write_bytes(b"function Example(set:bool) {}")
        report = scan(self.root)
        self.assertFalse(report["scripts"])
        self.assertTrue(any(f["code"] == "non_loaded_script_skipped" and f["severity"] == "info" for f in report["findings"]))

    def test_report_excludes_absolute_paths_and_source_text(self):
        self.write_script("modExample")
        report = scan(self.root)
        encoded = json.dumps(report)
        self.assertNotIn(str(self.root), encoded)
        self.assertNotIn("function F(set", encoded)
        self.assertIn("A clean scan does not establish", markdown(report))

    def test_cli_scan(self):
        self.write_script("modExample")
        destination = self.base / "scan"
        with redirect_stdout(io.StringIO()):
            code = main(["scan", "--game-root", str(self.root), "--out", str(destination)])
        self.assertEqual(code, 0)
        self.assertTrue((destination / "scan.md").is_file())
        self.assertTrue((destination / "scan.json").is_file())


if __name__ == "__main__":
    unittest.main()
