# Backbone Protocol 规范

> **实现状态**：本文保留原始对象设计。v0.1 可执行协议以 `src/backbone_conductor/models.py` 和 `backbone schema` 输出为准；新增 Task、Artifact、操作/路径声明、Git 提交锚点和检查结果。MCP 参数见 [MCP_API.md](MCP_API.md)。
> v0.2 新增 Task `cancelled` 终态，以及取消后 Intent `in_progress → accepted`、分派前修订后重置为 draft、任务上下文 rebase。实际状态机仍以代码和 Schema 为准。
> v0.5 在状态快照中增加可选 `merged_parent_version`，记录结构化元数据合并的另一侧审计版本；Git 双父提交仍是完整历史的权威证据。普通变更清空此字段。

> **版本**：v1.0
> **状态**：草案——待团队评审
> **关联文档**：[ARCHITECTURE.md](./ARCHITECTURE.md) · [PLAN.md](./PLAN.md)

---

## 1. 核心对象模型

### 1.1 Intent（意图）

```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class IntentStatus(Enum):
    DRAFT = "draft"
    ACCEPTED = "accepted"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SUPERSEDED = "superseded"


@dataclass
class Intent:
    """一个意图 = 项目要解决的一个问题或目标"""

    id: str
    author: str
    problem: str
    proposed_outcome: str
    affected_symbols: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    status: IntentStatus = IntentStatus.DRAFT
    parent_intent: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    artifacts: list[str] = field(default_factory=list)
```

### 1.2 Decision（决策）

```python
class DecisionStatus(Enum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    SUPERSEDED = "superseded"
    REVERTED = "reverted"


@dataclass
class Decision:
    """一个决策 = 架构/设计选择，带作者、理由、时间"""

    id: str
    author: str
    decision_type: str  # tech_choice / api_design / data_model / ...
    summary: str
    rationale: str
    supersedes: Optional[str] = None
    related_intents: list[str] = field(default_factory=list)
    status: DecisionStatus = DecisionStatus.PROPOSED
```

### 1.3 Conflict（冲突）

```python
class ConflictType(Enum):
    INTENT_OVERLAP = "intent_overlap"
    DECISION_CONFLICT = "decision_conflict"
    SEMANTIC_MERGE = "semantic_merge"
    RESOURCE_CONTENTION = "resource_contention"


class Severity(Enum):
    ADVISORY = "advisory"
    BLOCKING = "blocking"
    CRITICAL = "critical"


@dataclass
class Conflict:
    """一个冲突 = 两个意图/决策/产物之间的语义碰撞"""

    id: str
    conflict_type: ConflictType
    parties: list[str]  # 涉及的意图/决策 ID
    severity: Severity
    detection_method: str  # deterministic / llm_assisted / human_flagged
    resolution: Optional[dict] = None
    arbitration_packet: Optional[dict] = None
```

### 1.4 BackboneState（骨架状态）

```python
@dataclass
class BackboneState:
    """项目骨架的完整快照——每次 sync 产生一个新 commit"""

    intents: dict[str, Intent] = field(default_factory=dict)
    decisions: dict[str, Decision] = field(default_factory=dict)
    conflicts: dict[str, Conflict] = field(default_factory=dict)
    sessions: dict[str, dict] = field(default_factory=dict)
    version: str = ""
    parent_version: Optional[str] = None
```

---

## 2. 状态机

### 2.1 Intent 状态流转

```
draft ──accept──▶ accepted ──start──▶ in_progress ──complete──▶ completed
  │                   │                    │
  │                   │                    └──supersede──▶ superseded
  │                   └──reject──▶ rejected（隐含）
  └──discard──▶ （删除，不进入 backbone）
```

### 2.2 Decision 状态流转

```
proposed ──accept──▶ accepted ──supersede──▶ superseded
    │                    │
    │                    └──revert──▶ reverted
    └──reject──▶ （删除）
```

---

## 3. Git-Native Backbone 结构

```
.backbone/
├── intents/
│   ├── 0001-user-export.md
│   └── 0002-oauth-integration.md
├── decisions/
│   ├── 0012-use-postgresql.md
│   └── 0013-use-stripe.md
├── conflicts/
│   └── 0003-payment-service-collision.json
├── sessions/
│   └── session-2026-09-15-alice.md
└── BACKBONE.md              # 人类可读的骨架概览（自动生成）
```

