import type { A2uiMessage } from "./components/a2ui/types";
import type {
  AppConfig,
  Citation,
  DocumentDetail,
  DocumentEmbeddings,
  DocumentEmbeddingsRaw,
  DocumentList,
  GraphData,
  Job,
  SearchMode,
  SearchResponse,
  SessionInfo,
} from "./types";

/** Error carrying the HTTP status so callers can distinguish 401 from 503. */
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: "include", ...init });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (body?.detail) detail = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function login(username: string, password: string): Promise<SessionInfo> {
  return request<SessionInfo>("/api/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
}

export function logout(): Promise<void> {
  return request<void>("/api/session", { method: "DELETE" });
}

/** Runtime flags the shell reads on load (e.g. baseline mode). Never auth-gated. */
export function getConfig(): Promise<AppConfig> {
  return request<AppConfig>("/api/config");
}

/** Flip baseline mode live (no restart). Requires a signed-in session. */
export function setConfig(baselineMode: boolean): Promise<AppConfig> {
  return request<AppConfig>("/api/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ baselineMode }),
  });
}

export async function getSession(): Promise<SessionInfo | null> {
  try {
    return await request<SessionInfo>("/api/session");
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) return null;
    throw err;
  }
}

/** Authenticated JSON fetch for feature endpoints; 401 surfaces as ApiError(401). */
export function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  return request<T>(path, init);
}

export function listDocuments(parentId?: string): Promise<DocumentList> {
  const q = parentId ? `?parentId=${encodeURIComponent(parentId)}` : "";
  return apiFetch<DocumentList>(`/api/documents${q}`);
}

export function createFolder(title: string, parentId?: string): Promise<DocumentDetail> {
  const q = parentId ? `?parentId=${encodeURIComponent(parentId)}` : "";
  return apiFetch<DocumentDetail>(`/api/folders${q}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
}

export function getDocument(id: string): Promise<DocumentDetail> {
  return apiFetch<DocumentDetail>(`/api/documents/${encodeURIComponent(id)}`);
}

export function getDocumentAcl(id: string): Promise<unknown> {
  return apiFetch<unknown>(`/api/documents/${encodeURIComponent(id)}/acl`);
}

export function getDocumentEmbeddings(id: string): Promise<DocumentEmbeddings> {
  return apiFetch<DocumentEmbeddings>(`/api/documents/${encodeURIComponent(id)}/embeddings`);
}

export function getDocumentEmbeddingsRaw(id: string): Promise<DocumentEmbeddingsRaw> {
  return apiFetch<DocumentEmbeddingsRaw>(
    `/api/documents/${encodeURIComponent(id)}/embeddings?raw=true`,
  );
}

export function deleteDocument(id: string): Promise<void> {
  return apiFetch<void>(`/api/documents/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function moveDocument(id: string, targetParentId: string): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(`/api/documents/${encodeURIComponent(id)}/move`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ targetParentId }),
  });
}

/** All files the caller can read, for the inline document finder. */
export async function listFiles(): Promise<{ id: string; title: string | null }[]> {
  const r = await search("hxql", "SELECT * FROM SysFile ORDER BY sys_title", 200);
  return r.results
    .filter((x) => Boolean(x.id))
    .map((x) => ({ id: x.id as string, title: x.title ?? null }));
}

/** All folders the caller can read, for the move-target picker. */
export async function listFolders(): Promise<{ id: string; title: string | null }[]> {
  const r = await search("hxql", "SELECT * FROM SysFolder ORDER BY sys_title", 200);
  return r.results
    .filter((x) => Boolean(x.id))
    .map((x) => ({ id: x.id as string, title: x.title ?? null }));
}

export function uploadDocument(file: File, parentId?: string): Promise<DocumentDetail> {
  const form = new FormData();
  form.append("file", file);
  const q = parentId ? `?parentId=${encodeURIComponent(parentId)}` : "";
  return apiFetch<DocumentDetail>(`/api/documents${q}`, { method: "POST", body: form });
}

/** Same-origin URL for streaming a document's binary (used by preview/download). */
export function contentUrl(id: string): string {
  return `/api/documents/${encodeURIComponent(id)}/content`;
}

/** Browser-renderable image URL (TIFF/BMP converted to PNG server-side). */
export function previewUrl(id: string): string {
  return `/api/documents/${encodeURIComponent(id)}/preview`;
}

export function getGraph(scope?: string): Promise<GraphData> {
  const q = scope ? `?scope=${encodeURIComponent(scope)}` : "";
  return apiFetch<GraphData>(`/api/graph${q}`);
}

export function listJobs(): Promise<{ jobs: Job[] }> {
  return apiFetch<{ jobs: Job[] }>("/api/jobs");
}

export function enrichDocument(id: string): Promise<Job> {
  return apiFetch<Job>(`/api/documents/${encodeURIComponent(id)}/enrich`, { method: "POST" });
}

export function retryJob(id: string): Promise<Job> {
  return apiFetch<Job>(`/api/jobs/${encodeURIComponent(id)}/retry`, { method: "POST" });
}

export function search(
  mode: SearchMode,
  query: string,
  limit = 10,
  scope?: string,
): Promise<SearchResponse> {
  return apiFetch<SearchResponse>("/api/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode, query, limit, scope }),
  });
}

export interface ChatHandlers {
  onRetrievalStart?: (toolName: string) => void;
  onRetrieval?: (count: number, rerank: string | null) => void;
  onToken: (token: string) => void;
  onCitations: (citations: Citation[]) => void;
  onSurface?: (messages: A2uiMessage[]) => void;
  onError?: (message: string) => void;
  onDone?: () => void;
}

/** Stream a grounded answer over SSE. Aborting the signal closes the upstream stream. */
export async function streamChat(
  question: string,
  history: { role: string; content: string }[],
  handlers: ChatHandlers,
  scope?: string,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch("/api/chat", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ question, history, scope }),
    signal,
  });
  if (!response.ok || !response.body) {
    throw new ApiError(response.status, "Chat request failed");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const raw = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      let event = "message";
      let data = "";
      for (const line of raw.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data = line.slice(5).trim();
      }
      if (!data) continue;
      const payload = JSON.parse(data);
      const type = payload.type ?? event;
      if (type === "TOOL_CALL_START") handlers.onRetrievalStart?.(payload.toolCallName);
      else if (type === "TOOL_CALL_END")
        handlers.onRetrieval?.(payload.result?.readable ?? 0, payload.result?.rerank ?? null);
      else if (type === "TEXT_MESSAGE_CONTENT") handlers.onToken(payload.delta ?? "");
      else if (type === "STATE_SNAPSHOT") handlers.onCitations(payload.snapshot?.citations ?? []);
      else if (type === "CUSTOM" && payload.name === "a2ui") handlers.onSurface?.(payload.value);
      else if (type === "RUN_ERROR") handlers.onError?.(payload.message);
      else if (type === "RUN_FINISHED") handlers.onDone?.();
    }
  }
}
