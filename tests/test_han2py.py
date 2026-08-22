"""han2py 模块测试：目录名汉转英（零依赖缺省仓名）。"""

import os
import tempfile
import unittest
from pathlib import Path

from github_automator.han2py import han_to_repo_name, han_to_pinyin


class TestHan2Py(unittest.TestCase):
    def test_chinese_dir_to_pinyin_slug(self):
        # 「自动点击脚本」-> 拼音 slug（连字符分隔、小写）
        out = han_to_repo_name("自动点击脚本")
        self.assertEqual(out, "zi-dong-dian-ji-jiao-ben")

    def test_mixed_ascii_and_chinese(self):
        # ASCII 保留、中文转拼音、空格/标点归一为 -
        out = han_to_repo_name("My 项目 v2")
        self.assertEqual(out, "my-xiang-mu-v2")

    def test_ascii_only_passthrough(self):
        # 纯 ASCII 目录名：小写 slug 原样
        out = han_to_repo_name("My-Cool Project")
        self.assertEqual(out, "my-cool-project")

    def test_empty_fallback(self):
        # 无可用字符 -> 回退 github-automator
        out = han_to_repo_name("  ")
        self.assertEqual(out, "github-automator")

    def test_no_double_hyphen(self):
        # 多分隔符不应产生连续 --，且不以 - 开头/结尾
        out = han_to_repo_name("项目___名称...v1")
        self.assertNotIn("--", out)
        self.assertFalse(out.startswith("-"))
        self.assertFalse(out.endswith("-"))
        self.assertTrue(out.endswith("v1"))

    def test_pinyin_map_loaded(self):
        # 基本映射可用：汉字 -> 小写拼音
        self.assertEqual(han_to_pinyin("自"), "zi")
        self.assertEqual(han_to_pinyin("项目"), "xiangmu")


if __name__ == "__main__":
    unittest.main()
