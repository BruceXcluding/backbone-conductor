# v0.1 验证报告（历史基线）

日期：2026-09-16。环境：macOS arm64，Python 3.12.13，Git，uv 0.11.1。

## 自动化验证

- 219 项测试通过；核心包语句覆盖率 **90.80%**（CI 门槛 85%）。
- 协议模型与冲突检测覆盖率 100%；服务层 91%；Git 存储 93%。
- Ruff 代码检查和格式检查通过。
- 24/24 合成冲突场景通过：13 TP、0 FP、0 FN、11 个负场景。只代表此数据集，不证明真实项目召回率。
- 临时 Git 仓库完整示例通过：意图 completed、任务 merged，产生 7 个审计提交。
- 源码分发和 wheel 构建通过；安装包 CLI Schema 和完整示例可运行。
- 真正的 MCP stdio 客户端/服务端完成握手、tools/list、工具调用及身份冒用拒绝。

覆盖的重要回归：不夹带用户已暂存文件、写入失败回滚、跨进程更新不丢失、外部 Git 元数据更新拒绝覆盖、路径穿越/符号链接、重命名前后范围检查、禁止伪造制品检查结果、分支更新后重审、未合并不能完成、非目标分支不能记录完成、全局决策冲突、自动消失的冲突重新出现时恢复阻塞。

DSH 测试覆盖已安装 SDK 参数兼容、输入隔离、输出 Schema、错误/超时清理和未完成回合；测试没有调用真实模型。存在两个来自上游 Starlette/httpx/AnyIO 的弃用警告，不影响测试通过。

## 并发测量

`scripts/benchmark.py` 使用 10 个独立进程同时创建意图，在临时 Git 仓库验证快照、预期提交数量和干净状态。单次本机测量：

| 指标 | 结果 |
| --- | --- |
| 保存成功 | 10/10 intents |
| 审计提交 | 11（含初始化） |
| 写入中位数 | 1.140 秒 |
| p95 / 最大值 | 2.109 秒 |
| 写入窗口 | 2.110 秒 |
| 总时间（含子进程与验证，不含仓库设置） | 2.418 秒 |

样本 n=10，p95 用 nearest-rank 等于最大值。没有时间阈值断言；这不是持续负载测试，也未证明每次 MCP 响应都小于 2 秒。

## v0.1 时尚未验证

- Docker 镜像构建：本机镜像代理返回 401；绕过代理后 Docker Hub 认证端点超时。失败发生在拉取基础镜像阶段，尚未验证镜像构建和容器启动。
- 真实 DSH 模型调用、语义审查质量和费用。
- 外部团队接入、真实冲突检测率、远程服务器部署。
- Windows、网络文件系统、突然断电事务恢复。
- PyPI 发布与许可证选择。

可复现命令见 README；CI 状态以 GitHub Actions 实际运行结果为准。

## v0.2 增量

日期：2026-09-28。新增分派前意图修订、任务取消与上下文 rebase。新增回归测试覆盖过期版本拒绝、重新接受、父意图循环拒绝、取消后重新分派、成员归属检查、已提交产物失效、决策变化后的重检或人工复核理由，以及 CLI/HTTP 入口。

基础环境完整测试：**236 passed，1 skipped，覆盖率 91.31%**。被跳过的是仅用于核对真实 DSH SDK 构造接口的可选测试；在安装了 `dsh` extra 的隔离环境中，runtime 测试 **17 passed**（含该检查）。Ruff 检查与格式检查、24 个合成冲突场景、完整 Git 示例、source distribution 和 wheel 构建通过。基础测试在 `/private/tmp` 隔离环境运行，因为本机 Documents 下旧 `.venv` 的部分包文件被系统标记为 `dataless`，导入时会等待文件回填。远程 CI 状态以对应提交的 GitHub Actions 为准。

## v0.3 增量

日期：2026-09-28。HTTP 新增可选私有凭据文件、bearer 验证、管理员/成员角色和成员身份绑定。接口测试覆盖无凭据/错误凭据拒绝、默认禁止成员访问管理员路径、跨成员任务读取和操作拒绝、author 伪造拒绝、私有凭据文件约束、只写摘要的令牌生成，以及未配置认证时拒绝非 loopback 绑定。完整基础套件 **241 passed，1 skipped，覆盖率 91.72%**；Ruff 检查与格式检查、`uv lock --check --offline`、0.3.0 wheel/source distribution 构建通过。尚未完成 TLS 代理、真实远程客户端、容器启动或多人审计演练，不能据此宣称生产远程部署已验证。

## v0.4 增量

日期：2026-09-28。新增显式远端 `refresh`：获取同名分支后，只对有效 Backbone 快照和干净工作树执行 Git 快进；本地领先与分叉返回状态，分叉时列出两侧变更对象和路径，不自动合并。双克隆测试覆盖快进后审计历史一致、本地领先、分叉不改写、脏工作树保护和无效远端快照拒绝。完整基础套件 **246 passed，1 skipped，覆盖率 91.73%**；Ruff 检查与格式检查、`uv lock --check --offline`、合成评测 24/24、Git 示例、0.4.0 wheel/source distribution 构建通过。分叉后结构化合并和真实多人远程部署仍未实现。

## v0.5 增量

日期：2026-09-28。新增显式 `reconcile`，要求管理员提供审查过的本地/远端 HEAD 和理由。它只自动合并两侧独立的 `.backbone/` 对象变更，用双父 Git 提交保留审计历史并重算确定性冲突；代码路径变化、同一对象竞争、双活任务、跨分支父意图循环及过期 SHA 均拒绝或返回 `requires_review`。真实双克隆测试覆盖合并后推送与另一克隆快进、生成视图和冲突、代码重命名边界、历史不改写。完整基础套件 **252 passed，1 skipped，覆盖率 91.28%**；Ruff 检查与格式检查、`uv lock --check --offline`、合成评测 24/24、Git 示例、0.5.0 wheel/source distribution 构建通过。代码合并、竞争对象人工裁决和真实多人服务器演练仍未验证。

## v0.6 增量

