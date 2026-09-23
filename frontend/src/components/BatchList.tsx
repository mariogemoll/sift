import type { Batch, ItemState } from "../api/client";

const time = (iso: string): string =>
  new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

/** In pipeline order; the segments of a batch's bar are drawn in this order too. */
const STAGES: readonly [ItemState, string][] = [
  ["done", "done"],
  ["dead", "failed"],
  ["judge", "to judge"],
  ["fetch", "to fetch"],
  ["screen", "to screen"],
];

const count = (batch: Batch, state: ItemState): number => batch.progress[state] ?? 0;

/** A batch still doing something: harvesting, or papers still between stages. */
export const isActive = (batch: Batch): boolean =>
  batch.status === "queued" || batch.status === "harvesting" || batch.status === "processing";

/** How far the harvest has got. arXiv gives no total, so there is none to show. */
const harvest = (batch: Batch): string => {
  const pages = `${batch.pages} page${batch.pages === 1 ? "" : "s"}`;
  return `${pages} · ${batch.items} papers · ${batch.added} new`;
};

const retrying = (batch: Batch): boolean => batch.state === "harvesting" && batch.attempts > 0;

/** Where the batch's papers are: one segment per state, labelled underneath. */
function StageBar({ batch }: { batch: Batch }) {
  const present = STAGES.filter(([state]) => count(batch, state) > 0);
  return (
    <div className="stagebar">
      <div className="segments" role="img" aria-label={present.map(([s, l]) => `${count(batch, s)} ${l}`).join(", ")}>
        {present.map(([state, label]) => (
          <span
            key={state}
            className={`segment stage-${state}`}
            style={{ flexGrow: count(batch, state) }}
            title={`${count(batch, state)} ${label}`}
          />
        ))}
      </div>
      <ul className="legend">
        {present.map(([state, label]) => (
          <li key={state}>
            <span className={`swatch stage-${state}`} />
            {count(batch, state)} {label}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function BatchList({ batches }: { batches: readonly Batch[] }) {
  if (batches.length === 0) return null;
  return (
    <ul className="batches">
      {batches.map((batch) => (
        <li key={batch.id}>
          <span className={`badge state-${retrying(batch) ? "retrying" : batch.status}`}>
            {retrying(batch) ? `retrying · attempt ${batch.attempts + 1}` : batch.status}
          </span>
          <span className="what">
            {batch.category} since {batch.since}
          </span>
          <span className="progress">{harvest(batch)}</span>
          <span className="when">{time(batch.created_at)}</span>
          {batch.items > 0 && <StageBar batch={batch} />}
          {batch.last_error !== null && <span className="why">{batch.last_error}</span>}
        </li>
      ))}
    </ul>
  );
}
