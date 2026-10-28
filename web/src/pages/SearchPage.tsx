import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { PageIntro } from "../components/PageIntro";
import { ScopeBanner } from "../components/ScopeBanner";
import { ApiError, search } from "../api";
import { useScope } from "../scope";
import { useSession } from "../session";
import type { SearchMode, SearchResponse } from "../types";

const MODES: { id: SearchMode; label: string; hint: string }[] = [
  { id: "keyword", label: "Keyword", hint: "Title match via OpenArch query" },
  { id: "semantic", label: "Semantic", hint: "Studio embedding + vector search" },
  { id: "hybrid", label: "Hybrid", hint: "OpenArch vector + BM25 keyword search, merged with RRF" },
  { id: "hxql", label: "HXQL", hint: "Advanced query, passed through" },
];

const PLACEHOLDER: Record<SearchMode, string> = {
  keyword: "e.g. policy",
  semantic: "Ask in natural language…",
  hybrid: "Meaning plus exact terms, e.g. invoice INV-2209",
  hxql: "SELECT * FROM SysContent WHERE …",
};

// HXQL is SQL-like but unfamiliar — give people working starting points.
const HXQL_SAMPLES: { label: string; query: string }[] = [
  { label: "All documents", query: "SELECT * FROM SysContent ORDER BY sys_title" },
  { label: "Files only", query: "SELECT * FROM SysFile ORDER BY sys_title" },
  { label: "Folders only", query: "SELECT * FROM SysFolder ORDER BY sys_title" },
  {
    label: "AI-ready (enriched) docs",
    query: "SELECT * FROM SysContent WHERE sys_mixinTypes = 'SysHasEmbeddings'",
  },
  {
    label: "Inside a folder (subtree)",
    query: "SELECT * FROM SysContent WHERE sys_ancestorIds = 'PASTE-FOLDER-ID'",
  },
  {
    label: "By exact title",
    query: "SELECT * FROM SysFile WHERE sys_title = '21Greek_GR01_InvoiceNo.tif'",
  },
  {
    label: "Extracted total over 1000",
    query: "SELECT * FROM SysContent WHERE cinctx_contextProperties.total > 1000",
  },
];

export function SearchPage() {
  const { scope } = useScope();
  const { generation } = useSession();
  const [mode, setMode] = useState<SearchMode>("keyword");
  const [query, setQuery] = useState("");
  const [response, setResponse] = useState<SearchResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Results belong to the identity that ran them.
  useEffect(() => {
    setResponse(null);
    setError(null);
  }, [generation]);

  async function run(event: FormEvent) {
    event.preventDefault();
    if (!query.trim()) return;
    setBusy(true);
    setError(null);
    try {
      setResponse(await search(mode, query, 10, scope?.id));
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 403
          ? err.message && err.message !== "Forbidden"
            ? err.message
            : "You do not have permission for this query."
          : "Search failed.",
      );
      setResponse(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageIntro
        eyebrow="OpenArch retrieval"
        title="Search"
        lede="Four ways to find the same corpus — all scoped to what you're allowed to read."
      />

      <ScopeBanner />

      <div className="segmented" role="tablist">
        {MODES.map((m) => (
          <button
            key={m.id}
            role="tab"
            aria-selected={mode === m.id}
            className={mode === m.id ? "seg active" : "seg"}
            onClick={() => setMode(m.id)}
            title={m.hint}
          >
            {m.label}
          </button>
        ))}
      </div>

      <form className="search-bar" onSubmit={run}>
        <input
          aria-label="Search query"
          value={query}
          placeholder={PLACEHOLDER[mode]}
          onChange={(e) => setQuery(e.target.value)}
        />
        <button type="submit" className="btn-primary" disabled={busy}>
          {busy ? "Searching…" : "Search"}
        </button>
      </form>

      {mode === "hxql" && (
        <div className="hxql-help">
          <span className="hxql-help-label">Examples</span>
          <div className="hxql-samples">
            {HXQL_SAMPLES.map((s) => (
              <button
                key={s.label}
                type="button"
                className="hxql-sample"
                title={s.query}
                onClick={() => setQuery(s.query)}
              >
                {s.label}
              </button>
            ))}
          </div>
          <p className="hxql-note muted">
            HXQL is SQL-like: <code>SELECT * FROM &lt;Type&gt; WHERE &lt;field&gt; = '…'</code>.
            Types include <code>SysContent</code>, <code>SysFile</code>, <code>SysFolder</code>.
            Click an example to load it, then edit and run.
          </p>
        </div>
      )}

      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}

      {response && (
        <>
          <div className="results">
            {response.results.length === 0 ? (
              <p className="muted">No matches.</p>
            ) : (
              response.results.map((r, i) => (
                <div className="result" key={`${r.id}-${i}`}>
                  <div className="result-head">
                    {r.id ? (
                      <Link
                        to={`/documents/${r.id}${r.page ? `?page=${r.page}` : ""}`}
                        className="result-title"
                      >
                        {r.title ?? r.id}
                      </Link>
                    ) : (
                      <span className="result-title">{r.title ?? "Untitled"}</span>
                    )}
                    {typeof r.score === "number" && (
                      <span className="result-score">{r.score.toFixed(3)}</span>
                    )}
                  </div>
                  {r.snippet && <p className="result-snippet">{r.snippet}</p>}
                </div>
              ))
            )}
          </div>

          <details className="provenance-trace">
            <summary>How this ran</summary>
            <ul>
              <li>
                Provided by <strong>{response.provenance.providedBy}</strong>
              </li>
              {response.provenance.extendedBy && (
                <li>
                  Extended by <strong>{response.provenance.extendedBy}</strong>
                </li>
              )}
              <li>
                Request path <code>{response.provenance.requestPath}</code>
              </li>
              {response.provenance.embeddingType && (
                <li>
                  Embedding type <code>{response.provenance.embeddingType}</code>
                </li>
              )}
              {response.provenance.rerank && (
                <li>
                  Rerank <strong>{response.provenance.rerank}</strong>
                </li>
              )}
              <li>{response.provenance.tookMs} ms</li>
            </ul>
          </details>
        </>
      )}
    </>
  );
}
