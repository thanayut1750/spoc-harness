import {
  Check,
  FileText,
  GitBranch,
  History,
  ShieldCheck,
  X,
} from "lucide-react";
import { ArtifactFiles } from "./ArtifactFiles";
import { pretty } from "./office";
import { reviewFocus, reviewReason } from "./review";
import type {
  ActivityEvent,
  Artifact,
  Evaluation,
  ReviewAttempt,
  Run,
} from "./types";
function Gate({ evaluation }: { evaluation?: Evaluation | null }) {
  if (!evaluation)
    return (
      <p className="review-empty">
        No structured gate evaluation was preserved for this attempt. The
        blocker reason above is the recorded feedback.
      </p>
    );
  const checks = Object.entries(evaluation.criterion_results ?? {});
  return (
    <div className="review-gate">
      <div className="gate-facts">
        {typeof evaluation.score === "number" && (
          <span>
            Score <strong>{Math.round(evaluation.score * 100)}%</strong>
          </span>
        )}
        {typeof evaluation.passed_constitution === "boolean" && (
          <span>
            Constitution{" "}
            <strong>
              {evaluation.passed_constitution ? "Passed" : "Failed"}
            </strong>
          </span>
        )}
        {typeof evaluation.passed_kr_criteria === "boolean" && (
          <span>
            Criteria{" "}
            <strong>
              {evaluation.passed_kr_criteria ? "Passed" : "Failed"}
            </strong>
          </span>
        )}
      </div>
      <p>
        {evaluation.feedback ??
          evaluation.reasoning ??
          "No written gate feedback was recorded."}
      </p>
      {checks.length > 0 && (
        <ul className="gate-checks">
          {checks.map(([criterion, passed]) => (
            <li key={criterion} className={passed ? "passed" : "failed"}>
              {passed ? <Check size={13} /> : <X size={13} />}
              <span>{criterion}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
function EvidenceLinks({ values }: { values: string[] }) {
  return (
    <ul className="review-evidence-links">
      {values.map((value, index) => (
        <li key={`${index}:${value}`}>
          {/^https?:\/\//i.test(value) ? (
            <a href={value} target="_blank" rel="noreferrer">
              {value}
            </a>
          ) : (
            value
          )}
        </li>
      ))}
    </ul>
  );
}
function Attempt({
  attempt,
  files,
  latest,
}: {
  attempt: ReviewAttempt;
  files: Artifact[];
  latest: boolean;
}) {
  const references = attempt.artifact_ids ?? [];
  const evidence = attempt.evidence ?? [];
  return (
    <details className="review-attempt" open={latest}>
      <summary>
        <History size={13} />
        <span>
          {attempt.work_package_id ??
            pretty(attempt.stage ?? "Recorded attempt")}
        </span>
        {typeof attempt.execution_attempt === "number" && (
          <small>attempt {attempt.execution_attempt + 1}</small>
        )}
        <span
          className={`attempt-result ${attempt.approved === true ? "passed" : attempt.approved === false ? "failed" : ""}`}
        >
          {attempt.approved === true
            ? "Approved"
            : attempt.approved === false
              ? "Rejected"
              : "Recorded"}
        </span>
      </summary>
      <div className="attempt-meta">
        {attempt.role && <span>{pretty(attempt.role)}</span>}
        {attempt.epoch !== undefined && <span>Epoch {attempt.epoch}</span>}
        {attempt.version !== undefined && <span>KR v{attempt.version}</span>}
        {attempt.stage && <span>{pretty(attempt.stage)} gate</span>}
      </div>
      {attempt.task && (
        <details className="attempt-task">
          <summary>Assigned work and criteria</summary>
          <p>{attempt.task}</p>
          {attempt.acceptance_criteria?.length ? (
            <ol>
              {attempt.acceptance_criteria.map((criterion) => (
                <li key={criterion}>{criterion}</li>
              ))}
            </ol>
          ) : null}
        </details>
      )}
      <div className="attempt-deliverable">
        <h5>Deliverable summary</h5>
        <p>
          {attempt.summary?.trim() || "No deliverable summary was recorded."}
        </p>
        <div className="attempt-evidence-counts">
          <span>
            {references.length} artifact{" "}
            {references.length === 1 ? "reference" : "references"}
          </span>
          <span>
            {evidence.length} evidence{" "}
            {evidence.length === 1 ? "item" : "items"}
          </span>
        </div>
        {references.length > 0 && (
          <ul className="attempt-artifact-links">
            {references.map((id) => (
              <li key={id}>
                <a
                  href={`/api/artifacts/${encodeURIComponent(id)}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  <FileText size={12} />
                  {files.find((file) => file.artifact_id === id)?.name ?? id}
                </a>
              </li>
            ))}
          </ul>
        )}
        {evidence.length > 0 && <EvidenceLinks values={evidence} />}
      </div>
      {attempt.reason && attempt.reason !== attempt.evaluation?.feedback && (
        <p className="attempt-reason">{attempt.reason}</p>
      )}
      <details className="attempt-gate">
        <summary>Evaluation for this attempt</summary>
        <Gate evaluation={attempt.evaluation} />
      </details>
    </details>
  );
}
export function ReviewEvidence({
  run,
  files,
  events,
}: {
  run: Run;
  files: Artifact[];
  events: ActivityEvent[];
}) {
  const context = run.review?.context;
  const focus = reviewFocus(run, events);
  const constitution = context?.constitution ?? run.constitution;
  const retries = context?.retry_summary;
  return (
    <div className="review-evidence">
      <section className="review-mission">
        <span className="eyebrow">MISSION</span>
        <p>{context?.mission ?? run.user_request}</p>
        <code>{run.run_id}</code>
      </section>
      <section className="review-blocker">
        <h3>
          <ShieldCheck size={16} />
          Why execution stopped
        </h3>
        <span className="review-kind">
          Recorded as {pretty(run.review?.kind ?? "review")}
        </span>
        {context?.blockers?.some((blocker) => blocker.classification) && (
          <p className="review-diagnosis">
            Evidence diagnosis:{" "}
            {pretty(
              context.blockers.find((blocker) => blocker.classification)
                ?.classification ?? "",
            )}
            .
          </p>
        )}
        <p>{reviewReason(run)}</p>
      </section>
      {focus.blocked.map((result) => {
        const filesForKr = files.filter((file) => file.kr_id === result.kr_id);
        const attempts = result.attempts ?? [];
        const evaluation =
          result.evaluation ??
          [...attempts].reverse().find((attempt) => attempt.evaluation)
            ?.evaluation;
        return (
          <section
            className="review-kr"
            key={result.kr_id}
            aria-label={`Review ${result.kr_id}`}
          >
            <div className="review-kr-heading">
              <h3>{result.kr_id}</h3>
              <span>
                {pretty(result.department ?? "Department")} · v
                {result.version ?? 1}
                {result.epoch !== undefined ? ` · epoch ${result.epoch}` : ""}
              </span>
            </div>
            <p className="review-kr-description">{result.description}</p>
            <h4>Acceptance criteria for this key result</h4>
            <ol className="review-criteria">
              {result.acceptance_criteria.map((criterion) => (
                <li key={criterion}>{criterion}</li>
              ))}
            </ol>
            {result.reason && result.reason !== reviewReason(run) && (
              <div className="kr-blocker-reason">
                <strong>Blocker</strong>
                <p>{result.reason}</p>
              </div>
            )}
            <h4>Latest gate feedback</h4>
            <Gate evaluation={evaluation} />
            {!attempts.length && result.summary && (
              <div className="attempt-deliverable">
                <h5>Latest deliverable</h5>
                <p>{result.summary}</p>
              </div>
            )}
            <div className="review-history-heading">
              <h4>Attempt history</h4>
              <span>{attempts.length} recorded</span>
            </div>
            {result.history_complete === false && (
              <p className="review-empty">
                These are recovered legacy records. The complete work history
                was not persisted.
              </p>
            )}
            {attempts.length > 0 ? (
              <div className="review-attempts">
                {[...attempts].reverse().map((attempt, index) => (
                  <Attempt
                    key={attempt.attempt_id}
                    attempt={attempt}
                    files={filesForKr}
                    latest={index === 0}
                  />
                ))}
              </div>
            ) : (
              <p className="review-empty">
                Detailed attempt history is unavailable for this saved review.
                Existing files are listed below.
              </p>
            )}
            <details className="review-files" open={filesForKr.length > 0}>
              <summary>
                <FileText size={14} />
                Files for {result.kr_id}
                <span>{filesForKr.length}</span>
              </summary>
              <ArtifactFiles files={filesForKr} />
            </details>
          </section>
        );
      })}
      {focus.waiting.length > 0 && (
        <details className="review-waiting">
          <summary>
            <GitBranch size={14} />
            {focus.waiting.length} key{" "}
            {focus.waiting.length === 1 ? "result is" : "results are"} waiting
            on dependencies
          </summary>
          <p>
            These pending results have no recorded failure. The review concerns
            the blocked work above.
          </p>
          <ul>
            {focus.waiting.map((kr) => (
              <li key={kr.kr_id}>
                <strong>{kr.kr_id}</strong>
                {kr.description}
              </li>
            ))}
          </ul>
        </details>
      )}
      {constitution && (
        <details className="review-constitution">
          <summary>
            <ShieldCheck size={14} />
            Constitution and boundaries
          </summary>
          <p>{constitution.mission_statement}</p>
          {constitution.prohibited_actions?.length ? (
            <>
              <h5>Prohibited actions</h5>
              <ul>
                {constitution.prohibited_actions.map((rule) => (
                  <li key={rule}>{rule}</li>
                ))}
              </ul>
            </>
          ) : null}
          {constitution.compliance_rules?.length ? (
            <>
              <h5>Compliance rules</h5>
              <ul>
                {constitution.compliance_rules.map((rule) => (
                  <li key={rule}>{rule}</li>
                ))}
              </ul>
            </>
          ) : null}
        </details>
      )}
      <section className="review-retry-summary">
        <h4>Retry budget</h4>
        {retries ? (
          <div>
            <span>
              Executive replans
              <strong>
                {retries.automatic_replans_used ?? "—"} /{" "}
                {retries.automatic_replans_limit ?? 1}
              </strong>
            </span>
            <span>
              Revision limit<strong>{retries.revision_limit ?? "—"}</strong>
            </span>
            <span>
              Attempts recorded
              <strong>
                {retries.attempts_recorded ??
                  focus.blocked.reduce(
                    (count, kr) => count + (kr.attempts?.length ?? 0),
                    0,
                  )}
              </strong>
            </span>
          </div>
        ) : (
          <p className="review-empty">
            Retry counters were not recorded in this saved review.
          </p>
        )}
      </section>
      {context?.truncated && (
        <p className="review-empty">
          This is a bounded review summary. Download the relevant artifacts for
          complete evidence.
        </p>
      )}
    </div>
  );
}
