import type { Batch } from "../api/client";

const time = (iso: string): string =>
  new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });

/** How far a batch has got, in words. arXiv gives no total, so there is none to show. */
const progress = (batch: Batch): string => {
  const pages = `${batch.pages} page${batch.pages === 1 ? "" : "s"}`;
  return `${pages} · ${batch.items} papers · ${batch.added} new`;
};

const retrying = (batch: Batch): boolean =>
  batch.state === "harvesting" && batch.attempts > 0;

export function BatchList({ batches }: { batches: readonly Batch[] }) {
  if (batches.length === 0) return null;
  return (
    <ul className="batches">
      {batches.map((batch) => (
        <li key={batch.id}>
          <span className={`badge state-${retrying(batch) ? "retrying" : batch.state}`}>
            {retrying(batch) ? `retrying · attempt ${batch.attempts + 1}` : batch.state}
          </span>
          <span className="what">
            {batch.category} since {batch.since}
          </span>
          <span className="progress">{progress(batch)}</span>
          <span className="when">{time(batch.created_at)}</span>
          {batch.last_error !== null && <span className="why">{batch.last_error}</span>}
        </li>
      ))}
    </ul>
  );
}
