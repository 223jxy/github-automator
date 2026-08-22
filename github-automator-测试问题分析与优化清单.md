# github-automator · 测试问题分析与优化清单

> 配套文档：`github-automator-项目介绍.md` / `github-automator-优化分析.md` / `github-automator-优化与更新记录.md` / `github-automator-规范手册.md`
> 本文档记录 **2026-08-23 真实发布测试**（首次真实跑通 ③ 全流程）中发现的问题与后续优化项，作为《优化分析》的实战补充。

---

## 一、测试回顾（这次做了什么）

| 步骤 | 命令 | 结果 |
|------|------|------|
| ① 单元自测 | `python -m unittest discover -s tests -v` | ✅ 22 tests OK |
| ② 自举 dry-run | `python -m github_automator.cli . --dry-run` | ✅ 分析正确、零写入 |
| ③ 真实发布（首次） | `...cli . --version v1.0.0`（未指定 --repo） | ⚠️ 建仓成功、本地提交成功、zip 生成成功，但 `git push` 失败 |
| ③ 真实发布（二次） | 同上（用户先跑 `gh auth setup-git`） | ✅ 全链路跑通：仓库 `223jxy/github-automator`、分支 `main`、Release v1.0.0 含 zip 资产 |

**结论**：工具核心逻辑（分析 / 打包 / 建仓 / Release）正确；暴露的问题是**凭据通道的健壮性缺口**，不是业务逻辑错误。

---

## 二、问题清单

状态图例：🔴 待修　🟡 待补（文档/流程）　✅ 已修复　⏸ 待议

### 问题 T1 — gh 路径推送未降级，缺 `gh auth setup-git` 即崩
- **现象**：首次发布到 `git push` 阶段报错
  ```
  fatal: could not read Username for 'https://github.com': No such device or address
  /dev/tty: No such device or address
  ```
- **根因**：`push()` 的 gh 分支（github.py:174-180）假设"系统装有 `gh` = git 已能用 gh 凭据"。但 `gh` 安装后默认**不会**自动接管 git 凭据，必须显式 `gh auth setup-git` 把 gh 注册为 git credential helper。未配置时，git 回退到交互式用户名/密码提示，非交互环境无 tty → 直接失败。
- **影响**：🟡 中等。首次使用 gh 通道的用户 100% 会踩；但失败**安全**（无 token 落盘，已验证），只是体验差、需人工干预。
- **优化项**：gh 路径推送失败时，运行时为本仓库**局部**配置 git 用 gh 作 credential helper（等效 `gh auth setup-git`，不写全局、不暴露明文 token），重试一次——"装了 gh 即开箱即推"，不依赖用户手动 `setup-git`。
- **优先级**：🟡 P1（健壮性）
- **状态**：✅ 已修复（`github.py` `push()` 的 gh 分支 + `_ensure_gh_git_credentials()`；测试 `test_push_gh_path_degrades_on_credential_error` 固化）

### 问题 T2 — 真实发布前无"凭据通道预检"
- **现象**：工具直到 `git push` 执行才暴露凭据不可用，前面建仓/提交/打包都已发生，浪费一次半流程。
- **根因**：`run()` 编排顺序为 建仓 → 提交 → 推送，推送前的 git 凭据可用性**未做任何前置探测**。
- **影响**：🟡 低-中。不改变结果正确性，但拉长反馈闭环、增加人工排错成本。
- **优化项**：在 `push()` 之前新增 `_check_git_credentials(root)` 预检——探测 git 能否拿到凭据（检查 `gh auth status` / `GITHUB_TOKEN`），不可用时**早失败并给出明确修复指引**（"请先 `gh auth setup-git` 或设置 GITHUB_TOKEN"）。
- **优先级**：🟡 P2（体验增强）
- **状态**：✅ 已修复（`github.py` `_check_git_credentials()`；测试 `test_check_git_credentials_*` 固化）

