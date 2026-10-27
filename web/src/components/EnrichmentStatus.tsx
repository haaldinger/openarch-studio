import type { JobStage } from "../types";

// Which layer owns each enrichment stage — shown so the pipeline's provenance is explicit.
const OWNER: Record<string, string> = {
  stored: "OpenArch",
  extracted: "Studio + Docling (Tika fallback)",
  chunked: "Studio",
  embedded: "Studio + model",
  indexed: "OpenArch",
};

export function EnrichmentStatus({ stages }: { stages: JobStage[] }) {
  return (
    <ol className="stages" aria-label="Enrichment stages">
      {stages.map((stage) => (
        <li key={stage.name} className={`stage stage-${stage.status}`}>
          <span className="stage-dot" aria-hidden="true" />
          <span className="stage-body">
            <span className="stage-name">{stage.name}</span>
            <span className="stage-owner">{OWNER[stage.name] ?? "Studio"}</span>
            {stage.detail && <span className="stage-detail">{stage.detail}</span>}
          </span>
        </li>
      ))}
    </ol>
  );
}
