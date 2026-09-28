# Backbone Conductor

**让多个 Coding Agent 共享意图、约束与决策，用 Git 记录每次协作变更。**

这是独立个人兴趣项目。v0.12 提供 Git 协调内核、CLI、HTTP API、stdio MCP、确定性冲突检查、人工仲裁和可选 DeepSeek Harness 语义审查。HTTP 可选择启用可不停机轮换的令牌认证；已认证请求的元数据提交记录 principal 与角色。多个克隆可显式获取远端、安全快进，并对经复核的元数据变更进行结构化合并，竞争对象可由管理员逐一裁决。新仓库可选择独立的 `backbone` 元数据分支，已有内联快照也可显式迁移并保留审计历史；Compose 的内联和独立分支配置已在本机及 Linux CI 验证。多人共享部署仍需独立验证。

## 快速开始

需要 Python 3.12+、Git 和 [uv](https://docs.astral.sh/uv/)。

```sh
git clone https://github.com/BruceXcluding/backbone-conductor.git
cd backbone-conductor
uv sync --locked --group dev
uv run python examples/demo.py
```

演示在临时仓库完成意图创建、任务分派、代码提交、检查、Git 合并和完成记录，不修改当前项目，不需要模型密钥。输出应有 `"intent": "completed"` 和 `"task": "merged"`。

接入自己的 Git 仓库：

```sh
uv run backbone --repo /absolute/path/to/your-repo init
uv run backbone --repo /absolute/path/to/your-repo serve
```

打开 [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) 使用交互式 API。服务默认监听本机，供可信本地管理员使用。

要给 HTTP API 增加管理员和成员令牌，先在仓库外创建私有凭据文件。下面的命令仅在创建时输出一次明文令牌，文件仅保存哈希；请把输出保存在合适的密钥管理位置，不要提交到 Git：

```sh
backbone --repo /path/to/project auth create \
  --file /private/path/backbone-http-tokens.json --admin owner \
  --member alice --member bob
backbone --repo /path/to/project serve \
  --auth-file /private/path/backbone-http-tokens.json
```

请求使用 `Authorization: Bearer TOKEN`。管理员可执行全部 HTTP 操作；成员令牌绑定自己的 author 和 member_id，仅能创建草稿意图与提议决策、查看和提交自己的任务，以及检查自己的更新。远程访问须在可信反向代理处终止 TLS；没有 `--auth-file` 时命令拒绝绑定非本机地址。更换令牌需重建凭据文件并重启服务。详见 [部署与恢复](docs/OPERATIONS.md)。

## 完整工作流

以下命令在已安装本项目的环境中执行，`--repo` 指向被协调的代码仓库。先配置该仓库的 Git 用户名和邮箱。
本例目标分支为 main，先切换到 main 再初始化和分派；其他目标分支需同步修改示例 artifact 的 base_ref。

```sh
git -C /path/to/project switch main
backbone --repo /path/to/project init
backbone --repo /path/to/project intent create --file examples/intent.json
backbone --repo /path/to/project intent transition intent-greeting accepted
backbone --repo /path/to/project task dispatch intent-greeting --member alice
backbone --repo /path/to/project task list --member alice
backbone --repo /path/to/project task start TASK_ID --member alice
```

用返回的任务 ID 替换 `TASK_ID`。成员在 `feature/greeting` 分支实现并提交 `greeting.py`，协调端在目标分支 `main` 检查：

```sh
backbone --repo /path/to/project task submit --member alice --file examples/artifact.json
backbone --repo /path/to/project conflict list
```

检查基于实际 Git diff。禁止路径、空产物、`.backbone/` 改写、空白错误和阻塞冲突会阻止提交；意图声明了非空 affected_paths 时，也会检查超出声明范围的修改。`accepted: true` 仅表示确定性检查通过，语义仍需人审查。

如有阻塞冲突，查看证据、记录裁决后重新提交：

```sh
backbone --repo /path/to/project conflict resolve CONFLICT_ID \
  --author owner --action coordinate --rationale '保留兼容接口，后续单独移除'
```

人工审查后执行真正的 Git 合并，再记录完成：

```sh
git -C /path/to/project switch main
git -C /path/to/project merge --no-edit feature/greeting
backbone --repo /path/to/project task merge TASK_ID --author owner
backbone --repo /path/to/project log
backbone --repo /path/to/project sync
```

`task merge` 验证提交已进入目标分支并记录人工审查，不执行代码合并。`sync` 显式推送当前分支，包括代码和元数据提交，不拉取或强推。另一个克隆在同名分支可运行 `backbone --repo /path/to/project refresh`：远端领先且本地工作树干净时快进；本地领先或双方分叉时只报告状态和差异，不自动合并。`refresh` 返回 `diverged` 时须人工检查和合并 Git 历史。已成功提交的任务在分支更新后，需 `task start` 再重新提交；检查失败的任务仍为 in_progress，可直接修复后重交。

若分叉只涉及 `.backbone/`，且两侧修改的是不同领域对象，管理员审查 `refresh` 返回的 `local_head`、`remote_head` 和差异后，可记录理由并合并：

```sh
backbone --repo /path/to/project reconcile \
  --local-head OBSERVED_LOCAL_HEAD --remote-head OBSERVED_REMOTE_HEAD \
  --author owner --rationale '已审查两侧独立意图及新产生的冲突'
backbone --repo /path/to/project sync
```

`reconcile` 会重新获取远端，任何一侧 SHA 变化即拒绝；工作树必须干净。它生成保留两个 Git 父提交的合并提交并重算冲突，**不执行代码合并或语义审批**。若代码路径有变化，返回 `requires_review`，不改变仓库。同一对象两侧均被修改时也先返回 `requires_review` 和对象 ID；管理员审查两侧值后，可以用 `--resolutions-file /path/to/resolutions.json` 再次运行。JSON 必须恰好覆盖每个竞争对象，例如 `{"intents":{"intent-shared":{"source":"remote"}}}` 选择远端整对象，`source` 也可为 `local`；要合并双方字段则提供 `{"value":{...完整对象...}}`。代码会验证对象和跨对象生命周期，审查理由及所选来源写入 Git 合并提交。新阻塞冲突仍需按正常流程人工裁决。

## 独立 Backbone 分支

已提交首个代码提交、尚未执行内联 `backbone init` 的仓库可以选择独立元数据分支：

```sh
backbone --repo /path/to/project ledger create
backbone --repo /path/to/project --ledger-branch backbone status
backbone --repo /path/to/project --ledger-branch backbone intent create \
  --file examples/intent.json
backbone --repo /path/to/project --ledger-branch backbone sync
```

`ledger create` 在 Git 管理目录中建立隐藏 worktree，创建只含 `.backbone/` 的 orphan `backbone` 分支，不移动代码工作树。已有内联快照的仓库须先完成或取消活跃任务，并确保代码工作树及索引干净，再显式运行 `backbone --repo /path/to/project ledger migrate`。迁移创建以原代码 HEAD 为父提交的元数据专用分支，在代码分支另作提交移除 `.backbone/`；历史提交仍可从新分支追溯。迁移会改动代码分支，因此应在协作者暂停写入时进行。使用独立模式时，每次 CLI 命令都需在子命令前传入 `--ledger-branch backbone`；HTTP `serve` 和 MCP `mcp` 同理。任务的代码分支、制品 diff 与实际 Git 合并仍在 `--repo` 指向的代码工作树执行；`sync` 只推送 `backbone` 分支，代码分支需要另行使用 Git 推送。迁移后需分别推送代码分支与 `backbone` 分支。其他克隆可在拉取代码后执行 `backbone --repo /path/to/clone ledger attach`，再用相同标志访问元数据。详细限制见 [部署与恢复](docs/OPERATIONS.md)。
若分派后有新的已接受决策或旧决策撤回，提交检查会要求先执行 `task rebase`，再重新提交产物。若决策是在提交通过之后才改变，而且代码已经合入目标分支，管理员需在 `task merge` 上提供 `--rationale`，说明如何审查了变更的决策。

需求变化时，可在分派前修订意图。先从 `backbone status` 读取 `version`，再提交 JSON 字段补丁；已接受的意图会回到 draft，须重新接受：

```sh
backbone --repo /path/to/project intent revise INTENT_ID \
  --file /path/to/patch.json --author owner --version OBSERVED_VERSION
```

已分派的任务可刷新到最新 Backbone 版本和决策集合。此操作仅刷新任务上下文，不执行 `git rebase`；旧检查结果会失效，需重新提交。取消任务会留下原因，并把意图重新开放给下一次分派：

```sh
backbone --repo /path/to/project task rebase TASK_ID \
  --member alice --version OBSERVED_VERSION
backbone --repo /path/to/project task cancel TASK_ID \
  --author owner --reason '需求调整'
```

`intent revise` 和 `task rebase` 都要求先读取当前 `version`，防止使用过期上下文覆盖新决策；命令记录后版本会变化，下次需重新读取。已合入目标分支的产物不能通过取消或刷新任务来撤销，需先处理代码回退。

## Agent 接入

```sh
backbone --repo /absolute/path/to/project mcp --member alice
```

由 Agent 客户端启动这个 stdio MCP 进程。成员绑定固定身份并隐藏管理员工具。完整配置见 [MCP_API.md](MCP_API.md)。

## 可选 DSH 审查

```sh
uv sync --locked --group dev --extra dsh
uv run backbone --repo /path/to/project review TASK_ID \
  --dsh-home /absolute/path/to/isolated-dsh-home --model YOUR_MODEL
```

需自行配置模型凭据。审查返回 `aligned / concerns / uncertain` 建议并记入审计，不替代人工裁决或合并。真实模型调用尚未验证。见 [DSH_PLUGIN_PLAN.md](DSH_PLUGIN_PLAN.md)。

## 开发与验证

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest --cov=backbone_conductor --cov-fail-under=85
uv run pytest tests/test_live_http.py -q
uv run python scripts/evaluate.py
uv run python scripts/benchmark.py
uv build
```

CI 对 Python 3.12、3.13 运行检查、测试、合成评测和示例；其中真实 HTTP 双客户端进程测试必须运行，不能因缺少 loopback socket 权限而跳过。本地受限沙箱若禁止监听 socket，该测试会明确跳过，可在允许本地网络的环境单独运行。合成用例通过率不代表真实项目冲突召回率。

若 macOS 的 editable `.pth` 被标记 hidden 导致模块不存在，可用 `uv sync --locked --group dev --no-editable`，随后执行 `uv run --no-sync ...`；源码修改后需重装。开发测试也可显式设置 `PYTHONPATH=src`。

## 文档与边界

- [项目章程](PROJECT_INITIATION.md)、[初始意图](INTENT.md)
- [当前实现和后续工作](docs/IMPLEMENTATION.md)
- [MCP 与 Codex 接入](MCP_API.md)、[冲突规则](CONFLICT_RULES.md)
- [DSH 适配](DSH_PLUGIN_PLAN.md)、[部署与恢复](docs/OPERATIONS.md)
- [测试报告](docs/VALIDATION.md)
- 原草案：[PLAN.md](PLAN.md)、[ARCHITECTURE.md](ARCHITECTURE.md)、[PROTOCOL_SPEC.md](PROTOCOL_SPEC.md)

当前版本不含远程多租户鉴权、自动代码合并、团队生产部署或 PyPI 发布。状态存于 `.backbone/state.json`，Markdown 概览和分对象文件由它生成；写入产生独立审计提交，不夹带其他暂存文件。
