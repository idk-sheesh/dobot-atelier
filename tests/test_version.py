import ast
import os
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class VersionTests(unittest.TestCase):
    def setUp(self):
        tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
        self.version = next(ast.literal_eval(node.value) for node in tree.body
                            if isinstance(node, ast.Assign)
                            and any(isinstance(target, ast.Name) and target.id == "APP_VERSION"
                                    for target in node.targets))

    def test_source_readme_and_windows_metadata_agree(self):
        self.assertIn(f"**{self.version}**", (ROOT / "README.md").read_text(encoding="utf-8"))
        tree = ast.parse((ROOT / "version_info.txt").read_text(encoding="utf-8"))
        expected = tuple(int(value) for value in self.version.split(".")) + (0,)
        found = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id == "FixedFileInfo":
                for key in node.keywords:
                    if key.arg in {"filevers", "prodvers"}:
                        self.assertEqual(ast.literal_eval(key.value), expected)
                        found.add(key.arg)
            if node.func.id == "StringStruct" and ast.literal_eval(node.args[0]) in {"FileVersion", "ProductVersion"}:
                self.assertEqual(ast.literal_eval(node.args[1]), self.version)
                found.add(ast.literal_eval(node.args[0]))
        self.assertEqual(found, {"filevers", "prodvers", "FileVersion", "ProductVersion"})

    @unittest.skipUnless(os.environ.get("GITHUB_REF_TYPE") == "tag", "not a tag build")
    def test_release_tag_matches_source(self):
        self.assertEqual(os.environ.get("GITHUB_REF_NAME"), f"v{self.version}")


if __name__ == "__main__":
    unittest.main()
