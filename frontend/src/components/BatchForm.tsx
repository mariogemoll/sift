import { useState, type FormEvent } from "react";

import { Unauthorized, messageOf, submitBatches } from "../api/client";

const DAY_MS = 24 * 60 * 60 * 1000;

/** `YYYY-MM-DD` in UTC, which is how the API reads a date. */
const isoDate = (date: Date): string => date.toISOString().slice(0, 10);

/**
 * Queue a harvest of the wishlist's categories. The API answers as soon as the
 * batches are queued; workers do the fetching, and the batch list shows it.
 */
export function BatchForm({
  categories,
  onDone,
  onEnded,
}: {
  categories: readonly string[];
  onDone: () => void;
  onEnded: () => void;
}) {
  const today = new Date();
  const [since, setSince] = useState(isoDate(new Date(today.getTime() - 3 * DAY_MS)));
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setRunning(true);
    setError(null);
    try {
      await submitBatches({ since });
      onDone();
    } catch (thrown: unknown) {
      if (thrown instanceof Unauthorized) {
        onEnded();
        return;
      }
      setError(messageOf(thrown));
    } finally {
      setRunning(false);
    }
  };

  return (
    <form
      className="batch"
      onSubmit={(event) => {
        void submit(event);
      }}
    >
      <div className="field">
        <span>Categories</span>
        <code>{categories.join(" ")}</code>
      </div>
      <label>
        <span>Since</span>
        <input
          type="date"
          value={since}
          max={isoDate(today)}
          onChange={(event) => setSince(event.target.value)}
          disabled={running}
        />
      </label>
      <button type="submit" disabled={running || since === ""}>
        {running ? "Queueing…" : "Fetch from arXiv"}
      </button>
      {error !== null && <p className="note error">{error}</p>}
    </form>
  );
}
