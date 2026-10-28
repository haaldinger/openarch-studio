import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { DocumentPage } from "../src/pages/DocumentPage";
import { SessionProvider, useSession } from "../src/session";

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

function SwitchButton() {
  const { refresh } = useSession();
  return (
    <button
      type="button"
      onClick={() =>
        void refresh({
          username: "admin",
          actingAs: { username: "sam", label: "Sales rep", groups: [] },
          demoAdmin: true,
        })
      }
    >
      switch
    </button>
  );
}

describe("Identity switch", () => {
  it("re-fetches the document and lists when the session generation changes", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/documents/d1")) {
        return new Response(JSON.stringify(DOC), { status: 200 });
      }
      return new Response(JSON.stringify({ results: [] }), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const count = (suffix: string) =>
      fetchMock.mock.calls.filter(([u]) => String(u).endsWith(suffix)).length;
    render(
      <MemoryRouter initialEntries={["/documents/d1"]}>
        <SessionProvider initial={{ username: "admin", actingAs: null, demoAdmin: true }} demoMode>
          <SwitchButton />
          <Routes>
            <Route path="/documents/:docId" element={<DocumentPage />} />
          </Routes>
        </SessionProvider>
      </MemoryRouter>,
    );
    await waitFor(() => screen.getByText("vendor_name"));
    expect(count("/api/documents/d1")).toBe(1);
    const before = fetchMock.mock.calls.length;

    await user.click(screen.getByRole("button", { name: "switch" }));

    await waitFor(() => expect(count("/api/documents/d1")).toBe(2));
    expect(fetchMock.mock.calls.length).toBeGreaterThan(before + 1);
    await waitFor(() => screen.getByText("vendor_name"));
  });
});

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
