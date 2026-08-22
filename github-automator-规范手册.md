# github-automator 规范手册

> 本手册是项目的**单一规范源**，统合四块：维修要求、发展方向、文件格式、代码规范。
> 配套文档：项目介绍 / 优化分析 / 优化与更新记录（见仓库 README 总索引）。

---

## 一、维修要求（Maintenance）

任何人（包括未来的你）接手改动时，按以下流程操作，可降低返工与事故概率。

### 1.1 改动前必读
1. 先看《github-automator-项目介绍.md》理解模块职责与数据流。
2. 再看《github-automator-优化与更新记录.md》的"状态对照表"，确认要动的项是否已被修过、有无已知坑。
3. 明确本次改动属于哪一类：
   - **纯说明**（注释/docstring/文档）→ 零风险，直接改，跑测试即可；
   - **逻辑改动** → 必须先在本地 `git` 提交一个基线，便于回滚；
   - **外部行为改动**（推送/Release/网络）→ 先在 `--dry-run` 下验证，再决定是否真推。

### 1.2 改动中约束
- **不引入第三方依赖**。本项目刻意保持"纯标准库"，任何 `pip install` 新增都是破坏性原则违反。
- **不动 token/密钥相关逻辑的安全性约定**：`push()` 只用临时凭据 URL、不写 `git remote set-url`、不在 `.git/config` 落盘 token（详见 `github.py` 的 `build_push_url`）。
- **保持 `--dry-run` 真正只读**：写动作（生成 README / 写 .gitignore / 打 zip）必须全部后置到非 dry-run 分支。

### 1.3 改动后验证（强制）
```bash
# 1. 逻辑层全量测试（纯 stdlib，无需 pytest）
python -m unittest discover -s tests -v
# 期望：Ran 31 tests ... OK

# 2. 自举 dry-run：把工具作用于它自己，确认零写入、计划正确
python -m github_automator.cli . --repo github-automator --dry-run
# 期望：仅打印计划，dist/ 与 .git/ 不被改动

# 3.（若要做真实发布）凭据通道预检，早失败早提示：
gh auth status          # 应显示已登录；否则先 `gh auth setup-git`
# 或设置环境变量 GITHUB_TOKEN=ghp_xxx
```
- 测试不绿 → 不允许提交/推送。
- dry-run 若产生了文件写入 → 说明"只读"约束被破坏，需回查 `cli.py run()`。
- 真实发布前必须确认凭据通道可用（`gh auth status` 正常或 `GITHUB_TOKEN` 已设）；工具也会在 `push()` 前自动 `_check_git_credentials` 预检，凭据缺失会早失败并提示 `gh auth setup-git`。

### 1.4 回滚与故障
- 本地：一律用 `git` 回退（`git log` 找基线 → `git checkout <sha> -- <file>` 或 `git revert`）。
- 远程仓库已创建但推送失败：仓库可手动在 GitHub 删除；本工具**不会**因推送失败而留下空仓库（已加 `has_commit` 闸门）。
- 误发 Release：GitHub 网页端可删除 Release（不删 git tag 时可一并删 tag）。

---

## 二、发展方向（Roadmap）

边界线写清楚，后来者才知道"能往哪走、不该往哪走"。

### 2.1 已定方向（已做 / 正在收口）
- 维持"零依赖、纯标准库、开箱即跑"的核心定位。
- 自举（eat its own dog food）：工具优先作用于自身仓库验证。
- 安全优先于便利：token 不落盘、dry-run 真正只读、打包排除密钥点文件。

### 2.2 明确不做（永久边界）
- **不做重型错误处理/重试框架**：保持轻量，失败即显式抛出 `RuntimeError` 带上下文，由调用方处理。
- **不做插件化/可扩展架构**：当前 6 模块足够，过早抽象是负担。
- **不引入配置文件（如 TOML 配置段）**：参数走 CLI，避免额外心智。

