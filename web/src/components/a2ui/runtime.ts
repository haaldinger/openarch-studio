/**
 * Minimal A2UI v0.9 renderer.
 *
 * The client owns the catalog: an agent can only reference component types that
 * appear in CATALOG, so a payload can describe UI but never execute code or
 * introduce a widget the host did not approve. Unknown types render nothing.
 *
 * Only the subset Studio actually emits is implemented — see api/app/a2ui.py.
 */
import type { ReactNode } from "react";
import type { A2uiComponentNode, A2uiMessage, A2uiValue, DataNode } from "./types";

/** Component types this host will render. Anything else is dropped. */
export const CATALOG = ["Card", "Column", "Row", "Text", "Divider", "Button"] as const;
export type CatalogType = (typeof CATALOG)[number];

export interface Surface {
  surfaceId: string;
  root: string;
  components: Record<string, A2uiComponentNode>;
  data: DataNode;
}

/**
 * Fold an ordered message list into a surface. Returns null until createSurface
 * arrives, matching the spec's "buffer updates until the surface is created".
 */
export function applyMessages(messages: A2uiMessage[]): Surface | null {
  const components: Record<string, A2uiComponentNode> = {};
  let data: DataNode = {};
  let created: { surfaceId: string; root: string } | null = null;

  for (const message of messages) {
    const update = message.updateComponents ?? message.surfaceUpdate;
    if (update) {
      for (const entry of update.components ?? []) {
        if (entry?.id) components[entry.id] = entry;
      }
    }

    const model = message.updateDataModel ?? message.dataModelUpdate;
    if (model) {
      data = writeContents(data, model.path, model.contents ?? []);
    }

    const create = message.createSurface ?? message.beginRendering;
    if (create?.root) {
      created = { surfaceId: create.surfaceId, root: create.root };
    }
  }

  if (!created) return null;
  return { ...created, components, data };
}

function writeContents(
  tree: DataNode,
  path: string | undefined,
  contents: { key: string; valueString?: string; valueNumber?: number; valueBoolean?: boolean; valueMap?: unknown }[],
): DataNode {
  const next: DataNode = { ...tree };
  const target = path ? ensurePath(next, path) : next;
  for (const entry of contents) {
    if (!entry?.key) continue;
    if (entry.valueMap !== undefined) {
      target[entry.key] = writeContents({}, undefined, (entry.valueMap as never) ?? []);
    } else if (entry.valueString !== undefined) target[entry.key] = entry.valueString;
    else if (entry.valueNumber !== undefined) target[entry.key] = entry.valueNumber;
    else if (entry.valueBoolean !== undefined) target[entry.key] = entry.valueBoolean;
  }
  return next;
}

function ensurePath(tree: DataNode, path: string): DataNode {
  let node = tree;
  for (const segment of path.split("/").filter(Boolean)) {
    if (typeof node[segment] !== "object" || node[segment] === null) node[segment] = {};
    node = node[segment] as DataNode;
  }
  return node;
}

/** Resolve `{literalString}` or `{path}` against the surface data model. */
export function resolve(value: A2uiValue | undefined, data: DataNode): string {
  if (value === undefined || value === null) return "";
  if (typeof value === "string") return value;
  if ("literalString" in value && value.literalString !== undefined) return String(value.literalString);
  if ("path" in value && value.path) {
    let node: unknown = data;
    for (const segment of value.path.split("/").filter(Boolean)) {
      if (typeof node !== "object" || node === null) return "";
      node = (node as DataNode)[segment];
    }
    return node === undefined || node === null ? "" : String(node);
  }
  return "";
}

/**
 * A payload may use either the wrapper form `{component: {Text: {...}}}` or the
 * flat form `{component: "Text", ...props}`; the published docs show both.
 */
export function readNode(node: A2uiComponentNode): { type: string; props: Record<string, unknown> } | null {
  const component = node.component;
  if (typeof component === "string") {
    const { id: _id, component: _c, ...props } = node as Record<string, unknown>;
    return { type: component, props };
  }
  if (component && typeof component === "object") {
    const [type] = Object.keys(component);
    if (!type) return null;
    return { type, props: (component as Record<string, Record<string, unknown>>)[type] ?? {} };
  }
  return null;
}

export function childIds(props: Record<string, unknown>): string[] {
  const children = props.children as { explicitList?: string[] } | string[] | undefined;
  if (Array.isArray(children)) return children;
  if (children && Array.isArray(children.explicitList)) return children.explicitList;
  if (typeof props.child === "string") return [props.child];
  return [];
}

export type ActionHandler = (name: string, context: Record<string, string>) => void;

export interface RenderContext {
  surface: Surface;
  onAction: ActionHandler;
  seen: Set<string>;
}

export function isCatalogType(type: string): type is CatalogType {
  return (CATALOG as readonly string[]).includes(type);
}

export type { ReactNode };
