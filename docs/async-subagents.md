# Async subagents in SPOC

SPOC keeps its local LangGraph worker and PostgreSQL persistence. It uses background
R&D tasks when a lead has useful independent work, and dependency-aware parallel
specialist batches when several assignments can proceed independently. These are
separate scheduling mechanisms.

## Which agents use which execution mode

| Agent or assignment | Execution | Reason |
| --- | --- | --- |
| TypeSafe triage, strategic Planner, Executive router | Awaited | Their decisions determine what may run next. |
| Research and Engineering department leads | Awaited coordination | They create assignments and own the dependency join. The two departments already run concurrently when their KRs are ready. |
| Tools R&D exploration or tool building | Background when independent | Planner or Engineering lead can start a durable job, continue planning, and retrieve its result later. A prerequisite consultation can still run inline. |
| Independent source research, paper mapping, data analysis | Async specialist batch | Independent inputs and isolated outputs allow useful overlap. |
| Independent Engineering analysis or staged deliverables | Async specialist batch | Work stays in its task workspace and returns immutable artifacts for integration. |
| Architecture needed by a coder, shared-project implementation, integration | Awaited with dependencies | Consumers must wait for the required result; simultaneous writes to the same project would conflict. |
| Worker reviewers and department acceptance gates | Async within their branches; joined before approval | Review can overlap other independent workers. A pending child or unverified result cannot approve a KR or complete a mission. |
| Fast-track single worker | Direct | Simple tasks do not acquire an extra planner or R&D delegation. |

An agent role alone does not make its work independent. For example, an analyst
using a researcher's findings must declare that dependency. A coder changing a
configured project should use serial integration, rather than treating a private
staging directory as the final project.

## Background R&D

Only Planner and Engineering lead receive background task tools. The synchronous
`consult_tools_rd` tool remains available for immediately required answers.
`start_async_task` launches the allowed `tools_rd_lead` capability and returns a
stable task ID without waiting for its result. Check/list/cancel operations and
`wait_async_task` (bounded to 30 seconds per wait) address that task in its original
planning scope. Workers, Research lead, reviewers, and
R&D itself do not gain delegation access.

Task records live in the existing operation journal, independently of compacted
conversation history. They retain the immutable request, parent, KR version/epoch,
status, and public result references. R&D uses a private checkpoint and workspace,
with a distinct office identity for each background job. Its model inherits the
saved Tools R&D selection; a display name cannot grant new tools.

The current mission worker owns every child task. Children may overlap the
parent's model/tool work, but do not continue outside its execution ownership.
At a shutdown, yield, pause, or cancellation boundary, the owner stops and awaits
its active children before closing clients and releasing its worker guard. Saved
jobs can resume from their private checkpoints in a fresh service instance.
Required joins and final planning reconciliation happen before downstream work is
accepted; a background launch receipt is not evidence of task completion. Every
report is reconciled in ordered pages of at most four reports and 32 KiB of public
result data. Completed page receipts prevent repeated reconciliation on replay.
Replacement planning cancels obsolete pending tasks for that same caller and KR,
retaining evidence and any command receipt that still requires reconciliation.
The office projects queued, running, completed, failed, and cancelled transitions
under each task's own identity.

## Dependency-aware specialist batches

Work packages support two scheduling fields:

```json
{
  "execution_mode": "async",
  "depends_on": ["source-inventory"]
}
```

An async package needs a named specialist and explicit dependencies. An empty
`depends_on` list declares independence. Unknown, duplicate, self-referencing,
and cyclic dependencies are rejected before execution. Omitted dependencies keep
the legacy ordered-input behavior, and execution defaults to `sync`.

The department scheduler dispatches at most two ready async specialists per batch
through LangGraph `Send`. It collects keyed results in plan order, supplies only
declared predecessor outputs, and retains successful siblings when a rejected
assignment needs a retry. Synchronous assignments run exclusively. The normal
whole-KR acceptance gate still checks the combined result.

This uses LangGraph's parallel super-step semantics: a batch joins before the next
batch starts. A fast branch does not release its next dependent while an unrelated
slow sibling is still in that batch. Background R&D's start/check lifecycle is the
nonblocking supervisor mechanism; parallel specialist batches are not advertised
as independent server processes.

Async file operations stay inside a task-specific managed directory, even when
the mission selected an existing project. Retried attempts can inspect their own
partial files. Dependency artifacts provide the handoff into subsequent work.
Shell tools retain the trusted local account's authority; workspace isolation is
not an operating-system sandbox. Actual shared-project integration stays serial.

## Recovery and limits

All requests and tools share the original mission's budgets and constitution.
Finite limits and manual pause/cancel remain authoritative. Private checkpoints,
completed operation receipts, and stable task identities provide replay control;
background execution does not authorize repeating uncertain external commands.
The finite two-consultation allowance is shared by inline and background R&D and
survives service restart. All-unlimited missions have no lifetime consultation cap;
two background R&D tasks can execute concurrently.
Regenesis uses the existing worker guard and clears child records/checkpoints with
other managed state.

The implementation follows the lifecycle distinction in [LangChain subagents](https://docs.langchain.com/oss/python/langchain/multi-agent/subagents#sync-vs-async)
and [Deep Agents async subagents](https://docs.langchain.com/oss/python/deepagents/async-subagents),
plus [LangGraph persistence and subgraphs](https://docs.langchain.com/oss/python/langgraph/use-subgraphs#subgraph-persistence).
The Deep Agents `AsyncSubAgent` middleware requires an Agent Protocol server. SPOC
implements its lifecycle locally within the existing worker rather than adding
that separate server runtime or switching agent frameworks.
