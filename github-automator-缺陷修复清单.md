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