### 2.3 待议（可选打磨 · 状态与《优化分析》路线图严格一致）
> 状态图例：✅ 已定方向　⏸ 待议/可选。详细落地状态见《github-automator-优化分析》第三章路线图。

- ⏸ 问题 6：重复运行的幂等/已发布检测与更新语义——首次发布已够用，更新发布暂由人工删旧 Release 完成；若实际需求出现再评估（**非永久不做，仅当前未排期**）。
- ⏸ 问题 10：依赖解析展示增强（更丰富的生态识别）。
- ⏸ 多平台 Release（GitLab / Gitee）适配——仅当有明确需求时。

---

## 三、文件格式（File Format）

### 3.1 目录树与职责
```text
github自动化/
├── cli.py                      # 顶层命令入口（薄壳，转发到 github_automator 包）
├── github_automator/           # 核心包（纯标准库）
│   ├── __init__.py             # 包标识 + __version__
│   ├── analyzer.py             # 项目扫描/语言识别/目录树（只读不写）
│   ├── cli.py                  # 包内 CLI 编排（run()）
│   ├── docgen.py               # 基于 ProjectInfo 生成 README
│   ├── github.py               # GitHub 推送/Release（认证+安全）
│   └── packager.py             # .gitignore 生成 + 干净 zip 快照
├── tests/                      # 单元测试（unittest，不触网部分）
│   ├── test_analyzer.py
│   ├── test_cli.py             # dry-run 零写入断言
│   ├── test_docgen.py
│   ├── test_github.py          # build_push_url / has_commit / _git_check
│   └── test_packager.py        # GitignoreMatcher / 点文件 / 自定义忽略
├── dist/                       # Release 产物（zip），由工具生成，可删可重建
├── github-automator-项目介绍.md
├── github-automator-优化分析.md
├── github-automator-优化与更新记录.md
├── github-automator-规范手册.md
├── README.md                   # 总索引（四份文档入口）
├── LICENSE
├── pyproject.toml              # 仅元数据，无运行依赖
└── .gitignore                  # 自身仓库忽略规则（Python 片段 + 通用）
```

### 3.2 格式约定
| 项 | 约定 |
|----|------|
| 编码 | UTF-8（无 BOM） |
| 换行 | LF（`\n`），不混用 CRLF |
| 缩进 | 4 空格，不用 Tab |
| 命名 | 模块/包 `snake_case`；类 `PascalCase`；函数/变量 `snake_case`；常量 `UPPER_SNAKE` |
| 行宽 | 建议 ≤ 100 字符 |
| 文档 | Markdown，标题层级从 `#` 开始连续，不跳级 |
| 文档命名 | `github-automator-<用途>.md`，连字符分隔，前缀统一便于检索 |

---

## 四、代码规范（Code Style）

### 4.1 文件头模板（每个模块必须）
```python
"""<模块名> —— 一句话职责描述。

设计要点（可选，1–3 句）：关键约束、对外暴露的函数、是否只读。
维护约定：见 github-automator-规范手册.md。
依赖：仅 Python 标准库（不引入第三方包）。
"""
```

### 4.2 注释与 docstring
- **中文注释 + 英文变量命名**（沿用项目约定）；术语保留英文原词（如 `token`、`release`）。
- 公开函数必须有一行 docstring 说明"做什么 + 关键参数语义"；复杂分支用行内注释解释 *why* 而非 *what*。
- 安全相关代码（token/密钥/远程写）必须注释说明"为什么这样写才安全"。

### 4.3 命名与结构
- 单一职责：分析（analyzer）/ 打包（packager）/ 文档（docgen）/ 远程（github）/ 编排（cli）各司其职，不跨层调用写逻辑。
- 对外高层函数集中在 `github.py`（`create_repo` / `push` / `create_release`）与包级 `cli.run()`，降低调用方认知负担。
- 错误用 `RuntimeError` 带上下文抛出，不用静默 `check=False` 吞掉（见 `github._git_check`）。