### 问题 T3 — 测试套件未覆盖"gh 路径推送失败降级"分支
- **现象**：我们给 `create_repo` 冲突分支补了 mock 测试，但 `push()` 的 gh→token 降级路径**没有任何测试**。
- **根因**：T1 的修复（若落地）会引入新分支，当前 `tests/` 没有对应覆盖；即便不修 T1，也应固化"gh 路径推送行为"的契约。
- **影响**：🔴 高（若修 T1 后无测试，会回归无人知）。
- **优化项**：`tests/test_github.py` 新增 `TestPush`：
  - `test_push_gh_path_degrades_on_credential_error`：mock `detect_gh=True` + mock `git push` 首次凭据失败 → 验证兜底配置后重试成功；
  - `test_push_gh_path_non_credential_error_still_raises`：分支冲突类错误 → 不盲目降级、直接抛出；
  - `test_push_no_gh_no_token_raises`：无 gh 且无 token → 预检即显式报错；
  - `test_check_git_credentials_*`：凭据预检三种分支（无 gh 无 token / 有 token / gh 就绪 / gh 未就绪）；
  - `test_git_check_credential_error_hint` + `test_git_check_missing_git_binary`：`_git_check` 语义化与缺失 git 兜底。
- **优先级**：🔴 P1（与 T1 绑定，修 T1 必带）
- **状态**：✅ 已修复（用例 22 → 31，全绿）

### 问题 T4 — 规范手册"维修要求 1.3 验证"未提及真实发布凭据预检
- **现象**：规范手册要求改动后跑 ①②，但没写"真实发布前必须确认凭据通道接通"。
- **根因**：手册写于真实发布之前，未沉淀本次教训。
- **影响**：🟡 低。文档滞后，不阻断使用，但后来者会重复踩 T1/T2。
- **优化项**：在《规范手册》"维修要求 1.3"补真实发布凭据预检；并把 T1/T2/T5 作为已知坑记录到"容错契约"新增 5.3 节。
- **优先级**：🟡 P2（文档同步）
- **状态**：✅ 已修复（规范手册 1.3 增补 + 新增 5.3 凭据通道节）

### 问题 T5 — 推送失败信息未指向根因
- **现象**：首次失败报 `could not read Username`，用户难以一眼判断是"没 setup-git"还是"token 错"。
- **根因**：`_git_check` 只透传 git 原始 stderr，未对"Username/tty"类错误做语义识别与友好提示。
- **影响**：🟡 低。排错体验，不改正确性。
- **优化项**：`_git_check` 命中 `could not read Username` / `No such file or directory` / `/dev/tty` 等凭据类错误时，附加根因提示。
- **优先级**：🟡 P2
- **状态**：✅ 已修复（`github.py` `_git_check` 的 `_CREDENTIAL_ERROR_HINTS` 语义化；测试 `test_git_check_credential_error_hint` 固化）

---

## 三、优化路线图（基于本次测试）

> 与《优化分析》P0/P1/P2 体系对齐：T 系列为本次测试新增项。

**Phase 4 — 发布健壮性（已全部落地 ✅）**
- ✅ T1：gh 路径推送自动降级（局部配置 gh credential helper 兜底，不依赖手动 `setup-git`）；
- ✅ T3：补 `TestPush` 等固化降级与预检契约（与 T1 绑定）；
- ✅ T2：发布前凭据通道预检，早失败早提示；
- ✅ T5：推送失败信息语义化（指向"没 setup-git / 没 token"）；
- ✅ T4：规范手册同步本次教训。

**优先级建议**（历史记录，均已落地）
- 必做：T1 + T3（成对，修一个必须带测试）→ 已完成；
- 推荐：T2（预检能显著缩短反馈闭环）→ 已完成；
- 可选：T5、T4（文档与提示增强）→ 已完成。

> **实现中发现的附加 bug（已修）**：T1 首次实现时，`push()` 的 gh 分支 `except` 块末尾写了无条件的 `raise`，导致即使降级重试成功仍会把原错误重新抛出——测试 `test_push_gh_path_degrades_on_credential_error` 直接暴露并修复（降级成功即 `return`，不再 `raise`）。这正是"修 T1 必带测试（T3）"的价值。

---

## 四、本次已验证"没问题"的点（避免误报）

| 检查项 | 结果 |
|--------|------|
| token 是否落盘 | ✅ 未写 `.git/config`（失败即因未用内联 URL，反证安全逻辑有效） |
| 缺省 `--repo` 逻辑 | ✅ 未指定时用包名 `github-automator`，与规范手册容错契约一致 |
| `has_commit()` 闸门 | ✅ 本地有提交才推，未建空仓库 |
| 仓库冲突复用 | ✅ 二次运行检测到仓库已存在 → 复用，未重复建仓 |
| Release 资产 | ✅ zip 正确上传为 Release 资产 |
| 22 个单元测试 | ✅ 全绿，纯注释/逻辑改动无回归 |

---

*本文档随测试演进更新；新增优化项落地后，状态由 ⏸ 改为 ✅ 并同步回《优化与更新记录》。*
