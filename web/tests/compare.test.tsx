import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { AskPage } from "../src/pages/AskPage";
import { diffCitations } from "../src/components/CompareColumn";
import { SessionProvider } from "../src/session";
import type { Citation, SessionInfo } from "../src/types";

const cite = (docId: string, title?: string): Citation => ({
  docId,
  chunkId: `c-${docId}`,
  snippet: `snippet ${docId}`,
  score: 0.9,
  page: 1,
  title,
});

describe("diffCitations", () => {
  it("splits disjoint lists", () => {
    expect(diffCitations([cite("a")], [cite("b")])).toEqual({
      leftOnly: ["a"],
      rightOnly: ["b"],
      both: [],
    });
  });

  it("finds the overlap, in first-seen order", () => {
    const d = diffCitations([cite("a"), cite("b"), cite("c")], [cite("c"), cite("b"), cite("d")]);
    expect(d).toEqual({ leftOnly: ["a"], rightOnly: ["d"], both: ["b", "c"] });
  });

  it("collapses duplicates", () => {
    const d = diffCitations([cite("a"), cite("a"), cite("b")], [cite("b"), cite("b")]);
    expect(d).toEqual({ leftOnly: ["a"], rightOnly: [], both: ["b"] });
  });
});

function sse(citations: Citation[], text: string): Response {
  const body =
    'event: TEXT_MESSAGE_CONTENT\ndata: ' +
    JSON.stringify({ type: "TEXT_MESSAGE_CONTENT", delta: text }) +
    "\n\n" +
    "event: STATE_SNAPSHOT\ndata: " +
    JSON.stringify({ type: "STATE_SNAPSHOT", snapshot: { citations } }) +
    "\n\n" +
    'event: RUN_FINISHED\ndata: {"type": "RUN_FINISHED", "runId": "r"}\n\n';
  const stream = new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(body));
      controller.close();
    },
  });
  return new Response(stream, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

const PERSONAS = [
  { username: "sam", label: "Sales rep", groups: ["sales"], available: true },
  { username: "erin", label: "Executive", groups: ["finance", "hr", "sales"], available: true },
];

const CITES: Record<string, Citation[]> = {
  admin: [cite("shared", "Handbook"), cite("adm", "Admin notes")],
  erin: [cite("shared", "Handbook"), cite("fin", "Bonus budget")],
  sam: [cite("pricing", "Q4 pricing")],
};

let chatBodies: { question: string; actAs?: string }[];

function installFetch() {
  chatBodies = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url === "/api/demo/personas") {
        return new Response(JSON.stringify(PERSONAS), { status: 200 });
      }
      const body = JSON.parse(String(init?.body));
      chatBodies.push(body);
      const who = body.actAs as string;
      return sse(CITES[who] ?? [], `answer for ${who}`);
    }),
  );
}

function renderAsk(session: Partial<SessionInfo> = {}, demoMode = true) {
  return render(
    <MemoryRouter>
      <SessionProvider
        initial={{ username: "admin", actingAs: null, demoAdmin: true, ...session }}
        demoMode={demoMode}
      >
        <AskPage />
      </SessionProvider>
    </MemoryRouter>,
  );
}

beforeEach(installFetch);
afterEach(() => vi.unstubAllGlobals());

