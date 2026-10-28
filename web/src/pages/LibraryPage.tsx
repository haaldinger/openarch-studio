import { useCallback, useEffect, useRef, useState } from "react";
import { UploadCloud, FolderPlus, Target, ChevronRight } from "lucide-react";
import { PageIntro } from "../components/PageIntro";
import { DocumentRow } from "../components/DocumentRow";
import { Modal } from "../components/Modal";
import { EMPTY_DRAFT, RuleEditor, draftToRule, type RuleDraft } from "../components/RuleEditor";
import { ApiError, createFolder, deleteDocument, listDocuments, uploadDocument } from "../api";
import { useScope } from "../scope";
import { useSession } from "../session";
import type { DocumentSummary, RuleInput } from "../types";

const ROOT_ID = "00000000-0000-0000-0000-000000000000";
const SUPPORTED = ".pdf,.docx,.txt,.md,.html,.htm,.tif,.tiff,.png,.jpg,.jpeg,.gif,.bmp";

interface Crumb {
  id: string;
  name: string;
}

interface AccessChoiceState {
  share: boolean;
  drafts: RuleDraft[];
}

const SAME_AS_FOLDER: AccessChoiceState = { share: false, drafts: [EMPTY_DRAFT] };

/** Null while a shared rule is still incomplete; an empty list means "same as folder". */
function resolveAccess(choice: AccessChoiceState): RuleInput[] | null {
  if (!choice.share) return [];
  const rules = choice.drafts.map((d) => draftToRule(d));
  return rules.every((r): r is RuleInput => r !== null) ? (rules as RuleInput[]) : null;
}

function AccessChoice({
  value,
  onChange,
}: {
  value: AccessChoiceState;
  onChange: (next: AccessChoiceState) => void;
}) {
  return (
    <div className="access-choice">
      <span className="rule-field-label">Who can access</span>
      <div className="rule-chips" role="group" aria-label="Who can access">
        <button
          type="button"
          className={value.share ? "rule-chip" : "rule-chip active"}
          aria-pressed={!value.share}
          onClick={() => onChange({ ...value, share: false })}
        >
          Same as folder
        </button>
        <button
          type="button"
          className={value.share ? "rule-chip active" : "rule-chip"}
          aria-pressed={value.share}
          onClick={() => onChange({ ...value, share: true })}
        >
          Also share with…
        </button>
      </div>
      {value.share && (
        <div className="access-choice-rules">
          {value.drafts.map((draft, i) => (
            <div key={i} className="access-choice-rule">
              <RuleEditor
                value={draft}
                onChange={(next) =>
                  onChange({ ...value, drafts: value.drafts.map((d, j) => (j === i ? next : d)) })
                }
              />
              {value.drafts.length > 1 && (
                <button
                  type="button"
                  className="link-button"
                  onClick={() =>
                    onChange({ ...value, drafts: value.drafts.filter((_, j) => j !== i) })
                  }
                >
                  Remove rule
                </button>
              )}
            </div>
          ))}
          <button
            type="button"
            className="btn-ghost"
            onClick={() => onChange({ ...value, drafts: [...value.drafts, EMPTY_DRAFT] })}
          >
            Add another rule
          </button>
        </div>
      )}
    </div>
  );
}

