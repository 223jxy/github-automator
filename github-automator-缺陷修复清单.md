# github-automator 缺陷修复清单

> 来源：第三方项目「七日世界自动制作脚本」真实发布（`223jxy/sevenday-automation` v1.0.0）暴露的工具自身缺陷。
> 关联 Issue：https://github.com/223jxy/github-automator/issues/1
> 状态图例：⏸ 待做 / 🔧 进行中 / ✅ 已完成

---

## 背景

`github-automator` 是一个零第三方依赖的 Python CLI 自托管工具：分析项目 → 生成 `.gitignore` → 生成 README → 打 zip 快照 → git 初始化/提交 → 建仓库 → 推送 → 打 Release。

本次对第三方项目做真实打包时，发现 3 个工具自身缺陷。其中缺陷 1、2 已在打包阶段靠「手工调整目标 `.gitignore`」规避；缺陷 3 导致 Release 资产上传中断、需手动 `gh release create` 补完。

**修复状态（2026-08-23 完成）**：缺陷 1/2/3 代码均已修复，并新增 15 个单测（测试总数 31→46 全绿）。同时按需求改造仓名推断为「目录名汉转英」+ 全链路零交互。

---

## 缺陷 1：GitignoreMatcher 不支持行内 `#` 注释

| 项 | 内容 |
|---|---|
| 严重度 | 中（排除规则可静默失效） |
| 位置 | `github_automator/packager.py` `GitignoreMatcher.__init__` 第 128–130 行 |
| 现象 | 解析 `.gitignore` 时仅跳过「行首 `#`」整行注释；若写成 `outputs/    # 注释`，会把整行（含 `    # 注释`）当成 glob 编译，导致该排除项**失效**，注释文本被当模式。 |
| 影响 | 本应排除的目录（如游戏截图 `outputs/`、日志 `logs/`）可能被打进 zip，违反「截图不上传」的隐私/体积要求。 |
| 本次规避 | 目标项目 `.gitignore` 改为「目录名独占一行、注释单独成行」，第 26 行留提示。 |

### 修复方案
在 `_parse` 阶段、判空/去空格之前，先剥离行内注释（需保护引号内的 `#`，虽然 `.gitignore` 罕见但严谨）：

```python
for raw in gif.read_text(encoding="utf-8", errors="ignore").splitlines():
    # 先剥离行内注释：遇到第一个未加引号的 '#' 截断
    line = _strip_inline_comment(raw.rstrip())
    if not line or line.lstrip().startswith("#"):
        continue
    ...
```

辅助函数（不破坏现有 `* / ** / 目录后缀 / 根锚点 / 否定(!)` 解析）：
```python
@staticmethod
def _strip_inline_comment(line: str) -> str:
    in_quote = False
    for i, ch in enumerate(line):
        if ch in ("'", '"'):
            in_quote = not in_quote
        elif ch == "#" and not in_quote:
            return line[:i].rstrip()
    return line.rstrip()
```

### 验收标准
- 新增单测 `TestGitignoreMatcher`：
  - `test_inline_comment_stripped`：`outputs/  # 运行产物` 应被解析为忽略 `outputs/`，且不把注释当模式。
  - `test_quoted_hash_not_stripped`：`"a#b"` 类（极端）不被误截。
- 回归：现有合法 `.gitignore`（整行注释/目录后缀/`!` 否定/`**/`）行为不变。
- 跑 `python -m unittest discover -s tests` 全绿。

---

## 缺陷 2：should_include 无条件保留所有 `.gitignore` 文件

| 项 | 内容 |
|---|---|
| 严重度 | 中（被忽略目录内的嵌套 `.gitignore` 会泄漏） |
| 位置 | `github_automator/packager.py` `should_include` 第 189–190 行；同类逻辑 `analyzer.py:277`（仅影响目录树展示，影响较小但应一致） |
| 现象 | `if path.name in (".gitignore",) or path.name.endswith(".gitignore"): return True` —— 该规则**优先级高于自定义 `.gitignore` 的忽略规则**。被忽略目录下若存在嵌套 `.gitignore`（如 `outputs/xxx/.gitignore`），仍会被打进 zip。 |
| 影响 | 本次真实打包 zip 内出现 1 条泄漏：`sevenday-automation/outputs/auto_craft_before_walk_fix_20260821_003524/.gitignore`（空占位、无隐私）。若被忽略目录含带敏感内容的 `.gitignore`，则会泄露。 |
| 本次规避 | 无（该泄漏无害，仅记录）。 |

