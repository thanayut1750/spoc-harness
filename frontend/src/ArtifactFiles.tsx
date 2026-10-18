import { ArrowDownToLine, FileText } from "lucide-react";
import { ArtifactLink } from "./ArtifactLink";
import { artifactGroup, artifactGroups, artifactSizeLabel } from "./review";
import type { Artifact } from "./types";
export function ArtifactFiles({
  files,
  summary = true,
}: {
  files: Artifact[];
  summary?: boolean;
}) {
  const outputs = files.filter(
    (file) => artifactGroup(file) === "Task outputs",
  );
  return (
    <div className="artifact-list grouped-artifacts">
      {summary && (
        <div className="artifact-counts">
          <strong>
            {outputs.length} task {outputs.length === 1 ? "output" : "outputs"}
          </strong>
          <span>
            {files.length - outputs.length} supporting{" "}
            {files.length - outputs.length === 1 ? "record" : "records"}
          </span>
        </div>
      )}
      {files.length === 0 ? (
        <p className="review-empty">
          No files have been recorded for this scope.
        </p>
      ) : (
        artifactGroups.map((group) => {
          const items = files.filter((file) => artifactGroup(file) === group);
          return items.length > 0 ? (
            <section key={group} aria-label={group}>
              <h4>
                {group}
                <span>{items.length}</span>
              </h4>
              {items.map((file) => (
                <ArtifactLink
                  key={file.artifact_id}
                  id={file.artifact_id}
                  name={file.name}
                >
                  <FileText size={16} />
                  <div>
                    <strong>{file.name}</strong>
                    <span
                      className={
                        file.size === 0 && group === "Task outputs"
                          ? "empty-output"
                          : ""
                      }
                    >
                      {artifactSizeLabel(file)}
                      {file.epoch !== undefined ? ` · epoch ${file.epoch}` : ""}
                      {file.exit_code !== undefined
                        ? ` · exit ${file.exit_code}`
                        : ""}
                    </span>
                  </div>
                  <ArrowDownToLine size={14} />
                </ArtifactLink>
              ))}
            </section>
          ) : null;
        })
      )}
    </div>
  );
}
