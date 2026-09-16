# 部署与恢复

先初始化代码仓库、配置 Git identity，再运行 `backbone --repo /repo init`。Git identity 为提交身份；领域 author 是调用方声明的业务身份。

HTTP 默认 127.0.0.1:8000，`/docs` 为交互 API、`/health` 检查进程、`/state` 验证快照读取。MCP 是客户端管理的 stdio 子进程，首版无远程 MCP HTTP 入口。

## Docker Compose

```sh
export BACKBONE_REPO=/absolute/path/to/git-repo
docker compose build
docker compose run --rm conductor --repo /workspace init
docker compose up -d
```

端口绑定主机 loopback。容器会写入挂载仓库，适合专用协调 checkout；仓库本地 Git identity 优先于镜像默认值。按宿主权限配置非 root UID 后用于长期运行；不要把公网流量直接送到无认证管理员 API。容器不自动配置远端凭据。

本次 Docker 验证在基础镜像拉取阶段被镜像代理 401 和 Docker Hub 网络超时阻断，容器启动尚未验证。Dockerfile 的 PYTHON_IMAGE 构建参数可显式选择可访问的同等 Python 3.12 基础镜像，无需修改 daemon 全局配置。

## 审计与恢复

- `backbone log` / `git log -- .backbone` 查看历史。
- `backbone decision transition DECISION_ID reverted` 撤销接受过的决策并重算冲突。
- 整体回退需先停服务和备份，查看差异后 `git revert <metadata-commit>`；再确认 backbone status。首选领域命令，整提交回退可能改变多个对象。
- state.json 是权威快照，其他文件是生成视图。未提交的手工修改会被拒绝；修复时先停服务、检查并提交一致快照。
- sync 仅 push，不自动解决分歧；non-fast-forward 时由维护者获取并检查合并，不强推审计历史。
- 成员分支不得改写 `.backbone/`。协调操作集中在目标分支；跨克隆元数据自动合并尚未实现。
- 锁被占用时先确认活跃 Git/协调进程，不盲目删除锁。

已验证 macOS/Linux 风格工作树与 linked worktree。Windows、网络文件系统和突然断电恢复未专门验证。进程内异常可回滚；异常断电后的差异需借助 Git 历史人工恢复。
