import type { Assessed, Profile, Verdict } from "../api/client";
import { Meter, STANDING_LABEL, authors, formatDate, percent, standing } from "./standing";

function Criteria({ verdict, profile }: { verdict: Verdict; profile: Profile }) {
  const wants = profile.criteria.filter((criterion) => criterion.kind === "want");
  return (
    <ul className="criteria">
      {verdict.merit !== null && (
        <li title="How strong the contribution and its evidence are, from the full text">
          <span className="name">merit</span>
          <Meter value={verdict.merit} />
        </li>
      )}
      {wants.map((criterion) => {
        const value = verdict.per_criterion[criterion.id];
        return (
          <li key={criterion.id} title={criterion.requirement}>
            <span className="name">{criterion.id}</span>
            {value === undefined ? <span className="missing">–</span> : <Meter value={value} />}
          </li>
        );
      })}
    </ul>
  );
}

function Row({ assessed, profile }: { assessed: Assessed; profile: Profile }) {
  const { paper, verdict } = assessed;
  const where = standing(verdict, profile);
  return (
    <li className={`paper standing-${where}`}>
      <div className="score" title={verdict?.stage === "full" ? "merit and fit" : "fit"}>
        {verdict === null ? "·" : percent(verdict.total)}
      </div>
      <div className="body">
        <a
          className="title"
          href={`https://arxiv.org/abs/${paper.arxiv_id}`}
          target="_blank"
          rel="noreferrer"
        >
          {paper.title}
        </a>
        <p className="meta">
          <span className={`badge standing standing-${where}`}>{STANDING_LABEL[where]}</span>
          {verdict !== null && verdict.blocked_by.length > 0 && (
            <span className="blocked">by {verdict.blocked_by.join(", ")}</span>
          )}
          {verdict?.needs_review === true && (
            <span className="review" title={verdict.notes.join("\n")}>
              uncertain
            </span>
          )}
          <span>{formatDate(paper.published_at)}</span>
          <span>{authors(paper.authors)}</span>
          <span className="categories">{paper.categories.join(" ")}</span>
        </p>
        {verdict !== null && <Criteria verdict={verdict} profile={profile} />}
        <details>
          <summary>Abstract</summary>
          <p>{paper.abstract}</p>
        </details>
      </div>
    </li>
  );
}

export function PaperList({
  papers,
  profile,
}: {
  papers: readonly Assessed[];
  profile: Profile;
}) {
  if (papers.length === 0) {
    return (
      <div className="empty">
        <strong>No papers in this window.</strong>
        <span>Fetch a category from arXiv above, or widen the window.</span>
      </div>
    );
  }
  return (
    <ol className="papers">
      {papers.map((assessed) => (
        <Row key={assessed.paper.arxiv_id} assessed={assessed} profile={profile} />
      ))}
    </ol>
  );
}
