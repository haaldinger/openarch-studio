import { Link } from "react-router-dom";
import { Folder, FileText } from "lucide-react";
import type { DocumentSummary } from "../types";

interface DocumentRowProps {
  doc: DocumentSummary;
  onOpenFolder?: (doc: DocumentSummary) => void;
}

/** One row in the Library list: folders navigate in place, files open the inspector. */
export function DocumentRow({ doc, onOpenFolder }: DocumentRowProps) {
  const Icon = doc.isFolderish ? Folder : FileText;
  const enriched = doc.mixinTypes?.includes("SysHasEmbeddings");

  const inner = (
    <>
      <Icon size={20} strokeWidth={1.6} className="doc-row-icon" />
      <span className="doc-row-main">
        <span className="doc-row-title">{doc.title ?? doc.name ?? doc.id}</span>
        <span className="doc-row-sub">{doc.primaryType}</span>
      </span>
      {!doc.isFolderish && (
        <span className={enriched ? "chip chip-ready" : "chip chip-stored"}>
          {enriched ? "Enriched" : "Stored"}
        </span>
      )}
    </>
  );

  if (doc.isFolderish && onOpenFolder) {
    return (
      <button type="button" className="doc-row doc-row-folder" onClick={() => onOpenFolder(doc)}>
        {inner}
      </button>
    );
  }
  return (
    <Link className="doc-row" to={`/documents/${doc.id}`}>
      {inner}
    </Link>
  );
}
