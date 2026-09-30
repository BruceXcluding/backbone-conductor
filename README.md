# Backbone Conductor

[简体中文](README.zh-CN.md)

Backbone Conductor coordinates coding agents around shared intentions, decisions, and Git evidence. It records attributed proposals and reviews, detects conflicts in declared symbols and paths, and keeps an auditable history alongside the code.

The core runs without a model. Agents can connect through MCP; maintainers can use the CLI or HTTP API. Optional DeepSeek Harness integration provides semantic advice, while people retain responsibility for resolving conflicts, reviewing code, and merging Git branches.

## What it does

- **Coordinate before coding.** Record intentions, constraints, affected symbols, decisions, and task assignments in a shared ledger.
- **Check actual work.** Compare a submitted artifact with its declared scope, current decisions, conflicting work, and a pinned Git commit.
- **Review before completion.** Inspect the submitted patch and the result on the target branch. Completion requires an actual Git merge and review against the observed ledger version and target commit.
- **Preserve an audit trail.** Store state and generated views in Git, with explicit synchronization, history verification, and optional commit signing. A separate metadata branch is available when coordination records should not appear on the code branch.

Conflict rules are deterministic and based on declared structure and Git paths; they do not establish semantic correctness. Model output is advisory and cannot approve or merge work.

## Try it locally

Requirements: Python 3.12+, Git, and [uv](https://docs.astral.sh/uv/). The package is currently installed from this repository.

```sh
git clone https://github.com/BruceXcluding/backbone-conductor.git
cd backbone-conductor
uv sync --locked --group dev
uv run python examples/demo.py
uv run python examples/two_agent_demo.py --mcp
```

Both examples create temporary Git repositories and leave this checkout unchanged. The second example uses two separate member-bound MCP clients to exercise conflicting intentions, artifact submission, review, and real Git merges. Its agent identities, code changes, and approvals are scripted demonstration data.

To coordinate an existing Git repository with an initial commit:

```sh
uv run backbone --repo /absolute/path/to/your-repo init
uv run backbone --repo /absolute/path/to/your-repo status
uv run backbone --repo /absolute/path/to/your-repo serve
```

The default HTTP service listens on `127.0.0.1:8000`; its interactive API is at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs). For a local agent, start the member-bound stdio server with `uv run backbone --repo /absolute/path/to/your-repo mcp --member alice`. See the [MCP interface](MCP_API.md) for tool scopes and the [deployment guide](docs/OPERATIONS.md) for authenticated remote access.

## Workflow

1. Create an intention before implementation and have a reviewer accept it.
2. Assign a task to a member. The member reads the shared context and starts work in a Git branch.
3. Submit the branch and exact commit as an artifact. Backbone checks scope, Git evidence, and blocking conflicts.
4. Review the pinned artifact, merge the code in Git, and inspect the resulting target branch.
5. Record approval using the ledger version and target commit from that inspection. Backbone rejects stale observations or code that was never integrated.

The [operations guide](docs/OPERATIONS.md) documents the CLI and remote member/reviewer flows. [Conflict rules](CONFLICT_RULES.md) explain what is checked automatically; [implementation details](docs/IMPLEMENTATION.md) describe storage, identity, and review boundaries.

## Documentation

| Topic | Guide |
| --- | --- |
| Architecture and capability boundaries | [Implementation](docs/IMPLEMENTATION.md) |
| Deployment, credentials, synchronization, and recovery | [Operations](docs/OPERATIONS.md) |
| Member and coordinator MCP tools | [MCP API](MCP_API.md) |
| Deterministic conflict checks | [Conflict rules](CONFLICT_RULES.md) |
| Optional DeepSeek Harness integration | [DSH integration](DSH_PLUGIN_PLAN.md) |
| Validation methods and evidence | [Validation](docs/VALIDATION.md) |
| Real-user pilot procedure | [Pilot](docs/PILOT.md) |
| Release procedure | [Releasing](docs/RELEASING.md) |

Additional research and historical design records are indexed in [docs/README.md](docs/README.md). The implementation and generated schemas are authoritative where older design notes differ.

## Contributing

Bug reports and proposals are welcome through [GitHub Issues](https://github.com/BruceXcluding/backbone-conductor/issues). See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, checks, and pull request guidance.

Licensed under [MIT](LICENSE).
