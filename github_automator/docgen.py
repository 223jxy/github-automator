"""文档生成模块：基于 ProjectInfo 生成标准 README.md。

生成的 README 包含：标题、简介、特性（推断）、技术栈、目录结构、安装、用法、许可证、自动生成声明。
不覆盖已有 README（若用户已有，则保留并提示）。
维护约定：见 github-automator-规范手册.md。
依赖：仅 Python 标准库（不引入第三方包）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .analyzer import ProjectInfo


def _infer_features(info: ProjectInfo) -> List[str]:
    """根据结构推断几条「特性」作为 README 卖点，纯启发式。"""
    features: List[str] = []
    if info.entry_points:
        features.append(f"开箱即用的入口：`{info.entry_points[0]}`")
    if "Node.js" in info.ecosystems:
        features.append("基于 Node.js 生态，依赖通过 package.json 管理")
    if "Python" in info.ecosystems:
        features.append("Python 项目，支持 requirements / pyproject 依赖管理")
    if info.manifests:
        total_deps = sum(len(v) for v in info.manifests.values())
        features.append(f"自动识别 {total_deps} 个依赖，技术栈清晰可追溯")
    features.append("由 github-automator 自动提炼、打包并发布到 GitHub")
    return features


def generate_readme(info: ProjectInfo, repo_url: Optional[str] = None,
                   title: Optional[str] = None) -> str:
    """生成 README 文本。title 缺省用项目名。"""
    title = title or info.name
    lang_line = info.primary_language if info.languages else "多语言"
    eco_line = "、".join(info.ecosystems) if info.ecosystems else "未识别特定生态"
    features = _infer_features(info)

    lines: List[str] = []
    # 隐形标记：HTML 注释在 GitHub 渲染时不可见，但能让分析器识别「自生成」并避免回环
    lines.append("<!-- 本 README 由 github-automator 自动生成 -->")
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"> {info.description}")
    lines.append("")
    lines.append("## 简介")
    lines.append("")
    lines.append(
        f"本项目由 **github-automator** 自动提炼并发布。主要语言为 **{lang_line}**，"
        f"技术栈涉及 {eco_line}。"
    )
    lines.append("")
    lines.append("## 特性")
    lines.append("")
    for f in features:
        lines.append(f"- {f}")
    lines.append("")
    lines.append("## 技术栈")
    lines.append("")
    if info.ecosystems:
        for e in info.ecosystems:
            deps = []
            for mf, ds in info.manifests.items():
                if e.split()[0] in mf or mf.replace(".", "") in e.lower():
                    deps = ds
                    break
            dep_str = f"（关键依赖：{', '.join(deps[:8])}）" if deps else ""
            lines.append(f"- {e} {dep_str}".rstrip())
    else:
        lines.append(f"- 主要语言：{lang_line}（纯标准库 / 无第三方依赖）")
    lines.append("")
    lines.append("## 目录结构")
    lines.append("")
    lines.append("```text")
    lines.append(info.tree)
    lines.append("```")
    lines.append("")

    # 安装
    lines.append("## 安装")
    lines.append("")
    if "Node.js" in info.ecosystems:
        lines.append("```bash")
        lines.append("npm install    # 或 pnpm install / yarn")
        lines.append("```")
    elif "Python" in info.ecosystems:
        lines.append("```bash")
        if "requirements.txt" in info.manifests:
            lines.append("python -m venv .venv && source .venv/bin/activate")
            lines.append("pip install -r requirements.txt")
        elif "pyproject.toml" in info.manifests:
            lines.append("# 可编辑安装（开发）或 poetry install")
            lines.append("pip install -e .   # 或 poetry install")
        else:
            lines.append("# 零依赖项目，无需安装第三方包")
        lines.append("```")
    elif "Go" in info.ecosystems:
        lines.append("```bash")
        lines.append("go mod download")
        lines.append("```")
    else:
        lines.append("按对应语言的依赖管理工具安装依赖即可。")
    lines.append("")

    # 用法
    lines.append("## 用法")
    lines.append("")
    if info.entry_points:
        ep = info.entry_points[0]
        if ep.endswith(".py"):
            lines.append(f"```bash\npython {ep}\n```")
        elif ep.endswith(".js"):
            lines.append(f"```bash\nnode {ep}\n```")
        elif ep.endswith(".go"):
            lines.append(f"```bash\ngo run {ep}\n```")
        else:
            lines.append(f"运行入口文件 `{ep}`。")
    else:
        lines.append("参考目录结构中的源码与测试运行项目。")
    lines.append("")

    # 许可证
    lines.append("## 许可证")
    lines.append("")
    if info.has_license:
        lines.append(f"本项目包含许可证文件：`{info.license_name}`。")
    else:
        lines.append("暂无明确许可证，如需开源请补充 LICENSE 文件。")
    lines.append("")

    # 发布信息
    lines.append("## 发布")
    lines.append("")
    if repo_url:
        lines.append(f"仓库地址：{repo_url}")
        lines.append("")
    lines.append(
        f"本文档由 github-automator v 自动化生成于 "
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}。"
    )
    lines.append("")
    return "\n".join(lines)


def write_readme(root: Path, info: ProjectInfo, repo_url: Optional[str] = None,
                 force: bool = False, title: Optional[str] = None,
                 dry_run: bool = False) -> Path | str:
    """写入 README.md；已存在且不 force 时跳过。

    dry_run=True 时仅返回生成的文本而不写入任何文件（用于「源项目只读」的
    临时目录发布流程：源项目已有 README 则跳过；缺失时把文本交给调用方写入
    临时发布目录，避免污染用户项目）。
    """
    root = Path(root)
    target = root / "README.md"
    if target.exists() and not force:
        return target
    text = generate_readme(info, repo_url, title)
    if dry_run:
        return text
    target.write_text(text, encoding="utf-8")
    return target
