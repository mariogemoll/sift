import { useEffect } from "react";

import { Unauthorized, fetchHealth, fetchPapers } from "./api/client";
import { useAsync } from "./api/useAsync";
import { useSession } from "./api/useSession";
import { HealthBadge } from "./components/HealthBadge";
import { PapersTable } from "./components/PapersTable";
import { SignIn } from "./components/SignIn";

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
  const papers = useAsync(() => fetchPapers());

  // A cookie can expire between loading the page and asking for data. That is
  // not an error to show, it is the login page again.
  useEffect(() => {
    if (papers.status === "failed" && papers.error instanceof Unauthorized) {
      onEnded();
    }
  }, [papers, onEnded]);

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
