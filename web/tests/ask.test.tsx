import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { AskPage } from "../src/pages/AskPage";
import { SearchPage } from "../src/pages/SearchPage";
import { CitationList } from "../src/components/CitationList";
import { RetrievalTrace } from "../src/components/RetrievalTrace";

function sseResponse(body: string): Response {
  const stream = new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(body));
      controller.close();
    },
  });
  return new Response(stream, { status: 200, headers: { "Content-Type": "text/event-stream" } });
}

const SSE =
  'event: RUN_STARTED\ndata: {"type": "RUN_STARTED", "runId": "r1", "threadId": "r1"}\n\n' +
  'event: TOOL_CALL_START\ndata: {"type": "TOOL_CALL_START", "toolCallId": "t1", "toolCallName": "search_documents"}\n\n' +
  'event: TOOL_CALL_END\ndata: {"type": "TOOL_CALL_END", "toolCallId": "t1", "result": {"retrieved": 2, "readable": 2}}\n\n' +
  'event: TEXT_MESSAGE_START\ndata: {"type": "TEXT_MESSAGE_START", "messageId": "m1"}\n\n' +
  'event: TEXT_MESSAGE_CONTENT\ndata: {"type": "TEXT_MESSAGE_CONTENT", "delta": "Hello "}\n\n' +
  'event: TEXT_MESSAGE_CONTENT\ndata: {"type": "TEXT_MESSAGE_CONTENT", "delta": "world"}\n\n' +
  'event: TEXT_MESSAGE_END\ndata: {"type": "TEXT_MESSAGE_END", "messageId": "m1"}\n\n' +
  'event: STATE_SNAPSHOT\ndata: {"type": "STATE_SNAPSHOT", "snapshot": {"citations": [{"docId": "d1", "chunkId": "c1", "snippet": "a source chunk", "score": 0.9, "page": 2}]}}\n\n' +
  'event: RUN_FINISHED\ndata: {"type": "RUN_FINISHED", "runId": "r1"}\n\n';

/** Same run, but the agent also composes the sources panel as an A2UI surface. */
const SSE_WITH_SURFACE =
  SSE.replace(
    'event: RUN_FINISHED',
    'event: CUSTOM\ndata: {"type": "CUSTOM", "name": "a2ui", "value": [' +
      '{"version": "v0.9", "updateComponents": {"surfaceId": "s1", "components": [' +
      '{"id": "root", "component": {"Card": {"child": "body"}}},' +
      '{"id": "body", "component": {"Column": {"children": {"explicitList": ["title", "row-0"]}}}},' +
      '{"id": "title", "component": {"Text": {"text": {"literalString": "Sources"}, "usageHint": "h5"}}},' +
      '{"id": "row-0", "component": {"Row": {"children": {"explicitList": ["label-0", "open-0"]}}}},' +
      '{"id": "label-0", "component": {"Text": {"text": {"path": "/sources/0/title"}}}},' +
      '{"id": "open-0", "component": {"Button": {"child": "open-text-0", "action": {"event": {"name": "open_document", "context": {"docId": {"path": "/sources/0/docId"}}}}}}},' +
      '{"id": "open-text-0", "component": {"Text": {"text": {"literalString": "Open"}}}},' +
      '{"id": "evil", "component": {"ScriptTag": {"src": "http://attacker.test/x.js"}}}' +
      ']}},' +
      '{"version": "v0.9", "updateDataModel": {"surfaceId": "s1", "contents": [{"key": "sources", "valueMap": [{"key": "0", "valueMap": [{"key": "title", "valueString": "Aurora Standard"}, {"key": "docId", "valueString": "d1"}]}]}]}},' +
      '{"version": "v0.9", "createSurface": {"surfaceId": "s1", "root": "root"}}' +
      ']}\n\n' +
      'event: RUN_FINISHED',
  );

beforeEach(() => vi.stubGlobal("fetch", vi.fn(async () => sseResponse(SSE))));
afterEach(() => vi.unstubAllGlobals());

function renderAsk() {
  return render(
    <MemoryRouter>
      <AskPage />
    </MemoryRouter>,
  );
}

