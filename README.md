# Backbone Conductor

**让多个 Coding Agent 共享意图、约束与决策，用 Git 记录每次协作变更。**

许可证：[MIT](LICENSE)。

这是独立个人兴趣项目。v0.46 提供 Git 协调内核、CLI、HTTP API、stdio MCP、确定性冲突检查、人工仲裁和可选 DeepSeek Harness 语义审查。HTTP 可选择启用可不停机轮换的令牌认证及直接 HTTPS；管理员、成员和审查者拥有不同接口权限，已认证请求的元数据提交记录 principal 与角色。多个克隆可显式获取远端、安全快进，并对经复核的元数据变更进行结构化合并，竞争对象可由管理员逐一裁决。新仓库可选择独立的 `backbone` 元数据分支，已有内联快照也可显式迁移并保留审计历史；Compose 的内联/独立分支与 HTTP/HTTPS 组合及可选成员 MCP 已在容器中验证，HTTPS 成员客户端还经过独立容器网络与挂载隔离测试。取消已分派任务后可创建有审计理由的替代意图草稿；审查者可记录意图草稿的接受或拒绝及理由，并在审批任务前读取固定提交的只读代码审查包。合并审批必须带上审查时观察到的账本版本与目标代码 SHA，并会拒绝保留提交祖先但丢弃全部产物改动的目标树；同一路径最终内容与产物不同则需记录复核理由。可选 Git 提交签名与审计签名验证；时间线支持按作者、HTTP principal、事件类型和时间筛选。前瞻评测工具可从干净的仓库采集未分派意图配对、冻结事前预测并合并双人盲审标签，但真实意图冲突检测率仍无数据可报告。DSH 审查结果可选择写入仓库外的私有运行日志，受限协调代理可通过本地 MCP 提出草稿并分派已接受意图；审查者可在无协调仓库的机器上用私有令牌通过远程 CLI 审阅意图和固定代码补丁，并在实际 Git 合并后记录审批；多人共享部署仍需独立验证。

## 快速开始

