<!-- 本 README 为项目总索引，由维护者维护（非工具自动生成） -->
# github-automator

> 一个**零依赖、纯标准库**的命令行工具：把任意项目自动提炼、打包并发布到 GitHub（分析 → 生成 README/.gitignore → 打 zip 快照 → 建仓库 → 推送 → 打 Release）。

## 文档导航（先读这里）

| 文档 | 用途 | 读者 |
|------|------|------|
| [github-automator-项目介绍.md](github-automator-项目介绍.md) | 工具是什么、架构、技术亮点、快速开始 | 新接触项目的人 |
| [github-automator-优化分析.md](github-automator-优化分析.md) | 该优化什么 / 为什么优化 + 带状态的路线图 | 想理解演进动机的人 |
| [github-automator-优化与更新记录.md](github-automator-优化与更新记录.md) | 具体改法、验证、修复状态对照 | 接手维护的人 |
| [github-automator-规范手册.md](github-automator-规范手册.md) | **维修要求 / 发展方向 / 文件格式 / 代码规范**（单一规范源） | 所有改动者（必读） |

> 改动代码或文档前，**先读规范手册第一章"维修要求"**。

## 快速开始

```bash
# 零依赖，无需 pip install（纯标准库）
python cli.py .                       # 提炼当前目录并发布
python cli.py /path/to/project --repo my-tool --version v1.0.0
python cli.py . --dry-run             # 仅预览计划，不写任何文件
python cli.py . --private --token ghp_xxx
```

- 认证：优先用已登录的 `gh` CLI（token 不落盘）；否则用 `--token` 或环境变量 `GITHUB_TOKEN`。
- 验证测试：`python -m unittest discover -s tests -v`（期望 Ran 55 tests ... OK）。

## 核心模块

```text
github_automator/
├── analyzer.py     # 只读分析：语言/依赖/入口/目录树
├── packager.py     # 生成 .gitignore + 干净 zip 快照（含 GitignoreMatcher）
├── docgen.py       # 基于分析结果生成 README
├── github.py       # GitHub 推送/Release（认证 + 安全约束）
└── cli.py          # 包内编排（run()）
```

## 许可证

见 [LICENSE](LICENSE)。
