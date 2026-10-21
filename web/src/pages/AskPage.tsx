import { useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { PageIntro } from "../components/PageIntro";
import { ScopeBanner } from "../components/ScopeBanner";
import { CitationList } from "../components/CitationList";
import { RetrievalTrace } from "../components/RetrievalTrace";
import { A2uiSurface } from "../components/a2ui/A2uiSurface";
import type { A2uiMessage } from "../components/a2ui/types";
import { streamChat } from "../api";
import { useScope } from "../scope";
import type { Citation, ChatMessage } from "../types";

interface Turn {
  question: string;
  answer: string;
  citations: Citation[];
  retrieved: number | null;
  searching: boolean;
  surface: A2uiMessage[] | null;
  error: string | null;
  streaming: boolean;
}

export function AskPage() {
  const { scope } = useScope();
  const navigate = useNavigate();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const historyRef = useRef<ChatMessage[]>([]);

  function patchLast(patch: Partial<Turn>) {
    setTurns((prev) => {
      const next = [...prev];
      next[next.length - 1] = { ...next[next.length - 1], ...patch };
      return next;
    });
  }

  async function ask(event: FormEvent) {
    event.preventDefault();
    const q = question.trim();
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
        searching: false,
        surface: null,
        error: null,
        streaming: true,
      },
    ]);

    let answer = "";
    try {
      await streamChat(
        q,
        historyRef.current,
        {
          onRetrievalStart: () => patchLast({ searching: true }),
          onRetrieval: (count) => patchLast({ retrieved: count, searching: false }),
          onToken: (token) => {
            answer += token;
            patchLast({ answer });
          },
          onCitations: (citations) => patchLast({ citations }),
          onSurface: (surface) => patchLast({ surface }),
          onError: (message) => patchLast({ error: message, searching: false }),
          onDone: () => patchLast({ streaming: false }),
        },
        scope?.id,
      );
      historyRef.current = [
        ...historyRef.current,
        { role: "user", content: q },
        { role: "assistant", content: answer },
      ];
    } catch {
      patchLast({ error: "The answer could not be generated. Your question is kept — try again." });
    } finally {
      patchLast({ streaming: false, searching: false });
      setBusy(false);
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
                      navigate(`/documents/${context.docId}`);
                    }
                  }}
                />
              ) : (
                <CitationList citations={turn.citations} />
              )}
              <RetrievalTrace count={turn.retrieved} />
            </div>
          </div>
        ))}
      </div>

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
        <button type="submit" className="btn-primary" disabled={busy}>
          {busy ? "…" : "Ask"}
        </button>
      </form>
    </>
  );
}
