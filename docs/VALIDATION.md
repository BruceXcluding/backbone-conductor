# Validation

The repository has automated checks for protocol behavior, Git storage and audit history, CLI/HTTP/MCP interfaces, conflict rules, real Git merges, and package builds. GitHub Actions runs the CI matrix on Python 3.12 and 3.13, plus DSH SDK startup checks and Compose deployment scenarios. See the [CI workflow](https://github.com/BruceXcluding/backbone-conductor/actions/workflows/ci.yml) for the current result and exact commands.

Run the main checks from a synchronized development checkout:

```sh
uv sync --locked --group dev
uv run ruff check .
uv run ruff format --check .
uv run pytest --cov=backbone_conductor --cov-fail-under=85
uv run python scripts/evaluate.py
uv run python examples/demo.py
uv run python examples/two_agent_demo.py --mcp
uv build
```

The examples use temporary repositories. The two-member MCP example exercises separate clients and real Git merges, but its agent identities and approvals are scripted. CI tests HTTP/HTTPS and Compose on local or container networks; these checks do not establish that a shared Internet deployment has been operated by different people.

The evaluation script uses synthetic conflict scenarios. Historical Git merge replay measures path contention against textual merge outcomes. Neither yields a measured recall or precision for prospective intention conflicts. Use the [prospective study protocol](../evals/PROSPECTIVE_STUDY.md) for that claim.

Release packaging has also been checked from a fresh remote clone: the source-built wheel installed into an isolated virtual environment, imported from its `site-packages`, and started the `backbone` CLI. This checks installation on the same machine, not a public package-index release. The [incremental validation record](archive/VALIDATION_HISTORY.md) retains exact earlier versions, environments, and measurements.
