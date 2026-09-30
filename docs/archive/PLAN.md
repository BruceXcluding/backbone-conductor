# Backbone Protocol + Conductor Agent 开发计划

> **历史设计提案**：以下团队规模、排期、版本和许可证设想未作为发布承诺。当前行为见[实现说明](../IMPLEMENTATION.md)和[验证记录](../VALIDATION.md)；实际许可证为 [MIT](../../LICENSE)。

> **提案版本**：v1.0（非软件发布版本）
> **状态**：归档
> **关联文档**：[PROTOCOL_SPEC.md](./PROTOCOL_SPEC.md) · [ARCHITECTURE.md](./ARCHITECTURE.md)

---

## 1. 项目概述

### 1.1 问题陈述

在 AI-native 开发中，代码不再是瓶颈。瓶颈转移到了构建阶段的左右两侧——规划、审查和部署仍然以人的速度运行。团队中的每个成员都在使用 Coding Agent（Codex、Claude Code 等）写代码，但存在三个结构性缺陷：

1. **Agent 各自为战**：每个人的 Agent 会话相互隔离，缺少共享的项目上下文和约束。
2. **意图级冲突不可见**：Git 能检测行级冲突，但检测不了“Agent A 移除了 PaymentService，Agent B 依赖这个扩展点”这种意图级碰撞。
3. **决策不可追溯**：谁在什么时候做了什么架构决策、为什么做——这些信息散落在 Slack、会议记录和个人记忆中。

### 1.2 产品定位

**Backbone Protocol 是一个 Git 原生的多智能体协作协议。Conductor Agent 是协议的自动化执行者和人机交互界面。**

它不是另一个 multi-agent framework，不是项目管理工具，也不是 Agent 编排平台。它的定位是 **多 Agent 协作的 Git**——定义 Agent 之间如何在意图层和决策层进行 fork、rebase、merge 和仲裁。

### 1.3 核心价值主张

> Git 让代码可以并行开发。Backbone Protocol 让意图和决策像代码一样，可以被 fork、diff、rebase、merge——并且整个过程对人类可审计。

### 1.4 目标用户

- **主要用户**：10 人规模的 AI-native 开发团队
- **团队特征**：每个成员使用 Codex / Claude Code 等 Coding Agent，项目涉及多个并行工作流
- **关键角色**：Tech Lead（仲裁决策）、团队成员（执行任务）、Conductor Agent（自动化管理）

### 1.5 成功指标

| 指标 | 目标值 | 衡量方式 |
|------|--------|----------|
| 意图级冲突检测率 | ≥80% | 在真实项目中检测到的冲突数 / 实际发生的冲突数 |
| 决策可追溯率 | 100% | 所有架构决策都有对应的 `decision` 记录 |
| 团队成员接入率 | 10/10 | 所有成员通过 MCP 接入 Conductor |
| 平均任务分派时间 | <5 分钟 | 从意图确认到任务推送到成员会话 |
| 冲突仲裁平均时间 | <30 分钟 | 从冲突检测到裁决完成（含人类审批） |

---

## 2. 需求分析

### 2.1 功能性需求

**FR-01: 意图管理**
- 支持通过对话创建 `intent.md`，包含问题描述、期望结果、受影响符号、约束条件
- 支持意图的状态流转：`draft → accepted → in_progress → completed / superseded`
- 支持意图之间的派生关系（`parent_intent`）

**FR-02: 决策记录**
- 支持自动和手动记录架构/设计决策，包含作者、类型、摘要、理由
- 支持决策的覆盖链（`supersedes`）
- 决策关联到相关的意图

**FR-03: 任务分派**
- Conductor 根据意图和 spec 自动创建任务，分派给成员
- 通过 MCP 将任务上下文推送到成员的 Codex 会话
- 任务状态跟踪：`dispatched → in_progress → submitted → merged`

**FR-04: 冲突检测**
- 确定性规则：`replace_vs_extend`、符号作用域重叠、依赖冲突
- LLM 辅助：语义级冲突检测（决策矛盾、意图不一致）
- 三关检查：代码层（Git）、意图层（LLM）、决策层（LLM + 历史）

**FR-05: 冲突仲裁**
- 生成仲裁包（包含冲突双方、证据、建议、选项）
- 支持三种仲裁模式：人类裁决、中立 Agent 裁决、自动裁决（低风险）
- 仲裁结果记录为新的决策

**FR-06: Backbone 同步**
- 每次状态变更产生 Git commit
- 支持 `backbone sync` 命令，推送变更到远程
- 支持 `backbone log` 查看完整历史
- 支持 `backbone revert` 撤销错误决策

**FR-07: MCP 接口**
- 暴露工具：`get_my_task`、`submit_artifact`、`check_backbone_sync`、`create_intent`、`log_decision`
- 支持 Codex、Claude Code 等通过 MCP 接入

