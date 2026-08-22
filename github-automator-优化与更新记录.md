# github-automator 优化与更新记录

> 项目：`D:\workdubby\github自动化`（github-automator v0.1.0）
> 更新日期：2026-08-22
> 配套文档：优化"What & Why"见《github-automator-优化分析》；工具本体介绍见《github-automator-项目介绍》。
> 原则：轻量化、执行成本低、可落地——**手术刀式小修改**：不引入新依赖、不重构，每个改动独立可验证。

---

## 一、已落地改动（优化文档）

| # | 优先级 | 文件 | 改动 | 验证 |
|---|--------|------|------|------|
| 1 | 🔴 P0 安全 | `github.py` | 新增 `build_push_url()`；重写 `push()`：非 gh 路径只把**不含 token 的 plain remote** 持久化，推送用内联 token URL 且**不加 `-u`**，并 `--set-upstream-to` plain origin。token 不再写入 `.git/config`。 | `build_push_url` 单测通过；`git remote set-url` 调用已移除 |
| 2 | 🟠 P1 | `cli.py` | `run()` 重构：`--dry-run` 分支提前返回，**只打印计划、不写任何文件/目录**（.gitignore/README/zip 全部后置）。新增 `--refresh-gitignore` 参数。 | `test_dry_run_writes_nothing` 验证：dry-run 后无 .gitignore/README/dist |
| 3 | 🟠 P1 | `packager.py` | `write_gitignore()` 增加 `force` 参数（支持刷新过时 .gitignore）；`should_include()` 改为**只排除密钥类点文件**（.env/.env.*/.netrc/.pypirc/.npmrc/.aws/.ssh/.git），保留 `.editorconfig` 等配置点文件。 | `test_should_include_keeps_config_dotfiles`、`test_write_gitignore_force_refresh` 通过 |
| 4 | 🟡 P2 | `docgen.py` | 安装说明按实际依赖清单输出：有 `requirements.txt` → `pip install -r`；有 `pyproject.toml` → `pip install -e .`；零依赖 → 提示无需安装。 | 本仓库 README 安装段已变为准确内容 |
| 5 | 测试 | `tests/` | 新增 `test_github.py`（含 `build_push_url` / `has_commit` / `_git_check`）、`test_cli.py`（dry-run 零写入）；扩展 `test_packager.py`（点文件 / force / 自定义 .gitignore / 匹配器）。用例 10 → **20**。 | `unittest discover` 全绿 |
| 6 | 🟠 P1 | `packager.py` | 新增 `GitignoreMatcher`（轻量 glob 匹配：支持 `*`/`**`/目录后缀/根锚点/否定 `!`）；`make_release_zip` 与 `should_include` 接入，使 **Release 快照尊重项目自定义 `.gitignore`**（如 `data/`、业务密钥目录、`*.log`）。 | `test_release_zip_respects_custom_gitignore`、`test_gitignore_matcher` 通过；对真实仓库核查 `dist/`、`.env`、`__pycache__/` 均被识别为忽略 |
| 7 | 🟠 P1 | `cli.py` / `github.py` | `push()` 改用 `_git_check` 显式抛错（不再 `check=False` 静默吞错）；`cli.run()` 提交失败直接抛出；推送前用 `has_commit()` 校验，本地无提交时拒绝创建空仓库。 | `test_git_check_raises_on_failure`、`test_has_commit_*` 通过；dry-run 与真实代码路径均验证 |

---

## 二、应用到本仓库（"吃自己的狗粮"）

- 用新工具刷新了本仓库 `.gitignore`，**补全缺失的 Python 片段**（`__pycache__/`、`*.pyc`、`*.egg-info/`、`.venv/`、`dist/` 等）。
- 删除了 `github_automator/__pycache__/` 字节码缓存与上次 dry-run 产生的 `dist/github自动化-v1.0.0.zip`（验证后清理）。
- 用新工具重新生成了 `README.md`（安装段现已准确反映"零依赖"）。
- 重新分析：`文件数 19 / 代码 12 / 生态 Python`，无 `.pyc` 残留（已被新 `.gitignore` 忽略）。

