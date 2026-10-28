import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { PageIntro } from "../components/PageIntro";
import { ScopeBanner } from "../components/ScopeBanner";
import { CitationList } from "../components/CitationList";
import { RetrievalTrace } from "../components/RetrievalTrace";
import { A2uiSurface } from "../components/a2ui/A2uiSurface";
import type { A2uiMessage } from "../components/a2ui/types";
import { CompareColumn, CompareSummary, type ColumnResult } from "../components/CompareColumn";
import { listPersonas, streamChat } from "../api";
import { useScope } from "../scope";
import { useSession } from "../session";
import type { Citation, ChatMessage, Persona } from "../types";

interface Turn {
  question: string;
  answer: string;
  citations: Citation[];
  retrieved: number | null;
  rerank: string | null;
  searching: boolean;
  surface: A2uiMessage[] | null;
  error: string | null;
  streaming: boolean;
}

export function AskPage() {
  const { scope } = useScope();
  const { session, demoMode, generation } = useSession();
  const navigate = useNavigate();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const historyRef = useRef<ChatMessage[]>([]);
  const singleAbort = useRef<AbortController | null>(null);

  const canCompare = demoMode && session.demoAdmin;
  const activeName = session.actingAs?.username ?? session.username;
  const [compare, setCompare] = useState(false);
  const comparing = canCompare && compare;
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [sides, setSides] = useState<[string, string]>([activeName, "erin"]);
  const [results, setResults] = useState<[ColumnResult | null, ColumnResult | null]>([null, null]);
  const columnAbort = useRef<[AbortController | null, AbortController | null]>([null, null]);

  // A conversation belongs to the identity that held it; its streams die with it.
  useEffect(() => {
    setTurns([]);
    setBusy(false);
    setResults([null, null]);
    setSides([activeName, "erin"]);
    historyRef.current = [];
    return () => {
      singleAbort.current?.abort();
      columnAbort.current.forEach((c) => c?.abort());
    };
  }, [generation]);

  useEffect(() => {
    if (!comparing || personas.length > 0) return;
    let live = true;
    listPersonas()
      .then((list) => live && setPersonas(list))
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [comparing, personas.length]);

  function patchColumn(index: 0 | 1, patch: Partial<ColumnResult>) {
    setResults((prev) => {
      const next: [ColumnResult | null, ColumnResult | null] = [...prev];
      const current = next[index];
      if (current) next[index] = { ...current, ...patch };
      return next;
    });
  }

  async function askColumn(index: 0 | 1, q: string, persona: string) {
    columnAbort.current[index]?.abort();
    const controller = new AbortController();
    columnAbort.current[index] = controller;
    const live = (patch: Partial<ColumnResult>) => {
      if (!controller.signal.aborted) patchColumn(index, patch);
    };
    setResults((prev) => {
      const next: [ColumnResult | null, ColumnResult | null] = [...prev];
      next[index] = {
        question: q,
        answer: "",
        citations: [],
        retrieved: null,
        rerank: null,
        searching: false,
        error: null,
        streaming: true,
      };
      return next;
    });

    let answer = "";
    try {
      await streamChat(
        q,
        [],
        {
          onRetrievalStart: () => live({ searching: true }),
          onRetrieval: (count, rerank) => live({ retrieved: count, rerank, searching: false }),
          onToken: (token) => {
            answer += token;
            live({ answer });
          },
          onCitations: (citations) => live({ citations }),
          onError: (message) => live({ error: message, searching: false }),
          onDone: () => live({ streaming: false }),
        },
        scope?.id,
        controller.signal,
        persona,
      );
    } catch {
      live({ error: "The answer could not be generated. Your question is kept — try again." });
    } finally {
      live({ streaming: false, searching: false });
    }
  }

  const compareBusy = results.some((r) => r?.streaming);

  function patchLast(patch: Partial<Turn>) {
    setTurns((prev) => {
      const next = [...prev];
      next[next.length - 1] = { ...next[next.length - 1], ...patch };
      return next;
    });
  }

  async function ask(event: FormEvent) {
    event.preventDefault();
    if (comparing) {
      const q = question.trim();
      if (!q || compareBusy) return;
      setQuestion("");
      await Promise.all([askColumn(0, q, sides[0]), askColumn(1, q, sides[1])]);
      return;
    }
    await askQuestion(question);
  }

  async function askQuestion(text: string) {
    const q = text.trim();
    if (!q || busy) return;
    setQuestion("");
    setBusy(true);
    setTurns((prev) => [
      ...prev,
      {
        question: q,
        answer: "",
        citations: [],
        retrieved: null,
        rerank: null,
        searching: false,
        surface: null,
        error: null,
        streaming: true,
      },
    ]);

    singleAbort.current?.abort();
    const controller = new AbortController();
    singleAbort.current = controller;
    const live = (patch: Partial<Turn>) => {
      if (!controller.signal.aborted) patchLast(patch);
    };

    let answer = "";
    try {
      await streamChat(
        q,
        historyRef.current,
        {
          onRetrievalStart: () => live({ searching: true }),
          onRetrieval: (count, rerank) => live({ retrieved: count, rerank, searching: false }),
          onToken: (token) => {
            answer += token;
            live({ answer });
          },
          onCitations: (citations) => live({ citations }),
          onSurface: (surface) => live({ surface }),
          onError: (message) => live({ error: message, searching: false }),
          onDone: () => live({ streaming: false }),
        },
        scope?.id,
        controller.signal,
      );
      if (!controller.signal.aborted) {
        historyRef.current = [
          ...historyRef.current,
          { role: "user", content: q },
          { role: "assistant", content: answer },
        ];
      }
    } catch {
      live({ error: "The answer could not be generated. Your question is kept — try again." });
    } finally {
      if (!controller.signal.aborted) {
        patchLast({ streaming: false, searching: false });
        setBusy(false);
      }
    }
  }

  return (
    <>
      <PageIntro
        eyebrow="Studio agent · grounded in OpenArch"
        title="Ask"
        lede="Ask questions of your enriched content. Answers are built only from chunks you're allowed to read, with citations you can open."
      />

      <ScopeBanner />

      {canCompare && (
        <div className="compare-toggle">
          <button
            type="button"
            className={compare ? "btn-ghost active" : "btn-ghost"}
            aria-pressed={compare}
            onClick={() => setCompare((on) => !on)}
          >
            Compare
          </button>
        </div>
      )}

      {comparing ? (
        <div className="chat-log">
          <div className="compare-cols">
            {([0, 1] as const).map((i) => (
              <CompareColumn
                key={i}
                persona={sides[i]}
                personas={personas}
                result={results[i]}
                onPersonaChange={(username) =>
                  setSides((prev) => (i === 0 ? [username, prev[1]] : [prev[0], username]))
                }
                onReask={() => {
                  const q = results[i]?.question;
                  if (q) void askColumn(i, q, sides[i]);
                }}
              />
            ))}
          </div>
          {results[0] && results[1] && !compareBusy && (
            <CompareSummary
              leftName={sides[0]}
              rightName={sides[1]}
              left={results[0].citations}
              right={results[1].citations}
            />
          )}
        </div>
      ) : (
      <div className="chat-log">
        {turns.length === 0 && (
          <p className="muted">Ask something about the documents you've enriched.</p>
        )}
        {turns.map((turn, i) => (
          <div className="turn" key={i}>
            <p className="turn-q">{turn.question}</p>
            <div className="turn-a">
              {turn.searching && (
                <p className="muted inline-status" role="status">
                  Searching documents you can read…
                </p>
              )}
              {turn.answer || (turn.streaming && !turn.searching ? <span className="muted">Thinking…</span> : null)}
              {turn.error && (
                <p className="form-error" role="alert">
                  {turn.error}
                </p>
              )}
              {turn.surface ? (
                <A2uiSurface
                  messages={turn.surface}
                  onAction={(name, context) => {
                    if (name === "open_document" && context.docId) {
                      navigate(
                        context.page
                          ? `/documents/${context.docId}?page=${encodeURIComponent(context.page)}`
                          : `/documents/${context.docId}`,
                      );
                    } else if (name === "ask_question" && context.question) {
                      void askQuestion(context.question);
                    }
                  }}
                />
              ) : (
                <CitationList citations={turn.citations} />
              )}
              <RetrievalTrace count={turn.retrieved} rerank={turn.rerank} />
            </div>
          </div>
        ))}
      </div>
      )}

      <form className="ask-bar" onSubmit={ask}>
        <textarea
          aria-label="Your question"
          rows={2}
          value={question}
          placeholder="Ask a question…"
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void ask(e as unknown as FormEvent);
            }
          }}
        />
        <button type="submit" className="btn-primary" disabled={comparing ? compareBusy : busy}>
          {(comparing ? compareBusy : busy) ? "…" : "Ask"}
        </button>
      </form>
    </>
  );
}