**FR-08: 项目时间线**
- 人类可读的时间线视图，展示意图、决策、冲突、合并的历史
- 支持按时间、作者、类型过滤

### 2.2 非功能性需求

| 需求 | 说明 |
|------|------|
| **性能** | MCP 工具调用响应 <2 秒；Backbone sync <10 秒 |
| **可靠性** | Git 作为持久化存储，天然容错；Agent 会话中断后可恢复 |
| **安全性** | 成员鉴权通过 MCP tool_meta_resolver 注入；Backbone repo 受 branch protection 保护 |
| **可审计性** | 所有操作记录在 Git 历史中，可查询、可追溯 |
| **可扩展性** | Protocol 与 Runtime 分离，支持未来接入新的 Agent runtime |
| **本地优先** | 支持 local-first 部署，数据不离开团队服务器 |

### 2.3 约束条件

- 10 人团队，自用优先，后续开源
- 使用 **Python** 作为主要开发语言
- 使用 **DeepSeek Harness（DSH）** 作为 Agent 运行时框架
- **Git** 作为持久化和审计层
- **MCP** 作为成员接入协议
- Rust 作为未来性能优化路径，当前不引入

---

## 3. SDLC 阶段与交付物

### 3.1 阶段总览

| 阶段 | 目标 | 主要产出物 | 进入下一阶段的条件 |
|------|------|------------|-------------------|
| **Plan** | 明确项目范围、愿景、约束 | `PROJECT_INITIATION.md`、`INTENT.md` | 团队对 MVP 达成一致 |
| **Design** | 定义 Protocol 对象模型、状态机、接口 | `PROTOCOL_SPEC.md`、`ARCHITECTURE.md` | 对象模型评审通过 |
| **Build** | 实现 Protocol 核心、Conductor、MCP Server | 可运行的 Conductor + MCP Server | 团队成员可通过 MCP 接入 |
| **Test** | 验证冲突检测、仲裁、Sync | 测试报告、Eval 套件 | 冲突检测覆盖率 ≥80% |
| **Deploy** | 部署到团队服务器，成员接入 | 部署文档、接入指南 | 10/10 成员成功接入 |
| **Maintain** | 持续优化、开源准备 | 开源仓库、文档、示例 | 项目可被外部团队复现 |

### 3.2 Phase 1: Plan（规划）—— 第 1-2 周

**目标**：明确项目范围、愿景、约束，达成团队共识。

**活动**：
1. 团队评审本文档，确认核心概念和架构方向
2. 明确 MVP 范围：只做“意图创建 + 任务分派 + 基础冲突检测 + Git 同步”
3. 确定技术栈和部署方式（团队服务器）
4. 编写 `PROJECT_INITIATION.md`

**交付物**：
- `PROJECT_INITIATION.md`：项目章程，包含目标、范围、干系人、时间线
- `INTENT.md`：Backbone Protocol 的初始意图声明

**质量门禁**：团队 10 人全部评审通过，对 MVP 范围达成一致。

### 3.3 Phase 2: Design（设计）—— 第 3-5 周

**目标**：定义 Protocol 的完整对象模型、状态机、接口规范。

**活动**：
1. 设计 `Intent`、`Decision`、`Conflict`、`BackboneState` 的完整字段和状态机
2. 设计 MCP 工具的输入输出 Schema
3. 设计 Git-Native Backbone 的目录结构和同步协议
4. 设计冲突检测的确定性规则集（初始版本）
5. 设计 Conductor 的 DSH 插件组装方案和指令模板

**交付物**：
- `PROTOCOL_SPEC.md`：完整对象模型和状态机定义
- `ARCHITECTURE.md`：系统架构、组件交互、部署拓扑
- `MCP_API.md`：MCP 工具规范
- `CONFLICT_RULES.md`：确定性冲突检测规则
- `DSH_PLUGIN_PLAN.md`：DSH 插件清单与组装配置

**质量门禁**：对象模型和状态机评审通过；MCP 接口规范得到至少 2 名团队成员确认。

### 3.4 Phase 3: Build（构建）—— 第 6-13 周

**目标**：实现 Protocol 核心、Conductor Agent、MCP Server。

**子阶段**：

**3a. Protocol Core（第 6-8 周）**
- 实现 `backbone-protocol` 包：对象模型、状态机、序列化/反序列化
- 实现 Backbone Sync Engine：Git commit 生成、状态增量计算
- 单元测试覆盖 ≥80%

**3b. MCP Server（第 9-10 周）**
- 基于 DSH 的 `dsh-mcp-client` 插件实现 MCP Server
- 暴露 `get_my_task`、`submit_artifact`、`check_backbone_sync` 等工具
- 实现成员鉴权（通过 DSH 的 context 注入 member_id）
- 本地测试：用 Codex 连接 MCP Server，验证工具可用

