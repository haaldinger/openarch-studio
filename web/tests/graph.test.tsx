import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { GraphPage } from "../src/pages/GraphPage";

const GRAPH = {
  nodes: [
    { id: "acme", label: "Acme", type: "Organization", docIds: ["d1"] },
    { id: "remote policy", label: "Remote Policy", type: "Policy", docIds: ["d1"] },
  ],
  edges: [{ source: "acme", target: "remote policy", type: "has" }],
  entityTypes: ["Person", "Organization", "Policy"],
};

beforeEach(() => {
  vi.stubGlobal("requestAnimationFrame", () => 0);
  vi.stubGlobal("cancelAnimationFrame", () => undefined);
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(GRAPH), { status: 200 })));
});
afterEach(() => vi.unstubAllGlobals());

describe("Graph", () => {
  it("renders extracted entities and a legend", async () => {
    render(
      <MemoryRouter>
        <GraphPage />
      </MemoryRouter>,
    );
    await waitFor(() => screen.getByText("Acme"));
    expect(screen.getByText("Remote Policy")).toBeInTheDocument();
    expect(screen.getByText(/2 entities · 1 relations/)).toBeInTheDocument();
    // Legend shows only types present in the data.
    expect(screen.getByText("Organization")).toBeInTheDocument();
    expect(screen.getByText("Policy")).toBeInTheDocument();
  });

  it("shows an empty state when there is no graph", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ nodes: [], edges: [], entityTypes: [] }), { status: 200 })),
    );
    render(
      <MemoryRouter>
        <GraphPage />
      </MemoryRouter>,
    );
    await waitFor(() => screen.getByText(/no graph yet/i));
  });
});
