import { useCallback, useEffect, useState } from "react";
import { useParams, useNavigate, useSearchParams, Link } from "react-router-dom";
import { FileText, Search, FolderInput } from "lucide-react";
import { PageIntro } from "../components/PageIntro";
import { Modal } from "../components/Modal";
import { PermissionsPanel } from "../components/PermissionsPanel";
import {
  ApiError,
  contentUrl,
  previewUrl,
  getDocument,
  getDocumentEmbeddings,
  getDocumentEmbeddingsRaw,
  deleteDocument,
  moveDocument,
  listFiles,
  listFolders,
} from "../api";
import type { DocumentDetail, EmbeddingChunk } from "../types";

type Tab = "metadata" | "permissions" | "content" | "embeddings" | "raw";

const ROOT_ID = "00000000-0000-0000-0000-000000000000";

const SYS_LABEL: Record<string, string> = {
  sys_title: "Title",
  sys_name: "Name",
  sys_primaryType: "Type",
  sys_path: "Path",
  sys_created: "Created",
  sys_modified: "Modified",
  sys_creator: "Creator",
};

export function DocumentPage({ baselineMode = false }: { baselineMode?: boolean }) {
  const { docId } = useParams<{ docId: string }>();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const page = Number(searchParams.get("page")) || undefined;
  const [doc, setDoc] = useState<DocumentDetail | null>(null);
  const [embeddings, setEmbeddings] = useState<EmbeddingChunk[] | null>(null);
  const [embRaw, setEmbRaw] = useState<Record<string, unknown>[] | null>(null);
  const [embView, setEmbView] = useState<"chunks" | "raw">("chunks");
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>(page ? "content" : "metadata");
  const [finderItems, setFinderItems] = useState<{ id: string; title: string | null }[]>([]);
  const [finderQuery, setFinderQuery] = useState("");
  const [folders, setFolders] = useState<{ id: string; title: string | null }[]>([]);
  const [moveOpen, setMoveOpen] = useState(false);
  const [moveTarget, setMoveTarget] = useState(ROOT_ID);
  const [moving, setMoving] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);

  useEffect(() => {
    if (!docId) return;
    setError(null);
    getDocument(docId)
      .then(setDoc)
      .catch((err) =>
        setError(
          err instanceof ApiError && err.status === 403
            ? "You do not have permission to view this document."
            : "Could not load the document.",
        ),
      );
  }, [docId]);

  useEffect(() => {
    if (page) setTab("content");
  }, [docId, page]);

  useEffect(() => {
    if (tab === "embeddings" && docId && embeddings === null) {
      getDocumentEmbeddings(docId)
        .then((e) => setEmbeddings(e.embeddings))
        .catch(() => setEmbeddings([]));
    }
    if (tab === "embeddings" && embView === "raw" && docId && embRaw === null) {
      getDocumentEmbeddingsRaw(docId)
        .then((e) => setEmbRaw(e.raw))
        .catch(() => setEmbRaw([]));
    }
  }, [tab, docId, embeddings, embView, embRaw]);

  const loadFinder = useCallback(() => {
    listFiles()
      .then(setFinderItems)
      .catch(() => setFinderItems([]));
  }, []);
  useEffect(loadFinder, [loadFinder]);
  useEffect(() => {
    listFolders()
      .then(setFolders)
      .catch(() => setFolders([]));
  }, []);

  const title = (doc?.sys_title as string) || (doc?.sys_name as string) || docId || "";
  const mixins = (doc?.sys_mixinTypes as string[]) ?? [];
  const enriched = mixins.includes("SysHasEmbeddings");

  const filtered = finderItems.filter((f) =>
    (f.title ?? f.id).toLowerCase().includes(finderQuery.toLowerCase()),
  );

  async function handleDelete() {
    if (!docId) return;
    try {
      await deleteDocument(docId);
      setDeleteOpen(false);
      loadFinder();
      navigate("/documents");
    } catch {
      setError("Could not delete the document.");
    }
  }

  async function handleMove() {
    if (!docId) return;
    setMoving(true);
    try {
      await moveDocument(docId, moveTarget || ROOT_ID);
      setMoveOpen(false);
      loadFinder();
      getDocument(docId).then(setDoc).catch(() => undefined);
    } catch {
      setError("Could not move the document.");
    } finally {
      setMoving(false);
    }
  }

  return (
    <>
      <PageIntro
        eyebrow="OpenArch record"
        title="Documents"
        lede="Browse your documents and inspect everything OpenArch holds — without leaving this screen."
      />

      <div className="doc-shell">
        <aside className="doc-finder">
          <div className="finder-search">
            <Search size={15} aria-hidden="true" />
            <input
              className="finder-input"
              placeholder="Find a document…"
              value={finderQuery}
              onChange={(e) => setFinderQuery(e.target.value)}
            />
          </div>
          {finderItems.length === 0 ? (
            <p className="muted finder-empty">No documents yet.</p>
          ) : (
            <ul className="finder-list">
              {filtered.map((f) => (
                <li key={f.id}>
                  <Link
                    to={`/documents/${f.id}`}
                    className={f.id === docId ? "finder-item active" : "finder-item"}
                  >
                    <FileText size={14} aria-hidden="true" />
                    <span className="finder-title">{f.title ?? f.id}</span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </aside>

        <section className="doc-main">
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}

          {!docId ? (
            <div className="placeholder-panel">
              <p className="placeholder-title">Select a document</p>
              <p className="muted">
                Pick one from the list to inspect its metadata, permissions, content, and
                embeddings — all on this screen.
              </p>
            </div>
          ) : (
            <>
              <div className="doc-main-head">
                <h2 className="doc-main-title">{String(title)}</h2>
                <div className="doc-actions">
                  <button type="button" className="btn-ghost" onClick={() => setMoveOpen(true)}>
                    <FolderInput size={15} /> Move
                  </button>
                  <button type="button" className="btn-danger" onClick={() => setDeleteOpen(true)}>
                    Delete
                  </button>
                </div>
              </div>

              <div className="tabs" role="tablist">
        {(["metadata", "permissions", "content", "embeddings", "raw"] as Tab[]).map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            className={tab === t ? "tab active" : "tab"}
            onClick={() => setTab(t)}
          >
            {t === "raw" ? "Raw JSON" : t[0].toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {doc && tab === "metadata" && (
        <div className="kv-panel">
          <p className="panel-attr">
            <span className="tag native">OpenArch</span> stores these values.
          </p>
          {Object.entries(SYS_LABEL).map(([key, label]) =>
            doc[key] !== undefined ? (
              <div className="kv-row" key={key}>
                <span className="kv-key">{label}</span>
                <span className="kv-val">{formatValue(doc[key])}</span>
              </div>
            ) : null,
          )}
          <div className="kv-row">
            <span className="kv-key">AI-ready</span>
            <span className="kv-val">
              {enriched ? (
                <span className="chip chip-ready">Enriched by Studio</span>
              ) : (
                <span className="chip chip-stored">Not yet enriched</span>
              )}
            </span>
          </div>
          <ExtractedFields
            properties={doc.cinctx_contextProperties as Record<string, unknown> | undefined}
            baselineMode={baselineMode}
          />
        </div>
      )}

      {tab === "permissions" && docId && (
        <div className="kv-panel">
          <p className="panel-attr">
            <span className="tag native">OpenArch</span> decides who can access this item.
          </p>
          <PermissionsPanel docId={docId} />
        </div>
      )}

      {tab === "content" && (
        <div className="kv-panel">
          <p className="panel-attr">
            Binary streamed from <span className="tag native">OpenArch</span>.
          </p>
          <DocumentViewer
            docId={docId}
            mime={(doc?.sysfile_blob as { mimeType?: string })?.mimeType}
            page={page}
          />
        </div>
      )}

      {tab === "embeddings" && (
        <div className="kv-panel">
          <p className="panel-attr">
            <span className="tag studio">Studio</span> generated these vectors;{" "}
            <span className="tag native">OpenArch</span> stores them as a{" "}
            <code>SysEmbeddings</code> child (mixin <code>SysHasEmbeddings</code>).
          </p>
          <div className="emb-toggle" role="tablist" aria-label="Embeddings view">
            <button
              type="button"
              className={embView === "chunks" ? "emb-toggle-btn active" : "emb-toggle-btn"}
              onClick={() => setEmbView("chunks")}
            >
              Chunks
            </button>
            <button
              type="button"
              className={embView === "raw" ? "emb-toggle-btn active" : "emb-toggle-btn"}
              onClick={() => setEmbView("raw")}
            >
              Raw JSON
            </button>
          </div>
          {embView === "raw" ? (
            embRaw === null ? (
              <p className="muted">Loading…</p>
            ) : embRaw.length === 0 ? (
              <p className="empty-state">No embeddings — this document isn't enriched yet.</p>
            ) : (
              <pre className="json">{JSON.stringify(embRaw, null, 2)}</pre>
            )
          ) : embeddings === null ? (
            <p className="muted">Loading…</p>
          ) : embeddings.length === 0 ? (
            <p className="empty-state">No embeddings — this document isn't enriched yet.</p>
          ) : (
            <div className="emb-list">
              {embeddings.map((chunk, i) => (
                <div className="emb-row" key={chunk.id || i}>
                  <div className="emb-head">
                    <span className="emb-index">chunk {i + 1}</span>
                    <span className="emb-dims">{chunk.dims}-dim vector</span>
                  </div>
                  <VectorBars values={chunk.preview} />
                  <p className="emb-text">{chunk.text}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {doc && tab === "raw" && (
        <div className="kv-panel">
          <p className="panel-attr">The exact OpenArch DocumentDTO.</p>
          <pre className="json">{JSON.stringify(doc, null, 2)}</pre>
        </div>
      )}
            </>
          )}
        </section>
      </div>

      <Modal
        open={moveOpen}
        title="Move document"
        onClose={() => setMoveOpen(false)}
        footer={
          <>
            <button type="button" className="btn-ghost" onClick={() => setMoveOpen(false)}>
              Cancel
            </button>
            <button
              type="button"
              className="btn-primary"
              onClick={() => void handleMove()}
              disabled={moving}
            >
              {moving ? "Moving…" : "Move here"}
            </button>
          </>
        }
      >
        <label className="modal-label" htmlFor="move-target">
          Destination folder
        </label>
        <select
          id="move-target"
          className="modal-input"
          value={moveTarget}
          onChange={(e) => setMoveTarget(e.target.value)}
        >
          <option value={ROOT_ID}>Library (root)</option>
          {folders.map((f) => (
            <option key={f.id} value={f.id}>
              {f.title ?? f.id}
            </option>
          ))}
        </select>
        <p className="modal-hint">
          Uses OpenArch's native <code>move</code> — permissions and the subtree move with it.
        </p>
      </Modal>

      <Modal
        open={deleteOpen}
        title="Delete document"
        onClose={() => setDeleteOpen(false)}
        footer={
          <>
            <button type="button" className="btn-ghost" onClick={() => setDeleteOpen(false)}>
              Cancel
            </button>
            <button type="button" className="btn-danger" onClick={() => void handleDelete()}>
              Delete document
            </button>
          </>
        }
      >
        <p className="modal-confirm">
          Delete <strong>{String(title)}</strong>? It will be removed from search, chat, and the
          graph.
        </p>
      </Modal>
    </>
  );
}

function ExtractedFields({
  properties,
  baselineMode,
}: {
  properties?: Record<string, unknown>;
  baselineMode: boolean;
}) {
  const type = properties?.document_type;
  if (baselineMode || !properties || !type) return null;
  const fields = Object.entries(properties).filter(([key]) => key !== "document_type");
  return (
    <section className="extracted" aria-label="Extracted fields">
      <div className="extracted-head">
        <span className="chip chip-type">{String(type)}</span>
        <span className="panel-attr">AI-extracted · Studio + model</span>
      </div>
      {fields.map(([key, value]) => (
        <div className="kv-row" key={key}>
          <span className="kv-key">{key}</span>
          <span className="kv-val">{formatValue(value)}</span>
        </div>
      ))}
    </section>
  );
}

function formatValue(value: unknown): string {
  if (value && typeof value === "object") {
    const v = value as Record<string, unknown>;
    if (v.username) return String(v.username);
    return JSON.stringify(value);
  }
  return String(value);
}

/** Compact preview of a chunk's embedding vector as signed bars. */
function VectorBars({ values }: { values: number[] }) {
  const max = Math.max(0.0001, ...values.map((v) => Math.abs(v)));
  return (
    <div className="vec-bars" aria-hidden="true">
      {values.map((v, i) => (
        <span
          key={i}
          className={v >= 0 ? "vec-bar pos" : "vec-bar neg"}
          style={{ height: `${(Math.abs(v) / max) * 100}%` }}
        />
      ))}
    </div>
  );
}

/** Inline viewer: images render directly (TIFF converted server-side), PDFs in a frame. */
function DocumentViewer({ docId, mime, page }: { docId: string; mime?: string; page?: number }) {
  const [failed, setFailed] = useState(false);

  if (mime?.startsWith("image/") && !failed) {
    return (
      <img
        className="doc-image"
        src={previewUrl(docId)}
        alt="Document preview"
        onError={() => setFailed(true)}
      />
    );
  }
  if (mime === "application/pdf") {
    const src = page ? `${contentUrl(docId)}#page=${page}` : contentUrl(docId);
    return <iframe className="doc-frame" src={src} title="Document preview" />;
  }
  return (
    <a className="btn-primary btn-inline" href={contentUrl(docId)} target="_blank" rel="noreferrer">
      Open document
    </a>
  );
}
