import type { Async } from "../api/useAsync";
import type { Health } from "../api/client";

export function HealthBadge({ health }: { health: Async<Health> }) {
  if (health.status === "loading") {
    return <span className="badge pending">checking…</span>;
  }
  if (health.status === "failed") {
    return <span className="badge bad">api unreachable</span>;
  }
  const { ok, database, revision } = health.value;
  if (!ok) {
    return (
      <span className="badge bad">
        {database ? "not migrated" : "database unreachable"}
      </span>
    );
  }
  return <span className="badge good">db ok · {revision}</span>;
}
