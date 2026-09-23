import { useState, type FormEvent } from "react";

import { Unauthorized, messageOf, submitBatch } from "../api/client";

const DAY_MS = 24 * 60 * 60 * 1000;

/** `YYYY-MM-DD` in UTC, which is how the API reads a date. */
const isoDate = (date: Date): string => date.toISOString().slice(0, 10);

/**
 * Queue a harvest of one arXiv category. The API answers as soon as the batch
 * is queued; a worker does the fetching, and the batch list shows it progress.
 */
export function BatchForm({
  onDone,
  onEnded,
}: {
  onDone: () => void;
  onEnded: () => void;
}) {
  const today = new Date();
  const [category, setCategory] = useState("cs.IR");
  const [since, setSince] = useState(isoDate(new Date(today.getTime() - 3 * DAY_MS)));
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setRunning(true);
    setError(null);
    try {
      await submitBatch({ category: category.trim(), since });
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
      <label>
        <span>Category</span>
        <input
          value={category}
          onChange={(event) => setCategory(event.target.value)}
          placeholder="cs.IR"
          spellCheck={false}
          disabled={running}
        />
      </label>
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
      <button type="submit" disabled={running || category.trim() === "" || since === ""}>
        {running ? "Queueing…" : "Fetch from arXiv"}
      </button>
      {error !== null && <p className="note error">{error}</p>}
    </form>
  );
}
