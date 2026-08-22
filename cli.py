#!/usr/bin/env python3
"""github-automator 根入口。

等价于 `python -m github_automator.cli`，方便直接 `python cli.py .` 调用。
"""

import sys
from pathlib import Path

# 确保能 import 到同目录下的 github_automator 包
sys.path.insert(0, str(Path(__file__).resolve().parent))

from github_automator.cli import main

if __name__ == "__main__":
    sys.exit(main())
