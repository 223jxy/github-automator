"""汉字转拼音仓库名（零运行时依赖）。

把中文目录名转成 ASCII 安全的英文仓库名，用于「未指定 --repo 时」的缺省仓名推断。
数据来源：vendored 的 `_han2py.json`（GB2312 6763 字拼音映射，由 pypinyin 预生成，
随包发布，运行时无需任何第三方库）。

转换规则：
- 汉字 -> 小写拼音（无声调）；
- ASCII 字母/数字原样保留（小写）；
- 空格、分隔符、标点统一归一为单个 `-`；
- 连续 `-` 合并、首尾 `-` 去除；
- 若结果全为空（无可用字符），回退为 `github-automator`。
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

_DATA_PATH = Path(__file__).resolve().parent / "_han2py.json"

# 懒加载，避免导入即读盘（仅首次调用时加载）
_map: dict[str, str] | None = None


def _load() -> dict[str, str]:
    global _map
    if _map is None:
        _map = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    return _map


def han_to_pinyin(text: str) -> str:
    """把字符串中的汉字转小写拼音，非汉字字符原样保留（不归一分隔符）。"""
    mp = _load()
    out: list[str] = []
    for ch in text:
        if ch in mp:
            out.append(mp[ch])
        else:
            out.append(ch)
    return "".join(out)


def han_to_repo_name(text: str) -> str:
    """把任意目录名转成合法的 GitHub 仓库名（小写、连字符分隔、ASCII 安全）。

    转换规则：
    - 汉字逐个转小写拼音，并在「相邻汉字音节」之间插入 `-`（提升可读性，
      符合 github slug 惯例：zi-dong-dian-ji-jiao-ben）；
    - ASCII 字母/数字连续段原样保留（小写）；
    - ASCII 段与拼音段、以及其它分隔符处，统一用单个 `-` 连接；
    - 连续 `-` 合并、首尾 `-` 去除；
    - 若结果全为空，回退为 `github-automator`。

    例：
        "自动点击脚本"   -> "zi-dong-dian-ji-jiao-ben"
        "My 项目 v2"     -> "my-xiang-mu-v2"
        "  "             -> "github-automator"（回退）
    """
    # 1) 逐字符处理：汉字转拼音并插入音节分隔；非汉字原样保留
    tokens: list[str] = []
    prev_was_han = False
    for ch in text:
        py = _map_char(ch)
        is_han = ch in _load()
        if py == "":
            # 非字母数字/非汉字的分隔符 -> 用占位标记词边界
            if tokens and tokens[-1] != "-":
                tokens.append("-")
            prev_was_han = False
            continue
        if is_han and prev_was_han:
            # 相邻汉字音节间加 -
            if tokens and tokens[-1] != "-":
                tokens.append("-")
        tokens.append(py.lower())
        prev_was_han = is_han

    raw = "".join(tokens)
    # 2) 合并连续 - 并去首尾 -
    raw = "-".join(p for p in raw.split("-") if p)
    if not raw:
        return "github-automator"
    return raw


def _map_char(ch: str) -> str:
    """单字符转写：汉字->拼音，ASCII 字母/数字原样，其它->空串。"""
    mp = _load()
    if ch in mp:
        return mp[ch]
    if ch.isascii() and (ch.isalpha() or ch.isdigit()):
        return ch
    return ""


if __name__ == "__main__":
    import sys
    sample = sys.argv[1] if len(sys.argv) > 1 else "自动点击脚本"
    print(han_to_repo_name(sample))
