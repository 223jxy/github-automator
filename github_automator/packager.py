"""打包模块：根据分析结果生成 .gitignore，并把「干净」的项目打成 zip 快照。

- gitignore 模板按识别到的生态组合（Python / Node / Go / Rust / Java / Ruby / PHP / Dart …）。
- zip 快照排除 .git、依赖目录、构建产物、大文件，作为 GitHub Release 的可下载产物。
- 额外排除密钥类点文件（.env 等），并尊重项目自定义 .gitignore（见 GitignoreMatcher）。
维护约定：见 github-automator-规范手册.md。
依赖：仅 Python 标准库（不引入第三方包）。
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import List

from .analyzer import DEFAULT_IGNORE_DIRS, ProjectInfo

# 各生态的 .gitignore 片段（精简版，覆盖 90% 场景）
_GITIGNORE_FRAGMENTS = {
    "Python": [
        "__pycache__/",
        "*.py[cod]",
        "*.egg-info/",
        ".venv/",
        "venv/",
        "env/",
        ".pytest_cache/",
        ".mypy_cache/",
        ".ruff_cache/",
        ".tox/",
        "build/",
        "dist/",
    ],
    "Node.js": [
        "node_modules/",
        "npm-debug.log*",
        "yarn-debug.log*",
        "yarn-error.log*",
        "pnpm-debug.log*",
        ".next/",
        "out/",
        "dist/",
        "coverage/",
    ],
    "Go": ["/vendor/", "*.test", "*.out", "bin/"],
    "Rust": ["/target/", "Cargo.lock.bak", "*.rs.bk"],
    "Java (Maven)": ["target/", "*.class", "*.jar", "*.war", ".settings/", ".project", ".classpath"],
    "Java (Gradle)": ["build/", ".gradle/", "*.class", "*.jar"],
    "Ruby": [".bundle/", "log/", "tmp/", "*.gem", ".ruby-version"],
    "PHP": ["/vendor/", "composer.phar", ".phpunit.result.cache"],
    "Dart": [".dart_tool/", "build/", ".flutter-plugins", ".packages"],
    "Elixir": ["/_build/", "/deps/", "*.beam", ".elixir_ls/"],
}

# 通用片段（始终附加）
_COMMON_FRAGMENTS = [
    "# ===== 编辑器 / OS =====",
    ".idea/",
    ".vscode/",
    ".DS_Store",
    "Thumbs.db",
    "# ===== 环境变量 / 密钥（务必保留，防止泄露） =====",
    ".env",
    ".env.*",
    "*.key",
    "*.pem",
    "secrets.json",
    "credentials.json",
    "# ===== 日志 / 临时 =====",
    "*.log",
    "tmp/",
    "temp/",
]


def _select_ecosystems(info: ProjectInfo) -> List[str]:
    """把生态名映射到 .gitignore 片段键。"""
    keys = []
    for eco in info.ecosystems:
        for frag_key in _GITIGNORE_FRAGMENTS:
            if eco.split()[0] in frag_key or frag_key.split()[0] in eco:
                if frag_key not in keys:
                    keys.append(frag_key)
                break
    return keys


def generate_gitignore(info: ProjectInfo) -> str:
    """生成 .gitignore 文本。幂等：重复调用结果稳定。"""
    lines: List[str] = ["# 由 github-automator 自动生成", ""]
    for eco in _select_ecosystems(info):
        lines.append(f"# ===== {eco} =====")
        lines.extend(_GITIGNORE_FRAGMENTS[eco])
        lines.append("")
    lines.extend(_COMMON_FRAGMENTS)
    lines.append("")
    return "\n".join(lines)


def write_gitignore(root: Path, info: ProjectInfo, force: bool = False) -> Path:
    """把 .gitignore 写入项目根目录。

    已存在且未加 force 时跳过，避免覆盖用户自定义；加 force（对应
    --refresh-gitignore）则强制刷新/补全生态片段。
    """
    root = Path(root)
    target = root / ".gitignore"
    if target.exists() and not force:
        return target
    target.write_text(generate_gitignore(info), encoding="utf-8")
    return target


class GitignoreMatcher:
    """轻量 .gitignore 匹配器，覆盖常见语法：* / ** / 目录后缀 / 根锚点 / 否定(!)。

    用于让 Release 快照尊重「项目自定义的忽略规则」（如 data/、业务密钥目录、
    *.log 等），而非仅依赖工具内置的 DEFAULT_IGNORE_DIRS。
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.rules: list[tuple[re.Pattern, bool]] = []  # (compiled_regex, is_negation)
        gif = self.root / ".gitignore"
        if not gif.is_file():
            return
        for raw in gif.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.rstrip()
            if not line or line.lstrip().startswith("#"):
                continue
            neg = line.startswith("!")
            if neg:
                line = line[1:]
            line = line.rstrip()
            dir_only = line.endswith("/")
            if dir_only:
                line = line[:-1]
            anchored = line.startswith("/")
            if anchored:
                line = line[1:]
            if line.startswith("**/"):  # **/foo 等价于任意层级（含根）匹配 foo
                line = line[3:]
            rx = self._glob_to_regex(line)
            regex = f"^{rx}" if anchored else f"(^|/){rx}"
            regex += r"(/|$)" if dir_only else r"(/.*)?$"
            self.rules.append((re.compile(regex), neg))

    @staticmethod
    def _glob_to_regex(pattern: str) -> str:
        out: list[str] = []
        i, n = 0, len(pattern)
        while i < n:
            c = pattern[i]
            if c == "*":
                if i + 1 < n and pattern[i + 1] == "*":
                    out.append(".*")
                    i += 2
                    continue
                out.append("[^/]*")
            elif c == "?":
                out.append("[^/]")
            elif c == "/":
                out.append("/")
            else:
                out.append(re.escape(c))
            i += 1
        return "".join(out)

    def ignored(self, rel_posix: str) -> bool:
        result = False
        for rx, neg in self.rules:
            if rx.search(rel_posix):
                result = not neg
        return result


