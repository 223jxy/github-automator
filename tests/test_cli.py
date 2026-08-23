"""cli 模块测试：重点验证 --dry-run 真正只读、不落盘，以及发布不污染源项目。"""

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


def _fake_repo_info(name: str, exists: bool = False) -> dict:
    return {"owner": "tester", "repo": name,
            "clone_url": f"https://github.com/tester/{name}.git",
            "html_url": f"https://github.com/tester/{name}",
            "exists": exists}


class TestRunDoesNotPolluteSource(unittest.TestCase):
    """发布修复验证：源项目保持只读，不产生 .git / dist；Release 打到正确仓库。

    模拟网络相关函数（create_repo / push / create_release / get_authenticated_user），
    真实执行 git init/commit 于临时目录，验证源项目零污染 + create_release 收到 cwd。
    """

    def _make_project(self, root: Path):
        (root / "main.py").write_text("print('hello')\n")
        (root / "README.md").write_text("# demo\n")
        (root / "dist").mkdir()
        (root / "dist" / "old.zip").write_text("stale asset\n")  # 源项目已有 dist（未跟踪）

    def test_source_project_untouched_no_git_no_dist_added(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "myproj"
            root.mkdir()
            self._make_project(root)
            before = sorted(p.name for p in root.iterdir())

            captured = {}
            with mock.patch("github_automator.cli.create_repo",
                            return_value=_fake_repo_info("myproj")), \
                 mock.patch("github_automator.cli.push", return_value=None), \
                 mock.patch("github_automator.cli.get_authenticated_user",
                            return_value="tester"), \
                 mock.patch("github_automator.cli.create_release",
                            side_effect=lambda **kw: captured.update(kw) or "https://x"):
                rc = run(root, repo="myproj", version="v1.0.0", private=False,
                         token=None, message="x", make_release=True, dry_run=False,
                         force_readme=False)

            self.assertEqual(rc, 0)
            # 源项目不应被 git 化，也不应新增 .git
            self.assertFalse((root / ".git").exists())
            # 源项目文件集合不应因发布而增加（dist/old.zip 本就存在，不算新增）
            after = sorted(p.name for p in root.iterdir())
            self.assertEqual(before, after)
            # 关键：create_release 必须收到 cwd（临时发布目录），而非工具自身目录，
            # 否则 gh 会把 Release 误打到工具仓库
            self.assertIn("cwd", captured)
            self.assertIsNotNone(captured["cwd"])
            self.assertNotEqual(Path(captured["cwd"]), Path.cwd())
            # repo 参数必须是目标仓库名，而非工具自身仓库
            self.assertEqual(captured["repo"], "myproj")

    def test_source_with_only_untracked_dist_does_not_crash(self):
        # 源项目无源码、仅有一个未跟踪 dist（被安全规则排除）时，工具仍会补生成
        # .gitignore / README.md 进临时目录，使临时目录有可提交内容；链路应能正常
        # 完成（rc=0）而非误触发 commit 崩溃，且源项目零污染。
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "onlydist"
            root.mkdir()
            (root / "dist").mkdir()
            (root / "dist" / "x.zip").write_text("asset\n")
            before = sorted(p.name for p in root.iterdir())
            captured = {}
            with mock.patch("github_automator.cli.create_repo",
                            return_value=_fake_repo_info("onlydist")), \
                 mock.patch("github_automator.cli.push", return_value=None), \
                 mock.patch("github_automator.cli.get_authenticated_user",
                            return_value="tester"), \
                 mock.patch("github_automator.cli.create_release",
                            side_effect=lambda **kw: captured.update(kw) or "https://x"):
                rc = run(root, repo="onlydist", version="v1.0.0", private=False,
                         token=None, message="x", make_release=True, dry_run=False,
                         force_readme=False)
            self.assertEqual(rc, 0)
            # 源项目零污染：无 .git，文件集合不变
            self.assertFalse((root / ".git").exists())
            after = sorted(p.name for p in root.iterdir())
            self.assertEqual(before, after)
            # Release 打到正确仓库 + 带 cwd
            self.assertEqual(captured.get("repo"), "onlydist")
            self.assertIn("cwd", captured)


class TestRunUpdateExistingRepo(unittest.TestCase):
    """覆盖式更新验证（Phase 8）：远程已有历史时，run 走 force-with-lease 覆盖分支。

    mock 掉网络函数（create_repo/push/create_release/get_authenticated_user），
    并部分 mock _git：让 `fetch origin main` 与 `reset --hard origin/main` 返回成功
    （模拟「远程已有内容」），其余 git 调用走真实临时目录 git，验证 push 收到 force=True
    且源项目零污染。
    """

    def _make_project(self, root: Path):
        (root / "main.py").write_text("print('updated')\n")
        (root / "README.md").write_text("# updated demo\n")

    def test_update_existing_repo_uses_force_push(self):
        import github_automator.cli as cli_mod
        real_git = cli_mod._git

        def partial_git(args, cwd=None, check=True):
            # 模拟「远程已有 main 历史」：fetch / reset 一律成功，其余走真实 git
            if args[:3] == ["fetch", "origin", "main"]:
                return mock.MagicMock(returncode=0, stdout="", stderr="")
            if args[:2] == ["reset", "--hard"]:
                return mock.MagicMock(returncode=0, stdout="", stderr="")
            return real_git(args, cwd=cwd, check=check)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "myproj"
            root.mkdir()
            self._make_project(root)
            before = sorted(p.name for p in root.iterdir())

            push_calls = []
            with mock.patch("github_automator.cli.create_repo",
                            return_value=_fake_repo_info("myproj", exists=True)), \
                 mock.patch("github_automator.cli.push",
                            side_effect=lambda *a, **k: push_calls.append(k) or None), \
                 mock.patch("github_automator.cli.get_authenticated_user",
                            return_value="tester"), \
                 mock.patch("github_automator.cli.create_release",
                            return_value="https://x"), \
                 mock.patch("github_automator.cli._git", side_effect=partial_git):
                rc = run(root, repo="myproj", version="v1.1.0", private=False,
                         token=None, message="x", make_release=False, dry_run=False,
                         force_readme=False)

            self.assertEqual(rc, 0)
            # 源项目零污染
            self.assertFalse((root / ".git").exists())
            self.assertEqual(sorted(p.name for p in root.iterdir()), before)
            # 关键断言：push 被调用且 force=True（覆盖式更新）
            self.assertEqual(len(push_calls), 1)
            self.assertTrue(push_calls[0].get("force"),
                            "更新已存在仓库时 push 必须 force=True")

    def test_update_existing_repo_fetch_failure_raises(self):
        import github_automator.cli as cli_mod
        real_git = cli_mod._git

        def partial_git(args, cwd=None, check=True):
            # 模拟「仓库存在但拉取远程历史失败」：fetch 一律失败，reset 不应被调用
            if args[:3] == ["fetch", "origin", "main"]:
                return mock.MagicMock(returncode=1, stdout="", stderr="fetch failed")
            return real_git(args, cwd=cwd, check=check)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "myproj"
            root.mkdir()
            self._make_project(root)
            before = sorted(p.name for p in root.iterdir())

            with mock.patch("github_automator.cli.create_repo",
                            return_value=_fake_repo_info("myproj", exists=True)), \
                 mock.patch("github_automator.cli.push",
                            side_effect=AssertionError("push 不应被调用")), \
                 mock.patch("github_automator.cli.get_authenticated_user",
                            return_value="tester"), \
                 mock.patch("github_automator.cli._git", side_effect=partial_git):
                with self.assertRaises(RuntimeError):
                    run(root, repo="myproj", version="v1.1.0", private=False,
                        token=None, message="x", make_release=False, dry_run=False,
                        force_readme=False)

            # 源项目零污染
            self.assertFalse((root / ".git").exists())
            self.assertEqual(sorted(p.name for p in root.iterdir()), before)


if __name__ == "__main__":
    unittest.main()
