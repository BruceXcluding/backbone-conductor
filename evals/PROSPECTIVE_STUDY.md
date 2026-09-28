# 前瞻意图冲突评测

本流程用事前记录的两个意图预测是否需要协调，再与事后**独立人工**标签比较。它与 [合成规则评测](conflicts.json) 和 [历史 Git 文本冲突回放](GIT_MERGE_PILOT.md) 分开；后两者都不能测真实意图冲突检测率。当前仓库没有已标注的真实前瞻样本，因而**尚无真实精确率、召回率或 ≥80% 结论**。

先写采样方案：项目范围、纳入/排除标准、连续收集的起止时间、任务对如何产生、标签定义，以及预期负例来源。不要按已知冲突或检测结果挑样本。每条 case 固定一个项目、同一代码基线的完整 Git SHA、采集时间和两份工作开始前的意图。意图字段遵循 `Intent` 模型，必须显式写 `id`、`author`、`created_at`；作者不同、状态为 `draft` 或 `accepted`，创建时间不晚于采集时间。路径和符号范围须按当时的计划声明，不能在完成代码后回填实际改动。

已有 Backbone 仓库可在工作开始、任务分派之前，从当前记录中一次采集**全部**合格配对并立即冻结预测：

```sh
python scripts/evaluate_prospective.py capture \
  --repo /absolute/project-checkout \
  --project owner/project \
  --sampling '事前固定的纳入窗口与所有候选配对规则' \
  --dataset /private/study/cases.json \
  --predictions /private/study/predictions.json
```

独立元数据分支增加 `--ledger-branch backbone`。`capture` 要求代码工作树干净，只选择当前 `draft` 或 `accepted`、**从未有任务记录**的意图，并生成不同作者之间的所有配对；若没有合格配对则失败。它从代码 HEAD 取得 `base_sha`，返回 Backbone 快照版本和两个文件的 SHA-256。输出必须是仓库外的绝对路径，以私有权限新建，不覆盖已有文件。采样文字仍需人工预先制定；重复快照、事前已有仓库外代码工作、伪造作者或时间戳都不能靠该命令排除。生成后应立刻将数据与预测固定在私有证据仓库或可信时间戳存储，再开始工作。

数据文件放在适当的**私有**位置。例如：

```json
{
  "schema_version": 1,
  "sampling": "连续收集项目 X 在指定时间窗内的所有并行任务对；排除规则事前固定",
  "cases": [
    {
      "id": "project-x-pair-001",
      "project": "owner/project-x",
      "base_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "captured_at": "2026-09-29T10:00:00Z",
      "intents": [
        {
          "id": "intent-a",
          "author": "alice",
          "problem": "改变付款接口",
          "proposed_outcome": "新付款接口可用",
          "affected_paths": ["src/payment.py"],
          "created_at": "2026-09-29T09:00:00Z"
        },
        {
          "id": "intent-b",
          "author": "bob",
          "problem": "扩展付款调用方",
          "proposed_outcome": "调用方兼容新接口",
          "affected_paths": ["src/checkout.py"],
          "created_at": "2026-09-29T09:30:00Z"
        }
      ]
    }
  ]
}
```

以上仅是**格式示例**，SHA 与案例不是观察数据。工作开始前运行：

```sh
python scripts/evaluate_prospective.py freeze \
  --dataset /private/study/cases.json \
  --output /private/study/predictions.json
```

`freeze` 只创建新文件，不覆盖旧预测；它记录原始数据文件和检测器及评测脚本源码的 SHA-256、冻结时间、每例规则与证据。把数据与预测提交到私有证据仓库或可信时间戳存储，记录提交 SHA，然后再开始工作。**自报时间和哈希不能单独证明冻结发生在工作之前**；保存可独立核对的外部时间顺序很重要。后续 `score` 不会重新运行当前版本的检测器，而是使用冻结的预测；修改原数据文件会被拒绝。本流程只评估两份事前意图之间的预警，不覆盖决策和任务规则。

工作结果可供审阅时，先制定标签定义：`conflict=true` 表示两份原计划若并行执行，需要在集成前协调范围、先后顺序或设计；`false` 表示不需要这种协调。文本 Git 合并冲突只是证据之一，不能自动充当标签。两位非意图作者的审阅者分别看到原意图、实际产物及必要上下文，但**不看预测或对方标签**。每人单独写一个文件；文件中的 `dataset_sha256` 与 `predictions_sha256` 是绑定值，可从冻结文件计算，不需要展示预测内容。每个文件形如：

```json
{
  "schema_version": 1,
  "dataset_sha256": "填入 cases.json 的 SHA-256",
  "predictions_sha256": "填入 predictions.json 的 SHA-256",
  "reviewer": "carol",
  "cases": [
    {
      "id": "project-x-pair-001",
      "conflict": true,
      "rationale": "两项变更对付款接口的兼容策略需要共同决定"
    }
  ]
}
```

若两人不同意，第三位非作者、非前两位审阅者可按相同格式提供裁决文件。未标注、只收到一份标签、或有分歧但无裁决的案例保留为 `incomplete`，不被默认为负例。运行：

```sh
python scripts/evaluate_prospective.py score \
  --dataset /private/study/cases.json \
  --predictions /private/study/predictions.json \
  --review /private/study/carol.json \
  --review /private/study/dave.json \
  --adjudications /private/study/erin.json --json
```

没有分歧时省略 `--adjudications`。报告列出已解决样本的 TP/FP/FN/TN、精确率、召回率、F1 和逐例状态；没有正例时召回率为 `null`，没有预警时精确率为 `null`。`complete_sample` 只说明此文件的案例标签齐备，不证明抽样代表性、审阅者确为不同自然人或达到原草案的真实项目目标。发布指标前应检查时间顺序、采样偏差、标签一致性和各项目分布，并保留未解决样本及理由。不要把敏感任务、代码或审阅记录直接提交到本公开仓库。
