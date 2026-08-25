# GitHub 发布规范框架（github-automator）

> 把"项目发布到 GitHub"从临时判断，变成标准化流水线。  
> 任何项目进来：先分析、打标签、套对应框架，再发布。  
> 本文档是规则的唯一真相源；github-automator 工具负责执行，本框架负责"判定该用什么框架"。

---

## 0. 定位与目标

- **问题**：每次发布都临时决定"该带什么、要不要协议、去不去敏感信息"，容易漏（如已发布的 sevenday-automation v1.0.0 就缺失 LICENSE、且把 dist/ 误带进仓库）。
- **目标**：用一套可复用的框架，让不同项目按标签自动匹配"上传要素 + 脱敏规则 + 协议"，保证一致性与合规性。
- **与工具的关系**：github-automator 执行发布（新建 / 覆盖式更新）；本框架决定"发布前该满足哪些规范"。

---

## 1. 核心流水线

```
[项目目录]
   │
   ↓ ① 分析
   扫描结构 / .gitignore / 敏感信息 / 协议声明 / 是否已存在远程仓库
   │
   ↓ ② 打标签
   T(类型) + A(受众) + R(敏感级) + L(协议)
   │
   ↓ ③ 套用上传框架
   按标签组合选定：要素矩阵 + 脱敏规则 + 协议文件
   │
   ↓ ④ 规范检查（发布前 Gate，必须全过）
   □ LICENSE 存在且匹配 L
   □ 敏感信息已按 R 清零
   □ README / CHANGELOG 齐备且符合模板
   □ .gitignore 排除私密目录与构建产物
   │
   ↓ ⑤ 发布
   github-automator 执行（仓库不存在→新建；已存在→覆盖式更新）
```

**原则**：Gate 未过不许发布。任何一项缺失，先补再发，不"先发了再补"。

---

## 2. 四维标签体系

每个项目发布前打一组标签：`T + A + R + L`。

### T — 项目类型（Type）

| 值           | 适用         | 触发追加要素（见 §3）       |
| ----------- | ---------- | ------------------ |
| `cli`       | 命令行工具      | 依赖声明 + 命令文档        |
| `library`   | 可复用库 / SDK | 打包配置 + API 文档      |
| `app`       | 带界面的应用     | 安装 / 启动说明          |
| `script`    | 单文件或少量脚本   | 运行说明               |
| `game-auto` | 游戏自动化 / 模组 | 使用教程 + 配置说明 + 免责声明 |
| `doc`       | 文档 / 知识库   | 索引目录               |
| `web`       | 网站 / 前端    | 部署说明               |
| `dataset`   | 数据集        | 数据说明 + 许可          |

### A — 受众（Audience）

| 值            | 含义        | 协议要求                                |
| ------------ | --------- | ----------------------------------- |
| `personal`   | 仅自己用，不公开  | 可不设协议、可不加 README                    |
| `public`     | 公开共享      | **必须** LICENSE + README + CHANGELOG |
| `commercial` | 商业 / 客户交付 | 注意专有协议 + 加强脱敏                       |

### R — 敏感级（Risk）

| 值           | 含义                        | 脱敏动作（见 §5）       |
| ----------- | ------------------------- | ---------------- |
| `clean`     | 无凭据、无个人路径                 | 扫描确认即可           |
| `path-only` | 含个人路径（用户名 / 工作区绝对路径）      | 替换为占位 / 相对路径     |
| `cred-high` | 含密钥 / 账号 / cookie / state | **阻断**，必须手动处理后再发 |

### L — 协议（License）

取值：`mit` / `apache` / `gpl` / `cc0` / `proprietary`。  
映射规则见 §4。

---

## 3. 要素矩阵

### 通用必备（所有 `A=public` 项目）

- `LICENSE` —— 按 L 生成，置于仓库根
- `README.md` —— 按 §6 模板
- `.gitignore` —— 至少排除 `.workbuddy/`、`dist/`（构建产物）、`logs/`、`outputs/`、`__pycache__/`、虚拟环境、私密目录
- `CHANGELOG.md` —— 按 §7 模板
- **敏感信息已按 R 清零**（发布前 Gate 必过项）

### 按 T 追加要素

