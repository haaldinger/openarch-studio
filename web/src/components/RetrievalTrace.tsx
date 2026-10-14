interface RetrievalTraceProps {
  count: number | null;
}

/** Shows the agent's provenance chain and how much permitted evidence it used. */
export function RetrievalTrace({ count }: RetrievalTraceProps) {
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
        <li>
          <span className="tag model">Local model</span> composes a cited answer
        </li>
      </ol>
    </details>
  );
}
