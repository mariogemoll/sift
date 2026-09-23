import { useState, type FormEvent } from "react";

import { Unauthorized, messageOf, submitBatch, type BatchResult } from "../api/client";

const DAY_MS = 24 * 60 * 60 * 1000;

/** `YYYY-MM-DD` in UTC, which is how the API reads a date. */
const isoDate = (date: Date): string => date.toISOString().slice(0, 10);

const summary = (result: BatchResult): string => {
  const more =
    result.matched > result.fetched
      ? ` — the first page of ${result.matched}`
      : "";
  return `Fetched ${result.fetched} from ${result.category} since ${result.since}${more}; ${result.added} new.`;
};

/**
 * Pull one arXiv category into the papers table. The request runs to
 * completion before it answers, so the form stays busy until the rows exist.
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
  const [outcome, setOutcome] = useState<
    { ok: true; text: string } | { ok: false; text: string } | null
  >(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setRunning(true);
    setOutcome(null);
    try {
      const result = await submitBatch({ category: category.trim(), since });
      setOutcome({ ok: true, text: summary(result) });
      onDone();
    } catch (thrown: unknown) {
      if (thrown instanceof Unauthorized) {
        onEnded();
        return;
      }
      setOutcome({ ok: false, text: messageOf(thrown) });
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
        {running ? "Fetching…" : "Fetch from arXiv"}
      </button>
      {outcome !== null && (
        <p className={outcome.ok ? "note" : "note error"}>{outcome.text}</p>
      )}
    </form>
  );
}
