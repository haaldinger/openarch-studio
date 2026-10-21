/** Wire types for the A2UI v0.9 messages Studio emits. */

export type A2uiValue =
  | string
  | { literalString?: string; path?: never }
  | { path?: string; literalString?: never };

export interface A2uiComponentNode {
  id: string;
  component: string | Record<string, Record<string, unknown>>;
  [key: string]: unknown;
}

export interface A2uiDataEntry {
  key: string;
  valueString?: string;
  valueNumber?: number;
  valueBoolean?: boolean;
  valueMap?: A2uiDataEntry[];
}

export interface A2uiMessage {
  version?: string;
  /** v0.9 */
  updateComponents?: { surfaceId: string; components: A2uiComponentNode[] };
  updateDataModel?: { surfaceId: string; path?: string; contents: A2uiDataEntry[] };
  createSurface?: { surfaceId: string; root: string; catalogId?: string };
  /** v0.8 aliases, accepted so an older agent still renders. */
  surfaceUpdate?: { surfaceId: string; components: A2uiComponentNode[] };
  dataModelUpdate?: { surfaceId: string; path?: string; contents: A2uiDataEntry[] };
  beginRendering?: { surfaceId: string; root: string; catalogId?: string };
  deleteSurface?: { surfaceId: string };
}

export type DataNode = Record<string, unknown>;