---

## 三、验证结果（更新文档 · 实测）

```bash
python -m unittest discover -s tests -v
# Ran 20 tests in ~11s  →  OK（全部通过）

python cli.py . --dry-run
# DRY-RUN 模式：不写入任何文件，仅预览计划。  ← 确认零写入
# 计划：写入/确认 .gitignore、README.md，生成 github-automator-v1.0.0.zip，新建仓库 …（公开），标签 v1.0.0

ls dist/        # 仅 github-automator-v0.1.0.zip（原始发布包），无新文件
grep -c "__pycache__\|\*.pyc" .gitignore   # 命中，Python 片段已补全
```

---

## 四、修复后状态对照

| 原问题 | 状态 |
|--------|------|
| P0 token 落盘（注释矛盾） | ✅ 已修复 |
| P1 `--dry-run` 写文件 | ✅ 已修复 |
| P1 `.gitignore` 过时 / 不刷新 | ✅ 已修复（新增 `--refresh-gitignore`） |
| P1 zip 丢弃配置点文件 | ✅ 已修复（保留 `.editorconfig` 等） |
| P2 README 引用不存在的 requirements.txt | ✅ 已修复（按依赖条件输出） |
| P2 cli/github 无测试 | ✅ 已补充（20 用例） |
| P1 不读取项目原有 `.gitignore`（zip 尊重自定义规则） | ✅ 已修复（新增 `GitignoreMatcher`） |
| P1 push 先推后判 remote / `check=False` 吞错 | ✅ 已修复（`_git_check` 显式抛错 + `has_commit()` 闸门） |
| Phase 4 发布凭据健壮性（T1–T5） | ✅ 代码已落地（详见第五节）；提交与重发见下文 |

> **收尾状态**：原分析的 P0、全部 P1 及 P2 中"README 引用不存在的 requirements.txt""cli/github 无测试"均已落地并验证。仅剩 P2 中"重复运行幂等/已发布检测"（问题 6）与"依赖解析展示增强"（问题 10）列为后续可选打磨项——二者均不影响当前工具的可用性与安全性，故按"轻量化、低成本可落地"原则暂不实施。
>
> **版本化说明（2026-08-23 复审后补）**：Phase 4（T1–T5）代码改动在落地时**未及时提交 git**，导致远程仓库与 Release v1.0.0 一度不含这些修复。经全量复审（见《审核报告》）发现后，已在本轮统一提交并重新发布，恢复"自举闭环"。测试用例数自 22 增至 **31**。

---

## 五、Phase 4 — 发布凭据健壮性（2026-08-23 真实发布测试后）

基于首次真实发布（建仓+提交+打包成功，但 `git push` 因 gh 未 `setup-git` 失败）暴露的 5 个问题（T1–T5，详见《测试问题分析与优化清单》），全部落地：

| 项 | 问题 | 改动位置 | 验证 |
|----|------|----------|------|
| T1 | gh 路径推送未降级 | `github.py` `push()` 新增 gh 分支降级：凭据不可用时局部配置 gh credential helper 兜底并重试一次（不写全局、不暴露明文 token） | `test_push_gh_path_degrades_on_credential_error` |
| T2 | 发布前无凭据预检 | `github.py` 新增 `_check_git_credentials()`，`push()` 开头调用，凭据缺失早失败并提示 `gh auth setup-git` / `GITHUB_TOKEN` | `test_check_git_credentials_*` |
| T3 | 测试未覆盖 push 降级 | `test_github.py` 新增 `TestPush` + `TestCheckCredentials`（mock 不触网） | 用例 22 → 31，全绿 |
| T4 | 规范手册未记该坑 | 规范手册 1.3 增补发布凭据预检；新增 5.3 凭据通道节 | 文档审查 |
| T5 | 推送失败信息未指向根因 | `github.py` `_git_check` 的 `_CREDENTIAL_ERROR_HINTS` 语义化（命中"could not read Username/tty"等附加根因提示）；并补 git 缺失兜底 | `test_git_check_credential_error_hint` / `test_git_check_missing_git_binary` |

