# Backbone Conductor

**让多个 Coding Agent 共享意图、约束与决策，用 Git 记录每次协作变更。**

这是独立个人兴趣项目。v0.1 提供本地协调内核：CLI、HTTP API、stdio MCP、确定性冲突检查、人工仲裁和可选 DeepSeek Harness 语义审查。

## 快速开始

需要 Python 3.12+、Git 和 [uv](https://docs.astral.sh/uv/)。

```sh
git clone https://github.com/BruceXcluding/backbone-conductor.git
cd backbone-conductor
uv sync --locked --group dev
uv run python examples/demo.py
```

演示在临时仓库完成意图创建、任务分派、代码提交、检查、Git 合并和完成记录，不修改当前项目，不需要模型密钥。输出应有 `"intent": "completed"` 和 `"task": "merged"`。

接入自己的 Git 仓库：

```sh
uv run backbone --repo /absolute/path/to/your-repo init
uv run backbone --repo /absolute/path/to/your-repo serve
```

打开 [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) 使用交互式 API。服务默认监听本机，供可信本地管理员使用。

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

用返回的任务 ID 替换 `TASK_ID`。成员在 `feature/greeting` 分支实现并提交 `greeting.py`，协调端在目标分支 `main` 检查：

```sh
backbone --repo /path/to/project task submit --member alice --file examples/artifact.json
backbone --repo /path/to/project conflict list
```

检查基于实际 Git diff。禁止路径、空产物、`.backbone/` 改写、空白错误和阻塞冲突会阻止提交；意图声明了非空 affected_paths 时，也会检查超出声明范围的修改。`accepted: true` 仅表示确定性检查通过，语义仍需人审查。

如有阻塞冲突，查看证据、记录裁决后重新提交：

```sh
backbone --repo /path/to/project conflict resolve CONFLICT_ID \
  --author owner --action coordinate --rationale '保留兼容接口，后续单独移除'
```

人工审查后执行真正的 Git 合并，再记录完成：

```sh
git -C /path/to/project switch main
git -C /path/to/project merge --no-edit feature/greeting
backbone --repo /path/to/project task merge TASK_ID --author owner
backbone --repo /path/to/project log
backbone --repo /path/to/project sync
```

`task merge` 验证提交已进入目标分支并记录人工审查，不执行代码合并。`sync` 显式推送当前分支，包括代码和元数据提交，不拉取或强推。已成功提交的任务在分支更新后，需 `task start` 再重新提交；检查失败的任务仍为 in_progress，可直接修复后重交。

## Agent 接入

```sh
backbone --repo /absolute/path/to/project mcp --member alice
```

由 Agent 客户端启动这个 stdio MCP 进程。成员绑定固定身份并隐藏管理员工具。完整配置见 [MCP_API.md](MCP_API.md)。

## 可选 DSH 审查

```sh
uv sync --locked --group dev --extra dsh
uv run backbone --repo /path/to/project review TASK_ID \
  --dsh-home /absolute/path/to/isolated-dsh-home --model YOUR_MODEL
```

需自行配置模型凭据。审查返回 `aligned / concerns / uncertain` 建议并记入审计，不替代人工裁决或合并。真实模型调用尚未验证。见 [DSH_PLUGIN_PLAN.md](DSH_PLUGIN_PLAN.md)。

## 开发与验证

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest --cov=backbone_conductor --cov-fail-under=85
uv run python scripts/evaluate.py
uv run python scripts/benchmark.py
uv build
```

CI 对 Python 3.12、3.13 运行检查、测试、合成评测和示例。合成用例通过率不代表真实项目冲突召回率。

若 macOS 的 editable `.pth` 被标记 hidden 导致模块不存在，可用 `uv sync --locked --group dev --no-editable`，随后执行 `uv run --no-sync ...`；源码修改后需重装。开发测试也可显式设置 `PYTHONPATH=src`。

## 文档与边界

- [项目章程](PROJECT_INITIATION.md)、[初始意图](INTENT.md)
- [当前实现和后续工作](docs/IMPLEMENTATION.md)
- [MCP 与 Codex 接入](MCP_API.md)、[冲突规则](CONFLICT_RULES.md)
- [DSH 适配](DSH_PLUGIN_PLAN.md)、[部署与恢复](docs/OPERATIONS.md)
- [测试报告](docs/VALIDATION.md)
- 原草案：[PLAN.md](PLAN.md)、[ARCHITECTURE.md](ARCHITECTURE.md)、[PROTOCOL_SPEC.md](PROTOCOL_SPEC.md)

当前版本不含远程多租户鉴权、自动代码合并、团队生产部署或 PyPI 发布。状态存于 `.backbone/state.json`，Markdown 概览和分对象文件由它生成；写入产生独立审计提交，不夹带其他暂存文件。
