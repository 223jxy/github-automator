"""github 模块测试（纯逻辑部分，不触网）。"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from github_automator.github import (
    build_push_url, has_commit, _git_check, create_repo, push, _check_git_credentials,
    _CREDENTIAL_ERROR_HINTS, create_release, _gh_release_view, _gh_upload_asset,
)


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
        # git 返回非零 -> 应当抛出带上下文的 RuntimeError（mock 隔离，不依赖真实 git）
        err = _FakeCompleted(returncode=1, stderr="some git error")
        with mock.patch("github_automator.github._run", return_value=err):
            with self.assertRaises(RuntimeError):
                _git_check(["git", "rev-parse", "--no-such-flag"], cwd=".")

    def test_git_check_missing_git_binary(self):
        # git 可执行文件缺失（FileNotFoundError）-> 转为明确 RuntimeError
        with mock.patch("github_automator.github._run",
                        side_effect=FileNotFoundError("git not found")):
            with self.assertRaises(RuntimeError) as ctx:
                _git_check(["git", "status"], cwd=".")
            self.assertIn("git 可执行文件", str(ctx.exception))


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


class _FakeCompleted:
    """模拟 subprocess.CompletedProcess，供 _run mock 使用。"""
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestCheckCredentials(unittest.TestCase):
    """_check_git_credentials：凭据通道预检（T2）。"""

    def test_no_gh_no_token_raises(self):
        # 无 gh 且无 GITHUB_TOKEN -> 早失败并提示
        with mock.patch("github_automator.github.detect_gh", return_value=False), \
             mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(RuntimeError) as ctx:
                _check_git_credentials(Path("."))
            self.assertIn("GITHUB_TOKEN", str(ctx.exception))

    def test_token_env_passes(self):
        # 无 gh 但有 GITHUB_TOKEN -> 通过（不抛）
        with mock.patch("github_automator.github.detect_gh", return_value=False), \
             mock.patch.dict("os.environ", {"GITHUB_TOKEN": "ghp_x"}, clear=True):
            _check_git_credentials(Path("."))  # 不应抛

    def test_gh_logged_in_passes(self):
        # gh 已装且 auth status 成功 -> 通过
        with mock.patch("github_automator.github.detect_gh", return_value=True), \
             mock.patch("github_automator.github._run",
                        return_value=_FakeCompleted(returncode=0)):
            _check_git_credentials(Path("."))  # 不应抛

    def test_gh_installed_but_not_ready_raises(self):
        # gh 已装但 auth status 失败 -> 早失败并提示 setup-git
        with mock.patch("github_automator.github.detect_gh", return_value=True), \
             mock.patch("github_automator.github._run",
                        return_value=_FakeCompleted(returncode=1, stderr="not logged in")):
            with self.assertRaises(RuntimeError) as ctx:
                _check_git_credentials(Path("."))
            self.assertIn("setup-git", str(ctx.exception))


class TestPush(unittest.TestCase):
    """push 凭据健壮性（T1/T5）：gh 路径降级、无凭据报错、凭据错误语义化。"""

    def _patch_gh_run(self, push_side_effects):
        """mock detect_gh=True 且 _run 按调用顺序返回。push_side_effects 为 git push 的返回序列。"""
        calls = {"push": iter(push_side_effects)}

        def fake_run(cmd, cwd=None, check=True):
            # cmd 形如 ["git", "-C", <root>, <subcmd>, ...]，subcmd 在索引 3
            if cmd[:2] == ["git", "-C"] and len(cmd) >= 4 and cmd[3] == "get-url":
                return _FakeCompleted(returncode=0, stdout="https://github.com/o/r.git\n")
            if cmd[:2] == ["git", "-C"] and len(cmd) >= 4 and cmd[3] == "add":
                return _FakeCompleted(returncode=0)
            if cmd[:2] == ["git", "-C"] and len(cmd) >= 4 and cmd[3] == "push":
                return next(calls["push"])
            if cmd[:2] == ["gh", "auth"]:
                return _FakeCompleted(returncode=0)  # auth status 通过
            if cmd[:2] == ["git", "-C"] and len(cmd) >= 4 and cmd[3] == "config":
                return _FakeCompleted(returncode=0)  # 兜底配置 credential helper
            return _FakeCompleted(returncode=0)

        return mock.patch("github_automator.github.detect_gh", return_value=True), \
               mock.patch("github_automator.github._run", side_effect=fake_run)

    def test_push_gh_path_degrades_on_credential_error(self):
        # gh 路径首次推送因「凭据不可用」失败 -> 兜底配置后重试成功（不抛）
        cred_fail = _FakeCompleted(
            returncode=1,
            stderr="fatal: could not read Username for 'https://github.com': No such device or address")
        ok = _FakeCompleted(returncode=0)
        p_gh, p_run = self._patch_gh_run([cred_fail, ok])
        with p_gh, p_run:
            push(Path("/tmp/x"), "https://github.com/o/r.git")  # 不应抛

    def test_push_gh_path_non_credential_error_still_raises(self):
        # gh 路径推送因「非凭据」错误（如分支冲突）失败 -> 直接抛出，不盲目降级重试
        branch_conflict = _FakeCompleted(
            returncode=1, stderr="! [rejected] main -> main (fetch first)")
        p_gh, p_run = self._patch_gh_run([branch_conflict])
        with p_gh, p_run:
            with self.assertRaises(RuntimeError):
                push(Path("/tmp/x"), "https://github.com/o/r.git")

    def test_push_no_gh_no_token_raises(self):
        # 无 gh 且无 token -> 预检即失败，提示 GITHUB_TOKEN
        # mock _run 隔离 current_branch 的真实 git 调用（避免依赖 PATH）
        with mock.patch("github_automator.github.detect_gh", return_value=False), \
             mock.patch.dict("os.environ", {}, clear=True), \
             mock.patch("github_automator.github._run",
                        return_value=_FakeCompleted(returncode=0, stdout="main\n")):
            with self.assertRaises(RuntimeError) as ctx:
                push(Path("."), "https://github.com/o/r.git")
            self.assertIn("GITHUB_TOKEN", str(ctx.exception))

    def test_git_check_credential_error_hint(self):
        # _git_check 对凭据类错误附加根因提示（T5）
        err = _FakeCompleted(returncode=1,
                             stderr="fatal: could not read Username for 'https://github.com'")
        with mock.patch("github_automator.github._run", return_value=err):
            with self.assertRaises(RuntimeError) as ctx:
                _git_check(["git", "push"], cwd=".", what="推送")
            self.assertIn("setup-git", str(ctx.exception))
            # 关键词确实命中 _CREDENTIAL_ERROR_HINTS
            self.assertTrue(any(h in "could not read username" for h in _CREDENTIAL_ERROR_HINTS))


class _FakePath:
    """模拟 Path，供 asset_path 参数使用。"""
    def __init__(self, name="app-v1.0.0.zip", exists=True):
        self.name = name
        self._exists = exists
    def exists(self):
        return self._exists


class TestCreateRelease(unittest.TestCase):
    """create_release 幂等（缺陷3修复）：查重跳过 / already-exists 续传 / 真错误仍抛。"""

    def test_gh_release_exists_skips_create(self):
        # 已存在且资产齐 -> 不调 create，返回现有 url（仅允许 release view 查重）
        view = _FakeCompleted(returncode=0,
                              stdout="https://github.com/o/r/releases/tag/v1.0.0\napp-v1.0.0.zip\n")
        with mock.patch("github_automator.github.detect_gh", return_value=True), \
             mock.patch("github_automator.github._run", return_value=view) as run:
            url = create_release("o", "r", "v1.0.0", "r v1.0.0", "notes",
                                 asset_path=_FakePath())
            self.assertEqual(url, "https://github.com/o/r/releases/tag/v1.0.0")
            # 绝不应出现 `gh release create` 调用
            create_calls = [c for c in run.call_args_list
                            if c.args[0][:3] == ["gh", "release", "create"]]
            self.assertEqual(len(create_calls), 0)

    def test_gh_release_exists_missing_asset_uploads(self):
        # 已存在但资产缺失 -> 续传资产后返回，不调 create
        view = _FakeCompleted(returncode=0,
                              stdout="https://github.com/o/r/releases/tag/v1.0.0\nother.txt\n")
        uploaded = []
        def fake_run(cmd, cwd=None, check=True):
            if cmd[:3] == ["gh", "release", "upload"]:
                uploaded.append(cmd)
                return _FakeCompleted(returncode=0)
            return view
        with mock.patch("github_automator.github.detect_gh", return_value=True), \
             mock.patch("github_automator.github._run", side_effect=fake_run):
            url = create_release("o", "r", "v1.0.0", "r v1.0.0", "notes",
                                 asset_path=_FakePath())
            self.assertEqual(url, "https://github.com/o/r/releases/tag/v1.0.0")
            self.assertEqual(len(uploaded), 1)

    def test_gh_release_already_exists_recovers(self):
        # create 报 already-exists -> 查重后续传资产返回，不抛
        create_fail = _FakeCompleted(returncode=1,
                                     stderr="a release with the same tag name already exists: v1.0.0")
        view = _FakeCompleted(returncode=0,
                              stdout="https://github.com/o/r/releases/tag/v1.0.0\nother.txt\n")
        uploaded = []
        def fake_run(cmd, cwd=None, check=True):
            if cmd[:3] == ["gh", "release", "upload"]:
                uploaded.append(cmd)
                return _FakeCompleted(returncode=0)
            if cmd[:3] == ["gh", "release", "create"]:
                return create_fail
            return view  # release view 等
        with mock.patch("github_automator.github.detect_gh", return_value=True), \
             mock.patch("github_automator.github._run", side_effect=fake_run):
            url = create_release("o", "r", "v1.0.0", "r v1.0.0", "notes",
                                 asset_path=_FakePath())
            self.assertEqual(url, "https://github.com/o/r/releases/tag/v1.0.0")
            self.assertEqual(len(uploaded), 1)

    def test_gh_release_real_error_still_raises(self):
        # 非 already-exists 错误（如网络/权限）-> 仍抛
        create_fail = _FakeCompleted(returncode=1,
                                     stderr="HTTP 422: Repository not found")
        with mock.patch("github_automator.github.detect_gh", return_value=True), \
             mock.patch("github_automator.github._run", return_value=create_fail):
            with self.assertRaises(RuntimeError):
                create_release("o", "r", "v1.0.0", "r v1.0.0", "notes",
                               asset_path=_FakePath())


if __name__ == "__main__":
    unittest.main()