describe("Ask", () => {
  it("links a citation to its page", () => {
    render(
      <CitationList citations={[{ docId: "d1", chunkId: "c1", snippet: "s", score: 0.5, page: 4 }]} />,
      { wrapper: MemoryRouter },
    );
    expect(screen.getByRole("link")).toHaveAttribute("href", "/documents/d1?chunk=c1&page=4");
  });

  it("shows the rerank and vector scores", () => {
    render(
      <CitationList
        citations={[{ docId: "d1", chunkId: "c1", snippet: "s", score: 0.95, vectorScore: 0.62, page: 1 }]}
      />,
      { wrapper: MemoryRouter },
    );
    expect(screen.getByText("0.95")).toBeInTheDocument();
    expect(screen.getByText("vector 0.62")).toBeInTheDocument();
  });

  it("opens a surface source at its page", async () => {
    const withPage = SSE_WITH_SURFACE.replace(
      '"context": {"docId": {"path": "/sources/0/docId"}}',
      '"context": {"docId": {"path": "/sources/0/docId"}, "page": {"path": "/sources/0/page"}}',
    ).replace(
      '{"key": "docId", "valueString": "d1"}',
      '{"key": "docId", "valueString": "d1"}, {"key": "page", "valueString": "5"}',
    );
    vi.stubGlobal("fetch", vi.fn(async () => sseResponse(withPage)));
    function Where() {
      const loc = useLocation();
      return <p data-testid="where">{loc.pathname + loc.search}</p>;
    }
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <AskPage />
        <Where />
      </MemoryRouter>,
    );

    await user.type(screen.getByLabelText(/your question/i), "q");
    await user.click(screen.getByRole("button", { name: /^ask$/i }));
    await user.click(await screen.findByRole("button", { name: /open/i }));

    expect(screen.getByTestId("where")).toHaveTextContent("/documents/d1?page=5");
  });

  it("streams an answer with citations and a retrieval trace", async () => {
    const user = userEvent.setup();
    renderAsk();

    await user.type(screen.getByLabelText(/your question/i), "what is the policy?");
    await user.click(screen.getByRole("button", { name: /^ask$/i }));

    await waitFor(() => expect(screen.getByText(/Hello world/)).toBeInTheDocument());
    expect(screen.getByText(/what is the policy\?/)).toBeInTheDocument();
    expect(screen.getByText(/Sources/i)).toBeInTheDocument();
    expect(screen.getByText(/a source chunk/)).toBeInTheDocument();
    expect(screen.getByText(/Retrieval trace/i)).toBeInTheDocument();
  });

  it("shows the rerank status from the retrieval result", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        sseResponse(SSE.replace('"readable": 2}', '"readable": 2, "rerank": "reranked"}')),
      ),
    );
    const user = userEvent.setup();
    renderAsk();

    await user.type(screen.getByLabelText(/your question/i), "what is the policy?");
    await user.click(screen.getByRole("button", { name: /^ask$/i }));

    await waitFor(() => expect(screen.getByText(/Hello world/)).toBeInTheDocument());
    expect(screen.getByText(/^Reranked$/)).toBeInTheDocument();
  });

  it("RetrievalTrace names why reranking was skipped", () => {
    render(<RetrievalTrace count={2} rerank="skipped (timeout)" />);
    expect(screen.getByText(/Rerank skipped \(timeout\)/)).toBeInTheDocument();
  });

  it("RetrievalTrace omits the rerank line when no status is known", () => {
    render(<RetrievalTrace count={2} rerank={null} />);
    expect(screen.queryByText(/rerank/i)).not.toBeInTheDocument();
  });

  it("search trace shows the rerank status", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              mode: "semantic",
              results: [{ id: "d1", title: null, snippet: "s", score: 0.9, vectorScore: 0.5, page: 1 }],
              provenance: {
                providedBy: "OpenArch vector search",
                extendedBy: "Studio embedding",
                requestPath: "/api/query/embeddings",
                embeddingType: "e",
                tookMs: 5,
                rerank: "reranked",
              },
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
      ),
    );
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <SearchPage />
      </MemoryRouter>,
    );
    await user.type(screen.getByLabelText(/search query/i), "policy");
    await user.click(screen.getByRole("button", { name: /^search$/i }));

    await waitFor(() => expect(screen.getByText(/Rerank/)).toBeInTheDocument());
    expect(screen.getByText(/Rerank/).closest("li")).toHaveTextContent("reranked");
  });

  it("search results link to the cited page, plain link without one", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              mode: "semantic",
              results: [
                { id: "d1", title: "Paged", snippet: "s", score: 0.9, page: 3 },
                { id: "d2", title: "Unpaged", snippet: "s", score: 0.8 },
              ],
              provenance: {
                providedBy: "OpenArch vector search",
                requestPath: "/api/query/embeddings",
                tookMs: 5,
              },
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          ),
      ),
    );
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <SearchPage />
      </MemoryRouter>,
    );
    await user.type(screen.getByLabelText(/search query/i), "policy");
    await user.click(screen.getByRole("button", { name: /^search$/i }));

    const paged = await screen.findByRole("link", { name: "Paged" });
    expect(paged).toHaveAttribute("href", "/documents/d1?page=3");
    expect(screen.getByRole("link", { name: "Unpaged" })).toHaveAttribute("href", "/documents/d2");
  });

  it("keeps the question visible if generation errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        sseResponse(
          'event: RUN_ERROR\ndata: {"type": "RUN_ERROR", "message": "model down"}\n\n',
        ),
      ),
    );
    const user = userEvent.setup();
    renderAsk();

    await user.type(screen.getByLabelText(/your question/i), "hi");
    await user.click(screen.getByRole("button", { name: /^ask$/i }));

    await waitFor(() => expect(screen.getByText("hi")).toBeInTheDocument());
    expect(screen.getByRole("alert")).toHaveTextContent(/model down/i);
  });

  it("renders an agent-composed A2UI surface and ignores types outside the catalog", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => sseResponse(SSE_WITH_SURFACE)));
    const user = userEvent.setup();
    renderAsk();

    await user.type(screen.getByLabelText(/your question/i), "what is the policy?");
    await user.click(screen.getByRole("button", { name: /^ask$/i }));

    // Bound from the surface data model, not from a hardcoded component.
    await waitFor(() => expect(screen.getByText("Aurora Standard")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /open/i })).toBeInTheDocument();
    // The payload asked for a ScriptTag; it is not in the catalog, so it is dropped.
    expect(document.querySelector("script[src*='attacker']")).toBeNull();
    expect(screen.queryByText(/attacker/)).not.toBeInTheDocument();
  });
});
