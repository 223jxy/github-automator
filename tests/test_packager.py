"""packager 模块测试。"""

import tempfile
import unittest
import zipfile
from pathlib import Path

from github_automator.analyzer import analyze
from github_automator.packager import (
    GitignoreMatcher,
    generate_gitignore,
    make_release_zip,
    should_include,
    write_gitignore,
)


class TestPackager(unittest.TestCase):
    def _make_project(self, root: Path):
        (root / "main.py").write_text("print('hi')\n")
        (root / "package.json").write_text('{"dependencies":{"express":"4"}}')
        (root / ".env").write_text("SECRET=1\n")
        (root / "node_modules").mkdir()
        (root / "node_modules" / "x.js").write_text("// big\n")
        (root / ".gitignore").write_text("what\n")

    def test_gitignore_has_node_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "p"
            root.mkdir()
            self._make_project(root)
            info = analyze(root)
            gi = generate_gitignore(info)
            self.assertIn("node_modules/", gi)
            self.assertIn(".env", gi)

    def test_write_gitignore_skips_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "p"
            root.mkdir()
            self._make_project(root)  # 已有 .gitignore
            info = analyze(root)
            p = write_gitignore(root, info)
            self.assertEqual(p.read_text(), "what\n")  # 未被覆盖

    def test_release_zip_excludes_junk(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "p"
            root.mkdir()
            self._make_project(root)
            info = analyze(root)
            zp = make_release_zip(root, info, "v1.0.0", root / "dist")
            self.assertTrue(zp.exists())
            with zipfile.ZipFile(zp) as zf:
                names = zf.namelist()
            self.assertTrue(any(n.endswith("main.py") for n in names))
            self.assertFalse(any("node_modules" in n for n in names))
            self.assertFalse(any(n.endswith(".env") for n in names))

    def test_should_include_filters(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "p"
            root.mkdir()
            self._make_project(root)
            self.assertTrue(should_include(root / "main.py", root))
            self.assertFalse(should_include(root / ".env", root))
            self.assertFalse(should_include(root / "node_modules" / "x.js", root))

    def test_should_include_keeps_config_dotfiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "p"
            root.mkdir()
            self._make_project(root)
            # 配置型点文件应保留，密钥型点文件应排除
            (root / ".editorconfig").write_text("# editor config\n")
            (root / ".env").write_text("SECRET=1\n")
            (root / ".env.production").write_text("SECRET=2\n")
            self.assertTrue(should_include(root / ".editorconfig", root))
            self.assertFalse(should_include(root / ".env", root))
            self.assertFalse(should_include(root / ".env.production", root))

    def test_write_gitignore_force_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "p"
            root.mkdir()
            self._make_project(root)  # 已有 .gitignore ("what\n")
            info = analyze(root)
            p = write_gitignore(root, info, force=True)
            # force 时覆盖为工具生成内容（含生态片段）
            self.assertIn("node_modules/", p.read_text())

    def test_release_zip_respects_custom_gitignore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "p"
            root.mkdir()
            self._make_project(root)
            # 项目自定义忽略规则
            (root / ".gitignore").write_text("secret.txt\ndata/\n*.log\n")
            (root / "secret.txt").write_text("top secret\n")
            (root / "data").mkdir()
            (root / "data" / "x.csv").write_text("1,2,3\n")
            (root / "debug.log").write_text("noise\n")
            info = analyze(root)
            zp = make_release_zip(root, info, "v1.0.0", root / "dist")
            with zipfile.ZipFile(zp) as zf:
                names = zf.namelist()
            self.assertTrue(any(n.endswith("main.py") for n in names))
            self.assertFalse(any("secret.txt" in n for n in names))
            self.assertFalse(any("/data/" in n or n.endswith("/data") for n in names))
            self.assertFalse(any(n.endswith("debug.log") for n in names))

    def test_gitignore_matcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "p"
            root.mkdir()
            (root / ".gitignore").write_text("build/\n*.tmp\n!keep.tmp\n")
            m = GitignoreMatcher(root)
            self.assertTrue(m.ignored("build/a.o"))
            self.assertTrue(m.ignored("sub/build/a.o"))
            self.assertTrue(m.ignored("x.tmp"))
            self.assertFalse(m.ignored("keep.tmp"))  # 否定规则重新包含
            self.assertFalse(m.ignored("main.py"))


if __name__ == "__main__":
    unittest.main()