### 修复方案
调整 `should_include` 顺序：先判自定义 `.gitignore` 命中，再决定是否因「是 `.gitignore` 文件」保留。

```python
def should_include(path, root, gitignore=None):
    rel = path.relative_to(root)
    if any(part in DEFAULT_IGNORE_DIRS for part in rel.parts):
        return False
    # 先应用项目自定义 .gitignore（优先级高于「保留 .gitignore」特殊规则）
    if gitignore is not None and gitignore.ignored(rel.as_posix()):
        return False
    # 仅当位于非忽略目录时，保留根/顶层 .gitignore（供下游复用规则）
    if path.name == ".gitignore" and len(rel.parts) <= 1:
        return True
    # 密钥 / 凭据类点文件排除 ...
    ...
```

注意：需保证「根 `.gitignore` 仍被打包」（下游 unpack 后才能复用忽略规则），但**被忽略目录内的嵌套 `.gitignore` 应随目录一起被排除**。

`analyzer.py:277` 同步改为：保留 `.gitignore` 仅当不在被忽略目录内。

### 验收标准
- 新增单测：
  - `test_nested_gitignore_in_ignored_dir_excluded`：构造 `outputs/x/.gitignore`，`outputs/` 已被自定义忽略 → `should_include` 返回 False。
  - `test_root_gitignore_still_included`：根 `.gitignore` → 仍返回 True。
- 回归：现有 31 测试 + 缺陷 1 测试全绿。

---

## 缺陷 3：create_release 不幂等，撞已存在 tag 直接抛异常并中断资产上传

| 项 | 内容 |
|---|---|
| 严重度 | 高（发布链路断裂，需手动补） |
| 位置 | `github_automator/github.py` `create_release` 第 269–280 行（gh 路径）；第 282–290 行（token 路径同样无幂等） |
| 现象 | 直接 `gh release create <tag>`，返回非 0 即 `raise RuntimeError`。**无 release/tag 预检、无重试、无续传**。本次因前置 502 抖动，远程实际无 Release 也无 tag ref，但 `gh` 报 "a release with the same tag name already exists"，方法抛异常 → **zip 资产上传被完全跳过**，Release 未建成。 |
| 影响 | 发布链路在「仓库已建、代码已推」之后断裂，用户需手动 `gh release create` 补完（本次已手动补）。 |
| 本次规避 | 手动 `gh release create v1.0.0 ./dist/...zip ...` 成功补完。 |

### 修复方案（gh 路径 + token 路径同时加固）
1. **创建前查重**：先 `gh release view <tag>`（gh 路径）/ `GET /releases/tags/<tag>`（token 路径）。
   - 若 Release 已存在且资产齐全 → 直接返回其 url（幂等跳过）。
   - 若 Release 已存在但资产缺失 → 补传资产，返回 url。
2. **捕获 already-exists**：`gh release create` 失败且 stderr 含 "already exists" → 转查重逻辑续传，而非直接抛。
3. **token 路径同样加 tag 查重**（避免重复 POST 同样 422）。

伪代码（gh 路径）：
```python
def create_release(...):
    if detect_gh():
        existing = _gh_release_view(tag)            # 查重，不存在返回 None
        if existing and _asset_present(existing, asset_path):
            return existing["url"]                  # 幂等跳过
        cmd = ["gh", "release", "create", tag, "--title", name, "--notes", notes]
        if asset_path:
            cmd.append(str(asset_path))
        r = _run(cmd, check=False)
        if r.returncode != 0:
            if "already exists" in r.stderr.lower():
                # 后端状态不一致：查重后补传资产
                existing = _gh_release_view(tag)
                if existing and asset_path:
                    _gh_release_upload_asset(existing["id"], asset_path)
                    return existing["url"]
            raise RuntimeError(f"gh release create 失败：{r.stderr.strip()}")
        ...
```

