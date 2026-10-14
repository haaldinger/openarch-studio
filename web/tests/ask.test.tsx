import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { AskPage } from "../src/pages/AskPage";

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
  'event: retrieval\ndata: {"count": 2}\n\n' +
  'event: token\ndata: {"token": "Hello "}\n\n' +
  'event: token\ndata: {"token": "world"}\n\n' +
  'event: citations\ndata: {"citations": [{"docId": "d1", "chunkId": "c1", "snippet": "a source chunk", "score": 0.9}]}\n\n' +
  "event: done\ndata: {}\n\n";

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

  it("keeps the question visible if generation errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        sseResponse('event: error\ndata: {"message": "model down"}\n\nevent: done\ndata: {}\n\n'),
      ),
    );
    const user = userEvent.setup();
    renderAsk();

    await user.type(screen.getByLabelText(/your question/i), "hi");
    await user.click(screen.getByRole("button", { name: /^ask$/i }));

    await waitFor(() => expect(screen.getByText("hi")).toBeInTheDocument());
    expect(screen.getByRole("alert")).toHaveTextContent(/model down/i);
  });
});
