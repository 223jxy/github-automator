#!/usr/bin/env python3
"""github-automator 命令行入口。

用法示例：
    # 默认把当前目录提炼打包，新建公开仓库并推送 + 打 Release
    python cli.py .

    # 指定项目路径、仓库名、版本
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
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .analyzer import analyze
from .docgen import write_readme
from .github import create_release, create_repo, get_authenticated_user, has_commit, push
from .packager import make_release_zip, write_gitignore

VERSION = "0.1.0"

# 缺省仓库名：当用户未用 --repo 指定时，回退到包名（ASCII 安全，避免中文目录名当仓名）。
# 详见规范手册「容错契约」节。
DEFAULT_REPO_NAME = "github-automator"


def _log(msg: str) -> None:
    print(f"[github-automator] {msg}", flush=True)


def _git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd),
                          capture_output=True, text=True, check=check)


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

    # 1) 生成 .gitignore（已存在则跳过；--refresh-gitignore 可强制刷新）
    gi = write_gitignore(project, info, force=refresh_gitignore)
    _log(f"已写入/确认 .gitignore：{gi}")

    # 2) 生成 README（已存在且未 force 则跳过）
    readme = write_readme(project, info, force=force_readme, title=repo)
    _log(f"已写入/确认 README：{readme}")

    # 3) 打 Release zip 快照
    zip_path = make_release_zip(project, info, version, project / "dist", archive_name=repo)
    _log(f"已生成发布快照：{zip_path}")

    # 4) git 初始化与提交
    if not (project / ".git").exists():
        _git(["init"], cwd=project)
        _git(["checkout", "-b", "main"], cwd=project, check=False)
    _git(["add", "-A"], cwd=project)
    # 若无可提交内容则跳过提交
    status = _git(["status", "--porcelain"], cwd=project, check=False)
    if status.stdout.strip():
        # check=True：提交失败（如未配置 git 身份）直接抛出，不再静默吞掉
        _git(["commit", "-m", message], cwd=project)
        _log("已提交本地改动。")
    else:
        _log("无可提交改动，跳过 commit。")

    # 5) 创建仓库 + 推送
    # 安全闸门：本地无任何提交时直接失败，避免创建空 GitHub 仓库
    if not has_commit(project):
        raise RuntimeError("本地无提交，无法推送（避免创建空 GitHub 仓库）。"
                           "请确认 git 身份已配置或项目有可提交内容。")
    owner = get_authenticated_user(token)
    _log(f"已登录 GitHub 用户：{owner}")
    repo_info = create_repo(repo, info.description, private, token)
    _log(f"仓库已就绪：{repo_info['html_url']}")
    push(project, repo_info["clone_url"], token)
    _log("已推送到 GitHub。")

    # 6) 创建 Release（可选）
    if make_release:
        rel_url = create_release(
            owner=repo_info["owner"], repo=repo_info["repo"], tag=version,
            name=f"{repo} {version}",
            notes=f"自动化发布 by github-automator @ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            asset_path=zip_path if zip_path.exists() else None,
            token=token,
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
    parser.add_argument("--repo", default=None, help="GitHub 仓库名（默认用项目目录名）")
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

    repo = args.repo or DEFAULT_REPO_NAME
    if not args.repo:
        # 未指定 --repo：回退到包名默认仓名，显式提示用户，避免静默用目录名（可能含中文）
        print(f"[github-automator] 未指定 --repo，使用默认仓库名：{repo}")
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


if __name__ == "__main__":
    sys.exit(main())
