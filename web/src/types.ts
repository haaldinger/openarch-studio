export interface SessionInfo {
  username: string;
}

export interface AppConfig {
  /** When true, Studio extensions are disabled and only native OpenArch is shown. */
  baselineMode: boolean;
}

export interface DocumentSummary {
  id: string;
  title: string | null;
  name: string | null;
  primaryType: string | null;
  isFolderish: boolean;
  modified: string | null;
  mixinTypes: string[];
  documentType?: string | null;
  parentId: string | null;
}

export interface DocumentList {
  parentId: string;
  documents: DocumentSummary[];
}

/** Raw OpenArch DocumentDTO — an open map of sys_* and custom properties. */
export type DocumentDetail = Record<string, unknown>;

export interface EmbeddingChunk {
  id: string;
  text: string;
  dims: number;
  preview: number[];
}

export interface DocumentEmbeddings {
  docId: string;
  count: number;
  embeddings: EmbeddingChunk[];
}

export interface DocumentEmbeddingsRaw {
  docId: string;
  count: number;
  raw: Record<string, unknown>[];
}

export type StageStatus = "pending" | "running" | "done" | "failed";

export interface JobStage {
  name: string;
  status: StageStatus;
  detail: string;
}

export interface Job {
  id: string;
  docId: string;
  filename: string;
  state: "running" | "complete" | "failed";
  error: string | null;
  stages: JobStage[];
}

export type SearchMode = "keyword" | "hxql" | "semantic" | "hybrid";

export interface SearchResult {
  id: string | null;
  title: string | null;
  snippet: string | null;
  score: number | null;
  vectorScore?: number | null;
  page?: number;
}

export interface SearchProvenance {
  providedBy: string;
  extendedBy: string | null;
  requestPath: string;
  embeddingType: string | null;
  tookMs: number;
  rerank?: string | null;
}

export interface SearchResponse {
  mode: SearchMode;
  results: SearchResult[];
  provenance: SearchProvenance;
}

export interface Citation {
  docId: string;
  chunkId: string;
  snippet: string;
  score: number | null;
  vectorScore?: number | null;
  page: number;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface GraphNode {
  id: string;
  label: string;
  type: string;
  docIds?: string[];
}

export interface GraphEdge {
  source: string;
  target: string;
  type: string;
  inferred?: boolean;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
  entityTypes: string[];
}

export type HealthState = "up" | "degraded" | "down";

export interface Health {
  status: string;
  openarch: HealthState;
  tika: HealthState;
  model: HealthState;
}
