# Long-running autonomous execution

SPOC treats a mission as durable work across many execution sessions. A mission
has no overall day/week deadline when its three call caps are unlimited. It still
finishes only after its acceptance gates pass; unlimited execution does not imply
that an impossible objective, unavailable service, or invalid output has succeeded.

## Activate the policy

In **Settings → Model → Call budgets**, select **No limit** for all three fields:
model calls per mission, agent turns per invocation, and tool calls per mission.
New missions inherit those values. For a stopped existing mission, save the
defaults and apply them to that mission. The worker automatically adopts routine
reviews once the mission itself has all three unlimited values. Explicit operator
pauses remain paused; terminal failures retain their retry control.

The API representation is explicit JSON `null` for `max_model_calls`,
`worker_model_calls`, and `max_tool_calls` in `limits`. Missing fields retain finite
legacy defaults. One or two unlimited values do not enable autonomous mode.
CLI callers can inherit workspace defaults or explicitly opt in:

```sh
uv run spoc run "Complete and verify the requested project" --autonomous
```

Workspace settings do not silently change an already-running mission. Limits
remain its saved snapshot until explicitly updated while execution is stopped.

## Work sessions and memory

The executive persists contracts, goals, approved outcomes, evidence references,
and task progress. Planner, Engineering lead, workers, and R&D pin authoritative
mission constraints and assigned criteria in their system context, independently
of lossy progress summaries. Research and Engineering leads can define named specialists
using their department's base-role capabilities. A task-specific name cannot add
unauthorized tools, impersonate another actor, or change department requirements.
Existing Engineering identities and serialized assignments remain compatible.

Autonomous private LangChain agents use deterministic, independent checkpoint
threads in the same PostgreSQL saver. A worker yields at a safe model boundary
after 32 model turns. Another worker resumes the pending private step; it does not
restart the assignment, charge completed tools again, or expose the conversation
to the executive. A one-hour worker deadline is a session boundary, not a mission
deadline. Partial files, tool receipts, private history, and artifacts survive.

LangChain summarization compacts older private messages as the conversation grows,
retaining recent tool exchanges and a factual progress summary. Summary requests
use the same metered, validated provider path. Large histories are split losslessly
into bounded UTF-8 inputs, then reduced through individually checkpointed typed
summaries. Completed summary calls survive restart; compaction yields cooperatively
rather than imposing a lifetime limit. Progress input is capped at 48,000 UTF-8
bytes per map request and 50,000 per reduction; instructions, schema, and JSON
overhead also consume context. These conservative defaults do not guarantee
compatibility with arbitrarily small provider context windows. Even one oversized parallel tool-result
batch is compacted before the next agent request. Failed summaries preserve the old
checkpoint and retry after a cooldown instead of fabricating replacement history.
New task epochs receive bounded, explicit artifact and interrupted-command
manifests, along with the unchanged assignment and rejection feedback. Returning
a previously autonomous mission to finite budgets preserves its private session
and enforces the newly selected limits; it does not start a new conversation.

The growing mission tool registry stays outside private prompts. Initial context
contains compact recent entries; authorized agents discover complete input schemas
through bounded pages and invoke immutable tool IDs. Old versions remain available.
Autonomous R&D consultation and registration have no lifetime count cap; finite
missions retain their established limits. R&D remains callable only by Planner
and Engineering lead.

## Automatic planning and recovery

Review and rework remain bounded inside each graph cycle. A rejected mandatory
result causes another saved planning cycle, with the original constitution and
acceptance criteria retained. Passed dependency outcomes remain reusable. Current
checkpoint state keeps bounded recent attempts and escalations. Historical
checkpoints, private summary threads, immutable artifacts, and durable events
remain retained until reset and continue to consume disk space. Reviewers validate every referenced artifact locally, then
receive a bounded evidence packet with explicit head/tail ranges and omitted
counts. Unseen content and metadata cannot establish a passing criterion. Large
outputs still need clear verification evidence; excerpts do not guarantee complete
semantic inspection. A human decision is not needed merely because a review count,
provider retry allowance, worker session, or graph traversal ended.

Routine availability failures use persisted `next_attempt_at` wakeups with capped
exponential cooldowns. Waiting work releases its lease so another mission can run.
Healthy work chunks requeue fairly behind already-waiting missions. Process
restarts recover the same checkpoint; temporary database connection loss reopens
worker-owned storage, saver, and store resources without marking work successful
or discarding its state.

Planner repair feedback survives the cycle boundary. Constitution or capability
failures trigger a compliant replan rather than changing the rules. Automatic
retries are not blanket permission to ignore requirements or to turn uncertainty
into a passing evaluation. Unexpected programming defects and irreconcilable
corruption remain explicit failures with diagnostic context.

## Commands and operator control

Commands have an independent supervisor with durable process identity and terminal
receipts. A supervisor can record completion even if the harness process dies.
Recovery verifies process identity before signalling; it never kills a recycled or
unrelated PID. Detached descendants are cleaned up within the supervisor's owned
process tree. A successful command is recovered from its exact receipt; an
interrupted command returns a truthful nonzero result with uncertainty and
inspection guidance. The harness does not blindly execute that command again.
Finite missions retain their explicit unknown-operation review behavior.

**Pause** and **Cancel** remain authoritative, including races with scheduled
continuation. A manual pause waits for the user's explicit resume. Cancellation
stops active work and prevents automatic requeue. Regenesis stops owned command
supervisors before removing managed data, including private conversations and
compaction checkpoints. Pending unverified cleanup returns a conflict and retains
managed files. These operator controls are independent
of call budgets.

The office shows automatic continuation reasons, wakeup times, and cycles without
a routine approval dialog. Agent avatars, activity history, artifacts, and failure
diagnostics continue to reflect recorded execution.

## Operating assumptions and evidence

Keep the worker service running and preserve PostgreSQL plus the managed artifact
directory. Machine suspension, provider outages, and process restarts can delay a
mission; its durable state remains the continuation point. Disk capacity, available
credentials, tool capabilities, and a feasible objective still matter. There is no
claim that every mission can finish or that elapsed time alone proves completion.

Regression coverage exercises Research specialists, repeated compliant replans,
operator races, context compaction, private conversation recovery in fresh workers,
PostgreSQL reopen, delayed retries across simulated day-two/day-seven boundaries,
database reconnection, command-process death and detached-child cleanup, exact
receipt replay, and unchanged finite-mode review behavior. Time advancement in
tests proves that no day/week expiry is imposed; it is not a week-long live run.

See [the research record](long-running-autonomy-research.md) for the primary
LangChain/LangGraph, Anthropic, and research sources informing these choices.