| T           | 追加要素                                                                |
| ----------- | ------------------------------------------------------------------- |
| `cli`       | `requirements.txt` 或 `pyproject.toml` + 命令用法文档（写入 README 或 `docs/`） |
| `library`   | 打包配置（`pyproject.toml` / `setup.py`）+ API 文档                         |
| `app`       | 安装包说明 / 启动入口说明                                                      |
| `script`    | 运行依赖与执行方式说明                                                         |
| `game-auto` | 使用教程 + 配置项说明 + **免责声明**（见 §6 模板）                                    |
| `doc`       | 目录索引（`README` 即索引或单独 `INDEX.md`）                                    |
| `web`       | 部署说明（平台 / 构建命令 / 环境变量）                                              |
| `dataset`   | 数据来源 / 字段说明 / 许可声明                                                  |

---

## 4. 协议映射决策表

| 意图（用户判断）                | 触发标签               | 协议 L                | 说明                   |
| ----------------------- | ------------------ | ------------------- | -------------------- |
| 想让人自由使用 / 修改 / 商用，仅保留署名 | `A=public` + 无闭源顾虑 | **MIT**             | 最宽松，个人工具首选           |
| 怕专利纠纷 / 企业法务友好          | 任意                 | **Apache-2.0**      | 含显式专利授权 + 防专利诉讼      |
| 保证衍生作品也开源               | 任意                 | **GPL-3.0**         | 强 copyleft，分发修改版须同开源 |
| 彻底放飞，放弃版权               | 任意                 | **CC0 / Unlicense** | 公有领域，无需署名            |
| 闭源 / 客户专有               | `A=commercial`     | **proprietary**     | 不公开源码或定制协议，不适用本框架默认流 |

**默认推荐**：`A=public` 且无特殊诉求 → MIT。  
**决策引导问题**：你希望别人怎么对待这份代码？（自由用 / 衍生须开源 / 无所谓 / 专有）

---

## 5. 脱敏规则（按 R）

### R = clean

- 全文扫描凭据关键词：`password` / `passwd` / `pwd` / `token` / `secret` / `api_key` / `apikey` / `cookie` / `session` / `authorization` / `.env` / 私钥文件。
- 无命中即过；有命中但属变量名（如 `token` 解析文本）须人工甄别，非真凭据可保留。

### R = path-only

- 替换规则（仅改字符串，不改逻辑）：
  - `C:\Users\<名>` / `/home/<名>` / `/Users/<名>` → `<USER_HOME>`
  - 工作区绝对路径（如 `D:\workdubby\xxx`）→ 相对路径或 `<WORKSPACE>`
- 保留历史语义：汇总类文档写"当前累计"，不歪曲阶段性真实数字。

### R = cred-high（阻断）

- **禁止上传**：`.env`、`*credential*`、`cookie*`、`state/`、`*secret*`、私钥文件（`*.pem` / `*.key`）、个人邮箱 / 手机号 / IP。
- 必须从源移除或外置（如环境变量 / 配置文件占位）后，再走发布。
- 不可"先发后删"——一旦进 Git 历史即难无痕抹除。

---

## 6. README 模板

```markdown
# 项目名

> 一句话定位（解决什么问题）

## 简介
## 功能特性
## 安装
## 使用
## 配置（如适用，注明配置项与默认值）
## 免责声明（game-auto / web 等涉及第三方条款时必填）
   本项目仅用于学习/个人自动化，使用者须遵守相关平台服务条款，作者不对使用后果负责。
## 协议
   基于 <LICENSE 名称> 开源，详见 LICENSE 文件。
## 更新日志
   见 CHANGELOG.md
```

---

## 7. CHANGELOG 模板（Keep a Changelog 风格）

```markdown
# 更新日志

## [vX.Y.Z] - YYYY-MM-DD
### 新增
### 变更
### 修复
### 破坏性变更
```

规范：

- 每个发布版本一节，含版本号 + 日期。
- 变更按"新增 / 变更 / 修复 / 破坏性"分类。
- 版本号语义：主版本=破坏性，次版本=新功能，修订=修复。

---

## 8. 发布前检查清单（Gate）

发布前逐项核对，全过才执行：

- [ ] **标签已打**：`T / A / R / L` 四值明确
- [ ] **LICENSE**：存在且匹配 L（public 必备）
- [ ] **README**：符合 §6 模板，含协议与免责声明（如适用）
- [ ] **CHANGELOG**：含本次版本节
- [ ] **脱敏**：按 R 已清零，无凭据 / 个人路径残留
- [ ] **.gitignore**：排除 `.workbuddy/` / `dist/` / 私密目录 / 构建产物
- [ ] **体积**：大目录（logs / outputs / work）未入包
- [ ] **远程**：仓库已存在→覆盖式；不存在→新建；版本号未冲突

---

## 9. 标签速查与示例

