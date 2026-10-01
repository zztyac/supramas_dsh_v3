# SupraMAS for DeepSeek Harness

材料学科研模式：**文献支撑的策略树挖掘** 与 **证据可追溯的超导材料 idea 设计**（默认领域：REBCO 涂层导体 / 磁通钉扎）。

装完后 DSH 里会出现一个 **`材料学科研`** 模式，包含专用 persona、科研工具集、14 个技能、7 个具名委派角色，以及可独立运行的确定性编排层。

---

## 安装

```bash
dsh plugin --profile desktop add git+ssh://git@github.com/zztyac/supramas_dsh_v3.git
```

`desktop` 是 Web GUI 用的 profile。装完必要时重启一次应用。

然后：**设置 → 通用 → agent preset → 选「材料学科研」**。

> `dsh plugin add` 会自动把包登记进该 profile 的 `dsh.profile.bundles`（非 `private` 包的行为）。
> 如果没登记上，用仓库里的 `install.py` 补齐：
>
> ```bash
> python3 ~/.dsh/profiles/desktop/node_modules/supramas-dsh/install.py --profile desktop
> ```

**前置条件**

- DeepSeek Harness（0.2.0-rc 系列）
- `dsh` 在 PATH 上。桌面版不会自动装，免 sudo 的修法：
  ```bash
  ln -sf "/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh" \
         /opt/homebrew/bin/dsh
  ```
- **无需 `pip install`**：所有 Python helper 只用标准库

---

## 装完能用什么

| 能力 | 说明 |
|---|---|
| `材料学科研` 模式 | persona + 科研工具集（bash / 文件 / 技能 / web / todo / present / jobs） |
| 14 个技能 | `research-lit`、`arxiv`、`semantic-scholar`、`openalex`、`deepxiv`、`exa-search`、`strategy-tree-builder`、`strategy-tree-validation`、`stage2-idea-*`、`superconducting-materials-idea-expert` |
| 项目契约技能 | `supramas-project-contract`：执行模型、角色、路由表、Stage 1/2 工作流、数据语义、证据纪律 |
| 7 个委派角色 | `strategy_builder`、`strategy_reviewer`、`idea_expert`、`idea_review`、`idea_proximity`、`idea_ranking`、`idea_evolution`；**两个 reviewer 被工具级强制只读** |
| 8 个 Python helper | arXiv / Semantic Scholar / OpenAlex / DeepXiv / Exa 检索、论文核验、证据检查、策略树组装 |
| 确定性编排层 | Stage 0/1/2 脚本 + 组装门禁 + schema 校验 |
| 2 个 JSON Schema | 策略树、idea 设计 |

---

## 用法

### 方式一：对话驱动（推荐）

切到 `材料学科研` 模式，开新会话，直接说：

```
帮我做一次完整的 Stage 1 策略树挖掘，方向是 REBCO 涂层导体人工钉扎中心提升高场 Jc，
job_id 用 rebco_001
```

agent 会读契约、建 `runs/rebco_001/input_task.yaml`、派发 builder/reviewer、收敛后导出三件套。

### 方式二：跑确定性编排层

编排层随包发布，可以在**你自己的项目目录**里直接调用（不会往包里写东西）：

```bash
BUNDLE=~/.dsh/profiles/desktop/node_modules/supramas-dsh
cd /path/to/your/research-project

python3 "$BUNDLE/assets/scripts/dsh_runner.py" --self-check        # 先自检

python3 "$BUNDLE/assets/scripts/stage0_task_setup.py" \
  --research-goal "REBCO 涂层导体人工钉扎中心提升高场 Jc" \
  --job-id myjob --use-defaults \
  --provider deepseek-account --model deepseek-flash \
  --permission-mode danger-full-access

python3 "$BUNDLE/assets/scripts/stage1_strategy_tree_builder.py" \
  --input-task runs/myjob/input_task.yaml \
  --provider deepseek-account --model deepseek-flash \
  --permission-mode danger-full-access
```

产物落在 `./runs/<job_id>/`：

```
runs/<job_id>/
├── input_task.yaml              任务定义
├── tree_state.json              权威续跑检查点
├── papers/                      论文元数据 + 证据 chunk
├── outputs/
│   ├── strategy_tree.json       策略树
│   ├── node_review_log.jsonl    评审日志
│   └── review_report.md         可读报告
└── logs/                        事件流 + 会话归档
```

### 三种凭证写法

| 场景 | 参数 |
|---|---|
| 本机登录态账号路由 | `--provider deepseek-account --model deepseek-flash` |
| 有 API key | `export DEEPSEEK_API_KEY=...`（headless 默认路由 `deepseek-official`） |
| 无人值守 | 必须加 `--permission-mode danger-full-access`，否则 `approval: ask` 会 fail-closed |

---

## 设计要点

**资产根与工作区是分开的。** 编排层从 `__file__` 推导自己的资产位置（`tools/`、`schemas/`、`agents/`、patch），`runs/` 写到当前目录。所以装在 profile 的 `node_modules/` 里也能对你的项目工作。

**技能自带。** `lib/index.js` 把 `assets/skills/` 注册进 harness，并给每个技能追加一段运行时说明，给出 helper 的**绝对路径**——技能正文里写的是源码仓的 `$REPO_ROOT/tools/...`，在别人机器上不存在。

**确定性收口。** 策略树不是 agent 自证的：`tools/assemble_strategy_tree.py` 会独立校验 frontier 闭合性、边一致性、`evidence.chunk_id` 可解析性，然后才产出三件套。

---

## 开发

源码仓（含测试、文档、发布脚本）不在这里。这个仓库是**生成物**：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/build_supramas_patch.py   # 从角色契约生成 patch
PYTHONDONTWRITEBYTECODE=1 python3 scripts/build_bundle.py            # 暂存 assets
sh scripts/publish_bundle.sh                                        # 发布到本仓库
```

请勿手工编辑 `cordis.patch.yml` 或 `presets/*.patch.yml`——它们从 `agents/*.md` 生成。
