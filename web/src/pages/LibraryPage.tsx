import { useCallback, useEffect, useRef, useState } from "react";
import { UploadCloud, FolderPlus, Target, ChevronRight } from "lucide-react";
import { PageIntro } from "../components/PageIntro";
import { DocumentRow } from "../components/DocumentRow";
import { Modal } from "../components/Modal";
import { ApiError, createFolder, listDocuments, uploadDocument } from "../api";
import { useScope } from "../scope";
import type { DocumentSummary } from "../types";

const ROOT_ID = "00000000-0000-0000-0000-000000000000";
const SUPPORTED = ".pdf,.docx,.txt,.md,.html,.htm,.tif,.tiff,.png,.jpg,.jpeg,.gif,.bmp";

interface Crumb {
  id: string;
  name: string;
}

export function LibraryPage() {
  const { scope, setScope } = useScope();
  const [path, setPath] = useState<Crumb[]>([{ id: ROOT_ID, name: "Library" }]);
  const [docs, setDocs] = useState<DocumentSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [folderOpen, setFolderOpen] = useState(false);
  const [folderName, setFolderName] = useState("");
  const [creating, setCreating] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);

  const current = path[path.length - 1];
  const atRoot = current.id === ROOT_ID;
  const isScoped = scope?.id === current.id;

  const refresh = useCallback(() => {
    setLoading(true);
    listDocuments(current.id)
      .then((list) => setDocs(list.documents))
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : "Could not load the library."),
      )
      .finally(() => setLoading(false));
  }, [current.id]);

  useEffect(refresh, [refresh]);

  async function handleFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    setUploading(true);
    setError(null);
    try {
      for (const file of Array.from(files)) {
        await uploadDocument(file, atRoot ? undefined : current.id);
      }
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed.");
    } finally {
      setUploading(false);
    }
  }

  async function handleCreateFolder() {
    const name = folderName.trim();
    if (!name) return;
    setCreating(true);
    try {
      await createFolder(name, atRoot ? undefined : current.id);
      setFolderOpen(false);
      setFolderName("");
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create folder.");
    } finally {
      setCreating(false);
    }
  }

  return (
    <>
      <PageIntro
        eyebrow="OpenArch record · Studio workspace"
        title="Library"
        lede="Organize documents into folders. Scope a folder to silo search, chat, and the graph to just that dataset."
      />

      <div className="lib-toolbar">
        <nav className="breadcrumb" aria-label="Folder path">
          {path.map((crumb, i) => (
            <span key={crumb.id} className="crumb-wrap">
              {i > 0 && <ChevronRight size={14} className="crumb-sep" />}
              <button
                type="button"
                className="crumb"
                onClick={() => setPath(path.slice(0, i + 1))}
                disabled={i === path.length - 1}
              >
                {crumb.name}
              </button>
            </span>
          ))}
        </nav>
        <div className="lib-actions">
          <button type="button" className="btn-ghost" onClick={() => setFolderOpen(true)}>
            <FolderPlus size={16} /> New folder
          </button>
          {!atRoot &&
            (isScoped ? (
              <button type="button" className="btn-ghost scoped" onClick={() => setScope(null)}>
                <Target size={16} /> Scoped ✓
              </button>
            ) : (
              <button
                type="button"
                className="btn-ghost"
                onClick={() => setScope({ id: current.id, name: current.name })}
              >
                <Target size={16} /> Scope to this folder
              </button>
            ))}
        </div>
      </div>

      <div
        className={dragging ? "dropzone dragging" : "dropzone"}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          void handleFiles(e.dataTransfer.files);
        }}
      >
        <UploadCloud size={26} strokeWidth={1.5} />
        <p className="dropzone-text">
          Drag a document into <strong>{current.name}</strong>, or{" "}
          <button type="button" className="link-button" onClick={() => inputRef.current?.click()}>
            choose a file
          </button>
        </p>
        <p className="dropzone-hint">PDF, DOCX, TXT, Markdown, HTML, or scanned images (OCR)</p>
        <input
          ref={inputRef}
          type="file"
          accept={SUPPORTED}
          multiple
          hidden
          onChange={(e) => void handleFiles(e.target.files)}
        />
      </div>

      {uploading && <p className="muted inline-status">Uploading &amp; storing in OpenArch…</p>}
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}

      <div className="doc-list">
        {loading ? (
          <p className="muted">Loading…</p>
        ) : docs.length === 0 ? (
          <div className="placeholder-panel">
            <p className="placeholder-title">This folder is empty</p>
            <p className="muted">
              Upload a document or create a folder. Documents are stored in{" "}
              <span className="tag native">OpenArch</span>; <span className="tag studio">Studio</span>{" "}
              enriches them.
            </p>
          </div>
        ) : (
          docs.map((doc) => (
            <DocumentRow
              key={doc.id}
              doc={doc}
              onOpenFolder={(f) =>
                setPath([...path, { id: f.id, name: f.title ?? f.name ?? f.id }])
              }
            />
          ))
        )}
      </div>

      <Modal
        open={folderOpen}
        title="New folder"
        onClose={() => {
          setFolderOpen(false);
          setFolderName("");
        }}
        initialFocusRef={folderInputRef}
        footer={
          <>
            <button
              type="button"
              className="btn-ghost"
              onClick={() => {
                setFolderOpen(false);
                setFolderName("");
              }}
            >
              Cancel
            </button>
            <button
              type="button"
              className="btn-primary"
              onClick={() => void handleCreateFolder()}
              disabled={!folderName.trim() || creating}
            >
              {creating ? "Creating…" : "Create folder"}
            </button>
          </>
        }
      >
        <label className="modal-label" htmlFor="folder-name">
          Folder name
        </label>
        <input
          id="folder-name"
          ref={folderInputRef}
          className="modal-input"
          value={folderName}
          placeholder="e.g. Invoices"
          onChange={(e) => setFolderName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void handleCreateFolder();
          }}
        />
        <p className="modal-hint">
          Created in <strong>{current.name}</strong> as a native{" "}
          <span className="tag native">OpenArch</span> <code>SysFolder</code>.
        </p>
      </Modal>
    </>
  );
}