| 项目                  | T           | A            | R           | L             | 说明                             |
| ------------------- | ----------- | ------------ | ----------- | ------------- | ------------------------------ |
| github-automator    | `cli`       | `public`     | `clean`     | `mit`         | 自托管发布工具，已合规                    |
| sevenday-automation | `game-auto` | `public`     | `path-only` | `mit`         | 七日世界自动制作脚本，需脱敏个人路径 + 补 LICENSE |
| 客户交付脚本              | `script`    | `commercial` | `cred-high` | `proprietary` | 专有，加强脱敏，不适用默认公开流               |

**sevenday-automation 套用示例**（待执行）：

1. 标签：`game-auto + public + path-only + mit`
2. 要素：`LICENSE(MIT)` + `README` + `CHANGELOG` + 使用教程 + 免责声明 + 依赖声明
3. 脱敏：`path-only` → 替换 `C:\Users\JXY`、`D:\workdubby\自动点击脚本` 为占位
4. Gate：补 LICENSE、清 dist/、确认无路径残留 → 发 v1.1.0

---

## 10. 渐进式工具化路线

本框架先以 SOP 文档落地（当前阶段），后续逐步把规则内置进 github-automator，实现半自动甚至自动发布。

- **阶段 1（当前）**：SOP 文档。人工 / AI 按本文档分析、打标签、执行 Gate、再发布。
- **阶段 2**：github-automator 增加 `--analyze <dir>` 子命令，扫描后输出标签建议（T/A/R/L 初判 + 缺失要素提示）。
- **阶段 3**：内置"标签 → 框架"映射配置（本框架的矩阵与规则转为机器可读配置），发布前自动跑 Gate 校验，缺项阻断并报告。
- **规则源唯一**：所有判定逻辑以本框架文档为唯一真相源，工具读取它执行，避免文档与代码双份真相漂移。

---

## 11. 反模式（禁止）

- ❌ 无 LICENSE 就公开发布（默认全保留，他人无权使用）。
- ❌ 把 `logs/` / `outputs/` / `dist/` / `.workbuddy/` 带进仓库。
- ❌ 含个人路径 / 凭据的源码直接发布。
- ❌ "先发了再补协议 / 再去敏"——Git 历史难无痕抹除。
- ❌ 每个项目临时定框架，不复用本矩阵。

---

## 12. 跨会话调用与上下文交接

### 12.1 前置条件（任何环境通用）

- Python ≥ 3.8（纯标准库，**零第三方依赖**，`pyproject.toml` 中 `dependencies = []`）
- `git` 已安装并在 PATH
- `gh`（GitHub CLI）已 `gh auth login`，且对目标账号有推送权限
- 网络可达 GitHub（企业网 / 大陆环境需配置代理，见 §12.2）

### 12.2 调用方式（在"其他地方"发布任意项目）

工具包位于 `D:\workdubby\github自动化\github_automator\`，**自包含、零依赖、可携带**。目标项目可以是任意位置的目录。

**方式 A — PYTHONPATH 直调（推荐：零安装、不污染环境）**

任意目录执行，把包路径注入 `PYTHONPATH` 即可：

```bash
PYTHONPATH=D:/workdubby/github自动化 python -m github_automator.cli "D:/其他项目/目标" --repo 目标仓库名 --version v1.0.0
```

- 第一个位置参数 = 要发布的项目路径（任意位置，建议绝对路径）
- `--repo` 显式指定仓库名（省略则按目录名「汉转英」生成）
- 加 `--dry-run` 先预览上传集合，确认无误再真发

**方式 B — 安装为全局命令**

```bash
pip install -e D:/workdubby/github自动化
# 之后任意位置：
github-automator "D:/其他项目/目标" --repo 目标仓库名 --version v1.0.0
```

**方式 C — 从工具目录调用（本会话一直用）**

```bash
cd D:/workdubby/github自动化
python -m github_automator.cli "D:/其他项目/目标" --repo 目标仓库名 --version v1.0.0
```

> 三种方式等价，产物一致。推荐 **方式 A**：不动全局环境、随时可换工具版本。

**代理（企业网 / 大陆环境）**：`gh` 与 `git` 走系统代理。直连失败先设：

```bash
export HTTPS_PROXY=http://127.0.0.1:7890 HTTP_PROXY=http://127.0.0.1:7890
```

（端口按你本地代理改；Windows PowerShell 用 `$env:HTTPS_PROXY=...`）

### 12.3 把上下文交给新会话（"告诉他聊天记录"）

任何新会话 / 新环境想高效接手，只需两步：

1. 让新会话先读**本框架文档**（规则唯一真相源）。
2. 粘贴下方 **会话交接 Briefing** 让它快速进入状态——无需重读全部历史。

> 把下面代码块整段复制，作为新会话的开场白即可。



```text
【github-automator 发布规范 · 会话交接 Briefing】
我是用户阳。我们已制定一套 GitHub 发布规范框架，文档：
  D:\workdubby\github自动化\github-automator-发布规范框架.md
