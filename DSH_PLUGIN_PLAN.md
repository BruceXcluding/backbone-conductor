# DSH 集成

当前使用发布的 deepseek-harness-sdk；锁文件固定 SDK/runtime 为 0.1.5rc1，位于可选 dsh extra。

DSHReviewer 将任务、意图、已接受决策和真实 diff 放入临时目录，以明确指定的 home 启动 DeepSeekHarness 的 sdk-minimal profile。输出必须符合 SemanticReview Schema；非法输出、超时和未完成回合不会生成批准。调用结束关闭 runtime，再核对 Backbone 版本和制品 SHA，拒绝过期结果。成功审查的 `runtime` 字段记录从创建 SDK 客户端到关闭的 `elapsed_ms`、SDK 返回的 `session_id` 与 `finish_reason`，随建议一起进入 Git 审计。失败尝试不修改 Backbone 状态；这些指标不代表模型生成阶段的独立耗时。

```sh
uv sync --locked --extra dsh
uv run backbone --repo /absolute/project review TASK_ID \
  --dsh-home /absolute/isolated-dsh-home --model YOUR_MODEL
```

需在本地配置 provider 凭据，不写入 Git。审查会向该 provider 发送任务和代码 diff；结果只作建议。输入目录隔离不是 OS 沙箱，SDK 最小 profile 仍有 shell 能力，应使用可信 profile 与适当的运行账户。

SDK 接口、结构化输出、错误清理和成功审查指标经过无模型测试；真实模型调用、token 用量与费用尚未验证。当前 SDK `RunResult` 未提供稳定的用量/费用字段，因此不推算费用。原生 DSH 插件组合、MCP client profile、多 Agent 调度插件仍待实现。

依据：[DSH 官方 Python SDK](https://github.com/deepseek-ai/deepseek-harness/blob/master/python/sdk/README.md)、[SDK 入门](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/guide/python-sdk.md)。MCP 服务端使用 [官方 MCP Python SDK v1](https://github.com/modelcontextprotocol/python-sdk/tree/v1.x)，固定 `<2` 避免主版本 API 变化。