**实现中修复的附加 bug**：T1 首次实现时 `push()` gh 分支 `except` 块末尾无条件 `raise`，导致降级重试成功仍抛原错——被 `test_push_gh_path_degrades_on_credential_error` 暴露后改为"降级成功即 return"。

**当前测试总数**：31（原 22 + 新增 9）。`python -m unittest discover -s tests` → **Ran 31 tests ... OK**。

> 设计原则保持：纯标准库、token 不落盘、轻量可落地。Phase 4 未引入任何第三方依赖。

---

## 六、Phase 5 — 缺陷修复 + 仓名汉转英 + 零交互（2026-08-23）

基于第三方项目「自动点击脚本」真实发布（`sevenday-automation` v1.0.0，见 issue #1）暴露的 3 个工具自身缺陷，全部修复，并按需求改造仓名推断与交互模式。

### 缺陷修复

| # | 缺陷 | 严重度 | 改动位置 | 验证 |
|---|------|--------|----------|------|
| 1 | `GitignoreMatcher` 不支持行内 `#` 注释（排除规则静默失效） | 中 | `packager.py` `GitignoreMatcher` 新增 `_strip_inline_comment()`（保护引号内 `#`），解析前剥离行内注释 | `test_gitignore_matcher_inline_comment` / `..._does_not_break_negation` |
| 2 | `should_include` 无条件保留所有 `.gitignore`（被忽略目录内嵌套 .gitignore 泄漏） | 中 | `packager.py` `should_include` 调整顺序：先判自定义 `.gitignore` 命中，再决定是否保留根 `.gitignore`；`analyzer.py:277` 同步 | `test_nested_gitignore_in_ignored_dir_excluded` / `test_root_gitignore_still_included` / `test_one_level_nested_gitignore_outside_ignored_kept` |
| 3 | `create_release` 不幂等（撞 already-exists 直接抛、中断资产上传） | 高 | `github.py` 新增 `_gh_release_view()` / `_gh_upload_asset()`；gh 与 token 路径均加 Release/Tag 查重，已存在则跳过或续传资产，非 already-exists 错误仍抛 | `TestCreateRelease`（exists_skips / exists_missing_asset_uploads / already_exists_recovers / real_error_still_raises） |

### 仓名汉转英 + 零交互改造

- 新增 `github_automator/han2py.py` + vendored 数据 `github_automator/_han2py.json`（GB2312 6763 字拼音映射，由 pypinyin 预生成，**随包发布、运行时零第三方依赖**）。
- `han_to_repo_name(dirname)`：汉字逐音节转小写拼音并以 `-` 分隔，ASCII 段保留，其它归一为 `-`；无可用字符回退 `github-automator`。
  - 例：`自动点击脚本` → `zi-dong-dian-ji-jiao-ben`；`My 项目 v2` → `my-xiang-mu-v2`。
- `cli.py`：缺省仓名从「包名 `github-automator`」改为 `_default_repo_name(project)`（目录名汉转英）；删除「未指定 --repo」提示打印，**全链路零交互**（给路径即跑到底）。`--repo` 显式指定仍优先。
- 限制（已写入缺陷清单）：自动转写为**音节级拼音**，无法语义翻译；极生僻/繁体字可能不在映射表，触发回退名。

### 验证
- `python -m unittest discover -s tests` → **Ran 46 tests ... OK**（原 31 + 新增 15）。
- dry-run 端到端：目录「自动点击脚本」不传 `--repo` → 推断仓名 `zi-dong-dian-ji-jiao-ben`，无交互提示。

> 设计原则保持：纯标准库（运行时）、token 不落盘、轻量可落地。仅新增一份 vendored 静态数据 `_han2py.json`（~93KB），不引入任何运行时第三方依赖。
