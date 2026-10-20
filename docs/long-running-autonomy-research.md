# Long-running autonomy: research and evidence for SPOC

Research checked on 2026-10-20. This record separates published evidence, repository observations, and proposed applications. It is research for implementation, not a claim that a week-long autonomous run has already passed. No provider calls, mission decisions, settings changes, or production changes were made for this research.

Repository observations below are pinned to commit `25e3a06`, before the concurrent autonomy implementation. Use `git show 25e3a06:<path>` to reproduce them; the working tree is being developed in parallel. Installed versions were read without syncing dependencies: LangChain 1.4.6, LangGraph 1.2.16, and langgraph-checkpoint-postgres 3.2.0.

## Conclusion supported by the research

Days or weeks of autonomy should consist of resumable work cycles with explicit progress, evidence, recovery, and completion rules. Removing call caps is compatible with bounded individual requests, commands, and work cycles. A checkpoint preserves execution state; a progress record explains what the next cycle should do. Neither requires retaining an ever-growing prompt or keeping one model request open for the mission's lifetime.

Keep SPOC's LangGraph orchestration, Postgres persistence, immutable artifact store, operation journal, and independent gates. Add durable continuation and context management around those foundations. The implementation should preserve requirements while changing tactics, and should distinguish useful progress, waiting for a recoverable resource, an exhausted strategy, and actual completion.