def should_include(path: Path, root: Path, gitignore: GitignoreMatcher | None = None) -> bool:
    """判断文件是否应被打入 zip。

    排除：内置忽略目录、密钥类点文件、项目自定义 .gitignore 命中的路径、超大文件。
    仅排除「可能含密钥」的点文件（.env / .env.* / .netrc / .pypirc / .npmrc /
    .aws / .ssh / .git）；其余配置型点文件（.editorconfig / .flake8 等）保留，
    保证 Release 快照完整。
    """
    rel = path.relative_to(root)
    if any(part in DEFAULT_IGNORE_DIRS for part in rel.parts):
        return False
    if path.name in (".gitignore",) or path.name.endswith(".gitignore"):
        return True
    name = path.name
    if name.startswith("."):
        # 密钥 / 凭据类点文件一律排除
        if name == ".env" or name.startswith(".env.") or name in (
            ".netrc", ".pypirc", ".npmrc", ".aws", ".ssh", ".git"
        ):
            return False
        # 其他点文件（如 .editorconfig）保留
    if gitignore is not None and gitignore.ignored(rel.as_posix()):
        return False
    try:
        if path.stat().st_size > 10_000_000:  # 10MB 以上视为大文件
            return False
    except OSError:
        return False
    return True


def make_release_zip(root: Path, info: ProjectInfo, version: str, dest_dir: Path,
                     archive_name: str | None = None) -> Path:
    """把干净项目打成 zip，返回产物路径。archive_name 缺省用项目名。

    打包时同时尊重工具内置忽略规则与项目自定义 .gitignore。
    """
    root = Path(root).resolve()
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    base = (archive_name or info.name).replace(" ", "-")
    zip_name = f"{base}-{version}.zip"
    zip_path = dest_dir / zip_name

    gitignore = GitignoreMatcher(root)
    files: List[Path] = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and should_include(p, root, gitignore=gitignore):
            files.append(p)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            arcname = f"{info.name}/{p.relative_to(root).as_posix()}"
            zf.write(p, arcname)

    return zip_path
