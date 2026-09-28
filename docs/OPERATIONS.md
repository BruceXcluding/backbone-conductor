# 部署与恢复

先初始化代码仓库、配置 Git identity，再运行 `backbone --repo /repo init`。Git identity 为提交身份；本地 CLI/MCP 的领域 author 由调用方声明。启用 HTTP 认证后，HTTP 请求的 author 和 member_id 与令牌 principal 绑定。

HTTP 默认 127.0.0.1:8000，`/docs` 为交互 API、`/health` 检查进程、`/state` 验证快照读取。无认证时拒绝非 loopback 绑定。MCP 是客户端管理的 stdio 子进程，目前无远程 MCP HTTP 入口。

## HTTP 令牌

在目标仓库之外创建仅当前用户可读的凭据文件：

```sh
backbone --repo /repo auth create \
  --file /private/path/backbone-http-tokens.json --admin owner \
  --member alice --member bob
backbone --repo /repo serve \
  --auth-file /private/path/backbone-http-tokens.json
```

创建命令仅输出一次明文令牌，不把它们写入凭据文件；文件权限为 0600，内容是 SHA-256 摘要与 principal/role 映射。妥善保存明文令牌，避免录入 shell 历史、应用日志或 Git。令牌持有者使用 `Authorization: Bearer TOKEN`。`/health` 无需令牌；其他路径均需令牌，成员对未列入成员接口的路径默认被拒绝。管理员可以使用全部端点；成员只能创建自己的草稿意图和提议决策、读取自己的任务和更新、执行自己的任务开始/上下文刷新/产物提交。

轮换时运行 `backbone --repo /repo auth rotate --file /private/path/backbone-http-tokens.json --admin owner --member alice`，保存命令输出的一次性新令牌并分发给对应用户。它先验证原文件，再原子替换为新的 0600 摘要文件；替换后的请求会拒绝旧令牌，未列出的成员也失去访问权。运行中的 HTTP 服务逐请求读取当前文件，无需重启；若文件缺失、权限不安全或内容损坏，受保护请求和 `/health` 返回 503，不会继续接受缓存的旧令牌。直接提供 HTTP 仍是明文传输，远程访问需在可信反向代理处终止 TLS，并限制后端端口只接受代理流量。Git 仓库写权限仍需在操作系统层隔离；HTTP 角色不限制拥有仓库文件权限的本机用户。

## Docker Compose

```sh
export BACKBONE_REPO=/absolute/path/to/git-repo
export BACKBONE_AUTH_FILE=/private/path/backbone-http-tokens.json
docker compose build
docker compose run --rm conductor --repo /workspace init
docker compose up -d
```

先用上述命令生成 `BACKBONE_AUTH_FILE`，再启动 Compose。端口绑定宿主 loopback，容器内也强制启用令牌认证。容器会写入挂载仓库，适合专用协调 checkout；仓库本地 Git identity 优先于镜像默认值。按宿主权限配置非 root UID 后用于长期运行，需确保该 UID 能读取私有令牌文件。容器不自动配置 Git 远端凭据。

本次 Docker 验证在基础镜像拉取阶段被镜像代理 401 和 Docker Hub 网络超时阻断，容器启动尚未验证。Dockerfile 的 PYTHON_IMAGE 构建参数可显式选择可访问的同等 Python 3.12 基础镜像，无需修改 daemon 全局配置。

## 独立元数据分支

新仓库至少要有一个代码提交，且不能已经有内联 `.backbone/state.json`。执行 `backbone --repo /repo ledger create` 后，元数据保存在 Git 管理目录的隐藏 `backbone-ledger` worktree 中，当前代码工作树不切分支。所有协调命令都要显式使用 `--ledger-branch backbone`；例如 `backbone --repo /repo --ledger-branch backbone sync` 只推送元数据分支。其他克隆在已有远端 `backbone` 分支时运行 `backbone --repo /clone ledger attach`。成员提交的代码分支必须可被协调端的代码工作树解析；代码推送仍走 Git 常规流程。

现有内联仓库可在协作者暂停写入时运行 `backbone --repo /repo ledger migrate`。迁移要求当前代码分支有提交、工作树和索引干净、所有任务已完成或取消，且不存在本地或远端跟踪的 `backbone` 分支。它创建以旧代码 HEAD 为父提交的元数据专用分支，再在代码分支提交删除旧 `.backbone/`；旧审计提交仍在新分支祖先中。迁移成功后使用 `--ledger-branch backbone`，分别推送代码分支及元数据分支，再让其他克隆拉取代码并 `ledger attach`。若提交已经完成但 worktree 附加失败，运行 `ledger attach` 修复；不要重新迁移或强推历史。迁移不会自动推送。

隐藏 worktree 的 `.git` 指针与本机绝对路径绑定。当前 Compose 把宿主仓库挂载到不同容器路径，**不能直接复用宿主创建的隐藏 worktree**；Compose 默认继续采用内联模式。若要在容器部署独立模式，需在容器内使用固定持久路径创建或附加 worktree，并单独验证，不要仅加 `--ledger-branch` 标志。`ledger create` 不会自动迁移现有内联审计历史。

## 审计与恢复

- `backbone log` / `git log -- .backbone` 查看历史。已认证 HTTP 写入会在提交中留下 `Backbone-HTTP-Principal` 与 `Backbone-HTTP-Role` trailer，`backbone log` 返回 `http_principal` / `http_role`；未认证本地调用没有这些字段。它们记录服务端已验证的 bearer principal，不是 Git 签名，也无法阻止拥有仓库写权限的人伪造提交；Git author 仍由仓库配置决定。
- `backbone decision transition DECISION_ID reverted` 撤销接受过的决策并重算冲突。
- 整体回退需先停服务和备份，查看差异后 `git revert <metadata-commit>`；再确认 backbone status。首选领域命令，整提交回退可能改变多个对象。
- state.json 是权威快照，其他文件是生成视图。未提交的手工修改会被拒绝；修复时先停服务、检查并提交一致快照。
- `sync` 仅 push；`refresh` 显式 fetch。若本地落后、同名分支且工作树/索引干净，`refresh` 会快进并验证新快照；本地领先则不变更。双方分叉时返回共同祖先、两侧对象与路径差异及重叠项，不改写历史。维护者审查两个 HEAD 后，对仅元数据的分叉可执行 `backbone reconcile --local-head ... --remote-head ... --author ... --rationale ...`。同一对象两侧变化时，先从 `requires_review` 响应取得对象 ID，审阅两侧快照，再在命令中增加 `--resolutions-file`：每个竞争对象须选 `{"source":"local"}`、`{"source":"remote"}` 或提供 `{"value":{...完整对象...}}`。接口会拒绝遗漏或多余决议，校验合并状态，生成双父提交并重算冲突，随后显式 `sync` 推送；SHA 已变化、代码路径改动或跨对象生命周期不一致时拒绝合并。代码路径变化需走常规 Git 人工合并，不得强推审计历史。
- 成员分支不得改写 `.backbone/`。内联模式在目标分支协调；独立模式在 `backbone` 分支协调，代码操作仍针对源工作树。
- 锁被占用时先确认活跃 Git/协调进程，不盲目删除锁。

已验证 macOS/Linux 风格工作树与 linked worktree。Windows、网络文件系统和突然断电恢复未专门验证。进程内异常可回滚；异常断电后的差异需借助 Git 历史人工恢复。
