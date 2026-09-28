# DSH 集成

当前使用发布的 deepseek-harness-sdk；锁文件固定 SDK/runtime 为 0.1.5rc1，位于可选 dsh extra。

DSHReviewer 将任务、意图、已接受决策和真实 diff 作为明确标记为不可信数据的 JSON 随请求提供，在一次性目录内以明确指定的 home 启动 DeepSeekHarness 的 sdk-minimal profile。运行时补丁禁用该 profile 默认的持久 bash/PowerShell 工具，并把文件策略设为 `read-only`；模型审查不需要本地命令或读取仓库。输出必须符合 SemanticReview Schema；非法输出、超时和未完成回合不会生成批准。调用结束关闭 runtime，再核对 Backbone 版本和制品 SHA，拒绝过期结果。成功审查的 `runtime` 字段记录从创建 SDK 客户端到关闭的 `elapsed_ms`、SDK 返回的 `session_id` 与 `finish_reason`，随建议一起进入 Git 审计。失败尝试不修改 Backbone 状态；这些指标不代表模型生成阶段的独立耗时。

可选 `--attempt-log` 记录已经通过任务和 diff 前置校验、但在 DSH 调用或写入审查结果时失败的尝试。路径必须是仓库和 Git 目录外的绝对路径，父目录仅当前用户可访问（0700），日志文件为仅当前用户可读写的普通文件（0600）；命令会在调用模型前验证该位置。JSONL 事件包含任务 ID、模型/provider 名称、审阅前版本、制品 SHA、`runtime` 或 `commit` 失败阶段、总耗时和错误**类型**，不包含提示词、代码 diff、令牌或 provider 原始错误内容。成功审查仍由 Git 记录；此文件是私有运行指标，不是 Backbone 审计提交，也不保证捕获进程崩溃或前置校验失败。

```sh
uv sync --locked --extra dsh
mkdir -m 700 /absolute/private-review-metrics
uv run backbone --repo /absolute/project review TASK_ID \
  --dsh-home /absolute/isolated-dsh-home --model YOUR_MODEL \
  --attempt-log /absolute/private-review-metrics/attempts.jsonl
```

需在本地配置 provider 凭据，不写入 Git。审查会向该 provider 发送任务和代码 diff；结果只作建议。补丁禁用默认 shell，但指定的 DSH home 若有自定义补丁，仍可能装载其他工具；请使用专用 home 和适当的运行账户。一次性目录与只读工具策略不限制 Harness 进程自身的 OS 权限或向 provider 发送数据。

## 成员代理接入

`backbone dsh` 使用同一可选 SDK 的 `sdk-minimal` profile，在临时补丁中装载 `@deepseek-ai/dsh-mcp-client`，启动绑定 `--member` 的 Backbone stdio MCP 服务。调用模型前，Python 端另起一次 MCP 连接，核对初始化、工具列表、成员上下文，并拒绝管理员工具泄露。`--workspace` 必须是与协调仓库分开的现存目录，`--dsh-home` 必须位于两者之外；补丁把 DSH 工具写入策略设为 `workspace-write`，并在系统提示中要求通过 MCP 操作协调元数据。独立元数据分支可在 `dsh` 子命令前传入 `--ledger-branch backbone`。

```sh
uv sync --locked --extra dsh
uv run backbone --repo /absolute/project dsh --member alice \
  --workspace /absolute/separate-worktree \
  --dsh-home /absolute/isolated-dsh-home --model YOUR_MODEL \
  --prompt-file /absolute/task-prompt.txt
```

此入口会实际向配置的 provider 发起模型请求；必须由操作者自行配置凭据。返回的会话 ID 带仓库与成员命名空间，可用 `--session-id` 继续同一成员会话；其他命名空间的 ID 会被拒绝。DSH 最小 profile 的 shell 与 MCP 子进程仍以调用者的 OS 身份运行；`workspace-write` 限制模型工具的写入范围，但不构成完整的读取或网络隔离。MCP `--member` 是本地工具约束，不是不同自然人之间的认证。会话日志保存在指定的 DSH home；不要把凭据或敏感日志放入 Git。模型建议、工具调用和代码修改都不能替代人工复核及真实 Git 合并。

SDK 接口、结构化输出、错误清理和成功审查指标经过无模型测试；审查专用补丁经有效配置输出和真实 SDK 无模型启动验证；成员 MCP 接入已通过真实 SDK 的无模型启动及工具发现验证。真实模型调用、token 用量与费用尚未验证。当前 SDK `RunResult` 未提供稳定的用量/费用字段，因此不推算费用。更完整的原生 DSH 插件组合、工作内存和多 Agent 调度插件仍待实现。

依据：[DSH 官方 Python SDK](https://github.com/deepseek-ai/deepseek-harness/blob/master/python/sdk/README.md)、[SDK 入门](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/guide/python-sdk.md)、[DSH MCP 客户端](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/mcp/mcp-client/README.md)。MCP 服务端使用 [官方 MCP Python SDK v1](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x)，固定 `<2` 避免主版本 API 变化。
