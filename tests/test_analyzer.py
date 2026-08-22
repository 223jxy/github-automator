"""analyzer 模块测试。"""

import tempfile
import unittest
from pathlib import Path

from github_automator.analyzer import analyze, build_tree


class TestAnalyzer(unittest.TestCase):
    def _make_project(self, root: Path):
        (root / "main.py").write_text("print('hi')\n")
        (root / "util.py").write_text("def f(): pass\n")
        (root / "package.json").write_text(
            '{"name":"x","dependencies":{"express":"4.0.0","react":"18.0.0"}}'
        )
        (root / "README.md").write_text("# Demo\n一句话说明项目用途。\n")
        (root / "LICENSE").write_text("MIT\n")
        sub = root / "src"
        sub.mkdir()
        (sub / "core.py").write_text("x = 1\n")

    def test_language_and_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "myproj"
            root.mkdir()
            self._make_project(root)
            info = analyze(root)
            self.assertIn("Python", info.languages)
            self.assertEqual(info.primary_language, "Python")
            self.assertIn("main.py", info.entry_points)
            self.assertTrue(info.has_readme)
            self.assertTrue(info.has_license)

    def test_manifest_parse(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "myproj"
            root.mkdir()
            self._make_project(root)
            info = analyze(root)
            self.assertIn("package.json", info.manifests)
            self.assertIn("express", info.manifests["package.json"])
            self.assertIn("Node.js", info.ecosystems)

    def test_description_from_readme(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "myproj"
            root.mkdir()
            self._make_project(root)
            info = analyze(root)
            self.assertIn("项目用途", info.description)

    def test_tree_contains_root_and_subdir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "myproj"
            root.mkdir()
            self._make_project(root)
            tree = build_tree(root, max_depth=3)
            self.assertIn("myproj/", tree)
            self.assertIn("src/", tree)


if __name__ == "__main__":
    unittest.main()
