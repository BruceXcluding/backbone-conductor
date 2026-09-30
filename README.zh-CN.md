# Backbone Conductor

[English](README.md)

Backbone Conductor 让多个编程 Agent 共享意图、决策与 Git 证据。它记录变更的提出和审查过程，检测已声明符号与路径之间的冲突，并把协作状态保存在可审计的 Git 历史中。

核心功能不依赖模型。Agent 可通过 MCP 接入，维护者可使用 CLI 或 HTTP API。可选的 DeepSeek Harness 集成提供语义建议；冲突裁决、代码审查和 Git 合并仍由人负责。

## 核心能力

- **实施前协调：**记录意图、约束、涉及的符号、决策和任务分派。
- **提交时核验：**依据固定 Git 提交，检查制品范围、当前决策和阻塞冲突。
- **合并后审批：**审阅提交补丁与目标分支的最终结果；完成记录必须绑定实际 Git 合并、审阅时的账本版本与目标提交。
- **Git 审计：**用 Git 保存状态与生成视图，支持显式同步、历史校验和可选提交签名。协调记录也可放在独立元数据分支。

确定性冲突规则依赖结构化声明和 Git 路径，不保证语义正确性。模型输出只是建议，不能代替人工审批或合并。

## 本地试用

需要 Python 3.12+ 和 Git。可从 PyPI 安装公开预览版：

```sh
python -m pip install backbone-conductor==0.75.0
backbone --help
```

开发或运行仓库示例还需安装 [uv](https://docs.astral.sh/uv/)，并使用源码仓库：

```sh
git clone https://github.com/BruceXcluding/backbone-conductor.git
cd backbone-conductor
uv sync --locked --group dev
uv run python examples/demo.py
uv run python examples/two_agent_demo.py --mcp
```

两个示例都使用临时 Git 仓库，不会修改当前项目。第二个示例通过两个独立、绑定成员身份的 MCP 客户端演示意图冲突、制品提交、审查和真实 Git 合并；Agent 身份、代码改动和审批由脚本模拟。

接入已有且至少包含一个提交的 Git 仓库：

```sh
uv run backbone --repo /absolute/path/to/your-repo init
uv run backbone --repo /absolute/path/to/your-repo status
uv run backbone --repo /absolute/path/to/your-repo serve
```

HTTP 服务默认只监听 `127.0.0.1:8000`，交互式 API 位于 [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)。本地 Agent 可运行 `uv run backbone --repo /absolute/path/to/your-repo mcp --member alice`，启动绑定成员身份的 stdio MCP 服务。工具范围见 [MCP API](MCP_API.md)，认证后的远程访问见[部署指南](docs/OPERATIONS.md)。

打开[决策脉络图](http://127.0.0.1:8000/decision-map)，可按替代关系浏览决策、搜索与筛选状态、拖动节点并缩放画布；选择节点可查看理由及关联证据。图谱是只读视图，Git 账本仍是唯一事实来源，个人节点位置只保存在当前浏览器。启用 HTTP 认证后，在页面输入管理员或审查者令牌即可读取决策。

## 工作流程

1. 实施前创建意图，由审查者接受。
2. 将任务分派给成员；成员读取共享上下文，在 Git 分支中实现。
3. 提交分支及精确提交 SHA 作为制品；Backbone 检查范围、Git 证据和阻塞冲突。
4. 审阅固定制品，在 Git 中合并代码，再检查目标分支的结果。
5. 使用这次检查返回的账本版本和目标提交记录审批；过期观察值或未集成的代码会被拒绝。

完整的 CLI、远程成员与审查者操作见[部署指南](docs/OPERATIONS.md)。[冲突规则](CONFLICT_RULES.md)说明自动检查的范围；[实现说明](docs/IMPLEMENTATION.md)说明存储、身份与审查边界。

## 文档

| 主题 | 文档 |
| --- | --- |
| 架构与能力边界 | [实现说明](docs/IMPLEMENTATION.md) |
| 部署、凭据、同步与恢复 | [部署指南](docs/OPERATIONS.md) |
| 成员及协调者 MCP 工具 | [MCP API](MCP_API.md) |
| 确定性冲突检查 | [冲突规则](CONFLICT_RULES.md) |
| 可选 DeepSeek Harness 集成 | [DSH 集成](DSH_PLUGIN_PLAN.md) |
| 验证方法与现有证据 | [验证指南](docs/VALIDATION.md) |
| 真人试用流程 | [试用验收](docs/PILOT.md) |
| 发布流程 | [发布说明](docs/RELEASING.md) |
| 版本记录 | [更新日志](CHANGELOG.md) |

[文档索引](docs/README.md)另列研究资料和历史设计记录。若旧设计文档与当前行为不一致，以实现代码和生成的 Schema 为准。

## 参与贡献

欢迎通过 [GitHub Issues](https://github.com/BruceXcluding/backbone-conductor/issues) 报告问题或提出建议。开发环境、检查命令和 Pull Request 要求见 [CONTRIBUTING.md](CONTRIBUTING.md)。

项目采用 [MIT 许可证](LICENSE)。
