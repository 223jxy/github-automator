---
name: github-publish-safety
version: 1.0.0
description: |
  This skill should be used when the user wants to package a local project and
  publish it to GitHub (create a repo, push code, and cut a Release with a zip
  snapshot), especially via a phrase like "发到 GitHub" / "帮我打包上传" / "发布这个项目"
  / "把这个目录推到 GitHub", or when handed a project path and asked to ship it.
  It drives the zero-dependency github-automator engine and adds an AI-side
  privacy or oversized-file gate plus a semantic repo-name suggestion before publishing.
agent_created: true
---

# GitHub 发布安全带（github-publish-safety）

## Overview

把"任意本地项目 → 安全发布到 GitHub"收敛成 AI 可接管的标准流程。底层引擎是
`github-automator`（纯标准库、零第三方依赖、零交互的 Python CLI）；本 skill 在引擎之上补上
**AI 侧的两道闸门**——发布前的隐私/体积审查和语义化仓库名建议——让"说一句就能发，且从没误传过错的东西"
成为现实。

定位：**AI 助手的项目发布安全带**（用户 = 本人 + AI 搭档，不做公网开源产品）。

---

## 引擎位置与调用方式

引擎代码固定在用户工作区 `D:\workdubby\github自动化`（包名 `github_automator`）。
调用统一用 `python -m github_automator.cli`，**不要另写发布脚本**，直接复用引擎。

```bash
# 0) 工具自检（确认 gh 已登录 + setup-git，否则发布必失败）
gh --version && gh auth status

# 1) 预览（零写入，先看将要打包/发布的计划）
python -m github_automator.cli "[项目路径]" --dry-run

# 2) 真实发布（不指定 --repo 时仓名=目录名汉转英；--repo 可指定语义英文名）
python -m github_automator.cli "[项目路径]" --repo [英文名] --version [标签]

# 常用参数
#   --repo [名]      仓库名（缺省=目录名拼音 slug，如 自动点击脚本→zi-dong-dian-ji-jiao-ben）
#   --version [标签] 默认 v1.0.0
#   --private        建私有仓库（默认公开）
#   --no-release     不打 Release（只建仓+推送）
#   --dry-run        只分析/生成/打包预览，不推送
#   --force-readme   覆盖已有 README
#   --refresh-gitignore  强制刷新/补全 .gitignore
```

**引擎已零交互**：给路径即全链路跑完（分析→.gitignore→README→zip→建仓→推送→Release），
致命错误（gh 未登录、仓库名被占）仍显式失败、不静默。

---

## Workflow（推荐流程）

### 步骤 1 — 识别发布意图
当用户表达"发布/上传/打包到 GitHub"或给出项目路径要求 ship 时，启用本 skill。
确认项目路径（若用户只说"这个项目"则取当前工作区）。

### 步骤 2 — dry-run 预览（必做，零成本）
先跑 `--dry-run`，拿到引擎计划：将生成的 `.gitignore` / `README`、zip 名、仓库名、标签。
这步不写任何文件，仅用于后续闸门判断。

### 步骤 3 — 隐私 / 体积闸门（本 skill 的核心增值）
**引擎只按 `.gitignore` 排除，不会"理解"目录语义**。AI 必须额外扫一遍项目根，主动识别
**不应上传**的内容，并在发布前处理（扩展目标项目 `.gitignore` 或提示用户）：

- **大目录**（超过 50MB 或明显是运行产物）：`logs/`、`outputs/`、`work/`、`__pycache__/`、
  `.venv/`、`node_modules/`、`dist/`（若非源码）、`_archive_*`、`tmp/`。
- **隐私 / 密钥**：`.env`、`.env.*`、`*.key`、`*.pem`、`secrets.json`、`credentials.json`、
  `.workbuddy/`（本地助手元数据，按隐私红线不公开）。
- **截图 / 媒体 / 数据集**：游戏截图、用户上传图片、大模型权重、训练数据等——除非用户明确要发。
- **嵌套 `.gitignore` 陷阱**：已被忽略目录内的 `.gitignore` 可能泄漏（引擎缺陷2已修，仍建议复核）。

**处理方式（二选一，按用户指令）**：
- 默认：把上述目录写进目标项目 `.gitignore`（目录名独占一行、注释单独成行——引擎的
  `GitignoreMatcher` **不支持行内 `#` 注释**，写在一行会失效），再发布。
- 用户说"直接发/别问"：跳过本步，进入零交互模式（步骤 5）。

**绝对红线**：`.workbuddy/`、密钥文件、个人/商业敏感数据**永不上传**。拿不准就先列出来让用户确认。

### 步骤 4 — 建议语义化仓库名（非中文目录时可选）
- 目录是中文：引擎默认给拼音 slug（如 `zi-dong-dian-ji-jiao-ben`），**可读性差但可用**。
  若用户能给语义英文名（如 `sevenday-automation`），优先用 `--repo` 指定。
- 目录已是英文/拼音：直接用，无需干预。
- 若用户未指定且目录含中文，可**主动提议**一个语义英文名供其确认（非强制）。

### 步骤 5 — 执行发布（按交互级别）
- **零交互模式**（用户说"直接发/别问"）：跳过步骤 3/4 的确认，直接跑真实发布命令。
- **确认模式**（默认）：步骤 3/4 后，用一两句话汇报"将要上传的内容 + 已排除的项"，
  等用户点头再执行真实发布。

### 步骤 6 — 验证与汇报
发布后核对：仓库是否建好（公开/私有符合预期）、代码已推送、Release 资产 zip 已上传、
zip 内顶层目录名是否与仓库名一致。把仓库地址和 Release 链接回报给用户。

---

## 已知限制（必须心里有数）

1. **拼音仓名非语义**：自动转写仅到音节级拼音，无法翻译为有意义的英文。语义名靠 `--repo`。
2. **极生僻 / 繁体字**可能不在拼音映射表，触发回退名 `github-automator`——中文目录建议显式 `--repo`。
3. **前置依赖**：本机需 `gh` CLI 已登录且跑过 `gh auth setup-git`（否则 git 推送因无凭据失败）。
   这是引擎安全设计（不把 token 写进 `.git/config`），非 bug。
4. **撞已存在 tag/Release**：引擎已做幂等（查重+续传资产），不会因"already exists"中断上传。
5. **引擎不审语义**：它只按 `.gitignore` 排除，AI 的隐私闸门（步骤 3）不可替代。

---

## 参考

- 引擎完整能力、模块结构、技术亮点见 `D:\workdubby\github自动化\github-automator-项目介绍.md`。
- 项目方向/边界/不做项见 `D:\workdubby\github自动化\github-automator-项目定位.md`。
- 引擎已知缺陷与修复记录见 `D:\workdubby\github自动化\github-automator-缺陷修复清单.md`（含 GitHub issue #1）。
- 变更与版本记录见 `D:\workdubby\github自动化\github-automator-优化与更新记录.md`。
