/**
 * Maps A2UI component types onto Studio's own elements, so an agent-composed
 * surface inherits the app's styling instead of shipping its own.
 */
import { Fragment } from "react";
import type { ReactNode } from "react";
import {
  applyMessages,
  childIds,
  isCatalogType,
  readNode,
  resolve,
  type ActionHandler,
  type Surface,
} from "./runtime";
import type { A2uiMessage } from "./types";

interface Props {
  messages: A2uiMessage[];
  onAction: ActionHandler;
}

export function A2uiSurface({ messages, onAction }: Props) {
  const surface = applyMessages(messages);
  if (!surface) return null;
  return (
    <section className="a2ui-surface" aria-label="Agent-composed panel">
      {renderNode(surface.root, surface, onAction, new Set())}
    </section>
  );
}

function renderNode(
  id: string,
  surface: Surface,
  onAction: ActionHandler,
  seen: Set<string>,
): ReactNode {
  if (seen.has(id)) return null; // the spec calls circular references out as an error
  const node = surface.components[id];
  if (!node) return null;
  const read = readNode(node);
  if (!read || !isCatalogType(read.type)) return null;

  const nextSeen = new Set(seen).add(id);
  const { type, props } = read;
  const kids = childIds(props).map((childId) => (
    <Fragment key={childId}>{renderNode(childId, surface, onAction, nextSeen)}</Fragment>
  ));

  switch (type) {
    case "Card":
      return <div className="a2ui-card">{kids}</div>;
    case "Column":
      return <div className="a2ui-col">{kids}</div>;
    case "Row":
      return (
        <div className="a2ui-row" data-justify={String(props.justify ?? "start")}>
          {kids}
        </div>
      );
    case "Divider":
      return <hr className="a2ui-divider" />;
    case "Text": {
      const hint = String(props.usageHint ?? props.variant ?? "body");
      const text = resolve(props.text as never, surface.data);
      if (hint === "h5" || hint === "h4") return <h3 className="a2ui-heading">{text}</h3>;
      if (hint === "caption") return <p className="a2ui-caption">{text}</p>;
      return <p className="a2ui-text">{text}</p>;
    }
    case "Button": {
      const event = (props.action as { event?: { name?: string; context?: Record<string, unknown> } })
        ?.event;
      return (
        <button
          type="button"
          className="a2ui-button"
          onClick={() => {
            if (!event?.name) return;
            const context: Record<string, string> = {};
            for (const [key, value] of Object.entries(event.context ?? {})) {
              context[key] = resolve(value as never, surface.data);
            }
            onAction(event.name, context);
          }}
        >
          {kids}
        </button>
      );
    }
    default:
      return null;
  }
}