请先读它并按其执行（这是规则唯一真相源）。

工具：github-automator（zero-dep 纯标准库 CLI，自托管发布）。调用：
  PYTHONPATH=D:/workdubby/github自动化 python -m github_automator.cli <项目路径> --repo <名> --version <v> [--dry-run]
前置：Python≥3.8 + git + gh(已登录) + 网络(企业网设代理)。

规范核心（详见框架文档）：
- 流水线：分析 → 打标签(T/A/R/L) → 套框架 → Gate 检查 → 发布；Gate 不过不许发。
- 四维标签：T 类型(cli/library/game-auto/script/web/doc/dataset)、A 受众(personal/public/commercial)、R 敏感级(clean/path-only/cred-high)、L 协议(mit/apache/gpl/cc0/proprietary)。
- public 项目必备：LICENSE + README + .gitignore + CHANGELOG + 脱敏清零。
- 协议默认 MIT（public 无闭源顾虑时）；怕专利→Apache；保证衍生开源→GPL；放飞→CC0。
- 脱敏：path-only 替换个人路径为占位(<USER_HOME>/<WORKSPACE>)；cred-high 阻断禁传密钥/.env/cookie/state。
- 反模式：无 LICENSE 不发；dist/.workbuddy/logs/outputs 不带进库；禁止"先发后补"。

当前状态（截至 2026-08-25）：
- github-automator 自身已发 v1.4.0（覆盖式）；本地 main 已对齐远程 b723c98。
- sevenday-automation（标签 game-auto+public+path-only+mit）待发 v1.1.0：补 MIT LICENSE + 脱敏个人路径(C:\Users\JXY、D:\workdubby\自动点击脚本) + 仓库排除 dist/ + 发 v1.1.0（并删旧 v1.0.0 Release/Tag 移除含旧路径的公开入口）。
- 工具已知坑：覆盖式发布会重 commit（本地与远程 hash 不同但内容等价，已 git diff 验证）；dist/ 须加 .gitignore 排除；小仓库 git 元数据 origin/main 引用有显示 bug，但 ls-remote+git diff 确权实际同步正常。

请按框架文档执行；任何改动前先给影响清单让我确认。
```

---

## 13. 反馈闭环：报错回传与工具迭代

### 13.1 机制（工具已内置）

`cli.py` 入口已包全局异常捕获（`try/except` + `_write_diagnostic`）。任何**未捕获异常**会：
1. 写结构化诊断日志到 `~/.cache/github-automator/error-<UTC时间戳>.log`
2. 终端提示日志路径
3. `sys.exit(1)`

已知校验错误（如项目路径不存在）走友好提示 `return 1`，**不写**诊断日志（非异常）。

### 13.2 诊断日志内容

- 字段：时间(UTC) / 工具版本 / Python / 平台 / cwd / argv / 错误类型 / 错误信息 / 完整 traceback
- 脱敏：`Path.home()` 整段 → `<USER_HOME>`，散落用户名 → `<USER>`（双保险，覆盖正反斜杠变体）。**不含个人身份的项目路径（如 `D:` 工作区）保留作复现上下文。**

### 13.3 如何把报错"发给我"（回传约定）

1. 工具报错后，按终端提示找到日志文件（如 `~/.cache/github-automator/error-20260825T145453Z.log`）。
2. 带回方式（任选）：
   - 把日志文件内容直接贴给小梦（当前或新会话）；
   - 或新会话启动时读取该文件并汇报。
3. 小梦据此定位根因 → 修复工具 → 发新版本（走本框架发布流程，含 Gate 检查）。

### 13.4 注意事项

- 日志对 home / 用户名脱敏，但**可能含项目绝对路径**（不含个人身份，属复现所需）。带回前请扫一眼，确认无 `token` / `cookie` / 密钥等真凭据；如有，手动删后再发。
- 诊断日志目录 `~/.cache/github-automator/` 可定期清理。
- 该回传为**手动带回**（阶段选择）：零依赖、零外部服务，先把报错"可携带化"作为闭环地基。

### 13.5 进阶（可选，未启用）

如需全自动，可在 `_write_diagnostic` 后追加 `gh issue create`，把报错直接送进 github-automator 仓库 issue 列表作为反馈中心（需 `gh` 授权）。当前手动带回已足够，启用前需评估 issue 刷屏与授权边界。
