# Implementation

Backbone Conductor is a Git-backed coordination service for coding agents. The core protocol and conflict checks do not require an agent runtime or model provider.

## Components

| Component | Responsibility |
| --- | --- |
| Protocol models | Validate intentions, decisions, tasks, artifacts, conflicts, and lifecycle transitions with Pydantic models and JSON Schema. |
| Conductor | Enforce state transitions, conflict policy, artifact checks, and review requirements. |
| GitStore | Persist snapshots and generated views in Git; serialize writers, check observed versions, and create isolated audit commits. |
| CLI, HTTP, and MCP | Expose the same coordination operations to maintainers, reviewers, members, and agent clients according to their roles. |
| Optional DSH adapter | Request structured semantic advice without changing deterministic conflict state or granting approval authority. |

The ledger can reside on the code branch or on a separate `backbone` metadata branch. Both modes use Git as the authoritative store. Cross-clone updates require explicit synchronization; divergent metadata requires review and reconciliation. No operation automatically merges members' code into the target branch.

## Review and audit boundaries

A task's artifact points to an actual Git commit. The inspection response pins its patch and records the target branch commit. Task completion requires the code to be integrated into the target branch and an approval tied to both the observed ledger version and target SHA. A reviewer must still examine the complete code and decide whether the outcome is acceptable.

Authenticated HTTP requests record their principal and role in metadata commits. This attests to the server's authorization decision, not to a person's physical identity. Git commit signing can establish which configured key signed a commit; it does not bind that key to an HTTP principal. A deployment must also control repository permissions, credentials, and trusted HTTPS certificates. The [operations guide](OPERATIONS.md) covers setup and recovery.

Deterministic conflict rules use declared symbols, dependencies, and paths. They cannot infer arbitrary code semantics or establish a real-world detection rate. Optional model advice remains advisory. The [prospective study](../evals/PROSPECTIVE_STUDY.md) describes how to measure alerts against independently reviewed work.

## Validation still required for broader claims

- A trial in which distinct people use isolated member and reviewer credentials, independent clones, and a shared HTTPS coordinator. See the [pilot procedure](PILOT.md).
- Prospective real-project conflict cases with independent human labels, including false positives and missed conflicts.
- Latency and recovery measurements on a specified server, network, and workload before advertising deployment-level performance targets.
- Online model quality, cost, and failure behavior before making claims about optional DSH-backed review.

The [validation guide](VALIDATION.md) summarizes existing checks. The [historical implementation log](archive/IMPLEMENTATION_HISTORY.md) records the sequence of features and decisions without defining the current interface.
