# v0.2 实现说明

| 范围 | 已实现行为 |
| --- | --- |
| 协议 | Pydantic v2 模型、UTC 时间、JSON Schema、状态机、路径/ID 校验 |
| 意图 | 草稿、接受、开始、拒绝、替代、合并后完成、父意图引用；分派前修订并重新接受 |
| 决策 | 提议、接受、覆盖链、撤销；仲裁和人工审查形成新决策 |
| 任务 | 分派、成员上下文、开始、提交、重试、取消并重新开放意图、上下文 rebase、合并后完成 |
| 制品 | 固定提交 SHA、真实 Git 路径、目标分支绑定、修改范围检查 |
| 冲突 | 四类确定性规则、稳定证据 ID、分级、仲裁包、人工裁决 |
| 存储 | Git 快照、生成视图、跨进程锁、异常回滚、并发版本检查 |
| 接入 | argparse CLI、FastAPI/OpenAPI、官方 MCP SDK stdio |
| 运行时 | 可选真实 DSH SDK 适配，结构化建议、超时和错误处理 |
| 验证 | 单元测试、真实 Git 流程、MCP stdio 通信、合成评测、CI |

## 模块关系

```text
CLI / HTTP / MCP
       │
       ▼
Conductor service ── optional DSHReviewer → DeepSeekHarness SDK
       ├── protocol models
       ├── conflict rules
       └── GitStore → state.json + generated views + audit commits
```

Git 是唯一权威存储；进程重启直接恢复快照，当前不需要 SQLite 缓存。

## 对原草案的修正

1. 个人项目首版不依赖假定的十人团队和 18 周排期。
2. Pydantic 模型提供输入验证和 JSON Schema，保留原领域对象与生命周期。
3. DSH 通过 `deepseek_harness.DeepSeekHarness` 接入；草案的 Python `dsh.Agent/Plugin` 不是核实过的 API。
4. MCP 客户端插件不充当服务端；服务端使用官方 Python MCP SDK。
5. `.backbone/` 记录在协调仓库当前分支；不隐式切换或推送独立 backbone 分支。成员只提交实现代码，协调端保持在目标分支。
6. 磁盘 `version` 为 null，`parent_version` 保存上次版本。读取时从最近 `.backbone/` commit 补全当前版本，避免保存提交自身 SHA 的循环依赖。
7. 无模型时明确要求人工语义审查；模型建议也不授予合并权限。
8. MCP `--member` 是本地工具约束，不防范拥有相同文件权限的用户。HTTP 是可信本地管理员接口。
9. 分派后的决策变化使产物检查中的 context 关卡失败，要求显式刷新任务。提交通过后才变化的决策需要在完成记录中留下人工复核理由。

## 后续里程碑

- [ ] 采集真实项目冲突样本，评估误报与漏报。
- [ ] 配置凭据后验证 DSH 在线质量、成本、延迟和故障恢复。
- [x] 增加分派前意图修订、任务取消和显式上下文 rebase（不执行 Git rebase）。
- [ ] 多人审查权限模型和更丰富的意图变更流程。
- [ ] 远程认证、授权与审计身份验证；随后开展服务器和多人演练。
- [ ] 独立 Backbone 分支、跨克隆协调与结构化合并策略。
- [ ] 原生 DSH 插件组合、工作内存与可观测性；当前仅实现 SDK 审查适配。
- [ ] 选定开源许可证、完成发布流程后再发布 PyPI。

首版未修改客户端全局配置、创建服务器或调用付费模型。
