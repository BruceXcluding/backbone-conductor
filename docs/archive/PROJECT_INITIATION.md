# 初始项目章程（历史记录）

Backbone Conductor 旨在让多个 Coding Agent 在共享意图与约束下协作。本文记录项目启动时的范围，当前行为以[实现说明](../IMPLEMENTATION.md)和代码为准。

首版目标是让一个人使用多个 Coding Agent 时，能够声明意图、分派任务、发现结构化冲突、记录人工裁决，并以 Git 保存可恢复的审计历史。

v0.1 的交付边界是可本地运行的 Python 包、CLI、HTTP API、stdio MCP 服务、确定性检查、可选 DSH 语义审查适配器、测试和可复现实例。原草案的十人团队、服务器部署、真实冲突召回率、长期自治编排和 PyPI 发布属于后续验证阶段。

实际接口由代码生成的 JSON Schema、OpenAPI 和 MCP tools/list 定义。
