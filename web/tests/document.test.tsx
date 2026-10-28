import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { DocumentPage } from "../src/pages/DocumentPage";

const DOC = {
  sys_id: "d1",
  sys_title: "Invoice.pdf",
  sys_primaryType: "SysFile",
  sys_mixinTypes: ["SysHasEmbeddings"],
  cinctx_contextProperties: { document_type: "invoice", vendor_name: "ACME", total: 1234.5 },
};

beforeEach(() =>
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/documents/d1")) {
        return new Response(JSON.stringify(DOC), { status: 200 });
      }
      return new Response(JSON.stringify({ results: [] }), { status: 200 });
    }),
  ),
);
afterEach(() => vi.unstubAllGlobals());

function renderDoc(baselineMode: boolean) {
  return render(
    <MemoryRouter initialEntries={["/documents/d1"]}>
      <Routes>
        <Route path="/documents/:docId" element={<DocumentPage baselineMode={baselineMode} />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("Extracted fields panel", () => {
  it("shows the type badge, fields and attribution", async () => {
    renderDoc(false);
    await waitFor(() => screen.getByText("vendor_name"));
    expect(screen.getByText("invoice")).toBeInTheDocument();
    expect(screen.getByText("ACME")).toBeInTheDocument();
    expect(screen.getByText("1234.5")).toBeInTheDocument();
    expect(screen.getByText("AI-extracted · Studio + model")).toBeInTheDocument();
  });

  it("is absent in baseline mode", async () => {
    renderDoc(true);
    await waitFor(() => screen.getByText("Enriched by Studio"));
    expect(screen.queryByText("vendor_name")).not.toBeInTheDocument();
    expect(screen.queryByText("AI-extracted · Studio + model")).not.toBeInTheDocument();
  });
});
