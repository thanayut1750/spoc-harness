# Runtime architecture

```mermaid
flowchart TD
    UI[React / Canvas office] --> API[FastAPI commands and snapshots]
    API --> DB[(Postgres application records and jobs)]
    DB --> Worker[Leased host worker]
    Worker --> Triage[Checkpointed TypeSafe Jev triage]
    Triage -->|FAST_TRACK| Direct[One KR and one worker]
    Triage -->|DEPARTMENTAL| Single[One KR and one department]
    Triage -->|FULL_PYRAMID or unavailable| Plan[Strategic planner and plan validation]
    Direct --> Schedule
    Single --> Schedule
    Plan --> Schedule[Deterministic KR scheduler]
    Schedule -->|dependency-ready / at most two| Dept[Private department subgraph]
    Dept --> Head[Department tactical plan]
    Head --> Specialist[LangChain specialist agent]
    Specialist --> Tool[Journaled host or research tools]
    Tool --> Files[(Local evidence artifacts)]
    Specialist --> TacticalGate[Tactical acceptance gate]
    TacticalGate --> Head
    Head --> KRGate[Whole KR acceptance gate]
    KRGate --> Rollup[Typed outcome rollup]
    Rollup --> Schedule
    Schedule --> Replan[One executive replan]
    Replan --> Schedule
    Schedule --> Review[Persisted human interrupt]
    Review -->|validated decision| Schedule
    Schedule --> Report[Traceable executive report]
    Worker --> Checkpoint[(Postgres graph checkpoints)]
    Worker --> Events[Persisted activity events and office projection]
    Events -->|SSE replay by cursor| UI
    External[External activity webhooks] --> Events
```

## Boundary rules

The executive stores JSON contracts, not specialist transcripts. A department receives its constitution, versioned KR, approved dependency deliverables, and bounded feedback. A worker receives its tactical assignment and relevant inputs. Department outputs are typed KR outcomes. Only department approval updates executive KR progress to passed.

Checkpoints use the run ID as `thread_id`. Nested graphs inherit per-invocation persistence, preserving in-flight private work without carrying old assignments into a new KR. Keyed reducers merge concurrent results idempotently.

The worker owns one execution lease and a session advisory lock. Application jobs, graph checkpoints, and operation records have distinct purposes: a lease dispatches work, a checkpoint restores graph progress, and the operation journal prevents replay of known completed tool effects. Arbitrary host commands with unknown outcomes require human review before retry.

## Acceptance gates

The model supplies structured assessment and evidence references. Python decides routing. Approval requires constitution compliance, every required criterion, score at least 0.8, substantive stored artifacts, integrity checks, valid Python syntax where applicable, and successful referenced command/syntax checks. A worker's confidence or a suggested `approve` action is insufficient.

Full-pyramid work shares the configured rework cycles between worker and department gates in a KR epoch, and an ordinary escalation can consume the run's single automatic replan. Fast-track and departmental work cap rework at one and do not automatically replan; worker handoffs use structural checks and the whole KR receives one semantic review per attempt. Fast-track bypasses both planning models and executive narrative synthesis. Its report is generated from approved outcomes and evidence. Constitution violations persist a governance halt and require review. Human context starts another epoch; a KR revision also changes its definition version and invalidates transitive dependent approvals.

Worker invocation and deliverable extraction share an `asyncio.wait_for` deadline, defaulting to 180 seconds for new runs. Per-run `limits.worker_timeout` overrides and saved run limits determine each invocation's actual deadline. Explicitly optional packages can return incomplete fallback evidence to the lead; final approval still requires the mandatory work and all KR criteria. A pending host command remains an unknown-side-effect blocker rather than an optional fallback.

Public model selections are immutable run snapshots; per-agent overrides select server-owned provider connections. Credentials never enter persisted selections. Regenesis serializes API mutations, cancels unfinished work, acquires the same worker guard as execution, then erases managed disk directories and database/checkpoint/store contents. This excludes external user workspaces and preserves migration schemas and server credentials.

## Error boundaries

Expected tool-input failures use `ExpectedToolInputError` at the point that interprets a model-supplied file, artifact, URL, directory or command timeout. The journal records those errors as completed results; a model can read the error and correct its call without cancelling parallel work. Unknown run records, persistence failures and raw programming exceptions retain their failure semantics. Identical parallel operation IDs share a per-host lock and reuse the recorded result; conflicting requests still stop for review.

| Boundary | Expected failure behavior | Protected behavior |
| --- | --- | --- |
| Artifact, file and syntax tools | Missing/foreign/corrupt references, paging and path errors become actionable tool results | Missing run records and persistence failures propagate |
| URL and MCP tools | Engineering reads actual bounded HTTP sources; network/content errors remain explicit; research MCP failures become typed resource blockers | Cancellation, policy and budgets are not replaced by fallback content |
| Command journal | Invalid pre-start input is recorded; repeated identical IDs execute once | Started commands with unknown or unrecorded effects remain pending until reviewed |
| Model adapter | Missing response choices/messages/function fields and invalid usage become sanitized provider errors | Internal `KeyError`, storage errors and unrelated `ValueError` are not silently retried |
| Graph services | Returned contract validation and typed resource escalations have explicit routes | Exceptions inside services are not confused with malformed returned JSON |
| HTTP, CLI and UI | Resource errors are 404/422; failed runs can retry saved work; artifact/read failures show visible recoverable messages | Mutation requests are not automatically repeated; cancelled/succeeded runs cannot retry |

Unexpected worker failures retain a class-only message and safe diagnostic frames (file basename, function, line and execution phase), excluding exception bodies, prompts and credentials. Recovery preserves usage and epoch counters. The worker checks uncertain commands before constructing services or resuming graph work.

## Office projection

Version 1 activity events are persisted with monotonically ordered cursors and source-scoped event IDs. Projection updates and event inserts commit together. The browser snapshots a cursor, then replays subsequent SSE events; duplicate events are ignored. Internal handoff events identify both agent endpoints and the KR, allowing animation to reflect real transfers.

External webhooks update external display identities only. They cannot change run records, approvals, or reviews. The fixed office has six external desks; further agents remain available in its searchable list.

## Operational limits

This is a trusted local host deployment with loopback networking and no authentication. Role-scoped interfaces and prompt boundaries govern orchestration, while shell tools retain the local account's operating-system permissions. Broad semantic constitution rules remain model assessments; this architecture does not claim sandbox enforcement.