日期：2026-09-28。新仓库可显式创建只含 `.backbone/` 的 orphan `backbone` 分支及隐藏 linked worktree；第二个克隆可从远端附加。Conductor 在独立模式中分别使用元数据 worktree 和源代码工作树，确保任务 base_ref/SHA、产物 diff 与实际合并仍指向代码分支。集成测试覆盖创建后源码分支不变、完整意图→任务→代码提交→制品检查→合并、双克隆元数据同步、CLI/HTTP 入口、凭据不得位于源码仓库，以及拒绝静默迁移既有内联快照。完整基础套件 **257 passed，1 skipped，覆盖率 90.99%**；Ruff 检查与格式检查、`uv lock --check --offline`、合成评测 24/24、Git 示例、0.6.0 wheel/source distribution 构建通过。既有内联快照迁移、独立模式容器路径、真实远程多人演练仍未验证。

## v0.7 增量

日期：2026-09-28。新增 `ledger migrate`，要求无活跃任务且代码工作树与索引干净。迁移创建以原代码 HEAD 为父提交、当前树只含 `.backbone/` 的元数据分支，并在代码分支提交删除旧快照；新状态的 `parent_version` 指向迁移前审计提交。真实 Git 集成测试验证 CLI 入口、旧审计链可达、迁移后新写入不改变代码 HEAD，以及活跃任务或脏工作树拒绝迁移。完整基础套件 **259 passed，1 skipped，覆盖率 90.45%**；Ruff 检查与格式检查、`uv lock --check --offline`、合成评测 24/24、Git 示例、0.7.0 wheel/source distribution 构建通过。独立模式容器路径、真实远程多人演练仍未验证。

## v0.8 增量

日期：2026-09-28。`reconcile` 新增可选逐对象 `resolutions`，管理员可对每个竞争对象选择本地、远端或提供完整合并值；遗漏、多余或无效决议拒绝提交。审查理由和选择摘要写入双父 Git 提交，合并后仍验证对象关系和任务生命周期并重算确定性冲突。CLI `--resolutions-file`、HTTP 和 MCP 已接入。真实 Git 测试覆盖无决议时保持 `requires_review`、选择远端、完整字段合并、错误 ID/额外决议不改变 HEAD，以及独立元数据分支双克隆合并与快进。完整基础套件 **261 passed，1 skipped，覆盖率 90.45%**；Ruff 检查与格式检查、`uv lock --check --offline`、合成评测 24/24、Git 示例、0.8.0 wheel/source distribution 构建通过。未进行真实多人服务器部署或人类语义审查。

## v0.9 增量

日期：2026-09-28。HTTP bearer 凭据改为逐请求重新读取和严格校验，`auth rotate` 在同一目录先写入并验证新 0600 摘要文件，再原子替换旧文件。运行中服务无需重启即可撤销旧令牌、接纳新令牌；凭据缺失、权限变宽、损坏或被换成符号链接/FIFO 时，受保护请求及 `/health` 返回 503。测试覆盖同一运行中的 HTTP 应用轮换、成员撤销、错误轮换保留原文件，以及上述失败关闭行为。完整基础套件 **262 passed，1 skipped，覆盖率 90.70%**；Ruff 检查与格式检查、`uv lock --check --offline`、合成评测 24/24、Git 示例、0.9.0 wheel/source distribution 构建通过。TLS、远程服务器和真实多人审计演练仍未验证。

## 本地真实 HTTP 多进程演练

日期：2026-09-28。新增 `tests/test_live_http.py`：启动实际 Uvicorn 子进程，两个独立客户端进程同时以各自 bearer 身份创建意图；管理员接受并分派后，客户端再次并发读取、隔离并开始自己的任务。测试核对仓库快照、9 个审计提交、干净工作树，并在服务不停机时轮换令牌，确认旧管理员令牌被拒而新令牌生效。本机受限沙箱禁止绑定 loopback，普通本地运行明确跳过；允许 socket 的本机完整套件 **263 passed，1 个可选 DSH 测试 skipped，覆盖率 90.70%**。CI 设置 `BACKBONE_REQUIRE_LIVE_HTTP=1`，不允许因 socket 权限而跳过。此为本地模拟客户端流程，不等于真实用户、TLS 或远程部署验证。

## v0.10 增量

日期：2026-09-28。经 bearer 验证的 HTTP 元数据写入，在 Git 提交消息中追加 principal 与角色 trailer；`backbone log`/时间线接口从提交中展示 `http_principal`、`http_role`。请求上下文在响应后清理，未认证本地调用没有 HTTP 归属。针对性测试覆盖普通领域写入、两个独立客户端进程并发写入、HTTP `reconcile` 双父提交、正确的成员/管理员对应关系、无明文令牌及请求结束后的本地写入。完整套件在强制执行真实 HTTP 测试时 **264 passed，1 个可选 DSH 测试 skipped，覆盖率 90.81%**；Ruff 检查与格式检查、合成评测 24/24、Git 示例、0.10.0 wheel/source distribution 构建通过。Git trailer 可由有仓库写权限者伪造，不是密码学签名；TLS、外部 Git 权限控制与真实多人部署仍未验证。

## v0.11 容器验证

日期：2026-09-29。Docker Desktop 29.1.5、macOS arm64，成功拉取官方 `python:3.12-slim`、构建项目镜像。用一次性 Git 仓库实际启动容器：默认内联模式的 `/health` 为 200，未认证 `/state` 为 401，测试令牌访问为 200，创建意图后宿主仓库有生成视图和带 HTTP principal trailer 的干净 Git 审计提交。独立模式在容器固定 `/workspace` 路径执行 `ledger create`，新容器可重开 worktree；HTTP 写入只推进 `backbone` 分支，代码分支 HEAD 不变，Compose 容器重启后可恢复快照。Compose 改挂载专用凭据目录，实测宿主原子替换凭据后，运行中服务拒绝旧令牌 401、接受新令牌 200。`compose.yaml` 与 `compose.ledger.yaml` 均通过 `docker compose config`，两种配置均实际启动；最终 0.11.0 镜像亦通过文档所列初始化与启动命令。完整套件在强制执行真实 HTTP 测试时 **264 passed，1 个可选 DSH 测试 skipped，覆盖率 90.81%**；Ruff 检查与格式检查、合成评测 24/24、Git 示例及 wheel/source distribution 构建通过。尚未在原生 Linux、TLS 代理或远程多人服务器上验证。

## v0.12 Linux Compose CI

