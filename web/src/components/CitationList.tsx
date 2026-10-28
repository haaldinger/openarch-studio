import { Link } from "react-router-dom";
import type { Citation } from "../types";

/** Citations link to the document inspector at the cited chunk and page. */
export function CitationList({ citations }: { citations: Citation[] }) {
  if (citations.length === 0) return null;
  return (
    <div className="citations">
      <p className="citations-label">Sources</p>
      <ol>
        {citations.map((c, i) => (
          <li key={`${c.chunkId}-${i}`}>
            <Link to={`/documents/${c.docId}?chunk=${encodeURIComponent(c.chunkId)}&page=${c.page}`}>
              {c.snippet ? c.snippet.slice(0, 90) : c.docId}
              {c.snippet && c.snippet.length > 90 ? "…" : ""}
            </Link>
            {typeof c.score === "number" && <span className="cite-score">{c.score.toFixed(2)}</span>}
            {typeof c.vectorScore === "number" && c.vectorScore !== c.score && (
              <span className="cite-score">vector {c.vectorScore.toFixed(2)}</span>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}