### 4.4 测试约定
- 用 `unittest`（非 `pytest`，因环境未装）；不触网用例直接断言，触网/依赖 git 的用例用 `unittest.skipUnless` 防爆环境。
- 命名 `test_<被测对象>_<场景>`；新增逻辑必须配套测试后再提交。

---

## 五、容错契约（仓库名处理）

工具发布时围绕"仓库名"有两类边界场景，行为必须可预测、不产生副作用。

### 5.1 未指定 `--repo`（缺省）
- **零交互**：给路径即全链路跑到底，不询问、不打印「使用默认仓库名」提示。
- 缺省仓名 = **目录名「汉转英」**：`cli.py` 的 `_default_repo_name(project)` 调用 `han2py.han_to_repo_name()`，把目录名转成 ASCII slug（汉字逐音节转小写拼音并以 `-` 分隔，ASCII 段保留，其它归一为 `-`）。
  - 例：`自动点击脚本` → `zi-dong-dian-ji-jiao-ben`；`My 项目 v2` → `my-xiang-mu-v2`。
- 仅当目录名经转写后无任何可用字符时，回退到常量 `DEFAULT_REPO_NAME = "github-automator"`。
- 实现位置：`cli.py` 的 `_default_repo_name()` / `DEFAULT_REPO_NAME`；数据依赖 `github_automator/_han2py.json`（GB2312 6763 字拼音映射，vendored，运行时零第三方依赖）。
- 限制：转写为**音节级拼音**，无法语义翻译；语义化英文名仍需显式 `--repo` 指定。

### 5.2 仓库已存在 / 冲突
按"是否属于你"区分，绝不自动改名重试（避免产生 `xxx-1`/`xxx-2` 垃圾仓库）：

| 子场景 | 行为 |
|--------|------|
| 无 `--repo` | 自动用目录名汉转英 slug（如 `自动点击脚本`→`zi-dong-dian-ji-jiao-ben`），零交互 |
| `--repo` 不存在 | 正常新建（现有行为） |
| `--repo` 已存在且属于你（空/非空仓） | 复用，继续推送 / Release |
| `--repo` 已存在但不属于你 / 无权限 / 名字非法 | **显式抛 `RuntimeError`**，信息含仓库名 + 建议（`换名（--repo）或确认权限`），不静默、不重试、不自动改名 |
| 网络 / API 其他错误 | 显式抛 `RuntimeError` 带上下文（见 `github._api` / `create_repo`） |

- 核心原则：**冲突即失败报错**，把"换名决策"交还给用户，而非工具擅自产生副作用。
- 实现位置：`github.py` 的 `create_repo()`（gh 路径与非 gh REST 路径均已区分 "already exists" 复用 vs 其他失败报错）。

### 5.3 凭据通道（推送前必读）
`push()` 依赖 git 能拿到 GitHub 凭据，而 git 默认**不会**自动用 `gh` 凭据——必须显式 `gh auth setup-git` 把 gh 注册为 git credential helper。这是真实发布测试（2026-08-23）暴露的坑，工具已做两层加固：

1. **预检（早失败）**：`push()` 先调 `_check_git_credentials()`，凭据不可用（无 gh 且未设 `GITHUB_TOKEN`）直接抛 `RuntimeError`，提示先 `gh auth setup-git` 或设 `GITHUB_TOKEN`，避免在 push 阶段才暴露。
2. **降级（兜底）**：gh 路径推送若因"凭据不可用"失败（git 回退到交互式问密码、非交互无 tty），工具运行时为本仓库**局部**配置 git 用 gh 作 credential helper（等效 `gh auth setup-git`，不写全局、不暴露明文 token），重试一次；仍失败才抛出。非凭据错误（如分支冲突）不盲目降级，直接抛出。
3. **语义化报错**：`_git_check` 命中"could not read Username / /dev/tty / No such file or directory"等凭据类错误时，附加根因提示，避免误判。

> 推荐做法：发布前手动 `gh auth setup-git` 一次即可，工具的降级逻辑是兜底而非替代。

---

*本手册随项目演进更新；改动手册本身也按"维修要求 1.1"先读关联文档。*
