import unittest

from w3compat.script import ScriptError, analyze


class ScriptTests(unittest.TestCase):
    def run_rule(self, text):
        result, edits, warnings = analyze(text.encode("utf-8"))
        return result.decode("utf-8"), edits, warnings

    def test_parameter_and_references(self):
        result, edits, warnings = self.run_rule("function Toggle(optional set : bool) { flag = set; if (set) flag = false; }")
        self.assertEqual(result, "function Toggle(optional w3compatSet : bool) { flag = w3compatSet; if (w3compatSet) flag = false; }")
        self.assertEqual(len(edits), 3)
        self.assertEqual(warnings, [])

    def test_import_parameter(self):
        result, edits, warnings = self.run_rule("import final function Toggle(out map : array<int>);")
        self.assertIn("out w3compatMap : array<int>", result)
        self.assertEqual(len(edits), 1)
        self.assertFalse(warnings)

    def test_local_comma_declaration_and_nested_blocks(self):
        result, edits, warnings = self.run_rule("function F() { var a, map, b : array<int>; if (ok) { map.Clear(); } a = map; }")
        self.assertEqual(len(edits), 3)
        self.assertNotIn("map", result)
        self.assertFalse(warnings)

    def test_only_affected_function_is_changed(self):
        result, _, warnings = self.run_rule("function F(set:bool) { value=set; } function G() { obj.set = false; }")
        self.assertIn("value=w3compatSet", result)
        self.assertIn("obj.set = false", result)
        self.assertFalse(warnings)

    def test_comments_literals_and_members_preserved(self):
        text = "function F(set:bool) { // set\r\n /* map set */ name='set'; s=\"map \\\" set\"; obj.set=set; }"
        result, edits, warnings = self.run_rule(text)
        self.assertIn("// set\r\n /* map set */ name='set'; s=\"map \\\" set\";", result)
        self.assertIn("obj.set=w3compatSet", result)
        self.assertEqual(len(edits), 2)
        self.assertFalse(warnings)

    def test_collection_types_are_preserved(self):
        text = "var values : map<name, array<int>>; function F(data: set<name>) { data.Clear(); }"
        result, edits, warnings = self.run_rule(text)
        self.assertEqual(result, text)
        self.assertFalse(edits)
        self.assertFalse(warnings)

    def test_mixed_type_and_value_is_manual(self):
        text = "function F(map:bool) { var table : map<name, int>; flag=map; }"
        result, edits, warnings = self.run_rule(text)
        self.assertEqual(result, text)
        self.assertFalse(edits)
        self.assertTrue(warnings)

    def test_class_field_blocks_partial_changes(self):
        text = "class Example { saved var set : bool; function F(map:int) { x=map; } }"
        result, edits, warnings = self.run_rule(text)
        self.assertEqual(result, text)
        self.assertFalse(edits)
        self.assertTrue(warnings)

    def test_function_named_reserved_is_manual(self):
        text = "function set() { return; }"
        result, edits, warnings = self.run_rule(text)
        self.assertEqual(result, text)
        self.assertFalse(edits)
        self.assertTrue(warnings)

    def test_shadowing_is_manual(self):
        text = "function F(set:bool) { if (ok) { var set : bool; set=false; } }"
        result, edits, warnings = self.run_rule(text)
        self.assertEqual(result, text)
        self.assertFalse(edits)
        self.assertTrue(warnings)

    def test_collision_anywhere_in_file(self):
        text = "var W3COMPATSET : bool; function F(set:bool) { x=set; }"
        result, edits, warnings = self.run_rule(text)
        self.assertEqual(result, text)
        self.assertFalse(edits)
        self.assertTrue(warnings)

    def test_utf_encodings_and_line_endings_preserved(self):
        text = "function F(set:bool) {\r\n s=\"中文😀\"; x=set;\r\n}\r\n"
        for encoding, bom in (("utf-8", b""), ("utf-8", b"\xef\xbb\xbf"), ("utf-16-le", b"\xff\xfe"), ("utf-16-be", b"\xfe\xff")):
            with self.subTest(encoding=encoding, bom=bom):
                result, edits, warnings = analyze(bom + text.encode(encoding))
                self.assertEqual(result, bom + text.replace("set:bool", "w3compatSet:bool").replace("x=set", "x=w3compatSet").encode(encoding))
                self.assertEqual(len(edits), 2)
                self.assertFalse(warnings)

    def test_legacy_encoding_is_not_guessed(self):
        with self.assertRaises(UnicodeDecodeError):
            analyze(b'function F() { s="\x96"; }')
        with self.assertRaises(ScriptError):
            analyze("function F() {}".encode("utf-16-le"))

    def test_malformed_sources_rejected(self):
        for text in ("/* broken", "function F() { x='broken; }", "function F() {", "<<<<<<< ours\nfunction F() {}", "function F(set) {}"):
            with self.subTest(text=text):
                if text.endswith("(set) {}"):
                    result, edits, warnings = self.run_rule(text)
                    self.assertTrue(warnings)
                    self.assertFalse(edits)
                else:
                    with self.assertRaises(ScriptError):
                        self.run_rule(text)

    def test_idempotent(self):
        first, _, _ = self.run_rule("function F(map:int) { x=map; }")
        second, edits, warnings = self.run_rule(first)
        self.assertEqual(first, second)
        self.assertFalse(edits)
        self.assertFalse(warnings)

    def test_line_numbers(self):
        _, edits, _ = self.run_rule("\nfunction F(set:bool) {\n x=set;\n}")
        self.assertEqual([edit["line"] for edit in edits], [2, 3])


if __name__ == "__main__":
    unittest.main()
