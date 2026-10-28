import { useState } from "react";
import { CitationList } from "./CitationList";
import { PersonaPicker, personaName } from "./PersonaPicker";
import { RetrievalTrace } from "./RetrievalTrace";
import type { Citation, Persona } from "../types";

export interface ColumnResult {
  /** Username the answer was generated as. */
  persona: string;
  question: string;
  answer: string;
  citations: Citation[];
  retrieved: number | null;
  rerank: string | null;
  searching: boolean;
  error: string | null;
  streaming: boolean;
}

/** Split two citation lists by `docId`, each in first-seen order. */
export function diffCitations(
  left: Citation[],
  right: Citation[],
): { leftOnly: string[]; rightOnly: string[]; both: string[] } {
  const leftIds = [...new Set(left.map((c) => c.docId))];
  const rightIds = [...new Set(right.map((c) => c.docId))];
  const inRight = new Set(rightIds);
  const inLeft = new Set(leftIds);
  return {
    leftOnly: leftIds.filter((id) => !inRight.has(id)),
    rightOnly: rightIds.filter((id) => !inLeft.has(id)),
    both: leftIds.filter((id) => inRight.has(id)),
  };
}

interface CompareColumnProps {
  persona: string;
  personas: Persona[];
  result: ColumnResult | null;
  onPersonaChange: (username: string) => void;
  onReask: () => void;
}

export function CompareColumn({ persona, personas, result, onPersonaChange, onReask }: CompareColumnProps) {
  const [picking, setPicking] = useState(false);
  const label = personas.find((p) => p.username === persona)?.label;
  const answeredAs = result?.persona ?? persona;
  const stale = !!result && result.persona !== persona;
  return (
    <section className="compare-col" aria-label={`Answer as ${personaName(answeredAs)}`}>
      <header className="compare-col-head">
        <button type="button" className="compare-persona" onClick={() => setPicking(true)}>
          <span className="compare-persona-prefix">Ask as</span>
          <span className="persona-name">{personaName(persona)}</span>
          {label && <span className="persona-label">{label}</span>}
          <span className="compare-persona-caret" aria-hidden="true">▾</span>
        </button>
        <button
          type="button"
          className="btn-ghost"
          disabled={!result || result.streaming}
          onClick={onReask}
        >
          Re-ask
        </button>
      </header>
      <PersonaPicker
        open={picking}
        onClose={() => setPicking(false)}
        onPick={(username) => {
          onPersonaChange(username);
          setPicking(false);
        }}
        personas={personas}
        current={persona}
      />
      {result ? (
        <div className="turn-a">
          {stale && (
            <p className="muted">Asked as {personaName(result.persona)} — Re-ask to update</p>
          )}
          {result.searching && (
            <p className="muted inline-status" role="status">
              Searching documents {personaName(result.persona)} can read…
            </p>
          )}
          {result.answer ||
            (result.streaming && !result.searching ? <span className="muted">Thinking…</span> : null)}
          {result.error && (
            <p className="form-error" role="alert">
              {result.error}
            </p>
          )}
          <CitationList citations={result.citations} />
          <RetrievalTrace count={result.retrieved} rerank={result.rerank} />
        </div>
      ) : (
        <p className="muted">Ask a question to see what {personaName(persona)} gets.</p>
      )}
    </section>
  );
}

interface CompareSummaryProps {
  leftName: string;
  rightName: string;
  left: Citation[];
  right: Citation[];
}

export function CompareSummary({ leftName, rightName, left, right }: CompareSummaryProps) {
  const diff = diffCitations(left, right);
  const titles = new Map<string, string>();
  for (const c of [...left, ...right]) if (!titles.has(c.docId)) titles.set(c.docId, c.title ?? c.docId);

  const group = (heading: string, ids: string[]) => (
    <div className="compare-group">
      <p className="citations-label">{heading}</p>
      {ids.length === 0 ? (
        <p className="muted">None</p>
      ) : (
        <ul>
          {ids.map((id) => (
            <li key={id}>{titles.get(id)}</li>
          ))}
        </ul>
      )}
    </div>
  );

  return (
    <section className="compare-summary" aria-label="Citation comparison">
      {group(`Only ${personaName(leftName)}`, diff.leftOnly)}
      {group("Both", diff.both)}
      {group(`Only ${personaName(rightName)}`, diff.rightOnly)}
    </section>
  );
}
