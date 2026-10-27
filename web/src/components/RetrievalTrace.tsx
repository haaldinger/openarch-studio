interface RetrievalTraceProps {
  count: number | null;
  rerank?: string | null;
}

/** Shows the agent's provenance chain and how much permitted evidence it used. */
export function RetrievalTrace({ count, rerank }: RetrievalTraceProps) {
  return (
    <details className="provenance-trace retrieval-trace">
      <summary>Retrieval trace</summary>
      <ol className="trace-flow">
        <li>
          <span className="tag studio">Studio agent</span> embeds your question
        </li>
        <li>
          <span className="tag native">OpenArch</span> returns permitted chunks
          {count !== null && <strong> · {count} used</strong>}
        </li>
        {rerank && (
          <li>
            <span className="tag studio">Reranker</span>{" "}
            {rerank === "reranked" ? "Reranked" : `Rerank ${rerank}`}
          </li>
        )}
        <li>
          <span className="tag model">Local model</span> composes a cited answer
        </li>
      </ol>
    </details>
  );
}
