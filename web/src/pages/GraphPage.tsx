import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Maximize2, Minimize2 } from "lucide-react";
import { PageIntro } from "../components/PageIntro";
import { ScopeBanner } from "../components/ScopeBanner";
import { ForceGraph, TYPE_COLOR } from "../components/ForceGraph";
import { ApiError, getGraph } from "../api";
import { useScope } from "../scope";
import type { GraphData } from "../types";

export function GraphPage() {
  const { scope } = useScope();
  const [data, setData] = useState<GraphData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const [hiddenTypes, setHiddenTypes] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    setLoading(true);
    getGraph(scope?.id)
      .then(setData)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load the graph."))
      .finally(() => setLoading(false));
  }, [scope?.id]);

  // Esc exits fullscreen.
  useEffect(() => {
    if (!expanded) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setExpanded(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [expanded]);

  const selectedNode = useMemo(
    () => data?.nodes.find((n) => n.id === selected) ?? null,
    [data, selected],
  );

  const typesPresent = useMemo(() => {
    const t = new Set(data?.nodes.map((n) => n.type));
    return (data?.entityTypes ?? []).filter((x) => t.has(x));
  }, [data]);

  // Entities grouped by type (the granular legend doubles as a filter).
  const countByType = useMemo(() => {
    const m = new Map<string, number>();
    data?.nodes.forEach((n) => m.set(n.type, (m.get(n.type) ?? 0) + 1));
    return m;
  }, [data]);

  // Relationships grouped by their verb/type, separating model vs. inferred edges.
  const relations = useMemo(() => {
    const m = new Map<string, { count: number; inferred: boolean }>();
    data?.edges.forEach((e) => {
      const cur = m.get(e.type) ?? { count: 0, inferred: !!e.inferred };
      cur.count += 1;
      m.set(e.type, cur);
    });
    return [...m.entries()].sort((a, b) => b[1].count - a[1].count);
  }, [data]);

  // Business objects: the distinct source documents the graph was extracted from.
  const docIds = useMemo(() => {
    const s = new Set<string>();
    data?.nodes.forEach((n) => n.docIds?.forEach((d) => s.add(d)));
    return [...s];
  }, [data]);

  function toggleType(t: string) {
    setHiddenTypes((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t);
      else next.add(t);
      return next;
    });
  }

  return (
    <>
      <PageIntro
        eyebrow="Studio + model · over OpenArch content"
        title="Knowledge graph"
        lede="Entities and relations the local model extracted from your enriched documents. The graph only shows what you're permitted to read."
      />

      <ScopeBanner />

      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}

      {loading ? (
        <p className="muted">Loading…</p>
      ) : !data || data.nodes.length === 0 ? (
        <div className="placeholder-panel">
          <p className="placeholder-title">No graph yet</p>
          <p className="muted">
            Enrich a document in the Library — the model extracts a graph automatically once
            embedding completes.
          </p>
        </div>
      ) : (
        <div className={expanded ? "graph-shell expanded" : "graph-shell"}>
          <div className="graph-toolbar">
            <p className="graph-count">
              {data.nodes.length} entities · {data.edges.length} relations ·{" "}
              {docIds.length} documents
            </p>
            <button type="button" className="btn-ghost" onClick={() => setExpanded((v) => !v)}>
              {expanded ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
              {expanded ? "Exit fullscreen" : "Expand"}
            </button>
          </div>

          <div className="graph-wrap">
            <div className="graph-canvas">
              <ForceGraph
                nodes={data.nodes}
                edges={data.edges}
                selected={selected}
                onSelect={setSelected}
                hiddenTypes={hiddenTypes}
              />
            </div>

            <aside className="graph-side">
              {selectedNode ? (
                <div className="graph-detail">
                  <p className="graph-detail-label" style={{ color: TYPE_COLOR[selectedNode.type] }}>
                    {selectedNode.type}
                  </p>
                  <p className="graph-detail-name">{selectedNode.label}</p>
                  {selectedNode.docIds && selectedNode.docIds.length > 0 && (
                    <>
                      <p className="muted graph-detail-sub">Appears in</p>
                      <ul className="graph-doclinks">
                        {selectedNode.docIds.map((d) => (
                          <li key={d}>
                            <Link to={`/documents/${d}`}>{d.slice(0, 8)}…</Link>
                          </li>
                        ))}
                      </ul>
                    </>
                  )}
                  <button type="button" className="link-button graph-clear" onClick={() => setSelected(null)}>
                    Clear selection
                  </button>
                </div>
              ) : (
                <p className="graph-hint muted">
                  Click a node to inspect it. Drag to reposition, scroll to zoom, drag the
                  background to pan.
                </p>
              )}

              <section className="graph-group">
                <h3 className="graph-group-head">Entities</h3>
                <div className="graph-legend">
                  {typesPresent.map((t) => {
                    const off = hiddenTypes.has(t);
                    return (
                      <button
                        key={t}
                        type="button"
                        className={off ? "legend-item off" : "legend-item"}
                        onClick={() => toggleType(t)}
                        aria-pressed={!off}
                        title={off ? "Show" : "Hide"}
                      >
                        <span className="legend-dot" style={{ background: TYPE_COLOR[t] }} />
                        {t}
                        <span className="legend-count">{countByType.get(t) ?? 0}</span>
                      </button>
                    );
                  })}
                </div>
              </section>

              <section className="graph-group">
                <h3 className="graph-group-head">Relationships</h3>
                <ul className="graph-rels">
                  {relations.map(([type, info]) => (
                    <li key={type} className="graph-rel">
                      <span className={info.inferred ? "rel-name inferred" : "rel-name"}>{type}</span>
                      <span className="rel-count">{info.count}</span>
                    </li>
                  ))}
                </ul>
              </section>

              <section className="graph-group">
                <h3 className="graph-group-head">Business objects</h3>
                <p className="graph-group-sub muted">Source documents the graph was built from.</p>
                <ul className="graph-doclinks">
                  {docIds.map((d) => (
                    <li key={d}>
                      <Link to={`/documents/${d}`}>{d.slice(0, 8)}…</Link>
                    </li>
                  ))}
                </ul>
              </section>
            </aside>
          </div>
        </div>
      )}
    </>
  );
}
