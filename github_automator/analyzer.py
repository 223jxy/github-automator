"""项目分析模块：扫描目录、识别语言/依赖/入口、构建目录树。

纯标准库实现，不依赖任何第三方包，保证工具「开箱即跑」。
设计原则：只读不写，所有分析产物都收敛到 ProjectInfo 数据类，供打包与文档模块消费。
维护约定：见 github-automator-规范手册.md。
依赖：仅 Python 标准库（不引入第三方包）。
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# 扩展名 -> 语言
LANG_EXT: Dict[str, str] = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin",
    ".c": "C",
    ".h": "C/C++",
    ".cpp": "C++",
    ".hpp": "C++",
    ".cs": "C#",
    ".rb": "Ruby",
    ".php": "PHP",
    ".swift": "Swift",
    ".lua": "Lua",
    ".sh": "Shell",
    ".ps1": "PowerShell",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".sass": "Sass",
    ".vue": "Vue",
    ".sql": "SQL",
    ".r": "R",
    ".jl": "Julia",
    ".dart": "Dart",
    ".ex": "Elixir",
    ".exs": "Elixir",
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".toml": "TOML",
    ".md": "Markdown",
}

# 依赖清单文件 -> 生态名（用于技术栈与 .gitignore 模板选择）
MANIFESTS: Dict[str, str] = {
    "package.json": "Node.js",
    "package-lock.json": "Node.js",
    "yarn.lock": "Node.js",
    "pnpm-lock.yaml": "Node.js",
    "requirements.txt": "Python",
    "pyproject.toml": "Python",
    "Pipfile": "Python",
    "poetry.lock": "Python",
    "go.mod": "Go",
    "go.sum": "Go",
    "Cargo.toml": "Rust",
    "Cargo.lock": "Rust",
    "pom.xml": "Java (Maven)",
    "build.gradle": "Java (Gradle)",
    "build.gradle.kts": "Java (Gradle)",
    "Gemfile": "Ruby",
    "Gemfile.lock": "Ruby",
    "composer.json": "PHP",
    "composer.lock": "PHP",
    "pubspec.yaml": "Dart",
    "pubspec.lock": "Dart",
    "mix.exs": "Elixir",
    "mix.lock": "Elixir",
}

# 常见入口文件（按优先级，首个命中即视为入口）
ENTRY_CANDIDATES: List[str] = [
    "main.py", "app.py", "server.py", "run.py", "manage.py", "wsgi.py", "cli.py",
    "index.js", "main.js", "app.js", "server.js",
    "index.ts", "main.ts", "app.ts",
    "main.go", "main.java", "main.rs", "main.c", "main.cpp",
    "main.rb", "main.php", "main.kt", "main.swift", "main.dart",
    "Program.cs", "app.exs",
]

# 主语言 -> 生态名（无依赖清单时用于推断技术栈展示）
LANG_TO_ECOSYSTEM: Dict[str, str] = {
    "Python": "Python",
    "JavaScript": "Node.js",
    "TypeScript": "Node.js",
    "Go": "Go",
    "Rust": "Rust",
    "Java": "Java",
    "Kotlin": "Kotlin",
    "Ruby": "Ruby",
    "PHP": "PHP",
    "Dart": "Dart",
    "Elixir": "Elixir",
    "C#": "C#",
    "C": "C",
    "C++": "C++",
    "Swift": "Swift",
}

# 默认忽略的目录（与生成的 .gitignore 保持一致，避免分析/打包时把垃圾算进去）
DEFAULT_IGNORE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
    "dist", "build", ".idea", ".vscode", "target", "vendor",
    ".mypy_cache", ".pytest_cache", ".tox", ".next", "out", "bin", "obj",
    ".ruff_cache", ".eggs", "*.egg-info", "site-packages",
}

# 超过该大小（字节）的文件视为「大文件」，分析时跳过内容读取
LARGE_FILE_THRESHOLD = 1_000_000


@dataclass
class ProjectInfo:
    """分析结果的统一载体。"""

    root: Path
    name: str
    languages: Counter = field(default_factory=Counter)
    total_files: int = 0
    code_files: int = 0
    manifests: Dict[str, List[str]] = field(default_factory=dict)  # 文件名 -> 依赖列表
    ecosystems: List[str] = field(default_factory=list)  # 去重后的生态名
    entry_points: List[str] = field(default_factory=list)
    has_readme: bool = False
    existing_readme: str = ""
    has_license: bool = False
    license_name: str = ""
    description: str = ""
    tree: str = ""

    @property
    def primary_language(self) -> str:
        return self.languages.most_common(1)[0][0] if self.languages else "未知"


def _read_text(path: Path) -> str:
    try:
        if path.stat().st_size > LARGE_FILE_THRESHOLD:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except (OSError, UnicodeDecodeError):
        return ""


def _parse_manifest(name: str, text: str) -> List[str]:
    """从依赖清单里抽取前若干个依赖名，仅作展示用。"""
    deps: List[str] = []
    try:
        if name == "package.json":
            data = json.loads(text)
            deps = list((data.get("dependencies") or {}).keys())
            deps += list((data.get("devDependencies") or {}).keys())
        elif name in ("requirements.txt", "pubspec.yaml", "go.mod", "Cargo.toml",
                      "pom.xml", "Gemfile", "composer.json", "mix.exs"):
            # 简单按行提取：依赖名通常是「包名==版本」或「包名 版本」或 「name = ".."」
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("//"):
                    continue
                # package name = 行首到第一个非单词字符
                token = ""
                for ch in line:
                    if ch.isalnum() or ch in "-_./@":
                        token += ch
                    else:
                        break
                if token and token not in ("name", "version", "dependencies", "require"):
                    deps.append(token)
                if len(deps) >= 15:
                    break
    except Exception:
        deps = []
    # 去重保序
    seen = set()
    out = []
    for d in deps:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out[:15]


def analyze(root: Path, max_tree_depth: int = 3) -> ProjectInfo:
    """扫描 root 目录，返回 ProjectInfo。"""
    root = Path(root).resolve()
    info = ProjectInfo(root=root, name=root.name or "project")

    readme_names = {"readme.md", "readme.txt", "readme.rst", "readme"}
    license_names = {"license", "license.md", "license.txt", "license.rst", "licence", "copying"}

    for path in sorted(root.rglob("*")):
        # 跳过忽略目录
        if any(part in DEFAULT_IGNORE_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        info.total_files += 1
        ext = path.suffix.lower()
        if ext in LANG_EXT:
            info.languages[LANG_EXT[ext]] += 1
            if LANG_EXT[ext] not in ("JSON", "YAML", "TOML", "Markdown"):
                info.code_files += 1
        fname = path.name
        if fname in MANIFESTS:
            text = _read_text(path)
            info.manifests[fname] = _parse_manifest(fname, text)
        low = fname.lower()
        if low in readme_names:
            info.has_readme = True
            info.existing_readme = _read_text(path)[:2000]
        if low in license_names or low.startswith("license"):
            info.has_license = True
            info.license_name = fname

    # 入口文件（同样跳过忽略目录）
    for cand in ENTRY_CANDIDATES:
        if (root / cand).is_file():
            info.entry_points.append(cand)

    # 生态去重（依赖清单优先）
    eco = []
    for mf in info.manifests:
        e = MANIFESTS.get(mf)
        if e and e not in eco:
            eco.append(e)
    # 没有依赖清单时，按主语言推断生态，保证技术栈不空白
    if not eco and info.primary_language in LANG_TO_ECOSYSTEM:
        eco.append(LANG_TO_ECOSYSTEM[info.primary_language])
    info.ecosystems = eco

    # 简介：优先复用已有 README 首段；但若是本工具自生成的（带标记），则用默认文案避免回环。
    # 防护标记与 docgen.generate_readme 中的 HTML 注释保持一致："github-automator 自动生成"。
    if info.existing_readme and "github-automator 自动生成" not in info.existing_readme:
        for para in info.existing_readme.split("\n\n"):
            para = para.strip().lstrip("#").strip().lstrip(">").strip()
            if para and len(para) > 10 and "github-automator" not in para:
                info.description = para[:200]
                break
    if not info.description:
        info.description = (
            f"{info.name} 是一个用于把项目自动提炼、打包并发布到 GitHub 的工具。"
        )

    info.tree = build_tree(root, max_depth=max_tree_depth)
    return info


def build_tree(root: Path, max_depth: int = 3, max_entries: int = 60) -> str:
    """生成受限深度的 ASCII 目录树，忽略构建产物目录与过多条目。"""
    root = Path(root).resolve()
    lines: List[str] = [root.name + "/"]
    counted = 0

    def walk(d: Path, prefix: str, depth: int) -> None:
        nonlocal counted
        if depth > max_depth:
            return
        entries = []
        for p in sorted(d.iterdir()):
            if p.name in DEFAULT_IGNORE_DIRS or p.name.startswith("."):
                # .git 等隐藏目录略过；但保留部分有意义的点文件(.gitignore/.env 不保留)
                if p.name in (".gitignore",):
                    entries.append(p)
                continue
            entries.append(p)
        # 目录优先
        entries.sort(key=lambda p: (not p.is_dir(), p.name.lower()))
        for i, p in enumerate(entries):
            if counted >= max_entries:
                lines.append(prefix + "└── … (省略)")
                return
            counted += 1
            is_last = i == len(entries) - 1
            connector = "└── " if is_last else "├── "
            if p.is_dir():
                lines.append(prefix + connector + p.name + "/")
                walk(p, prefix + ("    " if is_last else "│   "), depth + 1)
            else:
                lines.append(prefix + connector + p.name)

    walk(root, "", 1)
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    result = analyze(target)
    print(f"项目名 : {result.name}")
    print(f"主语言 : {result.primary_language}")
    print(f"文件数 : {result.total_files} (代码 {result.code_files})")
    print(f"生态   : {', '.join(result.ecosystems) or '无'}")
    print(f"入口   : {', '.join(result.entry_points) or '未识别'}")
    print(f"License: {result.license_name or '无'}")
    print("目录树:")
    print(result.tree)
