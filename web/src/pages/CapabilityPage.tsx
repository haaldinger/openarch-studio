import { useEffect, useState } from "react";
import { PageIntro } from "../components/PageIntro";
import { apiFetch } from "../api";

interface Capability {
  name: string;
  owner: string;
  description: string;
  evidence: string;
}

interface Capabilities {
  native: Capability[];
  extensions: Capability[];
  runtimes: { name: string; role: string }[];
}

export function CapabilityPage() {
  const [data, setData] = useState<Capabilities | null>(null);

  useEffect(() => {
    apiFetch<Capabilities>("/api/capabilities")
      .then(setData)
      .catch(() => setData(null));
  }, []);

  const rows = data
    ? Array.from({ length: Math.max(data.native.length, data.extensions.length) }, (_, i) => ({
        native: data.native[i],
        ext: data.extensions[i],
      }))
    : [];

  return (
    <>
      <PageIntro
        eyebrow="Attribution"
        title="Capability map"
        lede="Studio never claims OpenArch's work as its own. Left is what the platform provides; right is what this POC adds on top."
      />

      <div className="ledger">
        <div className="ledger-head">
          <span className="tag native">OpenArch native</span>
          <span className="tag studio">Studio extension</span>
        </div>
        {rows.map((row, i) => (
          <div className="ledger-row" key={row.native?.name ?? row.ext?.name ?? i}>
            <span className="ledger-native" title={row.native?.description}>
              {row.native ? row.native.name : "—"}
            </span>
            <span className="ledger-sep" aria-hidden="true">
              →
            </span>
            <span className="ledger-ext" title={row.ext?.description}>
              {row.ext ? row.ext.name : "—"}
            </span>
          </div>
        ))}
      </div>

      {data && (
        <div className="runtimes">
          {data.runtimes.map((r) => (
            <div className="runtime" key={r.name}>
              <span className="runtime-name">{r.name}</span>
              <span className="runtime-role">{r.role}</span>
            </div>
          ))}
        </div>
      )}

      <aside className="aside-note">
        <h2>How this differs from the enterprise reference deployment</h2>
        <p className="muted">
          The <code>content-lake-app-deployment</code> POC shows OpenArch as the engine room of a
          large multi-source stack (Alfresco, Nuxeo, SharePoint) with ingestion and RAG hidden
          inside Java services. Studio does the opposite: it builds directly on OpenArch's REST API
          and makes every enrichment step visible. The <span className="tag studio">Studio</span>{" "}
          embeddings use the same <code>SysEmbeddings</code> shape, so content enriched here stays
          interoperable with that stack.
        </p>
      </aside>
    </>
  );
}