describe("Ask compare", () => {
  it("shows the Compare toggle only for a demo admin in demo mode", () => {
    const { unmount } = renderAsk({ demoAdmin: true }, true);
    expect(screen.getByRole("button", { name: /compare/i })).toBeInTheDocument();
    unmount();

    const second = renderAsk({ demoAdmin: false }, true);
    expect(screen.queryByRole("button", { name: /compare/i })).not.toBeInTheDocument();
    second.unmount();

    renderAsk({ demoAdmin: true }, false);
    expect(screen.queryByRole("button", { name: /compare/i })).not.toBeInTheDocument();
  });

  it("sends one request per column with actAs defaults", async () => {
    const user = userEvent.setup();
    renderAsk();
    await user.click(screen.getByRole("button", { name: /compare/i }));
    await user.type(screen.getByLabelText(/your question/i), "bonus pool?");
    await user.click(screen.getByRole("button", { name: /^ask$/i }));

    await waitFor(() => expect(screen.getByText("answer for admin")).toBeInTheDocument());
    expect(screen.getByText("answer for erin")).toBeInTheDocument();
    expect(chatBodies).toHaveLength(2);
    expect(chatBodies.map((b) => b.actAs).sort()).toEqual(["admin", "erin"]);
    expect(chatBodies.every((b) => b.question === "bonus pool?")).toBe(true);
  });

  it("defaults the left column to the persona being viewed", async () => {
    const user = userEvent.setup();
    renderAsk({ actingAs: { username: "sam", label: "Sales rep", groups: ["sales"] } });
    await user.click(screen.getByRole("button", { name: /compare/i }));
    await user.type(screen.getByLabelText(/your question/i), "q");
    await user.click(screen.getByRole("button", { name: /^ask$/i }));

    await waitFor(() => expect(chatBodies).toHaveLength(2));
    expect(chatBodies.map((b) => b.actAs).sort()).toEqual(["erin", "sam"]);
  });

  it("summarises cited documents only-left, only-right and both by title", async () => {
    const user = userEvent.setup();
    renderAsk();
    await user.click(screen.getByRole("button", { name: /compare/i }));
    await user.type(screen.getByLabelText(/your question/i), "q");
    await user.click(screen.getByRole("button", { name: /^ask$/i }));

    const strip = await screen.findByRole("region", { name: /citation comparison/i });
    const left = within(strip).getByText(/only admin/i).closest("div")!;
    const right = within(strip).getByText(/only erin/i).closest("div")!;
    const both = within(strip).getByText(/^both$/i).closest("div")!;
    expect(left).toHaveTextContent("Admin notes");
    expect(right).toHaveTextContent("Bonus budget");
    expect(both).toHaveTextContent("Handbook");
  });

  it("re-asks a single column", async () => {
    const user = userEvent.setup();
    renderAsk();
    await user.click(screen.getByRole("button", { name: /compare/i }));
    await user.type(screen.getByLabelText(/your question/i), "q");
    await user.click(screen.getByRole("button", { name: /^ask$/i }));
    await waitFor(() => expect(screen.getByText("answer for erin")).toBeInTheDocument());
    await waitFor(() => expect(screen.getAllByRole("button", { name: /re-ask/i })[0]).toBeEnabled());
    chatBodies.length = 0;

    await user.click(screen.getAllByRole("button", { name: /re-ask/i })[1]);

    await waitFor(() => expect(chatBodies).toHaveLength(1));
    expect(chatBodies[0].actAs).toBe("erin");
    expect(chatBodies[0].question).toBe("q");
  });

  it("marks a column stale and hides the strip when its persona changes, until Re-ask", async () => {
    const user = userEvent.setup();
    renderAsk();
    await user.click(screen.getByRole("button", { name: /compare/i }));
    await user.type(screen.getByLabelText(/your question/i), "q");
    await user.click(screen.getByRole("button", { name: /^ask$/i }));
    await screen.findByRole("region", { name: /citation comparison/i });
    await waitFor(() => expect(screen.getAllByRole("button", { name: /re-ask/i })[0]).toBeEnabled());

    const leftCol = screen.getByRole("region", { name: /answer as admin/i });
    await user.click(within(leftCol).getByRole("button", { name: /admin/i }));
    await user.click(await screen.findByRole("button", { name: /sam\s*sales rep/i }));

    expect(screen.queryByRole("region", { name: /citation comparison/i })).not.toBeInTheDocument();
    const stale = screen.getByRole("region", { name: /answer as admin/i });
    expect(stale).toHaveTextContent(/asked as admin/i);
    expect(stale).toHaveTextContent(/re-ask to update/i);
    expect(within(screen.getByRole("region", { name: /answer as erin/i })).queryByText(/asked as/i)).toBeNull();

    await user.click(within(stale).getByRole("button", { name: /re-ask/i }));
    const strip = await screen.findByRole("region", { name: /citation comparison/i });
    expect(within(strip).getByText(/only sam/i)).toBeInTheDocument();
    expect(within(strip).queryByText(/only admin/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/asked as/i)).not.toBeInTheDocument();
  });
});

describe("Ask abort", () => {
  it("tells the user to use Re-ask when a compare column fails", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url === "/api/demo/personas") {
          return new Response(JSON.stringify(PERSONAS), { status: 200 });
        }
        throw new Error("network down");
      }),
    );
    renderAsk();
    await user.click(screen.getByRole("button", { name: /compare/i }));
    await user.type(screen.getByLabelText(/your question/i), "q");
    await user.click(screen.getByRole("button", { name: /^ask$/i }));

    expect((await screen.findAllByText(/use Re-ask to try again/)).length).toBe(2);
    expect(screen.queryByText(/Your question is kept/)).not.toBeInTheDocument();
  });

  it("aborts an in-flight stream on unmount", async () => {
    let signal: AbortSignal | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init?: RequestInit) => {
        signal = init?.signal ?? undefined;
        return new Promise<Response>(() => {});
      }),
    );
    const user = userEvent.setup();
    const { unmount } = renderAsk({}, false);
    await user.type(screen.getByLabelText(/your question/i), "q");
    await user.click(screen.getByRole("button", { name: /^ask$/i }));
    await waitFor(() => expect(signal).toBeDefined());

    unmount();
    expect(signal?.aborted).toBe(true);
  });
});
