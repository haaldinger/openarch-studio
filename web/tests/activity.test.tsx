import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { ActivityPage } from "../src/pages/ActivityPage";

function stubJobs(jobs: unknown[]) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify({ jobs }), { status: 200 })),
  );
}

const stages = (classified: string) => [
  { name: "indexed", status: "done", detail: "" },
  { name: "classified", status: classified, detail: "" },
];

afterEach(() => vi.unstubAllGlobals());

describe("Activity retry", () => {
  it("offers Retry for a complete job with a failed stage", async () => {
    stubJobs([
      { id: "j1", docId: "d1", filename: "a.pdf", state: "complete", error: null, stages: stages("failed") },
    ]);
    render(<ActivityPage />);
    await waitFor(() => screen.getByText("a.pdf"));
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("hides Retry when nothing failed", async () => {
    stubJobs([
      { id: "j1", docId: "d1", filename: "a.pdf", state: "complete", error: null, stages: stages("done") },
    ]);
    render(<ActivityPage />);
    await waitFor(() => screen.getByText("a.pdf"));
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  });
});