**3c. Conductor Agent（第 11-13 周）**
- 基于 DSH 组装 Conductor 的插件：Protocol、ConflictDetector、TaskDispatcher
- 实现任务分派逻辑（`dispatch_task`）
- 实现基础冲突检测（确定性规则）
- 实现决策记录（`log_decision`）
- 集成测试：完整流程——创建意图 → 分派任务 → 提交 Artifact → 检测冲突 → 记录决策

**交付物**：
- `backbone-protocol` Python 包（可 pip install）
- 可运行的 Conductor Agent（FastAPI 服务）
- 可运行的 MCP Server
- DSH 插件配置文件和组装脚本
- 集成测试套件

**质量门禁**：团队成员可通过 MCP 接入并完成一次完整的“意图 → 任务 → 提交 → 检测”流程。

### 3.5 Phase 4: Test（测试）—— 第 14-16 周

**目标**：验证冲突检测、仲裁、Sync 的完整性和可靠性。

**活动**：
1. **冲突检测测试**：构造 10 个真实场景的意图冲突，验证确定性规则和 LLM 辅助检测的覆盖率
2. **仲裁流程测试**：构造决策冲突，验证仲裁包生成和裁决流程
3. **Backbone Sync 测试**：验证 Git commit 生成、状态恢复、`git bisect` 可用性
4. **Eval 套件**：收集 20-50 个真实任务，编写 eval 用例，在 CI 中运行
5. **压力测试**：10 个并发 MCP 会话，验证响应时间和稳定性

**交付物**：
- 测试报告（含覆盖率数据）
- Eval 套件（可在 CI 中运行）
- 已知问题清单

**质量门禁**：冲突检测覆盖率 ≥80%；所有 P0/P1 问题修复；Eval 套件通过率 ≥90%。

### 3.6 Phase 5: Deploy（部署）—— 第 17-18 周

**目标**：部署到团队服务器，10 名成员全部接入。

**活动**：
1. 使用 Docker Compose 部署 Conductor + MCP Server 到团队服务器
2. 为每个成员配置 MCP 接入（Codex 的 `config.toml` 中添加 MCP server）
3. 编写接入指南和故障排查手册
4. 进行一次全团队演练：启动一个新项目，所有人通过 Conductor 协作
5. 收集反馈，修复接入过程中的问题

**交付物**：
- 部署文档（Docker Compose 或 systemd 服务）
- 成员接入指南
- 演练报告

**质量门禁**：10/10 成员成功接入；全团队演练完成一次完整的“意图 → 分派 → 提交 → 合并”流程。

### 3.7 Phase 6: Maintain（维护）—— 第 19 周起，持续

**目标**：持续优化、准备开源。

**活动**：
1. **持续优化**：根据团队反馈迭代 Conductor 的 DSH 插件配置和冲突规则
2. **Eval 维护**：每次生产问题都转化为新的 eval 用例
3. **开源准备**：
   - Protocol 与 Runtime 分离，通用化
   - 编写开源文档和示例项目
   - 发布到 PyPI（`backbone-protocol`、`backbone-conductor`）
   - 创建 GitHub 仓库，添加 LICENSE（建议 Apache-2.0）
4. **生态整合**：编写与 Foremerge、codeplane 等现有方案的互操作适配器
5. **性能评估（可选）**：若并发会话数或冲突检测延迟成为瓶颈，评估将 Protocol Core 用 Rust 重写的可行性

**交付物**：
- 开源 GitHub 仓库
- PyPI 包
- 文档站点
- 示例项目

**质量门禁**：外部团队可按照文档复现整个流程。

---

## 4. 开发计划

### 4.1 时间线

```
2026-09  │ Phase 1: Plan          │ 第 1-2 周   │ 项目启动
2026-10  │ Phase 2: Design        │ 第 3-5 周   │ 对象模型+架构设计
2026-11  │ Phase 3a: Protocol Core│ 第 6-8 周   │ 核心库实现
2026-12  │ Phase 3b: MCP Server   │ 第 9-10 周  │ MCP 接口实现
2027-01  │ Phase 3c: Conductor    │ 第 11-13 周 │ Agent 实现+集成测试
2027-02  │ Phase 4: Test          │ 第 14-16 周 │ 测试+Eval
2027-03  │ Phase 5: Deploy        │ 第 17-18 周 │ 部署+全员接入
2027-04  │ Phase 6: Maintain      │ 第 19 周+   │ 持续优化+开源
```

**总工期**：约 18 周（4.5 个月）到 MVP，第 19 周起进入维护和开源阶段。

### 4.2 团队分工（10 人）