The evidence does not establish that unlimited retries or more agents guarantee success. In particular, METR's task time horizon measures task difficulty using human completion times; it is not a measurement of how long an agent can remain running. Its methodology should not be presented as proof of week-long unattended wall-clock execution. See [METR's definition and caveats](https://metr.org/time-horizons/).

## What the baseline already has, and what remains missing

These are code observations, rather than claims from framework documentation.

| Boundary | Baseline evidence | Consequence for longer autonomy |
| --- | --- | --- |
| Mission persistence | `worker.py:Worker.run_forever` opens `AsyncPostgresSaver` and `AsyncPostgresStore`; `runtime.py:runtime_config` uses the mission ID as `thread_id`. | Preserve the existing checkpoint identity when recovering a mission. A restart is not a new mission. |
| Nested durability | Worker and department graphs compile with `checkpointer=None`; private agents are built with `create_agent`. | **Do not interpret `None` as disabled persistence.** It inherits parent persistence within an invocation. Cross-cycle memory and correct namespace replay still need explicit tests. |
| Execution ownership | `storage.py:claim_job`, `worker_lock`, heartbeat and `worker.py:_monitor` prevent concurrent mission execution and cancel work after lease/storage visibility loss. | Reuse these ownership controls for scheduled continuation. They are not yet a durable cooldown scheduler. |
| Three call caps | `models.py:ModelCallBudget` accepts independent `null` for mission model calls, agent turns, and mission tool calls. `storage.py:reserve_budget` continues counting usage. | Unlimited must remain explicit `null`; counters and audit evidence remain valuable when there is no finite cap. |
| Remaining time boundaries | `RunLimits.worker_timeout` is at most 3600 seconds. Worker execution, lead planning, and Tools R&D use `asyncio.wait_for`; requests and commands have separate deadlines. | Mission duration cannot be implemented by stretching a single worker invocation to weeks. A cycle must leave resumable progress before its deadline. |
| Recovery boundaries | `agent_services.py:model_request` makes up to three transient provider attempts with short exponential delays. `runtime.py:coordinate` normally allows one executive replan, then enters review; departmental/fast paths are more restrictive. | Retry exhaustion currently means a workflow stop, not a persisted delayed retry or alternate strategy on another day. |
| Revision boundaries | `Constitution.max_revision_loops` defaults to 2 and is bounded by 10. `runtime.py:revision` escalates on exhaustion. | Unlimited call caps do not remove semantic rework limits or human-review routes. Those need an explicit autonomy policy. |
| Private working context | `agent_services.py:planning_agent`/`_execute_worker` assemble role prompts and invoke `create_agent`; their middleware applies policy and optional call limits. No summarization middleware or cross-cycle progress packet is configured there. | Compaction and a durable handoff contract are separate from the existing within-invocation checkpoint behavior. Check both lead and worker paths, including R&D. |
| Replay-aware operations | `tools.py:HostTools._journal` fingerprints requests, returns completed results, and treats a pending command as an unknown operation. Artifacts have content hashes. | Preserve this journal. Checkpoint replay alone cannot prove that an external side effect did or did not happen. |
| Completion | `agent_services.py:evaluate` reads stored artifacts, runs deterministic checks, and supplies criterion evidence to an independent reviewer; `runtime.py` requires all criteria and a passing score. | Keep approval tied to current outputs and successful checks. A model summary, elapsed runtime, or “done” message is insufficient. |
| Verification visibility | Review evidence currently includes at most the first 12,000 characters of each artifact. | Large outputs may require indexed/chunked evidence or executable checks; a longer mission does not remove this coverage limitation. |
| Department structure | Baseline `Department` has Research and Engineering; dynamic `EngineeringSpecialistSpec` is Engineering-specific; tactical plans have 1–4 packages. `coordinate` dispatches at most two ready KRs, one per department. | Generalizing specialist schemas and tools does not automatically generalize scheduling, ownership, model inheritance, identity, or verification. Audit those boundaries together. |
| Long-lived queues | `claim_job` selects queued/running jobs. The baseline has no persisted `next_wake_at`, recovery category, or cycle-progress generation. | Waiting should release execution ownership and survive restarts, with a scheduler rechecking only when eligible. |
| Graph steps | `runtime_config` sets the outer graph recursion limit to 1000; unlimited private-agent calls use a very large step ceiling. | Step ceilings are emergency bounds, not progress-management strategies. Avoid turning the outer graph into an unbounded hot loop. |

Relevant local sources: [models](../src/org_harness/models.py), [worker](../src/org_harness/worker.py), [runtime](../src/org_harness/runtime.py), [agent services](../src/org_harness/agent_services.py), [storage](../src/org_harness/storage.py), and [tools](../src/org_harness/tools.py). These links follow the current checkout; the baseline commit above is the authority for this table.

## Primary evidence and its limits

### LangGraph: durable execution and recovery

1. [Checkpointers and durability modes](https://docs.langchain.com/oss/python/langgraph/checkpointers#durability-modes), retrieved through LangChain Docs MCP. `sync` writes the checkpoint before the next step; `async` can overlap persistence with execution; `exit` omits intermediate crash recovery. For SPOC, explicitly choose and test durability at progress/recovery boundaries rather than assuming a persisted application row and graph checkpoint always advance together.

2. [Graph replay and idempotency](https://docs.langchain.com/oss/python/langgraph/graph-api#re-execution-and-idempotency), retrieved through MCP. A resumed node can restart from its beginning. Completed task results may be replayed from persistence, but arbitrary side effects need their own idempotency/reconciliation. This supports retaining SPOC's operation IDs and journal, rather than replacing them with a generic node retry.

3. [Subgraph persistence](https://docs.langchain.com/oss/python/langgraph/use-subgraphs#subgraph-persistence), retrieved through MCP and checked against the installed runtime's checkpointer resolution. `None` provides per-invocation persistence inherited from the parent; `True` accumulates state across invocations; `False` disables it. `create_agent` is also a LangGraph graph. Do not globally change nested agents to `True`: parallel uses of the same stateful namespace require deliberate isolation.

4. [Fault tolerance](https://docs.langchain.com/oss/python/langgraph/fault-tolerance), retrieved through MCP. Python LangGraph ≥1.2 supports typed retry policies with backoff/jitter, async node run/idle deadlines, and recovery handlers after retry exhaustion. Its cooperative `RunControl.request_drain()` saves a resumable boundary; it does not preempt an executing node. Imports and signatures of `RunControl`, `TimeoutPolicy`, and `GraphDrained` were also verified in the installed runtime. The suggested local scheduler remains application code, not a feature automatically supplied by a checkpointer.

### Context management and agent memory

5. [LangChain summarization middleware](https://docs.langchain.com/oss/python/langchain/middleware/built-in#summarization), retrieved through MCP. It compresses older messages while retaining recent context, and replaces the old history in working state. Its installed constructor was verified to accept `trigger`, `keep`, and a custom `token_counter`. Fraction thresholds depend on usable model-profile data; absolute token/message thresholds and a tested counter are alternatives. For a custom OpenAI-compatible endpoint, verify profile/token accounting instead of copying a model-specific threshold.

6. [Deep Agents context engineering](https://docs.langchain.com/oss/python/deepagents/context-engineering#context-compression), retrieved through MCP. Deep Agents combines filesystem offloading, summarization, and isolated subagent context. Its richer summarization path preserves a text history outside the active prompt. The [public implementation](https://github.com/langchain-ai/deepagents/blob/main/libs/deepagents/deepagents/middleware/summarization.py) was checked through its raw source. This is a pattern to adapt, not evidence that SPOC already runs Deep Agents or has that archival behavior. The project does not currently declare `deepagents` as a dependency.

7. [Anthropic: effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents), 2025-09-29. It describes selective retrieval, compaction, persistent notes, and specialized subagents returning distilled findings. The applicable principle is to keep source identifiers and decisions retrievable while limiting working context. Its discussion concerns coherence across long tasks, not a proof that a particular summary format will preserve every fact.

### Long-running harnesses and public implementations

8. [Anthropic: effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents), 2025-11-26. The initializer creates a task/feature inventory; later sessions work incrementally, read progress, verify behavior, and leave a clean handoff. The article identifies premature completion and undocumented partial work as distinct failures. It also emphasizes user-like end-to-end testing. The accompanying [autonomous-coding README](https://raw.githubusercontent.com/anthropics/claude-quickstarts/main/autonomous-coding/README.md) exposes the session/progress-file pattern. It is a demo with provider-specific assumptions and moving `main` references; inspect its licensing before copying source.

9. [Anthropic: harness design for long-running application development](https://www.anthropic.com/engineering/harness-design-long-running-apps), 2026-03-24. It adds planner/generator/evaluator sprints, explicit agreements about completion, and browser/API/database verification. It also reports a model-dependent distinction: older-model runs benefited from context resets, while a stronger-model setup used automatic compaction in a continuous session. Therefore the durable handoff should support fresh contexts, but forced resets should be evaluated rather than treated as universally superior. These are vendor experiments on application development, not general guarantees for Research or SPOC's configured model.

10. [Anthropic: building a C compiler with parallel agents](https://www.anthropic.com/engineering/building-c-compiler), 2026-02-05. The reported two-week experiment used many independent sessions, task ownership, isolated workspaces, progress notes, and strong tests. The author also reports regressions, coordination failures on a shared bottleneck, and remaining compiler limitations. This is evidence that the environment and verifier matter over long horizons; copying an infinite shell loop would omit SPOC's ownership, journal, cancellation, and policy requirements.

11. [Anthropic: multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system), 2025-06-13. It describes a lead preserving its plan, bounded delegation with explicit output contracts, and a citation stage. Its mistakes included excessive agents, duplicated work, and continued search after enough evidence existed. Cross-department specialization should therefore have declared scope, source ownership, and an integration point, rather than simply expanding the number of agent identities.

12. [LangChain Open Deep Research implementation](https://raw.githubusercontent.com/langchain-ai/open_deep_research/main/src/open_deep_research/deep_researcher.py), retrieved 2026-10-20. Its researcher subgraph has a separate compression stage returning both a condensed result and raw notes. This is a concrete Research handoff example. Its iteration limits and generic compression retry/fallback behavior should not be copied as SPOC's autonomy policy; a failed compression cannot become a successful deliverable.

### Relevant research

13. [ACE: Agentic Context Engineering](https://arxiv.org/abs/2510.04618v3), submitted 2025-10-06, revised 2026-03-29; the record lists ICLR 2026. It treats memory as an evolving structured playbook with generation, reflection, and curation, and warns about losing detail through repeated whole-context rewrites. For SPOC, retain versioned incremental findings and failed approaches instead of repeatedly replacing one untraceable mission summary. Its benchmark improvements are not measured outcomes for this repository.

14. [AgentFold](https://arxiv.org/abs/2510.24699), submitted 2025-10-28. It explores proactive, multi-scale history consolidation for web agents. Its trained model and benchmark setting differ from SPOC. The applicable experiment is preserving detailed source/evidence references while condensing completed subtasks; its reported scores cannot be inferred from adding a summary prompt here.

15. [Scaling Long-Horizon LLM Agent via Context-Folding](https://arxiv.org/abs/2510.11967), submitted 2025-10-13. It branches into subtask trajectories and folds their results back into a compact parent context, using a learned policy. This supports testing hierarchical handoffs, but is not a drop-in substitute for dependency scheduling, shared-workspace isolation, or deterministic acceptance checks.

All documentation and `main` source links above are mutable. The papers' versions/dates are listed where available. Public vendor reports, released source, and research benchmarks are different evidence classes; none substitutes for a restart/continuation test on SPOC's actual database, provider, workspace, and tool configuration.

## Applicable design decisions

The following are implementation inferences from the evidence and baseline code, not claims that the sources prescribe this exact schema.

### 1. Define a bounded work cycle and a durable progress record

A cycle should execute one tractable work package or advance it to a documented milestone. It ends with a verified result, an explicit continuation point, a resource wait, or a terminal blocker. Preserve the mission ID, immutable constitution, criteria, and prior evidence across cycles. A cycle ending because its working allowance expires is not a failed mission when usable continuation has been recorded.

Store a server-authored progress revision with at least:

```json
{
  "mission_id": "existing-run-id",
  "cycle_id": "unique-cycle-id",
  "progress_revision": 17,
  "kr_id": "KR1.1",
  "kr_version": 1,
  "epoch": 2,
  "work_package_id": "wp-3",
  "actor_id": "specialist:...",
  "status": "continue",
  "completed_steps": ["Parsed the saved source inventory"],
  "remaining_steps": ["Resolve duplicate records", "Run acceptance checks"],
  "artifact_refs": [{"artifact_id": "...", "sha256": "..."}],
  "verification_refs": [],
  "failed_approaches": [],
  "next_action": "Deduplicate using the recorded schema",
  "retry": {"class": null, "attempt": 0, "next_wake_at": null}
}
```

The server should validate referenced artifacts, assignment ownership, version/epoch, and schema before advancing the revision. Model-written notes are proposals about progress; verified manifests and recorded checks remain authoritative. A new cycle consumes the latest validated record plus the relevant artifacts, rather than redoing discovery or replaying all source text. Keep public summaries separate from private transcripts/provider reasoning.

### 2. Preserve working context without making summaries the database

Apply token-aware compaction to both planning and execution loops, including Research, Engineering specialists, and R&D. Keep recent tool-call/result pairs valid; archive or retain canonical evidence before replacing old message content. Long file bodies and search results should be stored once and loaded by bounded reads. A summary should include the exact goal, current constraints, accepted work, remaining work, artifact references, decisions, failed approaches, and the latest gate feedback.

Use separate records for stable facts, hypotheses, and next actions. Incremental additions should have provenance and scope so an incorrect summary can be repaired without erasing earlier evidence. Refresh the working context from the current manifest when the mission resumes, and reject stale progress belonging to an earlier KR version or invalidated dependency epoch.

Test the difference between continuing an inherited nested checkpoint and starting another work cycle. Do not assume one implies the other. If separate long-lived agent threads are introduced, give them stable mission/assignment namespaces and avoid concurrent writers sharing a stateful namespace.

### 3. Turn retry exhaustion into an explicit recovery decision

Classify failures before deciding how to continue:

| Observed condition | Autonomous response to implement | Evidence that must remain visible |
| --- | --- | --- |
| Transient connection, 429, or eligible 5xx | Limited immediate attempts, then persisted exponential cooldown with jitter and a wake time; honor a usable provider retry hint. | Original exception category, attempts, next wake time, and counters. |
| Individual unavailable page or invalid model-supplied tool input | Return an actionable tool result; let the agent choose another valid source or correct the request. | Actual failed URL/input and stored prior sources; no fabricated replacement. |
| Quality/acceptance failure | Change tactics, split the package, repair a specific failing criterion, or assign a suitable specialist. | Unchanged criteria, current output hashes, failed checks, and the reason the next strategy differs. |
| Cycle timeout with saved progress | Finish or cancel the current operation safely, record continuation, release execution ownership, and run another cycle. | Partial artifacts, unresolved operations, and a usable next action. |
| Invalid credentials, explicit policy conflict, or unavailable required capability | Try only pre-authorized alternatives; otherwise record a truthful blocked outcome or an eligible delayed recheck. | The unresolved requirement and actual blocker. Do not turn it into approval or invented user guidance. |
| Host command with unknown effects | Reconcile using operation-specific receipts, filesystem/database state, or a predeclared idempotency contract. If that is impossible, stop that branch with an explicit unresolved outcome. | The original pending operation and all observations. A generic model assertion is not proof that replay is safe. |

A no-human-review mode should remove the requirement to wait for a person's decision; it should not remove acceptance checks or claim that impossible work completed. Distinguish autonomous recovery, durable waiting, and terminal inability to continue. Keep explicit user pause/cancel commands authoritative.

### 4. Schedule continuation durably instead of sleeping while holding a lease

Persist `next_wake_at`, recovery class, attempt count, and progress revision with the job. Claim only eligible work using database time and ownership checks. A cooldown should release the global execution lock. Restarting the API or worker must preserve the future wake time and must not immediately repeat every sleeping mission.

Separate process liveness from useful progress. Heartbeats prove ownership; progress revisions prove a meaningful state change. Detect repeated identical action/result fingerprints, repeated unchanged gate failures, and cycles that produce no new evidence. Respond with decomposition, another permitted tactic, or a truthful terminal blocker rather than a rapid infinite loop. Null call caps do not require null storage/concurrency boundaries.

Use graceful graph draining where supported, with a tested hard-shutdown fallback. Explicitly test whether the current nested node can finish within the shutdown grace period: drain waits for a superstep and does not itself cancel an active command.

### 5. Generalize specialist contracts across departments

Represent a specialist as a validated assignment with department, base role/model parent, task, tools, inputs, expected outputs, and acceptance criteria. Derive identity server-side from the mission and assignment definition. Its selected tool set may narrow capabilities, but must preserve the core artifact and blocker protocol.

Keep department-specific capabilities: a Research specialist's tools are not automatically Engineering host-command authority. Permit cross-department dependency artifacts and explicit collaboration edges without mixing private histories or allowing a specialist to impersonate a lead. Test model inheritance, notes, current snapshots, activity history, artifact ownership, and handoff targets for every supported department.

Parallelism should follow independent work and available resources. Protect shared files with scoped ownership or isolated workspaces and an integration step. Unlimited calls must not imply unlimited concurrent subprocesses or duplicate writers. The compiler experiment's shared-bottleneck failures make this especially relevant.

### 6. Make completion a verifiable mission property

Retain SPOC's independent gate and add a durable verification manifest covering every required criterion and current output revision. For software, include build/tests and the actual user journey; for research, include source validity, citation-to-claim coverage, completeness, and consistency checks. A file existing, a tool invocation succeeding, or an internal confidence score is not enough.

Run a small health check before extending previously accepted work. Invalidate affected verification when dependencies or files change. Record the best verified revision so a later failed attempt does not silently replace the last usable output. The final report should enumerate passing criteria, actual outputs, unresolved limitations, and reproducible verification references.

## Experiments needed before claiming days/weeks of reliable autonomy

| Experiment | Observable success condition |
| --- | --- |
| Checkpoint crash recovery inside a private tool loop | Completed journaled effects are not repeated; inherited nested state resumes correctly; the final artifact manifest and counters agree. |
| New-cycle recovery after compaction | The next cycle recovers exact requirements, source/artifact IDs, failed approaches, and remaining steps from durable records without reading the full transcript. |
| Planner, worker, Research, and R&D context saturation | Each path compacts or offloads before provider overflow, preserves valid tool message pairs, and still passes a later fact/criterion check. |
| 429/5xx across a worker restart | The job retains its cooldown and attempt state, releases ownership, and resumes only when due; another eligible mission can execute meanwhile. |
| All three caps unlimited | Model/tool counters increase; old two-field settings retain the tool default; no hidden model-turn or step default terminates useful continuation unexpectedly. |
| No-human-review quality failure | The system retries or changes tactics using recorded feedback without changing criteria or fabricating context; it eventually passes or reports a specific unresolved blocker. |
| Unknown command effects | Recovery reconciles a command-specific receipt or leaves a truthful unresolved branch; a restart does not blindly duplicate an effect. |
| Cross-department specialists | Research and Engineering assignments have distinct identities/capabilities and correct model inheritance, artifacts, dependency handoffs, and inspector history. |
| No-progress loop | Repeated identical failures produce a persisted recovery/escalation decision instead of a hot loop or an invented successful result. |
| Multi-day soak | Scheduled waits, restarts, lease loss, disk/log growth, cancellation, and resource recovery are exercised over real elapsed time; progress and completion correctness are measured separately from uptime. |

Use deterministic fault injection and a fake clock for most recovery cases, then an isolated real-provider mission and an actual soak. Record completion rate, verified criteria, duplicate effects, lost progress, time waiting, no-progress cycles, context size, and cost/usage. A process remaining alive for a week is not evidence that its mission was completed correctly.

## Adoption guidance

The lowest-risk route is to extend the current runtime with durable cycle/progress contracts, classified recovery, context management, and cross-department assignment schemas. Deep Agents supplies useful implementations of several context-harness mechanisms, but migrating the entire application is not a prerequisite and would require proving compatibility with the existing operation journal, gates, and saved checkpoints.

Do not copy provider-specific model IDs, automatic compaction percentages, infinite shell loops, or benchmark gains as product defaults. Validate the behavior against the configured model and tool contracts. Preserve existing mission/checkpoint/artifact evidence during rollout; keep older saved runs compatible or explicitly version their execution contract.
