import { useState } from "react";

import { Unauthorized, messageOf, submitBatches } from "../api/client";

/**
 * Queue a batch per wishlist category, each fetching its latest daily
 * announcement from arXiv. The API answers as soon as the batches are queued;
 * workers do the fetching, and the batch list shows it.
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
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setRunning(true);
    setError(null);
    try {
      await submitBatches();
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
    <div className="batch">
      <div className="field">
        <span>Categories</span>
        <code>{categories.join(" ")}</code>
      </div>
      <button
        type="button"
        disabled={running}
        onClick={() => {
          void submit();
        }}
      >
        {running ? "Queueing…" : "Fetch today's announcements"}
      </button>
      {error !== null && <p className="note error">{error}</p>}
    </div>
  );
}