### 验收标准
- 新增单测 `TestCreateRelease`（mock `_run`）：
  - `test_release_exists_skips`：已存在且资产齐 → 不调 create，返回现有 url。
  - `test_already_exists_recovers`：create 报 already-exists → 查重后续传资产、返回 url、不抛。
  - `test_real_error_still_raises`：非 already-exists 错误（如网络）→ 仍抛。
- 回归：现有 `TestPush`/`TestCheckCredentials` 不受影响。
- 端到端：对 `sevenday-automation` 重跑工具，确认无需手动补 Release。

---

## 执行顺序建议

| 次序 | 缺陷 | 状态 |
|---|---|---|
| 1 | 缺陷 1（行内注释） | ✅ 已修复（`GitignoreMatcher._strip_inline_comment`） |
| 2 | 缺陷 2（.gitignore 保留） | ✅ 已修复（`should_include` 顺序调整 + `analyzer.py` 同步） |
| 3 | 缺陷 3（create_release 幂等） | ✅ 已修复（`_gh_release_view` / `_gh_upload_asset` / token 路径查重） |
| 4 | 缺陷 4（`git add -A` 误推敏感目录） | ✅ 已修复（`_git_add_safe` 替代 `git add -A`） |

## 缺陷 4：`git add -A` 可能把敏感目录推到公开仓库（隐私隐患）

| 项 | 内容 |
|---|---|
| 严重度 | 高（隐私泄漏，曾在 v1.2.0 真实发生） |
| 位置 | `github_automator/cli.py` `run()` 第 99 行（原 `git add -A`） |
| 现象 | 工具自举发布时用 `git add -A` 暂存全部文件。若项目历史中 `.workbuddy/`（本地助手记忆/元数据）**已被 tracked**，`.gitignore` 对它无效（gitignore 只作用于未跟踪文件），会被一并提交并推到公开 GitHub 仓库。 |
| 影响 | 2026-08-23 发布 v1.2.0 时，`.workbuddy/memory/*.md` 被推到公开仓库（`223jxy/github-automator`），违反隐私红线（本地助手元数据不公开）。事后靠 `git rm --cached` + 删 tag 重建 Release 补救。 |
| 本次修复 | 新增 `_git_add_safe(project)`：遍历项目文件，仅 `git add` 通过 `should_include` 过滤的文件，并**显式兜底排除** `.git` / `.workbuddy` / `dist` 目录（dist 为发布资产已单独上传，不进历史）。替代 `git add -A`。 |

### 修复方案
```python
def _git_add_safe(project: Path) -> None:
    root = Path(project).resolve()
    gitignore = GitignoreMatcher(root)
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if ".git" in rel.parts or ".workbuddy" in rel.parts or "dist" in rel.parts:
            continue
        if should_include(p, root, gitignore=gitignore):
            _git(["add", str(p)], cwd=project, check=False)
```
- 复用打包快照同一套过滤逻辑（`should_include` + `GitignoreMatcher`），保证「仓库提交内容」与「Release zip 内容」一致。
- 即使 `should_include` 有疏漏，`.workbuddy` 兜底仍生效——双保险。

### 验收标准
- 新增单测 `TestGitAddSafe`：
  - `test_never_adds_workbuddy`：构造含 `.workbuddy/memory.md`（模拟历史 tracked）和 `dist/x.zip` 的项目，mock `_git` 捕获 add 调用，断言二者绝不被加、源码 `main.py` 被加。
  - `test_adds_source_respecting_gitignore`：自定义 `.gitignore` 排除 `secret.txt`，断言其不被加。
- 回归：现有 46 测试 + 该 2 项 = **48 测试全绿**（`unittest discover` Ran 48 tests OK）。
- 真实验证（可选）：在任意项目跑工具，核查远程根目录不含 `.workbuddy/`。

## 缺陷 5：发布直接 `git init` 源项目，污染用户项目（误 git 化 + 残留 dist）

