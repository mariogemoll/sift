import { fetchHealth, fetchPapers } from "./api/client";
import { useAsync } from "./api/useAsync";
import { HealthBadge } from "./components/HealthBadge";
import { PapersTable } from "./components/PapersTable";

export function App() {
  const health = useAsync(fetchHealth);
  const papers = useAsync(() => fetchPapers());

  return (
    <main>
      <header>
        <h1>sift</h1>
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