export function LibraryPage({ baselineMode = false }: { baselineMode?: boolean }) {
  const { scope, setScope } = useScope();
  const { generation } = useSession();
  const [path, setPath] = useState<Crumb[]>([{ id: ROOT_ID, name: "Library" }]);
  const [docs, setDocs] = useState<DocumentSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [folderOpen, setFolderOpen] = useState(false);
  const [folderName, setFolderName] = useState("");
  const [folderError, setFolderError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [uploadAccess, setUploadAccess] = useState<AccessChoiceState>(SAME_AS_FOLDER);
  const [folderAccess, setFolderAccess] = useState<AccessChoiceState>(SAME_AS_FOLDER);
  const [pendingDelete, setPendingDelete] = useState<DocumentSummary | null>(null);
  const [deleting, setDeleting] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);

  const current = path[path.length - 1];
  const atRoot = current.id === ROOT_ID;
  const isScoped = scope?.id === current.id;

  const refresh = useCallback(() => {
    setLoading(true);
    setError(null);
    listDocuments(current.id)
      .then((list) => setDocs(list.documents))
      .catch((err) =>
        setError(err instanceof ApiError ? err.message : "Could not load the library."),
      )
      .finally(() => setLoading(false));
    // generation: reload when the acting identity changes.
  }, [current.id, generation]);

  useEffect(refresh, [refresh]);

  useEffect(() => {
    setPath([{ id: ROOT_ID, name: "Library" }]);
  }, [generation]);

  async function handleFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    const access = resolveAccess(uploadAccess);
    if (access === null) {
      setError("Choose who to share with, or switch back to Same as folder.");
      return;
    }
    setUploading(true);
    setError(null);
    try {
      for (const file of Array.from(files)) {
        await uploadDocument(file, atRoot ? undefined : current.id, access);
      }
      setUploadAccess(SAME_AS_FOLDER);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed.");
    } finally {
      setUploading(false);
    }
  }

  async function handleCreateFolder() {
    const name = folderName.trim();
    const access = resolveAccess(folderAccess);
    if (!name || access === null) return;
    setCreating(true);
    setFolderError(null);
    try {
      await createFolder(name, atRoot ? undefined : current.id, access);
      setFolderOpen(false);
      setFolderName("");
      setFolderAccess(SAME_AS_FOLDER);
      refresh();
    } catch (err) {
      setFolderError(err instanceof ApiError ? err.message : "Could not create folder.");
    } finally {
      setCreating(false);
    }
  }

  async function handleDeleteFolder() {
    if (!pendingDelete) return;
    setDeleting(true);
    setError(null);
    try {
      await deleteDocument(pendingDelete.id);
      if (scope?.id === pendingDelete.id) setScope(null);
      refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not delete the folder.");
    } finally {
      setPendingDelete(null);
      setDeleting(false);
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
          <button
            type="button"
            className="btn-ghost"
            onClick={() => {
              setError(null);
              setFolderError(null);
              setFolderOpen(true);
            }}
          >
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

      <AccessChoice value={uploadAccess} onChange={setUploadAccess} />

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
              baselineMode={baselineMode}
              onOpenFolder={(f) =>
                setPath([...path, { id: f.id, name: f.title ?? f.name ?? f.id }])
              }
              onDeleteFolder={setPendingDelete}
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
          setFolderAccess(SAME_AS_FOLDER);
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
                setFolderAccess(SAME_AS_FOLDER);
              }}
            >
              Cancel
            </button>
            <button
              type="button"
              className="btn-primary"
              onClick={() => void handleCreateFolder()}
              disabled={!folderName.trim() || creating || resolveAccess(folderAccess) === null}
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
        <AccessChoice value={folderAccess} onChange={setFolderAccess} />
        {folderError && (
          <p className="form-error" role="alert">
            {folderError}
          </p>
        )}
      </Modal>

      <Modal
        open={pendingDelete !== null}
        title="Delete folder"
        onClose={() => setPendingDelete(null)}
        footer={
          <>
            <button type="button" className="btn-ghost" onClick={() => setPendingDelete(null)}>
              Cancel
            </button>
            <button
              type="button"
              className="btn-danger"
              onClick={() => void handleDeleteFolder()}
              disabled={deleting}
            >
              {deleting ? "Deleting…" : "Delete folder"}
            </button>
          </>
        }
      >
        <p className="modal-hint">
          Delete{" "}
          <strong>{pendingDelete?.title ?? pendingDelete?.name ?? pendingDelete?.id}</strong> and
          everything inside it? OpenArch removes the folder's documents and their embeddings, so
          they also leave search, chat, and the graph. This cannot be undone.
        </p>
      </Modal>
    </>
  );
}
