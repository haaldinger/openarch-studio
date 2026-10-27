import { Link } from "react-router-dom";
import { Folder, FileText, Trash2 } from "lucide-react";
import type { DocumentSummary } from "../types";

interface DocumentRowProps {
  doc: DocumentSummary;
  onOpenFolder?: (doc: DocumentSummary) => void;
  onDeleteFolder?: (doc: DocumentSummary) => void;
  baselineMode?: boolean;
}

/** One row in the Library list: folders navigate in place, files open the inspector. */
export function DocumentRow({
  doc,
  onOpenFolder,
  onDeleteFolder,
  baselineMode = false,
}: DocumentRowProps) {
  const Icon = doc.isFolderish ? Folder : FileText;
  const enriched = doc.mixinTypes?.includes("SysHasEmbeddings");
  const label = doc.title ?? doc.name ?? doc.id;

  const inner = (
    <>
      <Icon size={20} strokeWidth={1.6} className="doc-row-icon" />
      <span className="doc-row-main">
        <span className="doc-row-title">{label}</span>
        <span className="doc-row-sub">{doc.primaryType}</span>
      </span>
      {!doc.isFolderish &&
        !baselineMode &&
        typeof doc.documentType === "string" &&
        doc.documentType && (
          <span className="chip chip-type">{doc.documentType}</span>
        )}
      {!doc.isFolderish && (
        <span className={enriched ? "chip chip-ready" : "chip chip-stored"}>
          {enriched ? "Enriched" : "Stored"}
        </span>
      )}
    </>
  );

  if (doc.isFolderish && onOpenFolder) {
    return (
      <div className="doc-row-wrap">
        <button type="button" className="doc-row doc-row-folder" onClick={() => onOpenFolder(doc)}>
          {inner}
        </button>
        {onDeleteFolder && (
          <button
            type="button"
            className="doc-row-delete"
            aria-label={`Delete folder ${label}`}
            onClick={() => onDeleteFolder(doc)}
          >
            <Trash2 size={16} strokeWidth={1.7} />
          </button>
        )}
      </div>
    );
  }
  return (
    <Link className="doc-row" to={`/documents/${doc.id}`}>
      {inner}
    </Link>
  );
}
