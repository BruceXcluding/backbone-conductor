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

创建命令仅输出一次明文令牌，不把它们写入凭据文件；文件权限为 0600，内容是 SHA-256 摘要与 principal/role 映射。妥善保存明文令牌，避免录入 shell 历史、应用日志或 Git。令牌持有者使用 `Authorization: Bearer TOKEN`。`/health` 无需令牌；其他路径均需令牌，成员对未列入成员接口的路径默认被拒绝。管理员可以使用全部端点；成员只能创建自己的草稿意图和提议决策、读取自己的任务和更新、执行自己的任务开始/上下文刷新/产物提交。角色与令牌在进程启动时读取；轮换或撤销令牌须更换文件并重启进程。直接提供 HTTP 仍是明文传输，远程访问需在可信反向代理处终止 TLS，并限制后端端口只接受代理流量。Git 仓库写权限仍需在操作系统层隔离；HTTP 角色不限制拥有仓库文件权限的本机用户。

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

## 审计与恢复

- `backbone log` / `git log -- .backbone` 查看历史。
- `backbone decision transition DECISION_ID reverted` 撤销接受过的决策并重算冲突。
- 整体回退需先停服务和备份，查看差异后 `git revert <metadata-commit>`；再确认 backbone status。首选领域命令，整提交回退可能改变多个对象。
- state.json 是权威快照，其他文件是生成视图。未提交的手工修改会被拒绝；修复时先停服务、检查并提交一致快照。
- `sync` 仅 push；`refresh` 显式 fetch。若本地落后、同名分支且工作树/索引干净，`refresh` 会快进并验证新快照；本地领先则不变更。双方分叉时返回共同祖先、两侧对象与路径差异及重叠项，不改写历史。维护者审查两个 HEAD 后，对仅元数据、没有竞争对象的分叉可执行 `backbone reconcile --local-head ... --remote-head ... --author ... --rationale ...`。该命令生成双父合并提交、重算冲突，随后显式 `sync` 推送；SHA 已变化、代码路径改动、同一对象竞争修改或跨对象生命周期不一致时拒绝自动合并。代码与竞争元数据需人工处理，不得强推审计历史。
- 成员分支不得改写 `.backbone/`。协调操作集中在目标分支；独立 Backbone 分支尚未实现。
- 锁被占用时先确认活跃 Git/协调进程，不盲目删除锁。

已验证 macOS/Linux 风格工作树与 linked worktree。Windows、网络文件系统和突然断电恢复未专门验证。进程内异常可回滚；异常断电后的差异需借助 Git 历史人工恢复。
