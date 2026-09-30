# Backbone Conductor

[简体中文](https://github.com/BruceXcluding/backbone-conductor/blob/v0.75.0/README.zh-CN.md)

Backbone Conductor coordinates coding agents around shared intentions, decisions, and Git evidence. It records attributed proposals and reviews, detects conflicts in declared symbols and paths, and keeps an auditable history alongside the code.

The core runs without a model. Agents can connect through MCP; maintainers can use the CLI or HTTP API. Optional DeepSeek Harness integration provides semantic advice, while people retain responsibility for resolving conflicts, reviewing code, and merging Git branches.

## What it does

- **Coordinate before coding.** Record intentions, constraints, affected symbols, decisions, and task assignments in a shared ledger.
- **Check actual work.** Compare a submitted artifact with its declared scope, current decisions, conflicting work, and a pinned Git commit.
- **Review before completion.** Inspect the submitted patch and the result on the target branch. Completion requires an actual Git merge and review against the observed ledger version and target commit.
- **Preserve an audit trail.** Store state and generated views in Git, with explicit synchronization, history verification, and optional commit signing. A separate metadata branch is available when coordination records should not appear on the code branch.

Conflict rules are deterministic and based on declared structure and Git paths; they do not establish semantic correctness. Model output is advisory and cannot approve or merge work.

## Try it locally

Requirements: Python 3.12+ and Git. Install the public preview from PyPI:

```sh
python -m pip install backbone-conductor==0.75.0
backbone --help
```

For development or to run the repository examples, also install [uv](https://docs.astral.sh/uv/) and use this checkout:

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

The default HTTP service listens on `127.0.0.1:8000`; its interactive API is at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs). For a local agent, start the member-bound stdio server with `uv run backbone --repo /absolute/path/to/your-repo mcp --member alice`. See the [MCP interface](https://github.com/BruceXcluding/backbone-conductor/blob/v0.75.0/MCP_API.md) for tool scopes and the [deployment guide](https://github.com/BruceXcluding/backbone-conductor/blob/v0.75.0/docs/OPERATIONS.md) for authenticated remote access.

Open [the decision map](http://127.0.0.1:8000/decision-map) to explore decisions as a lineage graph. Edges show which decision supersedes another; search and status filters narrow the view, and you can drag nodes and zoom the canvas. Selecting a node shows its rationale and linked evidence. The map is read-only: Git ledger data remains authoritative, while personal node positions stay in that browser. When HTTP authentication is enabled, enter an administrator or reviewer token in the page to load decisions.

## Workflow

1. Create an intention before implementation and have a reviewer accept it.
2. Assign a task to a member. The member reads the shared context and starts work in a Git branch.
3. Submit the branch and exact commit as an artifact. Backbone checks scope, Git evidence, and blocking conflicts.
4. Review the pinned artifact, merge the code in Git, and inspect the resulting target branch.
5. Record approval using the ledger version and target commit from that inspection. Backbone rejects stale observations or code that was never integrated.

The [operations guide](https://github.com/BruceXcluding/backbone-conductor/blob/v0.75.0/docs/OPERATIONS.md) documents the CLI and remote member/reviewer flows. [Conflict rules](https://github.com/BruceXcluding/backbone-conductor/blob/v0.75.0/CONFLICT_RULES.md) explain what is checked automatically; [implementation details](https://github.com/BruceXcluding/backbone-conductor/blob/v0.75.0/docs/IMPLEMENTATION.md) describe storage, identity, and review boundaries.

## Documentation

| Topic | Guide |
| --- | --- |
| Architecture and capability boundaries | [Implementation](https://github.com/BruceXcluding/backbone-conductor/blob/v0.75.0/docs/IMPLEMENTATION.md) |
| Deployment, credentials, synchronization, and recovery | [Operations](https://github.com/BruceXcluding/backbone-conductor/blob/v0.75.0/docs/OPERATIONS.md) |
| Member and coordinator MCP tools | [MCP API](https://github.com/BruceXcluding/backbone-conductor/blob/v0.75.0/MCP_API.md) |
| Deterministic conflict checks | [Conflict rules](https://github.com/BruceXcluding/backbone-conductor/blob/v0.75.0/CONFLICT_RULES.md) |
| Optional DeepSeek Harness integration | [DSH integration](https://github.com/BruceXcluding/backbone-conductor/blob/v0.75.0/DSH_PLUGIN_PLAN.md) |
| Validation methods and evidence | [Validation](https://github.com/BruceXcluding/backbone-conductor/blob/v0.75.0/docs/VALIDATION.md) |
| Real-user pilot procedure | [Pilot](https://github.com/BruceXcluding/backbone-conductor/blob/v0.75.0/docs/PILOT.md) |
| Release procedure | [Releasing](https://github.com/BruceXcluding/backbone-conductor/blob/v0.75.0/docs/RELEASING.md) |
| Version history | [Changelog](https://github.com/BruceXcluding/backbone-conductor/blob/v0.75.0/CHANGELOG.md) |

Additional research and historical design records are indexed in the [documentation index](https://github.com/BruceXcluding/backbone-conductor/blob/v0.75.0/docs/README.md). The implementation and generated schemas are authoritative where older design notes differ.

## Contributing

Bug reports and proposals are welcome through [GitHub Issues](https://github.com/BruceXcluding/backbone-conductor/issues). See [CONTRIBUTING.md](https://github.com/BruceXcluding/backbone-conductor/blob/v0.75.0/CONTRIBUTING.md) for setup, checks, and pull request guidance.

Licensed under [MIT](https://github.com/BruceXcluding/backbone-conductor/blob/v0.75.0/LICENSE).
