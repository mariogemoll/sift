import type { Profile, Verdict } from "../api/client";

export const formatDate = (iso: string): string =>
  new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });

export const percent = (value: number): string => `${Math.round(value * 100)}`;

const AUTHORS_SHOWN = 3;

export const authors = (names: readonly string[]): string =>
  names.length <= AUTHORS_SHOWN
    ? names.join(", ")
    : `${names.slice(0, AUTHORS_SHOWN).join(", ")} +${names.length - AUTHORS_SHOWN}`;

export type Standing = "read" | "reading" | "passed-over" | "blocked" | "unscreened";

/**
 * Where a paper is in the funnel. A screen that passed but has no full verdict
 * yet is being fetched or judged, or failed on the way there.
 */
export const standing = (verdict: Verdict | null, profile: Profile): Standing => {
  if (verdict === null) return "unscreened";
  if (!verdict.eligible) return "blocked";
  if (verdict.stage === "full") return "read";
  return verdict.total >= profile.screen_threshold ? "reading" : "passed-over";
};

export const STANDING_LABEL: Record<Standing, string> = {
  read: "read in full",
  reading: "passed the screen",
  "passed-over": "abstract only",
  blocked: "blocked",
  unscreened: "not screened yet",
};

/** A position on the levels written for a criterion: an ordering, not a percentage. */
export function Meter({ value }: { value: number }) {
  return (
    <span className="meter" aria-label={percent(value)}>
      <span style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }} />
    </span>
  );
}
