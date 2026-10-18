import { useState } from "react";
import type { MouseEvent, ReactNode } from "react";
import { api } from "./api";
export function ArtifactLink({
  id,
  name,
  children,
}: {
  id: string;
  name: string;
  children: ReactNode;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function download(event: MouseEvent<HTMLAnchorElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const content = await api.downloadArtifact(id);
      const url = URL.createObjectURL(content);
      const link = document.createElement("a");
      link.href = url;
      link.download = name;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (failure) {
      setError(
        failure instanceof Error ? failure.message : "The file is unavailable.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="artifact-download">
      <a
        href={`/api/artifacts/${encodeURIComponent(id)}`}
        aria-busy={busy}
        aria-disabled={busy}
        onClick={(event) => void download(event)}
      >
        {children}
      </a>
      {error && (
        <p className="artifact-download-error" role="alert">
          Could not download {name}: {error}
        </p>
      )}
    </div>
  );
}
