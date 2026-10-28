import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Folder, FileText, Trash2 } from "lucide-react";
import type { AccessSummary, DocumentSummary } from "../types";

interface DocumentRowProps {
  doc: DocumentSummary;
  onOpenFolder?: (doc: DocumentSummary) => void;
  onDeleteFolder?: (doc: DocumentSummary) => void;
  /** Called once when a rule on this row reaches its end time. */
  onAccessExpired?: () => void;
  baselineMode?: boolean;
}

const MINE_LABEL = { read: "Read only", edit: "Can edit", manage: "Manage" } as const;
const SHOWN_PRINCIPALS = 3;
const DAY_MS = 24 * 60 * 60 * 1000;

function countdown(ms: number): string {
  const total = Math.max(0, Math.ceil(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = String(total % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

function ExpiryChip({ expiresAt, onExpired }: { expiresAt: string; onExpired?: () => void }) {
  const end = Date.parse(expiresAt);
  const [now, setNow] = useState(() => Date.now());
  const fired = useRef(false);
  const soon = end - now <= DAY_MS;

  useEffect(() => {
    if (!soon || fired.current) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [soon]);

  useEffect(() => {
    if (end <= now && !fired.current) {
      fired.current = true;
      onExpired?.();
    }
  }, [end, now, onExpired]);

  if (end <= now) return null;
  const text = soon
    ? `expires in ${countdown(end - now)}`
    : `until ${new Date(end).toLocaleDateString(undefined, { month: "short", day: "numeric" })}`;
  return <span className="chip chip-expiry">{text}</span>;
}

function AccessBadges({ access, onExpired }: { access: AccessSummary; onExpired?: () => void }) {
  const shared = access.sharedWith ?? [];
  const extra = shared.length - SHOWN_PRINCIPALS;
  return (
    <span className="doc-row-access">
      {access.mine && <span className="chip chip-access">{MINE_LABEL[access.mine]}</span>}
      {shared.length > 0 && (
        <span className="doc-row-shared" aria-label={`Shared with ${shared.map((p) => p.name).join(", ")}`}>
          {shared.slice(0, SHOWN_PRINCIPALS).map((p) => (
            <span key={`${p.kind}:${p.name}`} className={`chip chip-principal chip-${p.kind}`}>
              {p.name}
            </span>
          ))}
          {extra > 0 && <span className="chip chip-principal">+{extra}</span>}
        </span>
      )}
      {access.expiresAt && <ExpiryChip expiresAt={access.expiresAt} onExpired={onExpired} />}
    </span>
  );
}

/** One row in the Library list: folders navigate in place, files open the inspector. */
export function DocumentRow({
  doc,
  onOpenFolder,
  onDeleteFolder,
  onAccessExpired,
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
      {doc.access && <AccessBadges access={doc.access} onExpired={onAccessExpired} />}
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
