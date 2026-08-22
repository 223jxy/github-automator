"""docgen 模块测试。"""

import tempfile
import unittest
from pathlib import Path

from github_automator.analyzer import analyze
from github_automator.docgen import generate_readme, write_readme


class TestDocgen(unittest.TestCase):
    def _make_project(self, root: Path):
        (root / "main.py").write_text("print('hi')\n")
        (root / "package.json").write_text('{"dependencies":{"express":"4"}}')

    def test_readme_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "myproj"
            root.mkdir()
            self._make_project(root)
            info = analyze(root)
            md = generate_readme(info, repo_url="https://github.com/u/myproj")
            for sec in ("# myproj", "## 简介", "## 特性", "## 技术栈",
                        "## 目录结构", "## 安装", "## 用法", "## 许可证",
                        "## 发布", "https://github.com/u/myproj"):
                self.assertIn(sec, md)

    def test_write_readme_skips_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "myproj"
            root.mkdir()
            self._make_project(root)
            (root / "README.md").write_text("用户已有内容\n")
            info = analyze(root)
            p = write_readme(root, info)
            self.assertEqual(p.read_text(), "用户已有内容\n")
            # force 覆盖
            p2 = write_readme(root, info, force=True)
            self.assertIn("# myproj", p2.read_text())


if __name__ == "__main__":
    unittest.main()
