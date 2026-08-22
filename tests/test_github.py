"""github 模块测试（纯逻辑部分，不触网）。"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from github_automator.github import build_push_url, has_commit, _git_check, create_repo


def _git_available() -> bool:
    return shutil.which("git") is not None


class TestGithub(unittest.TestCase):
    def test_build_push_url_embeds_token(self):
        url = build_push_url("https://github.com/u/r.git", "ghp_abc")
        self.assertEqual(url, "https://ghp_abc@github.com/u/r.git")

    def test_build_push_url_no_token_passthrough(self):
        url = build_push_url("https://github.com/u/r.git", None)
        self.assertEqual(url, "https://github.com/u/r.git")
        # 无 token 时不改变 host 部分（不应出现 @）
        self.assertNotIn("@", url.split("//", 1)[1].split("/", 1)[0])


class TestHasCommit(unittest.TestCase):
    @unittest.skipUnless(_git_available(), "需要 git 可执行文件")
    def test_has_commit_true_after_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
            (root / "a.txt").write_text("x")
            subprocess.run(["git", "add", "-A"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=root, check=True)
            self.assertTrue(has_commit(root))

    @unittest.skipUnless(_git_available(), "需要 git 可执行文件")
    def test_has_commit_false_in_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(has_commit(Path(tmp)))


class TestGitCheck(unittest.TestCase):
    def test_git_check_raises_on_failure(self):
        # 非法 git 参数 -> 非零退出 -> 应当抛出带上下文的 RuntimeError
        with self.assertRaises(RuntimeError):
            _git_check(["git", "rev-parse", "--no-such-flag"], cwd=".")


class TestCreateRepo(unittest.TestCase):
    """create_repo 容错契约：已存在复用 vs 冲突显式报错（不触网，mock 掉 gh 与 _api）。"""

    def _patch_no_gh(self):
        # 模拟「未装 gh」走 REST 路径，并控制 _api 行为
        return mock.patch("github_automator.github.detect_gh", return_value=False)

    def test_create_repo_conflict_raises_not_silent(self):
        # 非「already exists」的 API 错误（如 422 无权限 / 名字非法）必须显式抛出，不静默、不自动改名
        with self._patch_no_gh(), \
             mock.patch("github_automator.github.get_authenticated_user", return_value="u"), \
             mock.patch("github_automator.github._api",
                        side_effect=RuntimeError("GitHub API POST ... 失败 [422]: Repository creation is not allowed")):
            with self.assertRaises(RuntimeError) as ctx:
                create_repo("taken-name", token="dummy")
            msg = str(ctx.exception)
            self.assertIn("taken-name", msg)          # 报错信息含仓库名
            self.assertIn("换名", msg)                 # 含可操作建议

    def test_create_repo_already_exists_reuses(self):
        # 「name already exists」属于你 -> 复用，返回合法的 repo 信息（不抛错）
        fake_info = {"owner": {"login": "u"}, "name": "mine",
                     "clone_url": "https://github.com/u/mine.git",
                     "html_url": "https://github.com/u/mine"}
        with self._patch_no_gh(), \
             mock.patch("github_automator.github.get_authenticated_user", return_value="u"), \
             mock.patch("github_automator.github._api",
                        side_effect=[RuntimeError("name already exists"), fake_info]):
            info = create_repo("mine", token="dummy")
            self.assertEqual(info["repo"], "mine")
            self.assertEqual(info["owner"], "u")


if __name__ == "__main__":
    unittest.main()
