# github-automator 项目介绍

> 项目：`D:\workdubby\github自动化`（github-automator v0.1.0）
> 定位：纯标准库、零依赖的"项目 → GitHub"自动化发布工具
> 整理日期：2026-08-22

---

## 一、项目是什么

**github-automator** 是一个**纯标准库、零第三方依赖**的 Python 命令行工具（要求 `Python >= 3.8`），用于把"任意项目"自动**提炼 → 打包 → 发布到 GitHub**。

它解决的核心痛点：每次新建/整理一个仓库，都要手动写 `.gitignore`、写 `README`、打 Release 压缩包、建仓库、推代码——这套流程机械且易漏。github-automator 把它收敛成一条命令。

### 核心能力（一条命令的 6 步流水线）
1. **分析**项目：识别主语言、依赖清单、入口文件、生成目录树。
2. **生成 `.gitignore`**（若项目没有则写，已有则跳过）。
3. **生成 `README.md`**（若没有则写；带隐形标记防止"自生成回环"）。
4. **打包 Release 快照**：把"干净"的项目打成 zip，排除依赖目录/构建产物/大文件/密钥。
5. **创建 GitHub 仓库**并推送（优先用 `gh` CLI，回退到 REST API）。
6. **创建 Release** 并附带 zip 资产。

### 自举（Self-hosting）特性
这个工具**用它自己把当前仓库发布到了 GitHub**——README 里的"本文档由 github-automator 自动生成"标记、以及 `dist/` 里的 `github-automator-v0.1.0.zip` 都是它自己产出的。这是它最有力的活广告。

### 快速开始
```bash
# 默认把当前目录提炼打包，新建公开仓库并推送 + 打 Release
python cli.py .

# 指定项目路径、仓库名、版本
python cli.py /path/to/project --repo my-tool --version v1.0.0

# 仅演示，不真正推送（dry-run）
python cli.py . --dry-run

# 私有仓库 + 自定义 token
python cli.py . --repo secret --private --token ghp_xxx
```
> 认证优先级：`gh` CLI（最省心，token 不落盘）→ 回退 GitHub REST API（token 来自 `--token` 或环境变量 `GITHUB_TOKEN`）。

---

## 二、架构与模块

| 模块 | 职责 | 关键设计 |
|------|------|----------|
| `analyzer.py` | 只读扫描目录 → 产出 `ProjectInfo` 数据类 | 不写任何文件；语言/依赖/入口/目录树全收敛到一个数据类供下游消费 |
| `packager.py` | 生成 `.gitignore` + 打干净 zip | 按识别到的生态拼 `.gitignore` 片段；zip 排除忽略目录与大文件 |
| `docgen.py` | 生成 `README.md` | 用 HTML 注释作隐形标记，让分析器能识别"自生成"并避免回环 |
| `github.py` | 建仓库 / 推送 / 建 Release | 认证优先级：`gh` CLI → REST API（token 来自参数或 `GITHUB_TOKEN`） |
| `cli.py` | 参数解析 + 6 步编排 | `argparse`，支持 `--dry-run` / `--private` / `--token` / `--no-release` / `--force-readme` / `--refresh-gitignore`；缺省仓名=目录名汉转英，全链路零交互。**发布全程在临时目录进行，源项目保持只读**（不 git 化、不留 `.git`/`dist`） |
| `han2py.py` | 目录名「汉转英」 | 汉字逐音节转小写拼音并以 `-` 分隔；数据依赖 vendored `_han2py.json`（GB2312 6763 字，零运行时依赖） |
| `cli.py`（根） | 薄入口，等价 `python -m github_automator.cli` | 仅做 `sys.path` 注入后转发 `main()` |
| `tests/` | 单元测试 | 覆盖 `analyzer` / `packager` / `docgen` / `cli` / `github` / `han2py` 共 55 个用例 |

**数据流**：`analyze()` → `ProjectInfo` →（打包 / 文档 / 推送）全程以同一个 `ProjectInfo` 为载体，模块间解耦清晰。

```
cli.run(project)
   └─ analyze(project)            → ProjectInfo（只读源项目）
   └─ [临时目录 stage = tempdir/<repo>]
        └─ 过滤后复制源码到 stage（源项目零写入）
        └─ write_gitignore / write_readme（仅当源项目缺失时，写入 stage 而非源项目）
        └─ [git init / add -A / commit]   ← 仅作用于临时目录
        └─ make_release_zip(stage) → tempdir/<repo>-<version>.zip（不进 git 历史）
   └─ create_repo() + push(stage) → GitHub
   └─ create_release(asset=zip, cwd=stage) → GitHub Release（精确打到目标仓库）
```

---

## 三、技术亮点（值得保留的设计）

1. **零依赖、纯标准库**——真正"开箱即跑"，没有环境地狱。`pyproject.toml` 里 `dependencies = []`。
2. **关注点分离干净**：分析 / 打包 / 文档 / GitHub 交互各司其职，单测好写。
3. **幂等设计**：`.gitignore` 和 `README.md` 在已存在且未加 `--force` 时**跳过**，尊重用户已有内容，不会覆盖。
4. **自识别标记防回环**（巧妙）：生成的 README 含 `<!-- 本 README 由 github-automator 自动生成 -->`，分析器读到这个标记就不把它当"真实项目简介"复用——避免了"用自生成 README 再生成 README"的死循环。
5. **认证优先级合理**：优先 `gh`（token 不落盘），回退 API。
6. **跨平台**：全程 `pathlib`，无硬编码路径分隔符。
7. **测试通过且能自举**：55 个单测全绿，工具对自身可端到端跑通（含 dry-run 零写入、缺陷回归测试、覆盖式更新回归）。
8. **发布安全**：提交用 `_git_add_safe` 显式过滤，永不包括 `.workbuddy/` 等本地元数据（隐私红线）；Release 创建幂等（查重+续传资产），不因数次中断而崩。
9. **零交互 + 汉转英仓名**：给路径即全链路跑完；未指定 `--repo` 时仓库名自动从目录名转拼音 slug，无需人工干预。
10. **源项目零污染（Phase 7 新增）**：发布的所有 git 操作（init/add/commit/push）与 zip 生成都在**临时目录**完成，源项目保持只读——不会把"非 git 项目"误 git 化，也不残留 `.git`/`dist`；且仅当源项目缺失 `.gitignore`/`README` 时才把生成内容写入临时目录，绝不写回源项目。
11. **Release 精确到目标仓库（Phase 7 新增）**：`gh release create` 必须带 `cwd=stage`（临时发布目录，其 remote 指向目标仓库），否则会误打到工具自身仓库的工作目录；已修复。