**同步流程**：

1. 读取当前 Git 状态
2. 计算增量（新意图、新决策、新冲突）
3. 生成 commit，message 格式：`backbone: intent 0001 accepted by alice`
4. Push 到远程

**审计能力**：
- `git log` 查看谁在什么时候改变了什么
- `git bisect` 定位导致冲突的决策
- `git revert` 撤销错误决策

---

## 4. MCP Server 接口

| 工具名 | 输入 | 输出 | 用途 |
|--------|------|------|------|
| `get_my_task` | `member_id` | 任务上下文包 | 成员启动时拉取任务 |
| `submit_artifact` | `member_id, artifact` | 检查结果 | 成员完成时提交 |
| `check_backbone_sync` | — | 更新通知 | 检查是否有新决策影响当前任务 |
| `create_intent` | `intent_data` | `intent_id` | 创建新意图 |
| `log_decision` | `decision_data` | `decision_id` | 记录决策 |

**任务上下文包格式**：

```json
{
  "intent": { ... },
  "spec": "spec.md 内容",
  "constraints": ["使用现有 auth 中间件", "不新增 PII 字段"],
  "decisions_at_fork": ["decision_001", "decision_002"],
  "forbidden_paths": ["src/legacy/"]
}
```

---

## 5. 冲突检测规则

### 5.1 确定性规则（优先）

| 规则名 | 触发条件 | 冲突类型 |
|--------|----------|----------|
| `replace_vs_extend` | 一个意图移除某符号，另一个意图扩展同一符号 | `INTENT_OVERLAP` |
| `symbol_scope_overlap` | 两个意图的 `affected_symbols` 有交集 | `INTENT_OVERLAP` |
| `dependency_conflict` | 新决策依赖的符号被另一决策移除 | `DECISION_CONFLICT` |
| `resource_contention` | 两个任务声明修改同一文件范围 | `RESOURCE_CONTENTION` |

### 5.2 LLM 辅助检测

用于语义级冲突：
- 决策矛盾（如“用 PostgreSQL” vs “用 MongoDB”）
- 意图不一致（如一个意图要求“无状态”，另一个引入 session）
- 约束违反（如“不新增 PII”但制品新增了 email 字段）

### 5.3 三关检查

```
第一关：代码层   → git diff --check main...member-branch
第二关：意图层   → LLM 校验产出是否满足原始 intent 和 spec
第三关：决策层   → LLM + 历史决策冲突检测
```

---

## 6. 仲裁协议

### 6.1 严重程度

| 级别 | 行为 |
|------|------|
| `advisory` | 自动记录，不阻塞合并 |
| `blocking` | 推送到人类裁决界面，阻塞合并 |
| `critical` | 中立 Agent 仲裁 + 人类确认 |

### 6.2 仲裁包格式

```json
{
  "conflict_id": "conflict-0003",
  "conflict_type": "decision_conflict",
  "parties": {
    "incoming": {
      "intent_id": "intent-0001",
      "author": "alice",
      "decision": "使用 Stripe 作为支付提供商"
    },
    "existing": {
      "decision_id": "decision-0012",
      "author": "bob",
      "decision": "使用 PostgreSQL 作为数据层"
    }
  },
  "detection": {
    "method": "deterministic",
    "rule": "replace_vs_extend",
    "evidence": "intent-0001 的语义作用域 'payment-service' 与 decision-0012 的 'data-layer' 存在依赖关系"
  },
  "suggestion": "建议沿用现有决策，因为...",
  "options": [
    {"action": "accept_existing", "impact": "..."},
    {"action": "override_existing", "requires": "tech_lead_approval"},
    {"action": "coordinate", "suggestion": "引入 PaymentProvider 抽象"}
  ],
  "human_required": true
}
```

### 6.3 仲裁模式

| 模式 | 适用场景 | 决策者 |
|------|----------|--------|
| 人类裁决 | `blocking` / `critical` | Tech Lead 或相关成员 |
| 中立 Agent 裁决 | `critical` 且规则明确 | 中立仲裁 Agent + 人类确认 |
| 自动裁决 | `advisory` 且确定性规则 | 系统自动记录 |
