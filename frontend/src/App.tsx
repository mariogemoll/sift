import { useCallback, useEffect, useState } from "react";

import {
  type Order,
  Unauthorized,
  fetchBatches,
  fetchHealth,
  fetchPapers,
  fetchProfile,
} from "./api/client";
import { useAsync } from "./api/useAsync";
import { useSession } from "./api/useSession";
import { BatchForm } from "./components/BatchForm";
import { BatchList, isActive } from "./components/BatchList";
import { HealthBadge } from "./components/HealthBadge";
import { PaperList } from "./components/PaperList";
import { RankTable } from "./components/RankTable";
import { SignIn } from "./components/SignIn";

const POLL_MS = 2000;
const PAGE = 50;
const HISTORY = 100;

/** Publication windows to choose from, in days; null is every paper. */
const WINDOWS: readonly (number | null)[] = [1, 3, 7, 30, null];

type Page = "papers" | "batches";
type View = "compact" | "detailed";

const pageOf = (hash: string): Page => (hash === "#/batches" ? "batches" : "papers");

/** The page named in the URL's fragment, so the browser's back button works. */
function usePage(): Page {
  const [page, setPage] = useState(() => pageOf(window.location.hash));
  useEffect(() => {
    const follow = () => setPage(pageOf(window.location.hash));
    window.addEventListener("hashchange", follow);
    return () => window.removeEventListener("hashchange", follow);
  }, []);
  return page;
}

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
  const page = usePage();
  const health = useAsync(fetchHealth);
  const profile = useAsync(fetchProfile);
  const [days, setDays] = useState<number | null>(7);
  const [order, setOrder] = useState<Order>("rank");
  const [view, setView] = useState<View>("compact");
  const [limit, setLimit] = useState(PAGE);
  // Bumped to reload batches and papers together: after a submission, and on a
  // timer while any batch is still harvesting or has papers between stages,
  // since workers fill them in.
  const [generation, setGeneration] = useState(0);
  const papers = useAsync(
    () => fetchPapers({ limit, days, order }),
    [generation, limit, days, order],
  );
  const batches = useAsync(() => fetchBatches(HISTORY), [generation]);
  const reload = useCallback(() => setGeneration((value) => value + 1), []);

  const active = batches.status === "ready" ? batches.value.filter(isActive) : [];
  const finished = batches.status === "ready" ? batches.value.length - active.length : 0;
  const running = active.length > 0;
  useEffect(() => {
    if (!running) return;
    const timer = setTimeout(reload, POLL_MS);
    return () => clearTimeout(timer);
  }, [running, generation, reload]);

  // A cookie can expire between loading the page and asking for data. That is
  // not an error to show, it is the login page again.
  useEffect(() => {
    const expired = [papers, batches, profile].some(
      (loaded) => loaded.status === "failed" && loaded.error instanceof Unauthorized,
    );
    if (expired) onEnded();
  }, [papers, batches, profile, onEnded]);

  return (
    <main>
      <header>
        <div className="bar">
          <h1>sift</h1>
          <nav>
            <a href="#/" className={page === "papers" ? "here" : undefined}>
              Papers
            </a>
            <a href="#/batches" className={page === "batches" ? "here" : undefined}>
              Batches
            </a>
            <button
              type="button"
              className="ghost"
              onClick={() => {
                void onLeave();
              }}
            >
              Sign out
            </button>
          </nav>
        </div>
        <p>
          New arXiv papers, screened on their abstracts and read in full when they pass,
          ranked against the wishlist.
        </p>
        <HealthBadge health={health} />
      </header>

      {page === "batches" ? (
        <section>
          <h2>Batches</h2>
          {batches.status === "failed" && <p className="note error">{batches.message}</p>}
          {batches.status === "ready" && batches.value.length === 0 && (
            <p className="note">No batches yet.</p>
          )}
          {batches.status === "ready" && <BatchList batches={batches.value} />}
        </section>
      ) : (
        <>
          {profile.status === "ready" && (
            <BatchForm categories={profile.value.categories} onDone={reload} onEnded={onEnded} />
          )}
          <BatchList batches={active} />
          {finished > 0 && (
            <p className="note">
              <a href="#/batches">
                {finished} finished batch{finished === 1 ? "" : "es"} →
              </a>
            </p>
          )}

          <div className="controls">
            <div className="choices" role="group" aria-label="Published within">
              {WINDOWS.map((window) => (
                <button
                  key={window ?? "all"}
                  type="button"
                  className={window === days ? "chosen" : "ghost"}
                  onClick={() => {
                    setDays(window);
                    setLimit(PAGE);
                  }}
                >
                  {window === null ? "all" : `${window}d`}
                </button>
              ))}
            </div>
            <div className="choices" role="group" aria-label="Order">
              {(["rank", "newest"] as const).map((choice) => (
                <button
                  key={choice}
                  type="button"
                  className={choice === order ? "chosen" : "ghost"}
                  onClick={() => setOrder(choice)}
                >
                  {choice === "rank" ? "best first" : "newest first"}
                </button>
              ))}
            </div>
            <div className="choices" role="group" aria-label="View">
              {(["compact", "detailed"] as const).map((choice) => (
                <button
                  key={choice}
                  type="button"
                  className={choice === view ? "chosen" : "ghost"}
                  onClick={() => setView(choice)}
                >
                  {choice}
                </button>
              ))}
            </div>
          </div>

          {(papers.status === "loading" || profile.status === "loading") && (
            <p className="note">Loading papers…</p>
          )}
          {papers.status === "failed" && <p className="note error">{papers.message}</p>}
          {profile.status === "failed" && <p className="note error">{profile.message}</p>}
          {papers.status === "ready" && profile.status === "ready" && (
            <>
              <p className="note">
                {papers.value.items.length < papers.value.total
                  ? `${papers.value.items.length} of ${papers.value.total} papers`
                  : `${papers.value.total} paper${papers.value.total === 1 ? "" : "s"}`}
                {" · ranked against "}
                <span
                  title={profile.value.criteria.map((c) => `${c.id}: ${c.requirement}`).join("\n")}
                >
                  {profile.value.name}
                </span>
              </p>
              {view === "compact" ? (
                <RankTable papers={papers.value.items} profile={profile.value} offset={0} />
              ) : (
                <PaperList papers={papers.value.items} profile={profile.value} />
              )}
              {papers.value.items.length < papers.value.total && (
                <button type="button" className="ghost more" onClick={() => setLimit(limit + PAGE)}>
                  Show {Math.min(PAGE, papers.value.total - papers.value.items.length)} more
                </button>
              )}
            </>
          )}
        </>
      )}
    </main>
  );
}
