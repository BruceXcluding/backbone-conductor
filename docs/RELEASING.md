# 发布流程

仓库的 `Release` GitHub Actions 工作流只支持手动启动，默认 `dry_run=true`，仅执行检查、构建并保存发行包，不上传。

## 一次性配置

1. 在 GitHub 仓库创建名为 `pypi` 的 Environment，设置 required reviewers，限制允许部署的标签为 `v*`。此环境是正式上传前的人类确认关口。
2. 在 PyPI 为 `backbone-conductor` 配置 [Trusted Publisher](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)：GitHub owner `BruceXcluding`，repository `backbone-conductor`，workflow `release.yml`，environment `pypi`。若项目仍不存在，可用 pending publisher 创建；项目名称直到首次上传才真正占用。无需在 GitHub 保存 PyPI API token。
3. 核对 PyPI 项目所有权、目标仓库和上述四个字段。PyPI 发行版本不可覆盖，正式上传前请检查版本号与发行包。

## 每次发布

1. 更新 `pyproject.toml` 和 `src/backbone_conductor/__init__.py` 的相同版本号，记录变更，保持 `uv.lock` 同步；同时更新 README 中的安装版本及指向该标签的文档链接。发布脚本目前只接受 `X.Y.Z` 正式版本。
2. 等待目标提交的 CI 全部通过，并在干净的工作树中运行 `uv build --out-dir /tmp/backbone-release`、`uv run python scripts/check_release.py --dist /tmp/backbone-release`。脚本要求指定目录恰好有当前版本的 wheel 与 sdist，检查内容、许可证和元数据。
3. 在 GitHub Actions 的 `Release` 工作流中，对目标提交运行 `dry_run=true`。检查保存的两个发行包。
4. 经确认后，为**同一提交**创建并推送 `vX.Y.Z` 标签。对该标签运行 `Release`，设置 `dry_run=false`。构建作业会重新运行测试并校验标签、发行包；`publish` 作业等待 `pypi` 环境审查，然后用 OIDC 将构建产物上传 PyPI。
5. 上传后核对 PyPI 版本页面及全新环境中的 `pip install backbone-conductor==X.Y.Z` 和 `backbone --help`，并确认 README 的安装说明与当前版本一致。

发布工作流的 `id-token: write` 权限只赋予上传作业。分支上的正式发布请求会失败；只有与源码版本匹配的标签可进入上传。Trusted Publisher 与 GitHub Environment 必须先配置，否则上传作业不会成功。
