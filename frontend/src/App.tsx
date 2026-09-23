import { useCallback, useEffect, useState } from "react";

import { Unauthorized, fetchBatches, fetchHealth, fetchPapers } from "./api/client";
import { useAsync } from "./api/useAsync";
import { useSession } from "./api/useSession";
import { BatchForm } from "./components/BatchForm";
import { BatchList } from "./components/BatchList";
import { HealthBadge } from "./components/HealthBadge";
import { PapersTable } from "./components/PapersTable";
import { SignIn } from "./components/SignIn";

const POLL_MS = 2000;

export function App() {
  const { view, enter, leave, ended } = useSession();

  switch (view.status) {
    case "checking":
      return (
        <main className="gate">
          <p className="note">One moment…</p>
        </main>
      );
    case "unreachable":
      return (
        <main className="gate">
          <p className="note error">The API is unreachable: {view.message}</p>
        </main>
      );
    case "out":
      return <SignIn configured={view.configured} onEnter={enter} />;
    case "in":
      return <Workspace onLeave={leave} onEnded={ended} />;
  }
}

function Workspace({
  onLeave,
  onEnded,
}: {
  onLeave: () => Promise<void>;
  onEnded: () => void;
}) {
  const health = useAsync(fetchHealth);
  // Bumped to reload batches and papers together: after a submission, and on a
  // timer while any batch is still running, since a worker fills them in.
  const [generation, setGeneration] = useState(0);
  const papers = useAsync(() => fetchPapers(), [generation]);
  const batches = useAsync(() => fetchBatches(), [generation]);
  const reload = useCallback(() => setGeneration((value) => value + 1), []);

  const running =
    batches.status === "ready" &&
    batches.value.some((batch) => batch.state === "queued" || batch.state === "harvesting");
  useEffect(() => {
    if (!running) return;
    const timer = setTimeout(reload, POLL_MS);
    return () => clearTimeout(timer);
  }, [running, generation, reload]);

  // A cookie can expire between loading the page and asking for data. That is
  // not an error to show, it is the login page again.
  useEffect(() => {
    const expired = [papers, batches].some(
      (loaded) => loaded.status === "failed" && loaded.error instanceof Unauthorized,
    );
    if (expired) onEnded();
  }, [papers, batches, onEnded]);

  return (
    <main>
      <header>
        <div className="bar">
          <h1>sift</h1>
          <button
            type="button"
            className="ghost"
            onClick={() => {
              void onLeave();
            }}
          >
            Sign out
          </button>
        </div>
        <p>Rank a pile of documents against weighted criteria.</p>
        <HealthBadge health={health} />
      </header>

      <BatchForm onDone={reload} onEnded={onEnded} />
      {batches.status === "ready" && <BatchList batches={batches.value} />}

      {papers.status === "loading" && <p className="note">Loading papers…</p>}
      {papers.status === "failed" && (
        <p className="note error">{papers.message}</p>
      )}
      {papers.status === "ready" && (
        <>
          <p className="note">
            {papers.value.total} paper{papers.value.total === 1 ? "" : "s"}
          </p>
          <PapersTable papers={papers.value.items} />
        </>
      )}
    </main>
  );
}
