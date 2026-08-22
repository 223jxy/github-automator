"""cli 模块测试：重点验证 --dry-run 真正只读、不落盘。"""

import tempfile
import unittest
from pathlib import Path

from github_automator.cli import run


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


if __name__ == "__main__":
    unittest.main()
