import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { CapabilityPage } from "../src/pages/CapabilityPage";

const CAPS = {
  native: [
    { name: "Document & binary storage", owner: "OpenArch", description: "d", evidence: "e" },
  ],
  extensions: [
    { name: "Visual content workspace", owner: "Studio", description: "d", evidence: "e" },
  ],
  runtimes: [{ name: "OpenArch", role: "System of record" }],
  provenanceFlow: ["Question"],
};

beforeEach(() =>
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(CAPS), { status: 200 })),
  ),
);
afterEach(() => vi.unstubAllGlobals());

describe("Capability map", () => {
  it("renders the native and extension ledger from the API", async () => {
    render(
      <MemoryRouter>
        <CapabilityPage />
      </MemoryRouter>,
    );
    await waitFor(() => screen.getByText("Document & binary storage"));
    expect(screen.getByText("Visual content workspace")).toBeInTheDocument();
    expect(screen.getByText("OpenArch native")).toBeInTheDocument();
    expect(screen.getByText(/differs from the enterprise reference/i)).toBeInTheDocument();
  });
});
