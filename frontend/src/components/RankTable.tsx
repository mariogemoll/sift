import { Fragment, useState } from "react";

import type { Assessed, Profile, Verdict } from "../api/client";
import {
  STANDING_LABEL,
  type Standing,
  authors,
  formatDate,
  percent,
  standing,
} from "./standing";

/** A shape per standing, so the funnel is readable without telling colors apart. */
const MARK: Record<Standing, string> = {
  read: "●",
  reading: "◐",
  "passed-over": "○",
  blocked: "✕",
  unscreened: "·",
};

interface Column {
  id: string;
  label: string;
  explains: string;
  value: (verdict: Verdict) => number | null | undefined;
}

const columnsOf = (profile: Profile): Column[] => [
  {
    id: "merit",
    label: "merit",
    explains: "How strong the contribution and its evidence are; judged from the full text only",
    value: (verdict) => verdict.merit,
  },
  ...profile.criteria
    .filter((criterion) => criterion.kind === "want")
    .map((criterion) => ({
      id: criterion.id,
      label: criterion.id.replaceAll("_", " "),
      explains: `${criterion.requirement} (weight ${criterion.weight})`,
      value: (verdict: Verdict) => verdict.per_criterion[criterion.id],
    })),
];

/** One criterion's position on its levels, as a bar rising from the cell's floor. */
function Cell({ value, column }: { value: number | null | undefined; column: Column }) {
  if (value === null || value === undefined) {
    return (
      <td className="cell none" title={`${column.label}: not judged`}>
        <span className="dash" />
      </td>
    );
  }
  return (
    <td className="cell" title={`${column.label}: ${percent(value)}\n${column.explains}`}>
      <span className="column" style={{ height: `${Math.max(0.06, Math.min(1, value)) * 100}%` }} />
    </td>
  );
}

function Details({ assessed, span }: { assessed: Assessed; span: number }) {
  const { paper, verdict } = assessed;
  return (
    <tr className="details">
      <td colSpan={span}>
        <p className="meta">
          <span>{formatDate(paper.published_at)}</span>
          <span>{authors(paper.authors)}</span>
          <span className="categories">{paper.categories.join(" ")}</span>
          {verdict !== null && verdict.blocked_by.length > 0 && (
            <span className="blocked">blocked by {verdict.blocked_by.join(", ")}</span>
          )}
        </p>
        {verdict !== null && verdict.notes.length > 0 && (
          <ul className="notes">
            {verdict.notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        )}
        <p className="abstract">{paper.abstract}</p>
      </td>
    </tr>
  );
}

/**
 * The ranking at a glance: one row per paper, its total as a bar, and every
 * criterion as a small column, so a row reads as a profile and a column as how
 * the papers compare on one interest. A row opens to the paper's details.
 */
export function RankTable({
  papers,
  profile,
  offset,
}: {
  papers: readonly Assessed[];
  profile: Profile;
  offset: number;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const columns = columnsOf(profile);
  const span = 3 + columns.length;

  if (papers.length === 0) {
    return (
      <div className="empty">
        <strong>No papers in this window.</strong>
        <span>Fetch from arXiv above, or widen the window.</span>
      </div>
    );
  }

  return (
    <>
      <ul className="marks-legend">
        {(Object.keys(MARK) as Standing[]).map((key) => (
          <li key={key} className={`standing-${key}`}>
            <span className="mark">{MARK[key]}</span> {STANDING_LABEL[key]}
          </li>
        ))}
      </ul>
      <div className="scroller">
        <table className="ranks">
          <thead>
            <tr>
              <th className="rank">#</th>
              <th className="total">score</th>
              <th className="paper">paper</th>
              {columns.map((column) => (
                <th key={column.id} className="criterion" title={column.explains}>
                  <span>{column.label}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {papers.map((assessed, index) => {
              const { paper, verdict } = assessed;
              const where = standing(verdict, profile);
              const isOpen = open === paper.arxiv_id;
              return (
                <Fragment key={paper.arxiv_id}>
                  <tr
                    className={`row standing-${where}${isOpen ? " open" : ""}`}
                    onClick={() => setOpen(isOpen ? null : paper.arxiv_id)}
                  >
                    <td className="rank">{offset + index + 1}</td>
                    <td
                      className="total"
                      title={
                        verdict === null
                          ? "not screened yet"
                          : verdict.stage === "full"
                            ? "merit and fit, from the full text"
                            : "fit, from the abstract"
                      }
                    >
                      {verdict !== null && (
                        <>
                          <span className="value">{percent(verdict.total)}</span>
                          <span className="track">
                            <span style={{ width: `${Math.min(1, verdict.total) * 100}%` }} />
                          </span>
                        </>
                      )}
                    </td>
                    <td className="paper">
                      <span className="mark" title={STANDING_LABEL[where]} aria-label={STANDING_LABEL[where]}>
                        {MARK[where]}
                      </span>
                      <a
                        href={`https://arxiv.org/abs/${paper.arxiv_id}`}
                        target="_blank"
                        rel="noreferrer"
                        title={paper.title}
                        onClick={(event) => event.stopPropagation()}
                      >
                        {paper.title}
                      </a>
                    </td>
                    {columns.map((column) => (
                      <Cell
                        key={column.id}
                        column={column}
                        value={verdict === null ? null : column.value(verdict)}
                      />
                    ))}
                  </tr>
                  {isOpen && <Details assessed={assessed} span={span} />}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}