日期：2026-09-29。新增 `scripts/verify_compose.py`，在 GitHub Actions `ubuntu-latest` runner 上构建镜像，并以宿主 UID/GID 运行一次性仓库。内联模式验证健康检查、认证与未认证访问、HTTP 意图写入、干净 Git 审计提交和运行中令牌原子轮换；独立分支模式验证代码 HEAD 不变、`backbone` 分支推进、审计归属和容器重启后读取。脚本在 macOS Docker Desktop 和 Linux CI 均通过；Linux CI 运行 [36451069545](https://github.com/BruceXcluding/backbone-conductor/actions/runs/36451069545) 的 Compose job 与 Python 3.12/3.13 常规 job 全部通过。此前的 v0.11 “原生 Linux 未验证”限制已收窄为远程服务器、TLS 代理与真实多人共享部署未验证。

## v0.13 直接 HTTPS

日期：2026-09-29。`serve` 新增成对的 `--tls-certfile` / `--tls-keyfile`，私钥须位于仓库外、为非符号链接的普通文件且仅所有者可访问。真实 Uvicorn 子进程使用临时自签证书接受已信任证书且持有 bearer 令牌的 HTTPS 请求；无令牌返回 401，不信任证书或用明文 HTTP 访问 HTTPS 端口时连接失败。HTTPS 写入仍留下已认证 principal 的 Git 审计 trailer。完整套件强制执行真实 HTTP/HTTPS 测试后 **268 passed，1 个可选 DSH 测试 skipped，覆盖率 90.84%**；Ruff 检查与格式检查、合成评测 24/24、Git 示例、0.13.0 wheel/source distribution 构建通过。证书自动签发/续期、远程服务器、可信反向代理及真实多人部署仍未验证。

## v0.14 Compose HTTPS

日期：2026-09-29。新增 `compose.tls.yaml` 与 `compose.ledger-tls.yaml`，扩展 `scripts/verify_compose.py` 在内联及独立元数据分支模式下实际运行 HTTPS 容器。一次性自签证书与私钥以只读目录挂载，测试验证被信任证书下的 `/health`、无令牌 401、有令牌读取与写入、HTTP principal Git trailer、重启恢复，以及不信任证书和明文 HTTP 访问失败。独立模式的代码分支 HEAD 保持不变。macOS Docker Desktop 和 Linux CI 均通过；[Linux CI 运行 36454451825](https://github.com/BruceXcluding/backbone-conductor/actions/runs/36454451825) 的 Python 3.12/3.13 及 Compose job 全部通过。最终 0.14.0 镜像的本机四模式验证、完整套件 **268 passed，1 个可选 DSH 测试 skipped，覆盖率 90.84%**、Ruff、合成评测 24/24、Git 示例及 wheel/source distribution 构建通过。TLS override 同时保留基础配置的宿主回环端口，该端口也使用 HTTPS。真实远程服务器、证书自动续期及多人共享部署仍未验证。

## v0.15 审查者权限

日期：2026-09-29。HTTP 凭据新增 `reviewer` 角色，`auth create`/`auth rotate` 可签发和轮换审查者令牌；文件加载拒绝重复 principal 名称。审查者可读取完整审查上下文、记录实际 Git 合并后的任务审批以及裁决冲突，但不能分派、同步或调用其他管理写入。审批要求非空理由；分派给审查者自己的任务不能由该令牌审批。真实 Git 与 HTTP TestClient 测试覆盖成员提交、外部 Git 合并、审查者记录决策、角色越权/author 冒用/自我审批拒绝、冲突仲裁及 `Backbone-HTTP-Role: reviewer` 审计 trailer；凭据测试覆盖只存摘要和轮换撤销。完整套件强制执行真实 HTTP/HTTPS 测试后 **270 passed，1 个可选 DSH 测试 skipped，覆盖率 91.10%**；Ruff 检查与格式检查、合成评测 24/24、Git 示例、0.15.0 wheel/source distribution 构建通过。令牌角色不能证明持有者是不同自然人，真实多人审查体验仍未验证。

## v0.16 替代意图流程

日期：2026-09-29。已接受且没有活跃任务的意图可通过 `intent replace` 或对应 HTTP/MCP 入口原子创建替代草稿。新意图记录 `supersedes` 与非空 `change_reason`，旧意图进入 `superseded`，已取消任务的历史保留；新草稿须重新接受才能分派。服务测试覆盖活跃任务拒绝、过期版本拒绝、非法字段与空理由拒绝、替代后重新分派；CLI、HTTP 和 MCP 测试覆盖入口与角色权限。完整套件强制执行真实 HTTP/HTTPS 用例后 **275 passed，1 个可选 DSH 用例 skipped，覆盖率 90.52%**；Ruff 检查与格式检查、合成评测 24/24、Git 示例、0.16.0 wheel/source distribution 构建及从 wheel 路径实际导入通过。离线 `uv sync` 因缓存缺少 `editables` 未完成，在线 `uv sync --locked --group dev` 后成功。本环境隐藏了 editable `.pth`，所以测试使用 `PYTHONPATH=src`，另独立验证 wheel 导入。合成评测不代表真实冲突检测率；本轮未运行付费模型语义审查或真实多人审查。

## v0.17 意图审查记录

日期：2026-09-29。`review_intent` 对 draft 意图记录 accepted/rejected 结果、审查者、非空理由和所审阅的 Backbone 版本；拒绝自我审查、过期版本及已非草稿的意图。修订会使已接受意图回到 draft，历史审查仍在新快照中，后续需再次审查。CLI、管理员 MCP 和 HTTP 管理员/审查者接入；HTTP 令牌绑定身份，成员无法访问审查端点。生成的意图 Markdown 视图显示结构化审查记录。完整套件强制执行真实 HTTP/HTTPS 用例后 **280 passed，1 个可选 DSH 用例 skipped，覆盖率 90.69%**；Ruff 检查与格式检查、合成评测 24/24、Git 示例、0.17.0 wheel/source distribution 构建、锁定开发环境离线同步及 wheel 独立导入通过。当前管理员直接 `transition_intent` 仍可接受意图而不产生审查记录；该操作不能声称已完成独立人工审查。未进行真实多人审查或付费模型语义验证。

## 多角色进程与容器演练

日期：2026-09-29。扩展真实 HTTP 集成测试：两个成员进程并发创建和启动任务，独立审查者进程先用旧版本审查而被拒绝，刷新后接受；成员进程提交真实 Git 分支制品，审查者进程在代码合并前无法批准，合并到目标分支后才记录完成。元数据提交验证成员、管理员与审查者各自的 bearer principal/role trailer，令牌轮换后旧令牌失效。`scripts/verify_compose.py` 在本机 Docker Desktop 逐一运行内联/独立元数据分支的 HTTP/HTTPS 容器，审查者令牌在每种模式下接受草稿意图，重启后仍可读取审查结果。客户端是独立 OS 进程和令牌模拟角色，并非不同自然人；真实多人体验仍需独立验收。

## v0.18 审计提交签名

日期：2026-09-29。验证了启用 `commit.gpgsign=true` 后，普通元数据写入、分叉合并和内联快照迁移都生成可由 Git 验证的 SSH 签名提交；签名私钥缺失会回滚元数据事务。审计查询区分有效、未签名和无效签名，并报告检查上限及是否还有更早的提交未检查。CLI 严格模式对未签名或无效签名返回非零状态；HTTP 审查者可读取报告，管理员 MCP 可调用检查。`backbone log` 现在也展示审查者 HTTP 身份记录。可信密钥签名不能证明 Git author、HTTP principal 或自然人身份，真实多人身份验证仍待完成。

强制执行真实 HTTP/HTTPS 用例的完整套件：**285 passed，1 个可选 DSH 用例 skipped，覆盖率 90.81%**。Ruff 检查与格式检查、合成评测 24/24、Git 示例、0.18.0 wheel/source distribution 构建、锁定开发环境离线同步及 wheel 独立导入通过。本环境隐藏 editable `.pth`，示例和源码测试使用 `PYTHONPATH=src`；本次未调用付费模型或做真实多人审查。

## v0.19 可筛选审计时间线

日期：2026-09-29。`backbone log` 与 HTTP `/timeline` 增加精确 Git author、已认证 HTTP principal、事件类型和带时区的 ISO 8601 起止时间筛选。先筛选再应用数量上限，因此可以取到较早的匹配提交；审查者仍可读、成员仍被拒绝。事件类型根据提交主题归类，时间来自 Git author 元数据，均不能作为独立验证的身份或事件事实。完整套件强制执行真实 HTTP/HTTPS 用例后 **286 passed，1 个可选 DSH 用例 skipped，覆盖率 90.84%**；Ruff、合成评测 24/24、Git 示例、0.19.0 wheel/source distribution 构建及隔离 wheel 导入通过。本机源码测试和示例继续使用 `PYTHONPATH=src`，因为环境隐藏 editable `.pth`。

## v0.20 公开历史 Git 合并回放试验

日期：2026-09-29。新增 [四例固定数据及来源](../evals/GIT_MERGE_PILOT.md)，包含 jsoup 和 Amaze File Manager 的真实双父合并提交。已在临时上游克隆逐例重放 `git merge-tree --write-tree`，并核对父 SHA、共同祖先到各父提交的修改路径和文本冲突标签。两例确有文本冲突；一例同文件修改却可干净合并，另一路径不重叠。Backbone `resource_contention` 对这些**文本冲突**标签的结果为 TP 2、FP 1、FN 0、TN 1；这是刻意选取的四例回顾性路径试验，不能据此宣称真实意图冲突 precision、recall 或 80% 目标。后续须用事前声明的意图及独立人工标签扩大评测。CI 仅离线运行固定数据，源仓库重放由显式验证命令完成。

完整测试强制执行真实 HTTP/HTTPS 用例后 **288 passed，1 个可选 DSH 用例 skipped，覆盖率 90.84%**。Ruff、24/24 合成评测、四例 Git 合并试验、Git 示例、0.20.0 wheel/source distribution 构建、锁定开发环境离线同步及隔离 wheel 导入通过。本机源码测试与示例使用 `PYTHONPATH=src`，因为环境隐藏 editable `.pth`；未调用付费模型。

## v0.21 DSH 成功审查指标

日期：2026-09-29。可选 DSH 审查在成功返回结构化建议时记录 SDK 客户端创建至关闭的单次耗时（毫秒）、SDK 会话 ID 和完成状态，随 `semantic_review` 写入 Git 审计；非法输出与未完成回合仍不会形成审查记录。使用无模型 Harness 替身验证时间计算、返回字段和服务层持久化，已安装 SDK 的构造接口另经独立测试。SDK 当前未提供稳定的 token 用量或费用字段，本版不估算费用；真实模型质量、费用、延迟和故障恢复仍未在线验证。

隔离开发环境强制执行真实 HTTP/HTTPS 用例后 **288 passed，1 个可选 DSH 用例 skipped，覆盖率 90.86%**；已安装可选 SDK 的接口测试另 **1 passed**。Ruff、24/24 合成评测、Git 示例、锁文件校验、0.21.0 wheel/source distribution 构建和隔离 wheel 导入通过。工作区 `.venv` 的首次全套运行出现一次失败并在较慢的测试阶段被中断；随后该接口测试文件单独重跑 **13 passed**。本环境的完整通过结果来自 `/private/tmp` 隔离虚拟环境，源码测试与示例使用 `PYTHONPATH=src`；本次未调用付费模型。

## v0.22 十会话 MCP stdio 并发验证

日期：2026-09-29。新增 `scripts/benchmark_mcp.py`：在一次性 Git 仓库启动十个独立、绑定不同成员的 MCP stdio 服务与客户端会话。所有会话初始化后同时调用 `create_intent`，然后核对十个不同作者与 ID、11 个 Git 提交（含初始化）、没有丢失或多出的对象以及干净工作树。首次本机运行 10/10 成功，中位数 1.088 秒、p95/最大值 1.931 秒；以锁定环境命令复跑 10/10 成功，中位数 1.102 秒、p95/最大值 2.066 秒。调用延迟包含 MCP 往返、Git 锁等待和提交，不含会话启动。样本小且受本机负载影响，**未证明原草案的每次 MCP 调用 <2 秒目标**；本基准在 CI 中只检查完整性，不设延迟阈值。

隔离环境全套测试强制执行真实 HTTP/HTTPS 用例后 **288 passed，1 个可选 SDK 用例 skipped，覆盖率 90.86%**。Ruff、24/24 合成评测、四例历史 Git 合并试验、Git 示例、锁文件校验、0.22.0 wheel/source distribution 构建及隔离 wheel 导入通过。真实不同自然人的并发使用、远程网络延迟和持续负载尚未验证。

## v0.23 DSH 成员 MCP 接入

日期：2026-09-29。新增 `backbone dsh` 入口：要求与协调仓库分开的代码工作目录和独立 DSH home；在模型调用前用真实 MCP stdio 客户端完成初始化、工具发现和成员上下文读取，拒绝管理员工具出现在成员范围。临时 DSH 补丁把 `sdk-minimal` 的工具写策略设为 `workspace-write`，装载绑定该成员的 Backbone MCP 客户端；会话 ID 按仓库与成员命名，错误命名空间不能复用。单元测试覆盖补丁、CLI、清理、错误路径及管理员工具暴露拒绝。安装了锁定 DSH SDK 的本机测试真实启动运行时，观察到 MCP `tools/list` 请求，无付费模型调用；新增 CI 作业以相同方式验证 Linux 启动。

完整隔离环境强制执行真实 HTTP/HTTPS 测试后 **293 passed，2 个可选 SDK 用例 skipped，覆盖率 90.79%**。另在安装 SDK 的环境中运行 MCP 启动用例 **1 passed**；Ruff、24/24 合成评测、四例 Git 合并试验、Git 示例、锁文件校验、0.23.0 wheel/source distribution 构建和隔离 wheel 导入通过。仍未验证真实模型生成、代码修改质量、跨成员自然人认证或实际费用；MCP 预检查与 DSH 启动验证不等于模型已成功使用工具完成任务。

## v0.24 DSH 审查工具收紧

日期：2026-09-29。语义审查不再通过默认持久 shell 读取临时 `context.json` 和 `artifact.diff`；任务上下文与真实 diff 作为标明不可信数据的 JSON 随请求提供。一次性 DSH 补丁禁用默认 bash/PowerShell 工具，将文件策略设为 `read-only`。已安装 SDK 的有效配置输出确认两个 shell 行均禁用，真实 SDK 以该配置无模型启动；成员 MCP 启动用例也再次通过。此举不限制 Harness 进程权限、provider 数据传输或专用 DSH home 中可能存在的自定义工具插件。

完整隔离环境强制执行真实 HTTP/HTTPS 测试后 **293 passed，3 个可选 SDK 用例 skipped，覆盖率 90.80%**；安装 SDK 的两个无模型启动用例另 **2 passed**。Ruff 检查与格式检查、24/24 合成评测、四例历史 Git 合并试验、Git 示例、锁文件检查、0.24.0 wheel/source distribution 构建及隔离 wheel 导入通过。未进行真实模型调用，费用和审查质量仍未验证。

## v0.25 成员专用 Streamable HTTP MCP

日期：2026-09-29。`serve --mcp-http --auth-file` 显式装载官方 MCP SDK 的无状态 HTTP 端点 `/mcp`。现有私有令牌文件逐请求认证，只允许成员角色；成员身份和 author 由令牌绑定，管理员工具根本不出现在工具列表。ASGI 测试覆盖无令牌/错误角色、冒名请求拒绝、审计提交中的 principal/role、令牌原子轮换与凭据权限失效关闭、未列入允许名单的 Host 拒绝，以及独立元数据分支写入不改变代码 HEAD。真实 Uvicorn 进程和官方 MCP 客户端完成 HTTP 握手、工具调用、两个成员并发写入及轮换；受信任的自签证书下，同一客户端完成 HTTPS 调用并留下成员审计记录。测试客户端和令牌由本机进程模拟，尚未证明不同自然人或公网部署。

完整隔离环境强制执行真实 HTTP/HTTPS 测试后 **297 passed，3 个可选 SDK 用例 skipped，覆盖率 90.86%**；全套启动之后补充的并发 HTTP MCP 调用在定向回归中通过，最终 Linux CI 对提交状态重新执行全套。Ruff 检查与格式检查、24/24 合成评测、四例历史 Git 合并试验、Git 示例、锁文件检查、0.25.0 wheel/source distribution 构建及隔离 wheel 导入通过。静态 bearer 凭据不是 OAuth，远程访问需自行配置可信 TLS、准确的 Host 名单和仓库 OS 权限。

## v0.27 独立容器网络的成员 MCP 演练

日期：2026-09-29。Compose 的 HTTPS 内联和独立元数据分支模式分别启动第二个 Docker 客户端容器，只挂载公开测试证书与探针脚本，不挂载协调仓库或服务端令牌摘要文件。客户端通过 Compose DNS 名 `conductor`、证书 SAN 与显式允许的 `conductor:8000` Host，使用官方 MCP SDK 和成员 bearer 令牌创建意图；验证成员工具范围、服务端审计归属、独立分支代码 HEAD 不变及重启后可读。此试验已在本机 Docker Desktop 通过；它验证了分离的网络命名空间和文件挂载，**不等于公网或不同自然人的共享部署**。

## v0.28 前瞻意图冲突评测流程

日期：2026-09-29。新增 `scripts/evaluate_prospective.py`，从两份事前意图冻结检测规则、证据、数据文件 SHA-256 和源码摘要；输出采用只创建不覆盖方式。之后可把两份彼此独立的审阅文件与可选第三方裁决文件汇总，拒绝数据或预测哈希不符、自我标注、重复审阅者、非法时间与非事前状态。缺失或分歧未裁决的标签保持 `incomplete`，不计为负例；无正例或无预警时对应召回率或精确率为 `null`。工具只评估意图对，不涵盖决策及任务规则。采样、数据私密性、证据冻结和人工标签流程见 [前瞻评测说明](../evals/PROSPECTIVE_STUDY.md)。

合成测试分别验证 TP/FP/FN/TN、分歧裁决、缺失标签、哈希篡改和无效事前意图；**没有真实项目的人类标签输入，也没有真实检测率结果**。本机基础完整套件 **303 passed，6 个环境/可选 SDK 用例 skipped，覆盖率 91.02%**；Ruff、锁文件检查、24/24 合成规则评测、四例历史合并回放、示例、0.28.0 wheel/source distribution 构建及隔离 wheel 导入通过。真实 HTTP/HTTPS 用例由 Linux CI 强制运行。

## v0.29 DSH 审查失败尝试的私有日志

日期：2026-09-29。`review --attempt-log` 可选地把通过前置任务与 diff 校验后、在 DSH 调用或审查结果入账阶段失败的尝试追加到仓库外 JSONL。记录任务、模型/provider、观察到的 Backbone 版本和制品 SHA、失败阶段、总耗时及错误类型；不记录提示词、diff 或原始 provider 错误。目录必须为当前用户所有且不对组和其他用户开放，文件需为 owner-only 普通文件，拒绝符号链接、硬链接及仓库/Git 目录内路径。失败不生成语义审查结论或 Git 审计提交；成功审查仍按原逻辑存入 Git。该日志不能捕获进程崩溃或前置校验失败，也不测实际模型成本。

定向测试覆盖运行时失败连续追加、脱敏、Git 状态不变、过期结果的入账阶段失败，以及不安全路径拒绝。基础完整套件 **307 passed，6 个环境/可选 SDK 用例 skipped，覆盖率 91.02%**；Ruff、锁文件检查、24/24 合成规则评测、四例历史合并回放、示例、0.29.0 wheel/source distribution 构建及隔离 wheel 导入通过。仍未执行付费模型调用或真实多人部署。

## v0.30 无本地协调仓库的 DSH 成员入口

日期：2026-09-29。`backbone dsh` 新增 `--mcp-url`、`--mcp-token-file` 与可选 `--mcp-ca-file`，可从独立工作树连接已认证的远程 `/mcp`，无需本地协调仓库。非回环地址要求 HTTPS；成员 bearer token 从当前用户持有的 0600 单硬链接文件读取，不能放在工作树或 DSH home；远程 DSH home 需为当前用户持有的 0700 目录。调用模型前，官方 Python MCP 客户端用同一令牌核对精确成员工具列表和 `get_my_task` 的成员绑定。DSH 客户端插件使用 `streamable-http`，本回合含 bearer header 的 0600 临时补丁运行后删除。会话命名空间绑定远程 URL 与成员。

本机真实回环 HTTP 测试验证正确成员、错误成员拒绝、Python MCP 工具发现与正式 DSH SDK 无模型启动；自签 HTTPS 测试验证自定义 CA、真实 MCP 握手与正式 SDK 无模型启动。远程 DSH 工具调用尚未通过 SDK 的无模型接口证实，真实付费模型回合和不同自然人的部署仍未执行。基础完整套件 **315 passed，2 个仅在 DSH 强制套件执行的用例 skipped，覆盖率 90.85%**；Ruff、锁文件检查、24/24 合成规则评测、四例历史 Git 合并回放、示例、0.30.0 wheel/source distribution 构建及 wheel 导入通过。

## v0.31 独立代码克隆的远程成员流程

日期：2026-09-29。新增端到端回归：一个裸 Git 远端、协调端代码克隆、成员代码克隆和真实本机 `/mcp` 服务。管理员创建意图、独立审查者接受并分派；成员通过 MCP 读取/开始任务，在自己的克隆提交并推送功能分支。协调端尚未 `git fetch` 时，MCP 产物提交被拒绝且 HEAD 不变；获取分支后，服务从 Git 解析提交 SHA 与真实修改路径，产物检查通过。审查者在代码合并前的 HTTP 完成记录被拒绝；实际 Git 合并后，审查者记录完成，意图和任务转入终态，HTTP principal 留在 Git 审计提交，目标分支可继续推送。测试使用独立仓库与令牌，但由同一测试进程模拟参与者，不能当作不同自然人部署验证。

完整本机套件在强制执行真实 HTTP/HTTPS 用例下 **316 passed，2 个 DSH 专项用例 skipped，覆盖率 90.86%**；Ruff、锁文件检查、24/24 合成规则评测、四例历史 Git 合并回放、示例、0.31.0 source distribution/wheel 构建及 wheel 导入通过。代码分支的获取是管理员显式 Git 操作，不由 MCP 传输；详见 [独立代码克隆流程](OPERATIONS.md#独立代码克隆的提交与合并)。真实多人使用、外部网络质量和前瞻人工标注仍需独立验证。

## v0.32 成员自助获取已推送代码分支

日期：2026-09-29。成员可通过 MCP `fetch_artifact_branch`、HTTP `POST /tasks/{task_id}/fetch` 或 CLI `task fetch` 请求协调端从已配置 Git remote 获取自己任务的功能分支。请求必须给出完整小写提交 SHA；获取先写入临时引用，核对远端 tip，再只允许快进远端跟踪引用。Git 默认 refmap 会在验证前隐式更新跟踪引用，因此实现显式使用空 `--refmap=`；端到端测试验证错误 SHA、正常快进、强推改写和身份冒用分别被拒绝或正确处理。`submit_artifact` 若携带 `commit_sha`，则必须与 Git 实际解析的提交一致；真实路径和检查仍由协调端计算。获取操作不切换 HEAD，也不产生元数据审计提交。

强制执行真实 HTTP/HTTPS 的完整本机套件 **316 passed，2 个 DSH 专项用例 skipped，覆盖率 89.71%**；增加正常快进用例后另单独重跑该跨克隆测试 **1 passed**。Ruff 检查与格式检查、锁文件检查、24/24 合成规则评测、四例历史 Git 合并回放、示例、0.32.0 source distribution/wheel 构建及 wheel 导入通过。Compose 的 HTTP/HTTPS、独立元数据分支与隔离网络成员 MCP 验证亦通过，两个部署检查器已更新为八工具契约。上述多人角色仍由同一测试进程模拟；真实不同自然人、公网部署和前瞻人工标签尚未验证。

## v0.33 从 Git 与 Backbone 快照采集前瞻评测案例

日期：2026-09-29。`evaluate_prospective.py capture` 从干净代码工作树与当前 Backbone 快照生成未分派、无任务历史、不同作者的所有意图配对；使用真实代码 HEAD 作为共同基线，并立即运行现有预测冻结。输出要求仓库外绝对路径，采用不覆盖的私有文件创建。新增测试验证真实 Git 基线、三意图的完整配对、预测结果、已取消任务历史的排除、脏工作树/仓库内输出拒绝，以及独立元数据分支使用代码而非账本 HEAD。手工采样计划、外部时间戳与事后独立人工标签仍必需；自动采集不构成真实检测率数据。

强制执行真实 HTTP/HTTPS 的本机完整套件 **320 passed，2 个 DSH 专项用例 skipped，覆盖率 89.71%**；Ruff、锁文件检查、24/24 合成规则评测、四例历史 Git 合并回放、示例、0.33.0 source distribution/wheel 构建及 wheel 导入通过。

## v0.34 固定提交的只读任务审查包

日期：2026-09-29。已提交任务可经审查者/管理员 HTTP `GET /tasks/{id}/inspection`、管理员 MCP `inspect_task` 或本地 CLI `task inspect` 获取审查包。包包含实际 Git 补丁预览及完整补丁 SHA-256、提交时固定的 base/artifact SHA、当前功能分支和目标分支 SHA、分支变动及是否已集成状态，以及意图、当前接受的决策、分派时决策 ID、决策变化和阻塞冲突。任务未成功提交时拒绝；功能分支在提交后变化时，仍展示原固定提交的补丁并指出引用已变化。接口不写入 Backbone 状态，不声称语义审查通过。HTTP 成员令牌无权读取；超过 128 KiB 的补丁标记截断，超过 1 MB 的差异要求拆分任务。

强制执行真实 HTTP/HTTPS 的本机完整套件 **324 passed，2 个 DSH 专项用例 skipped，覆盖率 89.69%**；新增回归验证未提交拒绝、固定补丁与哈希、只读性、分支漂移、截断与大小上限、HTTP 角色隔离及 CLI 入口。Ruff、锁文件检查、24/24 合成规则评测、四例历史 Git 合并回放、示例、0.34.0 source distribution/wheel 构建及 wheel 导入通过。人工代码与语义审阅、实际 Git 合并仍是完成任务的必要步骤；不同自然人使用该审查包尚未验证。

## v0.35 合并内容净效应与恢复

日期：2026-09-29。完成任务时除检查固定产物提交在目标分支祖先中，还比较产物声明的代码路径与提交时基线及最终目标树。若所有路径的净改动均消失，拒绝完成；如果最终路径内容与原产物不同，则要求审查者提供复核理由。人工审查决策保存产物 SHA、目标 SHA、净改动路径和差异路径。取消或刷新任务改用同一净效应检查，避免 `git merge -s ours` 或事后真实回退只因保留祖先关系而将任务卡住。测试覆盖空内容合并拒绝、取消/刷新恢复、正常合并后真实回退、同路径改写需理由与审计锚点。非空同路径改写仍须人工判断是否保留原意图；此确定性检查不声称能证明复杂语义集成。

强制执行真实 HTTP/HTTPS 的本机完整套件 **328 passed，2 个 DSH 专项用例 skipped，覆盖率 89.70%**；Ruff、锁文件检查、24/24 合成规则评测、四例历史 Git 合并回放、示例、0.35.0 source distribution/wheel 构建及 wheel 导入通过。

## v0.36 两个远程成员克隆并发提交

日期：2026-09-29。新增端到端回归：一次性裸 Git 远端、协调端代码克隆和真实 HTTP/MCP 服务为两个成员分派互不重叠的任务；两个独立成员克隆由不同 OS 进程并发提交代码、推送各自功能分支，以固定 SHA 请求协调端获取远端分支并提交产物。测试核对成员只能读取自己的任务、独立远端引用与产物 SHA、审查者只读补丁、Git 合并后两个任务和意图分别完成、审计 principal 与令牌不泄漏，最后把合并结果推回裸远端。成员和审查者仍由测试进程模拟，未验证不同自然人的使用体验、远程网络或公网部署。

强制执行真实 HTTP/HTTPS 的本机完整套件 **329 passed，2 个 DSH 专项用例 skipped，覆盖率 89.70%**。Ruff 检查与格式检查、锁文件检查、24/24 合成规则评测、四例历史 Git 合并回放、示例和 0.36.0 source distribution/wheel 构建通过。

## v0.37 无协调仓库的远程审查 CLI

日期：2026-09-29。HTTP 增加需要同样 bearer 认证的 `/whoami`，返回当前 principal 与角色。新增 `backbone reviewer`：只接受审查者令牌，可从无 Git 仓库的目录读取状态、意图、任务和固定提交审查包；以服务端确认的身份和明确理由审阅草稿意图，或在实际 Git 合并后记录任务审批。客户端拒绝非回环明文 HTTP，只读取当前用户持有的 0600 单链接普通令牌文件，可使用自有 CA 验证 HTTPS。真实本机服务回归覆盖独立目录/进程调用、成员令牌拒绝、合并前审批拒绝、完整双成员流程；真实自签 HTTPS 回归覆盖受信任 CA 的审查者调用。不同自然人的远程试用仍未执行。

强制执行真实 HTTP/HTTPS 的本机完整套件 **331 passed，2 个 DSH 专项用例 skipped，覆盖率 89.39%**；Ruff 检查与格式检查、锁文件检查、24/24 合成规则评测、四例历史 Git 合并回放、示例和 0.37.0 source distribution/wheel 构建通过。

## v0.38 完成审批绑定审查观察值

日期：2026-09-29。任务完成操作现在必须携带**实际 Git 合并后**审查包返回的 `version` 和 `git.target_sha`，分别核对当前 Backbone 状态与目标代码分支 SHA；缺失、过期或变动则拒绝，不写完成记录。HTTP、远程审查 CLI、本地 CLI 与管理员 MCP 均要求这两个值；审计理由保存观察版本和最终目标 SHA。新增回归分别在审查后移动目标代码分支、写入新的协调状态，验证过期审批拒绝、任务仍为 submitted、重新审查后可以完成。真实两成员 HTTP/MCP 流程还验证了远程审查 CLI 的过期审批拒绝。观察值校验不证明审查者实际阅读或理解了代码；独立元数据分支与外部 Git 写入之间仍无跨引用原子事务，审批时应暂停对协调代码 checkout 的其他写入。

强制执行真实 HTTP/HTTPS 的本机完整套件 **333 passed，2 个 DSH 专项用例 skipped，覆盖率 89.40%**；Ruff、锁文件检查、24/24 合成规则评测、四例历史 Git 合并回放、示例和 0.38.0 source distribution/wheel 构建通过。

## v0.39 单个 HTTP principal 的凭据生命周期

日期：2026-09-29。新增 `auth add`、`auth rotate-one` 和 `auth revoke`：分别签发新 principal、仅轮换指定 principal 的令牌、只撤销指定 principal；保留其他人的摘要、身份和角色，拒绝重复添加、未知目标和撤销最后一个管理员。保留原有 `auth rotate` 的全员重发语义。所有已有凭据文件的更改先经跨进程私有锁序列化，再写入并验证临时 0600 摘要文件，最后原子替换。真实运行中的 HTTP 服务验证新增和撤销即时生效、其他令牌持续有效；MCP 测试验证单人轮换后旧成员令牌失效而其他成员仍可访问；双独立进程同时轮换不同成员时两次更新均保留。凭据文件不含明文令牌，新令牌只在创建/轮换命令结果中显示一次。静态 bearer 令牌不能证明不同自然人的身份，真实远程部署仍待验收。

强制执行真实 HTTP/HTTPS 的本机完整套件 **338 passed，2 个 DSH 专项用例 skipped，覆盖率 89.50%**；Ruff 检查与格式检查、锁文件检查、24/24 合成规则评测、四例历史 Git 合并回放、示例和 0.39.0 source distribution/wheel 构建通过。

## v0.40 私有 DSH 审查尝试统计

日期：2026-09-29。可选私有 `--attempt-log` 现在记录 DSH 审查失败与 Git 审计已提交两种结果；后者严格在提交完成后写入。新增只读 `review-stats`，汇总记录内已提交数、失败阶段、提交比例和总耗时中位数。日志继续排除提示词、代码 diff、令牌和 provider 原始错误。旧版仅记录失败的日志会标出旧记录并隐藏不完整的提交比例。成功审查若已写入 Git 而私有日志写入失败，命令明确要求核对 ledger 后再重试。锁定 SDK 的 `RunResult` 未提供稳定 token/费用字段，因此统计返回不可用值；真实在线质量、成本和故障恢复仍需凭据及人工验证。

本机完整套件 **337 passed、8 skipped，覆盖率 87.69%**；其中 6 个因默认沙箱禁止监听端口而跳过的真实 HTTP/HTTPS 用例，另在允许本机监听的环境中单独执行对应套件 **10 passed**。其余 2 个为要求 DSH 启动配置的专项用例，CI 负责运行。Ruff 检查与格式检查、锁文件检查、24/24 合成规则评测、四例历史 Git 合并回放、示例和 0.40.0 source distribution/wheel 构建通过；构建出的 wheel 已从仓库外导入并识别 `review-stats` 命令。

## v0.41 受限 DSH 协调代理

日期：2026-09-29。新增 `backbone conductor` 与专用 `mcp --coordinator` 工具范围。模型可读取协调状态、以固定 `conductor-agent` 作者提出草稿意图和建议决策、检测确定性冲突、分派预先 accepted 的意图并读取固定提交审查包；不能通过该 MCP 接口接受意图/决策、裁决冲突、执行合并审批或同步远端。运行器要求仓库外、当前用户持有的 0700 DSH home；一次性补丁设置只读文件策略、禁用持久 shell 并装载正式 MCP 客户端。运行前独立 MCP 握手核对精确工具列表和状态读取，权限扩大时拒绝启动。测试验证草稿不可直接分派、外部人类审查接受后可分派、冒用人类作者被拒绝、SDK 资源清理及临时补丁删除；正式 SDK 的有效配置和无模型启动已在本机验证。尚未发起付费模型请求或让真实人类协作。

项目所有者选定 MIT 后，加入标准 `LICENSE`、README 入口及 PEP 639 包元数据。0.41.0 wheel 已核对 `License-Expression: MIT`、内含许可证文件且包内 `__version__` 与发行版本一致；尚未上传 PyPI。

本机完整套件 **342 passed、9 skipped，覆盖率 87.60%**；其中 6 个是默认沙箱不可监听端口的 HTTP/HTTPS 用例，已在允许本机监听的环境中单独执行对应套件 **10 passed**；3 个 DSH 无模型启动用例显式启用后 **3 passed**。Ruff 检查与格式检查、离线锁文件检查、24/24 合成规则评测、四例历史 Git 合并回放、十客户端 MCP 并发基准完整性、示例和 0.41.0 source distribution/wheel 构建通过。

## v0.42 发布前校验与手动工作流

日期：2026-09-29。新增默认只构建的手动 Release 工作流；正式上传只允许与包版本相同的 Git 标签，并由 `pypi` 环境保护后通过 Trusted Publisher OIDC 执行。发行包检查脚本核对源码版本、wheel 和 sdist 的精确文件集合、MIT SPDX 元数据、许可证内容及源码一致性；错误版本标签会拒绝。按照 Python Packaging 对 PEP 639 的说明，移除旧 `License ::` 分类项，只保留 `License-Expression: MIT`。PyPI 环境和 Trusted Publisher 尚未配置，未上传或测试真实发布。

本机完整套件 **342 passed、9 skipped，覆盖率 87.60%**；其中 6 个真实 HTTP/HTTPS 用例因沙箱禁止 loopback socket 跳过，3 个 DSH 无模型启动用例需专项启用。Ruff、离线锁文件检查、24/24 合成评测、四例历史 Git 合并回放、十客户端 MCP 并发完整性、示例通过；隔离输出目录的 0.42.0 wheel 和 sdist 构建及归档校验通过。推送提交 `c3f1a92` 后，GitHub [CI](https://github.com/BruceXcluding/backbone-conductor/actions/runs/36512391836) 四项作业通过，[Release dry-run](https://github.com/BruceXcluding/backbone-conductor/actions/runs/36512428823) 构建成功，`publish` 作业跳过；下载的 GitHub 发行包经本地归档脚本校验，并从 wheel 独立安装导入 0.42.0 成功。

## v0.43 私有 DSH home 约束

日期：2026-09-29。本地成员 DSH 入口和语义审查入口现在创建或验证仅当前用户可访问的 0700 home，拒绝最终路径为符号链接、其他用户所有或组/其他用户可访问的目录；本地成员还要求 home 位于协调仓库与代码工作区之外。此前远程成员和受限协调代理已有同类 home 检查。测试覆盖宽松权限、符号链接及正常私有目录，无需调用付费模型。已安装 DSH SDK 的审查、成员和协调入口无模型启动专项测试 **3 passed**。

本机完整套件 **344 passed、9 skipped，覆盖率 87.67%**；6 个真实 HTTP/HTTPS 用例因沙箱端口限制跳过，3 个 DSH 无模型启动用例已单独强制执行。Ruff、离线锁文件检查、24/24 合成评测、四例历史 Git 合并回放、十客户端 MCP 并发完整性、示例与 0.43.0 wheel/sdist 构建及归档校验通过。真实模型调用与不同自然人的使用验证仍未进行。