| 角色 | 人数 | 职责 |
|------|------|------|
| **Tech Lead** | 1 | 架构决策、冲突仲裁、代码审查 |
| **Protocol 工程师** | 2 | 对象模型、状态机、Git Sync |
| **DSH/Agent 工程师** | 3 | DSH 插件开发、Conductor 组装、MCP Server |
| **测试/Eval 工程师** | 2 | 测试套件、Eval、CI/CD |
| **DevOps 工程师** | 1 | 部署、监控、基础设施 |
| **文档/开源** | 1 | 文档、示例、开源准备 |

### 4.3 里程碑

| 里程碑 | 时间 | 交付物 | 验证标准 |
|--------|------|--------|----------|
| **M1: 项目启动** | 第 2 周末 | `PROJECT_INITIATION.md`、`INTENT.md` | 团队评审通过 |
| **M2: 设计完成** | 第 5 周末 | `PROTOCOL_SPEC.md`、`ARCHITECTURE.md`、`MCP_API.md`、`DSH_PLUGIN_PLAN.md` | 对象模型评审通过 |
| **M3: Protocol Core 完成** | 第 8 周末 | `backbone-protocol` 包 | 单元测试覆盖率 ≥80% |
| **M4: MCP Server 可用** | 第 10 周末 | 可运行的 MCP Server | Codex 可连接并调用工具 |
| **M5: Conductor MVP** | 第 13 周末 | 可运行的 Conductor（DSH 组装） | 完整流程跑通 |
| **M6: 测试通过** | 第 16 周末 | 测试报告、Eval 套件 | 冲突检测覆盖率 ≥80% |
| **M7: 全员接入** | 第 18 周末 | 部署文档、接入指南 | 10/10 成员接入 |
| **M8: 开源发布** | 第 24 周+ | GitHub 仓库、PyPI 包 | 外部团队可复现 |

### 4.4 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| DSH 版本早期，API 可能变更 | 中 | 高 | Protocol 与 DSH 解耦，DSH 仅用于参考实现；锁定 DSH 版本，关注社区更新 |
| 冲突检测准确率不足 | 中 | 高 | 确定性规则优先，LLM 辅助兜底；持续收集真实冲突案例迭代 |
| 团队成员抵触新流程 | 中 | 中 | Phase 1 充分沟通；MVP 只做最核心功能，降低使用门槛 |
| Git 仓库膨胀 | 低 | 中 | `.backbone/` 使用独立仓库或 Git LFS；定期归档 |
| 部署环境不可迁移 | 低 | 中 | Docker Compose 部署，所有依赖容器化 |

### 4.5 质量保证

- **代码审查**：所有 PR 需要至少 1 名团队成员 review
- **CI/CD**：每次 push 触发单元测试和 lint 检查
- **Eval 套件**：每次修改 Conductor 指令或冲突规则时运行 eval
- **真实场景测试**：每个生产问题转化为新的 eval 用例

---

## 5. 附录

### 5.1 术语表

| 术语 | 定义 |
|------|------|
| **Backbone** | 项目骨架，包含所有意图、决策、冲突和会话状态 |
| **Intent** | 一个意图，项目要解决的一个问题或目标 |
| **Decision** | 一个架构/设计决策，带作者、理由、时间 |
| **Conflict** | 两个意图/决策/产物之间的语义碰撞 |
| **Conductor** | 自动化大脑，协议的参考实现和执行者 |
| **Rebase** | 将一个意图/任务线重新锚定到新的 Backbone 版本 |
| **Merge** | 将完成的意图合并回项目主线 |
| **仲裁包** | 冲突检测后生成的包含双方证据、建议、选项的结构化数据 |
| **DSH** | DeepSeek Harness，全插件机制的 Agent 运行时框架 |

### 5.2 参考项目

| 项目 | 参考价值 |
|------|----------|
| **Foremerge** | 意图声明 + 确定性冲突检测（`replace_vs_extend` 规则） |
| **GNAP** | Git-native 任务协调，Git 作为共享消息总线 |
| **MPAC** | 五层协调协议（Session/Intent/Operation/Conflict/Governance） |
| **Hermes merge-reconciler** | 中立第三方 Agent 仲裁 git 合并冲突 |
| **OpenIntent** | 生命周期装饰器（`@on_conflict`、`@on_escalation`） |
| **DeepSeek Harness** | 全插件架构，模型无关，支持 MCP 和多 Agent 协作插件 |

### 5.3 下一步行动

1. **本周**：团队评审本文档，确认核心概念和架构方向
2. **下周**：启动 Phase 1，编写 `PROJECT_INITIATION.md`
3. **第 3 周**：进入 Phase 2，开始 Protocol 对象模型设计
4. **第 6 周**：进入 Phase 3，开始基于 DSH 的 Conductor 原型开发

---

> **文档维护**：本文档由 Tech Lead 维护，每次 Phase 评审后更新。
> **反馈渠道**：团队内部 GitHub Discussions 或每周技术评审会。