需要 Python 3.12+、Git 和 [uv](https://docs.astral.sh/uv/)。

```sh
git clone https://github.com/BruceXcluding/backbone-conductor.git
cd backbone-conductor
uv sync --locked --group dev
uv run python examples/demo.py
```

演示在临时仓库完成意图创建、任务分派、代码提交、检查、Git 合并和完成记录，不修改当前项目，不需要模型密钥。输出应有 `"intent": "completed"` 和 `"task": "merged"`。

冲突规则除 24 个合成场景外，可运行 `uv run python scripts/evaluate_git_merges.py` 查看四例公开历史 Git 合并的路径争用回放；[试验说明](evals/GIT_MERGE_PILOT.md)明确列出来源、标签与适用范围。这些文本冲突标签不能代替真实意图冲突标注。

要在真实工作中测量意图冲突检测率，请按[前瞻评测流程](evals/PROSPECTIVE_STUDY.md)先冻结事前意图与预测，再收集独立人工标签。当前没有已标注的真实前瞻样本，不能据合成或历史回放数字声称达到了原草案的 80% 目标。

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
  --member alice --member bob --reviewer carol
backbone --repo /path/to/project serve \
  --auth-file /private/path/backbone-http-tokens.json
```

请求使用 `Authorization: Bearer TOKEN`。管理员可执行全部 HTTP 操作；成员令牌绑定自己的 author 和 member_id，仅能创建草稿意图与提议决策、查看和提交自己的任务，以及检查自己的更新。审查者可读取审查上下文、接受或拒绝他人的草稿意图、记录实际 Git 合并后的审批并裁决冲突，但不能分派任务或同步仓库；自我审查与审批自己的任务会被拒绝。远程访问需使用可信反向代理终止 TLS，或为 `serve` 同时提供 `--tls-certfile` 和 `--tls-keyfile`；没有 `--auth-file` 时命令拒绝绑定非本机地址。`auth add`、`auth rotate-one` 和 `auth revoke` 可不停机管理单个 principal；`auth rotate` 用于全员重发令牌。详见 [部署与恢复](docs/OPERATIONS.md)。

审计提交可使用仓库的 Git `commit.gpgsign=true` 设置签名；`backbone --repo /path/to/project audit verify --require-signatures` 检查最近的元数据提交并对未签名或验证失败返回非零状态。历史上的未签名提交不会被追溯签名；签名证明 Git 密钥，不证明 HTTP principal 的真实身份。配置步骤与范围限制见 [部署与恢复](docs/OPERATIONS.md#审计与恢复)。

可用 `backbone --repo /path/to/project log --type intent --http-principal alice --limit 20` 查看匹配的审计时间线；HTTP `/timeline` 接受同名查询参数。时间筛选使用带时区的 ISO 8601 `since` / `until`。事件类型由 Git 提交主题归类，便于浏览，不代替审计签名或状态核验。

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

若由审查者决定是否接受草稿，先从 `backbone status` 读取当前 `version`，以 `intent review` 替代上例的 `intent transition ... accepted`。审查者必须不同于意图作者，结果可为 `accepted` 或 `rejected`；审查记录保留理由和所审阅的版本。管理员旧式 `transition` 仍可用，但不会生成审查记录。

```sh
backbone --repo /path/to/project intent review intent-greeting \
  --outcome accepted --author carol --rationale '目标和约束明确' \
  --version OBSERVED_VERSION
```

用返回的任务 ID 替换 `TASK_ID`。成员在 `feature/greeting` 分支实现并提交 `greeting.py`，协调端在目标分支 `main` 检查：

```sh
backbone --repo /path/to/project task submit --member alice --file examples/artifact.json
backbone --repo /path/to/project conflict list
```

检查基于实际 Git diff。禁止路径、空产物、`.backbone/` 改写、空白错误和阻塞冲突会阻止提交；意图声明了非空 affected_paths 时，也会检查超出声明范围的修改。`accepted: true` 仅表示确定性检查通过，语义仍需人审查。

在两份意图开始实施前，可选择调用 DSH 获取结构化的语义冲突建议：

```sh
backbone --repo /path/to/project conflict advise INTENT_A INTENT_B \
  --dsh-home /absolute/private-advice-home --model YOUR_MODEL
```

它只读取两份活跃意图、相关已接受决策和确定性冲突证据，并返回模型意见、观察到的账本版本与输入哈希；不会写入 Git、创建冲突或替代人工裁决。若运行期间账本变化，结果标记 `stale: true`。调用会把这些协调数据发给所配置的模型 provider，须由操作者自行配置凭据。

如有阻塞冲突，查看证据、记录裁决后重新提交：

```sh
backbone --repo /path/to/project conflict resolve CONFLICT_ID \
  --author owner --action coordinate --rationale '保留兼容接口，后续单独移除'
```

人工审查后执行真正的 Git 合并，再记录完成：

```sh
git -C /path/to/project switch main
git -C /path/to/project merge --no-edit feature/greeting
backbone --repo /path/to/project task inspect TASK_ID
backbone --repo /path/to/project task merge TASK_ID --author owner \
  --version OBSERVED_VERSION --target-sha OBSERVED_TARGET_SHA
backbone --repo /path/to/project log
backbone --repo /path/to/project sync
```

合并后由 `task inspect` 获取当前 `version` 和 `git.target_sha`；人工核对最终代码，再把两个观察值交给 `task merge`。期间若账本或目标代码变化，完成操作会拒绝并要求重新检查。`task merge` 验证提交已进入目标分支并记录人工审查，不执行代码合并。`sync` 显式推送当前分支，包括代码和元数据提交，不拉取或强推。另一个克隆在同名分支可运行 `backbone --repo /path/to/project refresh`：远端领先且本地工作树干净时快进；本地领先或双方分叉时只报告状态和差异，不自动合并。`refresh` 返回 `diverged` 时须人工检查和合并 Git 历史。已成功提交的任务在分支更新后，需 `task start` 再重新提交；检查失败的任务仍为 in_progress，可直接修复后重交。

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

如果取消后需要改变意图内容，用 `intent replace` 提交字段补丁和理由。旧意图及任务历史保留，新意图是带有 `supersedes` 引用的 draft，须重新接受后才能分派；此操作在一次 Git 审计提交中完成。已有任务历史的意图不能原地 `revise`。

```sh
backbone --repo /path/to/project intent replace INTENT_ID \
  --file /path/to/patch.json --author owner \
  --reason '需求调整' --version OBSERVED_VERSION
```

`intent review`、`intent revise`、`intent replace` 和 `task rebase` 都要求先读取当前 `version`，防止使用过期上下文覆盖新决策；命令记录后版本会变化，下次需重新读取。已合入目标分支的产物不能通过取消或刷新任务来撤销，需先处理代码回退。

## Agent 接入

```sh
backbone --repo /absolute/path/to/project mcp --member alice
```

由 Agent 客户端启动这个 stdio MCP 进程。成员绑定固定身份并隐藏管理员工具。完整配置见 [MCP_API.md](MCP_API.md)。

已有私有令牌文件和可信 HTTPS 证书时，可显式为远程成员启用同一 HTTP 服务上的 Streamable HTTP MCP：

```sh
uv run backbone --repo /path/to/project serve --host 0.0.0.0 --port 8443 \
  --auth-file /private/path/backbone-http-tokens.json --mcp-http \
  --mcp-allowed-host coordinator.example.org:8443 \
  --tls-certfile /private/path/server.crt --tls-keyfile /private/path/server.key
```

成员客户端连接 `https://coordinator.example.org:8443/mcp`，以 `Authorization: Bearer` 提供自己的成员令牌。该端点只公布成员工具，并逐请求绑定身份；管理员和审查者令牌不能访问。令牌轮换无需重启，远程 Host 必须列入允许名单。详见 [MCP_API.md](MCP_API.md) 和 [部署与恢复](docs/OPERATIONS.md)。

容器部署可在原有 Compose 文件组合后追加 `-f compose.mcp.yaml`，启用同一 `/mcp` 接口；远程域名通过 `BACKBONE_MCP_ALLOWED_HOSTS` 指定。四种部署组合与命令见 [部署与恢复](docs/OPERATIONS.md)。

## 可选 DSH 审查

```sh
uv sync --locked --group dev --extra dsh
uv run backbone --repo /path/to/project review TASK_ID \
  --dsh-home /absolute/path/to/isolated-dsh-home --model YOUR_MODEL
```

需自行配置模型凭据。审查输入随请求发送，运行补丁禁用默认 shell 工具并设置只读策略；请使用没有额外工具插件的专用 DSH home。成功审查返回 `aligned / concerns / uncertain` 建议，连同 SDK 会话 ID、完成状态和本次调用耗时记入 Git 审计；建议不替代人工裁决或合并。可选 `review --attempt-log` 把已提交和失败尝试写入仓库外私有 JSONL，`review-stats` 可汇总已记录样本，不记录提示词或 diff。真实模型调用、用量和费用尚未验证。见 [DSH_PLUGIN_PLAN.md](DSH_PLUGIN_PLAN.md)。

可选的本地协调代理通过受限 MCP 工具读取状态、提出草稿意图和建议决策、检测冲突、分派**已经人工接受**的意图。它不能调用意图接受、冲突仲裁或任务合并审批工具。请使用仓库外、仅当前用户可访问的专用 DSH home；模型回合仍需自行配置凭据：

```sh
uv run backbone --repo /absolute/project conductor \
  --dsh-home /absolute/private-coordinator-home --model YOUR_MODEL \
  --prompt "读取协调状态，提出下一步草稿并检查冲突"
```

运行前会用独立 MCP 连接核对精确工具范围；SDK 无模型启动由 CI 验证。代理持有调用者的 OS 权限，DSH 的只读文件策略和禁用 shell 不隔离 MCP 子进程；应使用专用账户与仓库权限。人类仍需复核并执行接受、仲裁及真实 Git 合并后的审批。

成员也可用可选 DSH 运行时接入 Backbone。先执行 `uv sync --locked --group dev --extra dsh`，准备与协调仓库分开的代码工作树，再显式运行：

```sh
uv run backbone --repo /absolute/project dsh --member alice \
  --workspace /absolute/alice-worktree --dsh-home /absolute/isolated-dsh-home \
  --model YOUR_MODEL --prompt "先读取我的任务与已接受决策"
```

若要保留同一回合链中的工作记忆，可把多个提示写成 JSON 字符串数组并改用 `--prompts-file /absolute/private/turns.json`；它们在同一 SDK 进程内依次运行。也可用 `--interactive` 替代 `--prompt`，逐行输入并立即收到每轮 JSON 结果；空行跳过，`:quit`、`:exit` 或 EOF 结束会话。该选项也适用于远程成员和受限协调代理。复杂的多行提示可继续使用 `--prompt-file`。锁定的 DSH SDK 目前不能在命令退出后以原 `--session-id` 恢复已持久化的会话，Backbone 会明确拒绝这种续接。该命令先通过真实 MCP 握手检查成员身份与工具范围，再装载 DSH 的 MCP 客户端插件；本地模拟模型已验证实际调用成员工具，真实付费模型质量尚未验证。详情与沙箱边界见 [DSH_PLUGIN_PLAN.md](DSH_PLUGIN_PLAN.md)。

成员若不能访问协调仓库，可使用已启用 `/mcp` 的 HTTPS 服务。在**成员机器**上把自己的 bearer token 放到工作树及 DSH home 外的 0600 文件；DSH home 须为当前用户所有的 0700 目录。`--repo` 和 `--ledger-branch` 不用于远程模式：

```sh
uv run backbone dsh --member alice \
  --workspace /absolute/alice-worktree --dsh-home /absolute/private-dsh-home \
  --mcp-url https://coordinator.example/mcp \
  --mcp-token-file /absolute/private/alice.token \
  --model YOUR_MODEL --prompt "先读取我的任务与已接受决策"
```

自签证书可加 `--mcp-ca-file /absolute/ca.crt`。非回环 HTTP 被拒绝；运行前会核对令牌对应的成员和精确工具列表。令牌只从私有文件读取并写入本次运行的 0600 临时 DSH 补丁，运行后删除；专用 DSH home 中的运行日志仍应按敏感资料管理。令牌轮换后需更新文件并启动新回合。远程 DSH 插件经 CI 验证无模型启动，并用本机模拟模型在认证 HTTP 与受信任 HTTPS 上实际调用成员工具、核对 Git 审计身份；尚未进行付费模型回合或真实多人部署。

跨克隆的代码提交需要成员推送 Git 功能分支，再通过成员 MCP 按完整 SHA 获取该分支，才能提交产物；实际 Git 合并后再由审查者记录完成。命令与边界见 [独立代码克隆流程](docs/OPERATIONS.md#独立代码克隆的提交与合并)。

## 开发与验证

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest --cov=backbone_conductor --cov-fail-under=85
uv run pytest tests/test_live_http.py -q
uv run python scripts/evaluate.py
uv run python scripts/benchmark.py
uv run python scripts/benchmark_mcp.py --clients 10
uv build
```

CI 对 Python 3.12、3.13 运行检查、测试、合成评测、十个独立 MCP stdio 会话的并发完整性验证和示例；其中真实 HTTP 双客户端进程测试必须运行，不能因缺少 loopback socket 权限而跳过。本地受限沙箱若禁止监听 socket，该测试会明确跳过，可在允许本地网络的环境单独运行。MCP 基准记录单次延迟，不设性能门槛；合成用例通过率不代表真实项目冲突召回率。

若 macOS 的 editable `.pth` 被标记 hidden 导致模块不存在，可用 `uv sync --locked --group dev --no-editable`，随后执行 `uv run --no-sync ...`；源码修改后需重装。开发测试也可显式设置 `PYTHONPATH=src`。

## 文档与边界

- [项目章程](PROJECT_INITIATION.md)、[初始意图](INTENT.md)
- [当前实现和后续工作](docs/IMPLEMENTATION.md)
- [MCP 与 Codex 接入](MCP_API.md)、[冲突规则](CONFLICT_RULES.md)
- [DSH 适配](DSH_PLUGIN_PLAN.md)、[部署与恢复](docs/OPERATIONS.md)
- [测试报告](docs/VALIDATION.md)
- [发布流程](docs/RELEASING.md)
- 原草案：[PLAN.md](PLAN.md)、[ARCHITECTURE.md](ARCHITECTURE.md)、[PROTOCOL_SPEC.md](PROTOCOL_SPEC.md)

当前版本不含远程多租户鉴权、自动代码合并、团队生产部署或 PyPI 发布。状态存于 `.backbone/state.json`，Markdown 概览和分对象文件由它生成；写入产生独立审计提交，不夹带其他暂存文件。
