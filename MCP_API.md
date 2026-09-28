# MCP API 与 Agent 接入

启动 `backbone --repo /absolute/repo mcp --member alice`，使用官方 MCP SDK 的 stdio 传输。stdout 仅用于协议。

| 工具 | 参数 | 返回 |
| --- | --- | --- |
| get_my_task | member_id? | 任务、意图、约束、决策、冲突 |
| create_intent | intent_data | draft 意图 |
| log_decision | decision_data | proposed 决策 |
| start_task | task_id, member_id? | in_progress 任务 |
| rebase_task | task_id, expected_version, member_id? | 刷新目标分支与决策上下文 |
| submit_artifact | artifact, member_id? | Git 证据、检查、冲突 |
| check_backbone_sync | member_id?, since_version? | 当前版本、新增/撤回决策、阻塞冲突 |

绑定成员时可省略 member_id；冒用其他成员或 author 会报错。artifact 至少含 intent_id、branch、summary，base_ref 默认为 main，且必须匹配任务目标分支。

省略 `--member` 为本地管理员进程，额外暴露 dispatch_task、transition_intent、transition_decision、revise_intent、cancel_task、detect_conflicts、resolve_conflict、merge_task、refresh_backbone、reconcile_backbone。不得将其当作远程认证服务。

工具 Schema 由 MCP tools/list 提供；领域 Schema 可由 `backbone schema` 或 HTTP `/schema` 获取。

## Codex

先安装本项目。替换两个绝对路径：

```sh
codex mcp add backbone -- /absolute/backbone-conductor/.venv/bin/backbone \
  --repo /absolute/your-project mcp --member alice
```

或配置 stdio server：

```toml
[mcp_servers.backbone]
command = "/absolute/backbone-conductor/.venv/bin/backbone"
args = ["--repo", "/absolute/your-project", "mcp", "--member", "alice"]
```

配置已对照本机 CLI 和 [OpenAI 官方 MCP 文档](https://learn.chatgpt.com/docs/extend/mcp?surface=cli) 核实。项目不会自动修改全局客户端设置。其他 stdio MCP 客户端可使用相同 command/args。

## 成员流程

1. 获取任务，阅读约束与决策，调用 start_task。
2. 在独立代码分支/worktree 实现，期间调用 check_backbone_sync。
3. 提交代码，确保协调仓库可访问 feature ref，再 submit_artifact。
4. 阻塞冲突交给管理员裁决；通过后仍需人工审查和真正的 Git 合并。

协调端保持在目标分支。get_my_task 是拉取接口；首版不主动向 Agent 会话推送消息。
当 check_backbone_sync 返回 new_decisions 或 withdrawn_decisions，成员应执行 rebase_task，使用当前 version 作为 expected_version，再提交制品。提交后才发生的决策变化由管理员在 merge_task 的 rationale 中明确审查并记录。