| 项 | 内容 |
|---|---|
| 严重度 | 高（污染用户工作区，且暴露工具内部行为） |
| 位置 | `github_automator/cli.py` `run()` 原第 106–125 行（`git init` / `commit` 直接作用于 `project` 源目录） |
| 现象 | 工具在**源项目目录**就地 `git init`、提交、生成 `dist/<repo>-<version>.zip`。若用户项目本不是 git 仓库（如 `网盘整理工具/netdisk-organizer`），会被强制 git 化；且源项目残留 `dist/`（工具产物）。 |
| 影响 | 真实发布 `netdisk-organizer` 时，源项目被建了 `.git`（首次运行的 commit 还因 gh 未认证失败，留下半截 git 状态）；用户工作区被污染，违背"工具只读取源项目"的假设。 |
| 本次修复 | 发布的所有 git 操作与 zip 生成**全部迁移到临时目录**（`tempfile.TemporaryDirectory`）：过滤后复制源码到 `stage`，在 `stage` 内 `init/add/commit/push`；zip 生成到临时目录顶层（不进 `stage` 的 git 历史）。源项目**全程只读**，不产生 `.git`/`dist`、不被写回。 |

### 修复方案（核心改动 `run()` 第 113–167 行）
```python
with tempfile.TemporaryDirectory(prefix="gh-auto-") as tmp:
    tmp = Path(tmp)
    stage = tmp / repo                      # 临时发布目录
    stage.mkdir(parents=True, exist_ok=True)
    # 1) 过滤后复制源码到 stage（源项目只读）
    for p in sorted(project.rglob("*")):
        ...
        if should_include(p, project, gitignore=gitignore):
            shutil.copy2(p, stage / rel)
    # 2) 仅当源项目缺失时才把生成内容写入 stage（不污染源项目）
    if gi_text is not None: (stage/".gitignore").write_text(gi_text, ...)
    if readme_text is not None: (stage/"README.md").write_text(readme_text, ...)
    # 3) git 操作仅作用于 stage
    _git(["init"], cwd=stage); _git(["add","-A"], cwd=stage); ...
    # 4) zip 生成到 tmp 顶层（不进 stage 的 git 历史）
    zip_path = make_release_zip(stage, info, version, tmp, archive_name=repo)
    push(stage, ...); create_release(..., cwd=stage)
```

### 验收标准
- 新增单测 `TestRunDoesNotPolluteSource`：
  - `test_source_project_untouched_no_git_no_dist_added`：源项目发布后无 `.git`、文件集合不变。
  - `test_source_with_only_untracked_dist_does_not_crash`：源项目仅含未跟踪 `dist` 时正常完成（rc=0）且不崩溃。
- 真实验证：`netdisk-organizer` 发布后 `ls` 源项目确认无 `.git`、无 `dist`（✅ 已验证）。

## 缺陷 6：`create_release` 的 `gh` 路径未传 `cwd`，Release 误打到工具自身仓库

| 项 | 内容 |
|---|---|
| 严重度 | 中（Release 发错仓库，需手动纠错） |
| 位置 | `github_automator/github.py` `create_release` / `_gh_release_view` / `_gh_upload_asset`（gh 路径未带 `cwd`） |
| 现象 | `gh release create` 默认作用于「进程当前工作目录」的 git remote，而工具进程 cwd 是 `github-automator` 工作区。导致 `netdisk-organizer` 发布时，Release 被误打到 `github-automator` 仓库（仅因它已有同名 tag 被幂等复用，未新建，但 URL 错误）。 |
| 影响 | 目标仓库 `netdisk-organizer` 缺 Release；工具日志显示错误仓库 URL，误导排查。 |
| 本次修复 | 给 `create_release` / `_gh_release_view` / `_gh_upload_asset` 增加 `cwd` 参数；`cli.run` 调用时传入 `cwd=stage`（临时发布目录，remote 指向目标仓库）。gh 作用到正确仓库。 |

### 验收标准
- 单测 `test_source_project_untouched_...` 已断言 `create_release` 被传入 `cwd` 且 `cwd != Path.cwd()`、`repo == "myproj"`（目标仓库名正确）。
- 真实验证：`netdisk-organizer` 已正确创建 v1.0.0 Release 于自身仓库（✅ `https://github.com/223jxy/netdisk-organizer/releases/tag/v1.0.0`）。

