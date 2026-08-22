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


def _git_check(args: list[str], cwd, what: str = "git 操作") -> subprocess.CompletedProcess:
    """执行 git 命令；失败则抛出带上下文的 RuntimeError（不再静默吞错）。"""
    r = _run(args, cwd=str(cwd), check=False)
    if r.returncode != 0:
        detail = (r.stderr or r.stdout or "（无错误信息）").strip()
        raise RuntimeError(f"{what}失败：`{' '.join(args)}`\n{detail}")
    return r


def has_commit(root) -> bool:
    """本地是否存在至少一个提交（用于推送前校验，避免创建空仓库）。"""
    r = _run(["git", "-C", str(root), "rev-parse", "HEAD"], check=False)
    return r.returncode == 0


def push(root: Path, clone_url: str, token: Optional[str] = None,
         branch: Optional[str] = None) -> None:
    """把当前提交推送到远程。

    安全约束：token 绝不写入 .git/config。
    - gh 路径：走系统凭据，remote 不含 token。
    - 非 gh 路径：仅把「不含 token 的 plain remote」持久化；推送时用内联
      token URL 且不加 -u，避免 branch.<name>.remote 记录 token。
    任何 git 失败都会显式抛出（不再以 check=False 静默吞掉）。
    """
    root = Path(root)
    branch = branch or current_branch(root)
    if detect_gh():
        # gh 走系统凭据，先确保 remote 存在再推送
        r = _run(["git", "-C", str(root), "remote", "get-url", "origin"], check=False)
        if r.returncode != 0:
            _git_check(["git", "-C", str(root), "remote", "add", "origin", clone_url], root, "添加 remote")
        _git_check(["git", "-C", str(root), "push", "-u", "origin", branch], root, "推送（gh）")
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
