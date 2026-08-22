"""GitHub 推送与 Release 模块。

认证优先级：
1. 若系统装有 `gh` CLI 且已登录 -> 用 gh（最省心，token 不落盘）。
2. 否则回退到 GitHub REST API，token 来自参数 --token 或环境变量 GITHUB_TOKEN。

对外只暴露三个高层函数：create_repo / push / create_release，cli 负责编排。
安全约定：token 仅用于临时推送 URL，不写 .git/config（见 build_push_url / _git_check）。
维护约定：见 github-automator-规范手册.md。
依赖：仅 Python 标准库（不引入第三方包）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

API_ROOT = "https://api.github.com"


def _run(cmd: list[str], cwd: Optional[Path] = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None,
                          capture_output=True, text=True, check=check)


def detect_gh() -> bool:
    try:
        _run(["gh", "--version"], check=False)
        return True
    except FileNotFoundError:
        return False


def _api(token: str, method: str, url: str, data: Optional[bytes] = None,
         headers_extra: Optional[dict] = None) -> dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "github-automator",
    }
    if headers_extra:
        headers.update(headers_extra)
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8") or "{}"
            return json.loads(body)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")
        raise RuntimeError(f"GitHub API {method} {url} 失败 [{e.code}]: {detail}") from e


def get_authenticated_user(token: Optional[str] = None) -> str:
    """获取当前登录用户名（gh 或 API）。"""
    if detect_gh():
        r = _run(["gh", "api", "user", "--jq", ".login"], check=False)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    token = token or os.environ.get("GITHUB_TOKEN")
    if token:
        return _api(token, "GET", f"{API_ROOT}/user")["login"]
    raise RuntimeError("未找到 GitHub 认证：请先 `gh auth login`，或提供 --token / GITHUB_TOKEN。")


def create_repo(name: str, description: str = "", private: bool = False,
                token: Optional[str] = None) -> dict:
    """新建仓库，返回 {owner, repo, clone_url, html_url}。

    容错契约（详见规范手册「容错契约」节）：
    - 仓库「已存在且属于你」：复用，继续后续推送/Release；
    - 仓库「已存在但不属于你 / 无权限 / 名字非法」：显式抛出 RuntimeError，
      信息含仓库名与建议（换名或确认权限），**绝不静默、绝不自动改名重试**。
    """
    visibility = "private" if private else "public"
    if detect_gh():
        r = _run(["gh", "repo", "create", name, "--" + visibility,
                  "--description", description or name, "--confirm"], check=False)
        if r.returncode != 0:
            if "already exists" in r.stderr:
                # 属于你的仓库（同名复用），继续
                owner = get_authenticated_user(token)
                return _repo_info(owner, name, token)
            # 其他失败（名字被占/无权限/网络）：明确报错，不重试不自动改名
            raise RuntimeError(
                f"创建仓库 {name!r} 失败：{r.stderr.strip()}\n"
                f"建议：换名（--repo）或确认你对 {name!r} 有创建权限。"
            )
        owner = get_authenticated_user(token)
        return _repo_info(owner, name, token)

    token = token or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("未提供 GitHub token，无法创建仓库。")
    try:
        data = json.dumps({"name": name, "description": description,
                           "private": private, "auto_init": False}).encode()
        resp = _api(token, "POST", f"{API_ROOT}/user/repos", data)
    except RuntimeError as e:
        if "name already exists" in str(e):
            # 属于你的仓库（同名复用），继续
            owner = get_authenticated_user(token)
            return _repo_info(owner, name, token)
        # 其他冲突（422 无权限 / 名字被他人占用等）：明确报错，不重试不自动改名
        raise RuntimeError(
            f"创建仓库 {name!r} 失败：{e}\n"
            f"建议：换名（--repo）或确认你对 {name!r} 有创建权限。"
        ) from e
    return {"owner": resp["owner"]["login"], "repo": resp["name"],
            "clone_url": resp["clone_url"], "html_url": resp["html_url"]}


def _repo_info(owner: str, name: str, token: Optional[str]) -> dict:
    if detect_gh():
        r = _run(["gh", "repo", "view", f"{owner}/{name}",
                  "--json", "url,sshUrl", "-q", ".url"], check=False)
        url = r.stdout.strip() if r.returncode == 0 else f"https://github.com/{owner}/{name}"
        return {"owner": owner, "repo": name,
                "clone_url": f"https://github.com/{owner}/{name}.git",
                "html_url": url}
    token = token or os.environ.get("GITHUB_TOKEN")
    resp = _api(token, "GET", f"{API_ROOT}/repos/{owner}/{name}")
    return {"owner": resp["owner"]["login"], "repo": resp["name"],
            "clone_url": resp["clone_url"], "html_url": resp["html_url"]}


def current_branch(root: Path) -> str:
    r = _run(["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"], check=False)
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    return "main"


def build_push_url(clone_url: str, token: Optional[str]) -> str:
    """构造带凭证的推送 URL。无 token 时返回原 URL（不嵌入凭证）。"""
    if token:
        return clone_url.replace("https://", f"https://{token}@", 1)
    return clone_url


# git 凭据类错误关键词：命中即说明 git 无法获取认证，根因通常是未配置 gh 凭据助手或缺失 token
_CREDENTIAL_ERROR_HINTS = ("could not read username", "/dev/tty", "no such file or directory",
                           "terminal prompts disabled", "authorization failed",
                           "authentication failed", "could not resolve host")


def _git_check(args: list[str], cwd, what: str = "git 操作") -> subprocess.CompletedProcess:
    """执行 git 命令；失败则抛出带上下文的 RuntimeError（不再静默吞错）。

    若错误属于「凭据不可用」类（如未配置 gh 凭据助手导致 git 回退到交互式
    问密码、非交互环境无 tty），额外附上根因提示，避免用户误判为其他错误。
    若 git 可执行文件本身缺失（FileNotFoundError），也转为明确报错。
    """
    try:
        r = _run(args, cwd=str(cwd), check=False)
    except FileNotFoundError as e:
        raise RuntimeError(
            f"{what}失败：未找到 git 可执行文件。请先安装 Git 并加入 PATH。\n{e}"
        ) from e
    if r.returncode != 0:
        detail = (r.stderr or r.stdout or "（无错误信息）").strip()
        hint = ""
        if any(h in detail.lower() for h in _CREDENTIAL_ERROR_HINTS):
            hint = ("\n根因：git 无法获取 GitHub 凭据——请先 `gh auth setup-git`，"
                    "或设置 GITHUB_TOKEN 环境变量。")
        raise RuntimeError(f"{what}失败：`{' '.join(args)}`\n{detail}{hint}")
    return r


def has_commit(root) -> bool:
    """本地是否存在至少一个提交（用于推送前校验，避免创建空仓库）。"""
    r = _run(["git", "-C", str(root), "rev-parse", "HEAD"], check=False)
    return r.returncode == 0


def _check_git_credentials(root: Path) -> None:
    """推送前的凭据通道预检：早失败、早提示，避免在 push 阶段才暴露凭据不可用。

    探测顺序：
    1. 系统装有 gh 且已登录（gh auth status 成功）→ 通过；
    2. 否则环境变量 GITHUB_TOKEN 已设置 → 通过；
    3. 否则抛出 RuntimeError，提示用户先 `gh auth setup-git` 或设置 GITHUB_TOKEN。
    """
    if detect_gh():
        r = _run(["gh", "auth", "status"], cwd=str(root), check=False)
        if r.returncode == 0:
            return
        # gh 已装但未登录 / setup-git 未配置：仍可能可用，但给出预警式失败
        raise RuntimeError(
            "GitHub 凭据不可用：gh 已安装但未就绪。\n"
            "请先执行 `gh auth setup-git`（或 `gh auth login`），"
            "或设置 GITHUB_TOKEN 环境变量后再发布。"
        )
    if os.environ.get("GITHUB_TOKEN"):
        return
    raise RuntimeError(
        "GitHub 凭据不可用：未检测到 gh，也未设置 GITHUB_TOKEN。\n"
        "请先 `gh auth login`（推荐，token 不落盘），或设置 GITHUB_TOKEN 环境变量。"
    )


def _ensure_gh_git_credentials(root: Path) -> None:
    """gh 路径兜底：确保 git 能用 gh 作为凭据助手（等效 `gh auth setup-git`）。

    仅在本会话为当前仓库配置 credential helper 指向 gh，**不写入用户级全局配置**，
    也不暴露 gh 的明文 token——安全约定（token 不落盘）不受影响。
    若 gh 未安装或不可用则静默跳过（交由后续推送逻辑报错）。
    """
    if not detect_gh():
        return
    _run(["git", "-C", str(root), "config", "--local", "credential.https://github.com.helper",
          ""], check=False)
    _run(["git", "-C", str(root), "config", "--local", "credential.https://github.com.useHttpPath",
          "true"], check=False)
    # 用 gh 提供的凭据助手（其本身从 gh 安全存储读取 token，脚本拿不到明文）
    _run(["git", "-C", str(root), "config", "--local", "credential.https://github.com.helper",
          "!/c/Program\\ Files/GitHub\\ CLI/gh.exe auth git-credential"], check=False)


def push(root: Path, clone_url: str, token: Optional[str] = None,
         branch: Optional[str] = None) -> None:
    """把当前提交推送到远程。

    安全约束：token 绝不写入 .git/config。
    - gh 路径：优先走系统凭据；若推送因「凭据不可用」失败，则运行时兜底配置
      git 用 gh 作凭据助手（等效 `gh auth setup-git`）并重试一次，仍失败才抛出。
    - 非 gh 路径：仅把「不含 token 的 plain remote」持久化；推送时用内联
      token URL 且不加 -u，避免 branch.<name>.remote 记录 token。
    推送前先经 `_check_git_credentials` 预检，凭据缺失则早失败并提示。
    """
    root = Path(root)
    branch = branch or current_branch(root)
    _check_git_credentials(root)  # T2：推送前预检凭据通道

    if detect_gh():
        # gh 走系统凭据，先确保 remote 存在再推送
        r = _run(["git", "-C", str(root), "remote", "get-url", "origin"], check=False)
        if r.returncode != 0:
            _git_check(["git", "-C", str(root), "remote", "add", "origin", clone_url], root, "添加 remote")
        try:
            _git_check(["git", "-C", str(root), "push", "-u", "origin", branch], root, "推送（gh）")
        except RuntimeError as e:
            # T1：gh 路径推送失败，若属「凭据不可用」，兜底配置 gh 凭据助手后重试一次；
            # 重试成功即返回，不再抛出原错误。
            if any(h in str(e).lower() for h in _CREDENTIAL_ERROR_HINTS):
                _ensure_gh_git_credentials(root)
                _git_check(["git", "-C", str(root), "push", "-u", "origin", branch], root, "推送（gh 重试）")
                return
            raise  # 非凭据错误（如分支冲突）：直接抛出，不盲目降级
        return

    token = token or os.environ.get("GITHUB_TOKEN")
    push_url = build_push_url(clone_url, token)
    # 只持久化「不含 token」的 plain remote，避免凭证落盘
    _git_check(["git", "-C", str(root), "remote", "remove", "origin"], root, "清理旧 remote")
    _git_check(["git", "-C", str(root), "remote", "add", "origin", clone_url], root, "添加 plain remote")
    # 用内联 token URL 推送；不加 -u，故 token 不会进入 branch 配置
    _git_check(["git", "-C", str(root), "push", push_url, branch], root, "推送（token）")
    # 把 upstream 指向 plain origin，方便后续无凭证推送/拉取
    _git_check(["git", "-C", str(root), "branch", "--set-upstream-to", f"origin/{branch}"], root, "设置 upstream")


def create_release(owner: str, repo: str, tag: str, name: str, notes: str,
                  asset_path: Optional[Path] = None, token: Optional[str] = None) -> str:
    """创建 GitHub Release，可选附带一个资产文件（zip）。返回 html_url。"""
    if detect_gh():
        cmd = ["gh", "release", "create", tag, "--title", name, "--notes", notes]
        if asset_path:
            cmd.append(str(asset_path))
        r = _run(cmd, check=False)
        if r.returncode != 0:
            raise RuntimeError(f"gh release create 失败：{r.stderr.strip()}")
        out = _run(["gh", "release", "view", tag, "--json", "url", "-q", ".url"], check=False)
        return out.stdout.strip() or f"https://github.com/{owner}/{repo}/releases/tag/{tag}"

    token = token or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("未提供 GitHub token，无法创建 Release。")
    data = json.dumps({"tag_name": tag, "name": name, "body": notes,
                       "draft": False, "prerelease": False}).encode()
    rel = _api(token, "POST", f"{API_ROOT}/repos/{owner}/{repo}/releases", data)
    if asset_path and asset_path.exists():
        _upload_asset(rel["upload_url"].split("{")[0], rel["id"], asset_path, token)
    return rel["html_url"]


def _upload_asset(upload_url: str, release_id: str, asset: Path, token: str) -> None:
    url = f"{upload_url}?name={asset.name}"
    with open(asset, "rb") as f:
        body = f.read()
    req = urllib.request.Request(
        url, data=body,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/zip",
                 "User-Agent": "github-automator"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        resp.read()