---

## 缺陷 7：覆盖式更新（更新已存在仓库）fetch/reset 引用失效 + lease 过期

> 触发场景：用户要求「更新已上传项目」→ 重新发布同名仓库的新版本（v1.1.0 覆盖 v1.0.0）。
> 这是 Phase 8「覆盖式更新」能力的真实落地，暴露两个工具自身缺陷。

### 缺陷 7a：覆盖式 `reset` 找不到 `origin/main`

| 项 | 内容 |
|---|---|
| 严重度 | 高（覆盖式更新完全不可用） |
| 位置 | `cli.py` `run()` 覆盖式分支 |
| 现象 | 初版用 `git fetch origin +refs/heads/main:refs/remotes/origin/main` 试图建立远程跟踪分支，再 `git reset --hard origin/main`。但强制 refspec 写入 `refs/remotes/origin/main` 在部分 git 版本/配置下**偶发未被注册**，导致 `reset` 报 `fatal: ambiguous argument 'origin/main': unknown revision`，覆盖式中止。 |
| 影响 | 已存在仓库无法用工具更新，只能手工 `gh` 操作。 |

**修复**：改用 `git fetch origin main` + `git reset --hard FETCH_HEAD`。`FETCH_HEAD` 是 fetch 后**必定存在**的引用，不依赖远程跟踪分支注册状态，稳定可靠。

### 缺陷 7b：`--force-with-lease` 因 lease 基准过期被拒（`stale info`）

| 项 | 内容 |
|---|---|
| 严重度 | 高（fetch/reset 修复后仍推不上去） |
| 位置 | `github.py` `push(force=True)` |
| 现象 | `push --force-with-lease` 默认以 `refs/remotes/origin/main` 为 lease 参考。但临时目录是全新 `git init`，该远程跟踪分支要么不存在、要么未随 `fetch origin main` 可靠更新，导致 git 判 lease 信息过期（`! [rejected] main -> main (stale info)`）。 |
| 影响 | 覆盖式推送被拒，发布失败。 |

**修复**：`push(force=True)` 时先 `git fetch origin main` 刷新，再 `git rev-parse FETCH_HEAD` 取出远程 main 当前 commit，**显式**作为 lease 期望值：`--force-with-lease=origin/main:<sha>`。既不依赖 `origin/main` 注册状态，又保留「远程被不知情改动时拒绝」的安全语义。

### 附带加固：`create_repo` 返回 `exists` 标记

- 原 `create_repo` 对「已存在同名仓库」静默复用，不返回是否新建。`run()` 无法据此判断首发布 / 覆盖式，只能靠脆弱的 `fetch` 探测。
- 现 `create_repo`（gh + token 两条路径）均返回 `exists: bool` 字段；`run()` 以 `repo_info["exists"]` 为权威判定：
  - `exists=True` → 必走覆盖式（`force=True`）。
  - `exists=False` → 首发布（普通 push）。
  - `exists=True` 但 `fetch` 失败 → 显式报错（而非静默走首发布撞 non-fast-forward）。

### 验收标准
- 单测：
  - `test_update_existing_repo_uses_force_push`：`exists=True` 时 `push(force=True)` 被调用 + 源项目零污染。
  - `test_update_existing_repo_fetch_failure_raises`：`exists=True` 但 fetch 失败时抛 RuntimeError。
  - `test_push_force_uses_force_with_lease`：`force=True` 的 push 命令含 `--force-with-lease`（非裸 `--force`）。
  - `test_push_force_refreshes_origin_main_before_lease`：`force=True` 时先 fetch origin main + rev-parse FETCH_HEAD，再 push。
- 真实验证：`netdisk-organizer` v1.0.0 → v1.1.0 覆盖式更新成功（✅ `https://github.com/223jxy/netdisk-organizer/releases/tag/v1.1.0`），源项目零污染、远程根目录干净（无 `state/`/`audit/`/`cookie.json`）。

