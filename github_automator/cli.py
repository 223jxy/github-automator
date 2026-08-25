#!/usr/bin/env python3
"""github-automator 命令行入口。

用法示例：
    # 默认把当前目录提炼打包，新建公开仓库并推送 + 打 Release
    python cli.py .

    # 指定项目路径、仓库名、版本（未指定 --repo 时，仓库名=目录名汉转英）
    python cli.py /path/to/project --repo my-tool --version v1.0.0

    # 仅演示，不真正推送（dry-run）
    python cli.py . --dry-run

    # 私有仓库 + 自定义 token
    python cli.py . --repo secret --private --token ghp_xxx

维护约定（改动流程/安全约束/验证命令）：见 github-automator-规范手册.md。
依赖：仅 Python 标准库（不引入第三方包）。
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path

from .analyzer import analyze
from .docgen import write_readme
from .github import create_release, create_repo, get_authenticated_user, has_commit, push
from .han2py import han_to_repo_name
from .packager import (make_release_zip, write_gitignore, generate_gitignore,
                       should_include, GitignoreMatcher)

VERSION = "0.1.0"

# 缺省仓库名回退值：当目录名经「汉转英」后无任何可用字符时使用（极少见）。
# 详见规范手册「容错契约」节。正常情况缺省仓名 = 目录名的拼音 slug（见 _default_repo_name）。
DEFAULT_REPO_NAME = "github-automator"


def _default_repo_name(project: Path) -> str:
    """缺省仓库名：目录名「汉转英」（零依赖，见 han2py）。

    例：目录「自动点击脚本」-> "zi-dong-dian-ji-jiao-ben"；
    目录「my-project」-> "my-project"（原样小写 slug）。
    """
    return han_to_repo_name(project.resolve().name)


def _log(msg: str) -> None:
    print(f"[github-automator] {msg}", flush=True)


def _git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd),
                          capture_output=True, text=True, check=check)


def _git_add_safe(project: Path) -> None:
    """安全暂存：只 add 通过 should_include 过滤的文件，永不动 .workbuddy/ 等敏感目录。

    替代 `git add -A`——后者会把历史已 tracked 的敏感文件（如 .workbuddy/ 本地记忆）
    也推到公开仓库，且 .gitignore 对已 tracked 文件无效，曾导致隐私泄漏。
    本函数复用打包快照同一套过滤逻辑，保证「仓库提交内容」与「Release zip 内容」一致，
    并显式兜底排除 .git / .workbuddy / dist（dist 为发布资产，已单独上传，不进历史）。
    """
    root = Path(project).resolve()
    gitignore = GitignoreMatcher(root)
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if ".git" in rel.parts or ".workbuddy" in rel.parts or "dist" in rel.parts:
            continue
        if should_include(p, root, gitignore=gitignore):
            _git(["add", str(p)], cwd=project, check=False)


def run(project: Path, repo: str, version: str, private: bool,
        token: str | None, message: str, make_release: bool, dry_run: bool,
        force_readme: bool, refresh_gitignore: bool = False) -> int:
    project = Path(project).resolve()
    if not project.is_dir():
        _log(f"项目路径不存在或不是目录：{project}")
        return 2

    _log(f"开始分析项目：{project}")
    info = analyze(project)
    _log(f"识别主语言={info.primary_language} 文件数={info.total_files} "
         f"生态={', '.join(info.ecosystems) or '无'} 入口={', '.join(info.entry_points) or '无'}")

    if dry_run:
        _log("DRY-RUN 模式：不写入任何文件，仅预览计划。")
        intended_gi = project / ".gitignore"
        intended_readme = project / "README.md"
        intended_zip = project / "dist" / f"{repo}-{version}.zip"
        _log(f"计划：写入/确认 {intended_gi.name}、{intended_readme.name}，"
             f"生成 {intended_zip.name}，新建仓库 {repo}（{'私有' if private else '公开'}），"
             f"标签 {version}")
        return 0

    # 1) 生成 .gitignore（仅在源项目缺失时生成「内容」，但写入临时发布目录而非污染源项目）
    gi_text = generate_gitignore(info) if (not (project / ".gitignore").exists() or refresh_gitignore) else None

    # 2) README（同上：缺失才生成内容，写入临时发布目录）
    readme_text = write_readme(project, info, force=force_readme, title=repo, dry_run=True) \
        if not (project / "README.md").exists() else None

    # 4) 暂存到临时目录并 git 初始化与提交
    #    关键修复：发布操作全部在临时目录进行，源项目保持只读（不在用户项目里 git init，
    #    避免把「非 git 项目」误 git 化；也不在源项目残留 .git / dist / 发布 zip）。
    with tempfile.TemporaryDirectory(prefix="gh-auto-") as tmp:
        tmp = Path(tmp)
        stage = tmp / repo
        stage.mkdir(parents=True, exist_ok=True)
        gitignore = GitignoreMatcher(project)
        copied = 0
        for p in sorted(project.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(project)
            if ".git" in rel.parts or ".workbuddy" in rel.parts or "dist" in rel.parts:
                continue
            if should_include(p, project, gitignore=gitignore):
                dest = stage / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, dest)
                copied += 1
        _log(f"已暂存 {copied} 个文件到临时发布目录（源项目未改动）。")
        # 源项目缺 .gitignore / README 时，把生成内容补进临时目录（不污染源项目）
        if gi_text is not None:
            (stage / ".gitignore").write_text(gi_text, encoding="utf-8")
        if readme_text is not None:
            (stage / "README.md").write_text(readme_text, encoding="utf-8")

        _git(["init"], cwd=stage)
        _git(["checkout", "-b", "main"], cwd=stage, check=False)
        # 仅 add（暂不 commit）：源项目新文件已就位，commit 推迟到「首发布/更新」
        # 分支判定之后，避免重复 commit 或白做。临时目录只含已过滤的干净文件，安全。

        # 3) 打 Release zip 快照（生成到临时目录顶层 tmp，而非 stage 内——
        #    保证 zip 不会被 git 跟踪进仓库历史，仅作为 Release asset 上传）
        zip_path = make_release_zip(stage, info, version, tmp, archive_name=repo)
        _log(f"已生成发布快照：{zip_path}")

        # 5) 创建仓库 + 推送（区分首发布 / 覆盖式更新）
        # 安全闸门：本地无任何文件可提交时直接失败，避免创建空 GitHub 仓库
        if not list(stage.rglob("*")):
            raise RuntimeError("临时发布目录为空，无法推送（避免创建空 GitHub 仓库）。"
                               "请确认项目有可提交内容。")
        owner = get_authenticated_user(token)
        _log(f"已登录 GitHub 用户：{owner}")
        repo_info = create_repo(repo, info.description, private, token)
        _log(f"仓库已就绪：{repo_info['html_url']}")

        # 区分首发布 / 覆盖式更新。判定依据：create_repo 返回的 exists 标记
        # （仓库是否在你名下已存在），比「尝试 fetch 远程历史」更可靠。
        # 覆盖式语义：远程即工具生成，仓库应然状态 = 源项目当前状态；用
        # --force-with-lease 安全覆盖（远程被不知情改动时会拒绝，不静默覆盖）。
        repo_exists = repo_info.get("exists", False)
        _git(["remote", "add", "origin", repo_info["clone_url"]], cwd=stage, check=False)
        if repo_exists:
            # 覆盖式更新：先把工作区对齐到远程基线（拉取并 reset），再叠加本次
            # 源项目文件，避免把远程已有但本地过滤掉的文件残留进仓库。
            # 用 `git fetch origin main` + `reset --hard FETCH_HEAD`：FETCH_HEAD
            # 是 fetch 后必定存在的引用，比依赖 origin/main 远程跟踪分支更稳
            # （后者在强制 refspec 下偶发未被注册，导致 reset 找不到目标）。
            fetch = _git(["fetch", "origin", "main"], cwd=stage, check=False)
            if fetch.returncode != 0:
                raise RuntimeError(
                    "仓库已存在，但拉取远程 main 分支失败（网络或凭证问题），"
                    "无法安全执行覆盖式更新。\n"
                    "建议：检查 gh 登录状态（`gh auth status`）与网络连通性后重试。"
                )
            reset = _git(["reset", "--hard", "FETCH_HEAD"], cwd=stage, check=False)
            if reset.returncode != 0:
                raise RuntimeError("拉取远程历史后对齐工作区失败，已中止覆盖式更新。")
            _log("检测到远程已有历史，采用覆盖式更新（对齐远程后叠加本次文件）。")
            # 重新叠加本次源项目文件 + 生成内容（reset 已把 stage 工作区对齐到远程状态）
            for p in sorted(project.rglob("*")):
                if not p.is_file():
                    continue
                rel = p.relative_to(project)
                if ".git" in rel.parts or ".workbuddy" in rel.parts or "dist" in rel.parts:
                    continue
                if should_include(p, project, gitignore=gitignore):
                    dest = stage / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(p, dest)
            if gi_text is not None:
                (stage / ".gitignore").write_text(gi_text, encoding="utf-8")
            if readme_text is not None:
                (stage / "README.md").write_text(readme_text, encoding="utf-8")
            _git(["add", "-A"], cwd=stage)
            diff = _git(["diff", "--cached", "--quiet"], cwd=stage, check=False)
            if diff.returncode != 0:
                _git(["commit", "-m", message], cwd=stage)
                _log("已提交更新（覆盖式）。")
            else:
                _log("与远程内容一致，无新提交。")
            push(stage, repo_info["clone_url"], token, force=True)
        else:
            # 首发布：直接提交本地新文件并普通推送
            _git(["add", "-A"], cwd=stage)
            _git(["commit", "-m", message], cwd=stage)
            _log("已提交本地改动（临时发布目录）。")
            push(stage, repo_info["clone_url"], token)
        _log("已推送到 GitHub。")

        # 6) 创建 Release（可选）；cwd=stage 确保 gh 作用到目标仓库而非工具自身仓库
        if make_release:
            rel_url = create_release(
                owner=repo_info["owner"], repo=repo_info["repo"], tag=version,
                name=f"{repo} {version}",
                notes=f"自动化发布 by github-automator @ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
                asset_path=zip_path if zip_path.exists() else None,
                token=token,
                cwd=stage,
            )
            _log(f"已创建 Release：{rel_url}")
        else:
            _log("按配置跳过 Release 创建。")

        _log("完成 ✅")
        print(f"\n仓库地址：{repo_info['html_url']}")
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="github-automator",
        description="把任意项目提炼、打包并自动化提交到 GitHub（含 Release 压缩包）。",
    )
    parser.add_argument("project", nargs="?", default=".", help="项目目录（默认当前目录）")
    parser.add_argument("--repo", default=None, help="GitHub 仓库名（缺省=目录名汉转英，如「自动点击脚本」→ zi-dong-dian-ji-jiao-ben）")
    parser.add_argument("--version", default="v1.0.0", help="Release 标签（默认 v1.0.0）")
    parser.add_argument("--private", action="store_true", help="创建私有仓库（默认公开）")
    parser.add_argument("--token", default=None, help="GitHub token（无 gh 时使用；也可设环境变量 GITHUB_TOKEN）")
    parser.add_argument("--message", default="chore: automated commit by github-automator", help="提交信息")
    parser.add_argument("--no-release", action="store_true", help="不打 Release")
    parser.add_argument("--dry-run", action="store_true", help="只分析/生成/打包，不推送")
    parser.add_argument("--force-readme", action="store_true", help="即使已有 README 也覆盖")
    parser.add_argument("--refresh-gitignore", action="store_true",
                        help="强制刷新/补全 .gitignore（即便已存在，用于修复过时片段）")
    parser.add_argument("--version-tool", action="version", version=f"github-automator {VERSION}")
    args = parser.parse_args(argv)

    # 零交互：未指定 --repo 时自动用「目录名汉转英」作缺省仓名，不再询问用户。
    repo = args.repo or _default_repo_name(Path(args.project))
    return run(
        project=args.project,
        repo=repo,
        version=args.version,
        private=args.private,
        token=args.token,
        message=args.message,
        make_release=not args.no_release,
        dry_run=args.dry_run,
        force_readme=args.force_readme,
        refresh_gitignore=args.refresh_gitignore,
    )


def _write_diagnostic(exc: BaseException, argv: list[str]) -> Path:
    """未捕获异常时写结构化诊断日志到用户缓存目录，便于带回修复工具。

    位置：~/.cache/github-automator/error-<UTC时间戳>.log
    内容：时间/版本/Python/平台/cwd/argv/错误类型/完整 traceback
    脱敏：home 路径替换为 <USER_HOME>，避免日志泄露用户名。
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    cache_dir = Path.home() / ".cache" / "github-automator"
    cache_dir.mkdir(parents=True, exist_ok=True)
    log_path = cache_dir / f"error-{ts}.log"
    home = str(Path.home())
    username = Path.home().name

    def _redact(text: str) -> str:
        # 先替换整段 home 路径（反斜杠），再替换散落的用户名（覆盖正斜杠等变体），避免个人目录泄露。
        return text.replace(home, "<USER_HOME>").replace(username, "<USER>")

    tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
    tb_redacted = [_redact(ln) for ln in tb]
    cwd_redacted = _redact(str(Path.cwd()))
    argv_redacted = [_redact(a) for a in argv]
    content = "\n".join([
        "github-automator 诊断日志",
        f"时间(UTC): {ts}",
        f"工具版本: {VERSION}",
        f"Python: {sys.version.split()[0]}",
        f"平台: {sys.platform}",
        f"cwd: {cwd_redacted}",
        f"argv: {' '.join(argv_redacted)}",
        f"错误类型: {type(exc).__name__}",
        f"错误信息: {exc}",
        "--- traceback ---",
        *tb_redacted,
    ])
    log_path.write_text(content, encoding="utf-8")
    return log_path


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:  # 顶层兜底：确保任何报错都可被携带回来修复工具
        log_path = _write_diagnostic(exc, sys.argv)
        _log(f"运行出错，诊断日志已写入：{log_path}")
        _log("将该文件内容发回维护者即可定位修复（日志已对 home 路径脱敏）。")
        sys.exit(1)
