"""cli 模块测试：重点验证 --dry-run 真正只读、不落盘。"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from github_automator.cli import run, _git_add_safe


class TestCliDryRun(unittest.TestCase):
    def _make_project(self, root: Path):
        (root / "main.py").write_text("print('hi')\n")
        (root / "package.json").write_text('{"dependencies":{"express":"4"}}')

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "myproj"
            root.mkdir()
            self._make_project(root)
            rc = run(root, repo="myproj", version="v1.0.0", private=False,
                     token=None, message="x", make_release=False, dry_run=True,
                     force_readme=False)
            self.assertEqual(rc, 0)
            # dry-run 不应创建任何文件 / 目录
            self.assertFalse((root / ".gitignore").exists())
            self.assertFalse((root / "README.md").exists())
            self.assertFalse((root / "dist").exists())


class TestGitAddSafe(unittest.TestCase):
    """_git_add_safe 安全暂存契约：永不 add .workbuddy / dist / .git 内部文件。"""

    def test_never_adds_workbuddy(self):
        # 构造含敏感目录的项目（含一个已存在的 .workbuddy 文件，模拟历史 tracked）
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "p"
            root.mkdir()
            (root / "main.py").write_text("print(1)\n")
            (root / ".workbuddy").mkdir()
            (root / ".workbuddy" / "memory.md").write_text("secret local notes\n")
            (root / "dist").mkdir()
            (root / "dist" / "x.zip").write_text("asset\n")

            added = []
            def fake_git(args, cwd=None, check=True):
                if args[:1] == ["add"]:
                    added.append(args[1])
                return mock.MagicMock(returncode=0, stdout="", stderr="")

            with mock.patch("github_automator.cli._git", side_effect=fake_git):
                _git_add_safe(root)
            # 断言：源码被加，敏感目录绝不被加
            self.assertIn(str(root / "main.py"), added)
            self.assertNotIn(str(root / ".workbuddy" / "memory.md"), added)
            self.assertNotIn(str(root / "dist" / "x.zip"), added)
            for a in added:
                self.assertNotIn(".workbuddy", Path(a).parts)
                self.assertNotIn("dist", Path(a).parts)

    def test_adds_source_respecting_gitignore(self):
        # 自定义 .gitignore 排除 secret.txt，应不被加
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "p"
            root.mkdir()
            (root / "main.py").write_text("print(1)\n")
            (root / ".gitignore").write_text("secret.txt\n")
            (root / "secret.txt").write_text("top secret\n")

            added = []
            def fake_git(args, cwd=None, check=True):
                if args[:1] == ["add"]:
                    added.append(args[1])
                return mock.MagicMock(returncode=0, stdout="", stderr="")

            with mock.patch("github_automator.cli._git", side_effect=fake_git):
                _git_add_safe(root)
            self.assertIn(str(root / "main.py"), added)
            self.assertNotIn(str(root / "secret.txt"), added)


if __name__ == "__main__":
    unittest.main()