### 环境踩坑记录（重要）
- 本机 `HTTPS_PROXY=http://127.0.0.1:7897/`（系统代理）。**工具发布必须走代理**：直连 GitHub API/TLS 会被 `Recv failure: Connection was reset` 重置。
- `unset` 代理反而导致直连失败；正确做法是**保留系统代理环境变量**，让 `gh`/`git` 子进程继承。
- 验证命令：`gh auth status` + `git ls-remote <repo>` 走代理均正常。

## 执行顺序建议

| 次序 | 缺陷 | 状态 |
|---|---|---|
| 1 | 缺陷 1（行内注释） | ✅ 已修复（`GitignoreMatcher._strip_inline_comment`） |
| 2 | 缺陷 2（.gitignore 保留） | ✅ 已修复（`should_include` 顺序调整 + `analyzer.py` 同步） |
| 3 | 缺陷 3（create_release 幂等） | ✅ 已修复（`_gh_release_view` / `_gh_upload_asset` / token 路径查重） |
| 4 | 缺陷 4（`git add -A` 误推敏感目录） | ✅ 已修复（`_git_add_safe` 替代 `git add -A`，Phase 6） |
| 5 | 缺陷 5（git init 污染源项目） | ✅ 已修复（临时目录发布，Phase 7） |
| 6 | 缺陷 6（Release 误打仓库） | ✅ 已修复（`create_release` 传 `cwd=stage`，Phase 7） |
| 7 | 缺陷 7（覆盖式更新 fetch/reset + lease） | ✅ 已修复（FETCH_HEAD + 显式 lease，Phase 8） |

> 测试总数：31（初版）→ 46（Phase 5）→ 48（Phase 6）→ 50（Phase 7）→ **55**（Phase 8，新增 5 项：覆盖式 force push、fetch 失败报错、push lease 校验 ×2、create_repo exists 标记相关）。

> 测试总数：31（初版）→ 46（Phase 5）→ 48（Phase 6）→ **50**（Phase 7，新增 `TestRunDoesNotPolluteSource` 2 项）。

## 附加改造：仓名汉转英 + 零交互（用户 2026-08-23 需求）

用户要求：直接给路径即自动打包上传，不在对话里询问；未指定 `--repo` 时仓库名「汉转英」。

### 改动
- 新增 `github_automator/han2py.py` + vendored 数据 `github_automator/_han2py.json`（GB2312 6763 字拼音映射，由 pypinyin 预生成，**随包发布、运行时零第三方依赖**）。
- `han_to_repo_name(dirname)`：汉字逐音节转小写拼音并以 `-` 分隔，ASCII 段保留，其它归一为 `-`；无可用字符回退 `github-automator`。
  - 例：`自动点击脚本` → `zi-dong-dian-ji-jiao-ben`；`My 项目 v2` → `my-xiang-mu-v2`。
- `cli.py`：缺省仓名从「包名 `github-automator`」改为 `_default_repo_name(project)`（目录名汉转英）；删除「未指定 --repo」的提示打印，**全链路零交互**（给路径即跑到底）。
- `--repo` 仍可用：显式指定则优先。

### 限制（务必告知用户）
- 自动转写是**音节级拼音**，无法做语义翻译（用户手动指定的 `sevenday-automation` 是语义级，自动只能到 `zi-dong-dian-ji-jiao-ben`）。如需语义化英文名，仍用 `--repo` 指定。
- 数据文件 `_han2py.json`（~93KB）随包，覆盖 GB2312 简体常用字；极生僻字/繁体不在表内时会原样保留（可能因非 ASCII 被 slug 丢弃，触发回退名）。

### 验证
- `python -m unittest discover -s tests` → Ran 46 tests OK（原 31，新增 15 覆盖缺陷1/2/3 + 汉转英）。
- dry-run 端到端：目录「自动点击脚本」不传 `--repo` → 推断仓名 `zi-dong-dian-ji-jiao-ben`，无交互提示。

## 关联文档
- 审核报告：`github-automator-审核报告.md`
- 测试问题清单：`github-automator-测试问题分析与优化清单.md`
- 优化与更新记录：`github-automator-优化与更新记录.md`
- 规范手册：`github-automator-规范手册.md`
- Issue：https://github.com/223jxy/github-automator/issues/1
