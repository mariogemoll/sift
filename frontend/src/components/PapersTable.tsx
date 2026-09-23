import type { Paper } from "../api/client";

const formatDate = (iso: string): string =>
  new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });

export function PapersTable({ papers }: { papers: readonly Paper[] }) {
  return (
    <table className="papers">
      <thead>
        <tr>
          <th>Published</th>
          <th>Title</th>
          <th>Authors</th>
          <th>Categories</th>
        </tr>
      </thead>
      <tbody>
        {papers.length === 0 ? (
          <tr className="empty">
            <td colSpan={4}>
              <strong>No papers yet.</strong>
              <span>Fetch a category from arXiv above.</span>
            </td>
          </tr>
        ) : (
          papers.map((paper) => (
            <tr key={paper.arxiv_id}>
              <td className="date">{formatDate(paper.published_at)}</td>
              <td>
                <a
                  href={`https://arxiv.org/abs/${paper.arxiv_id}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  {paper.title}
                </a>
              </td>
              <td>{paper.authors.join(", ")}</td>
              <td className="categories">{paper.categories.join(" ")}</td>
            </tr>
          ))
        )}
      </tbody>
    </table>
  );
}
