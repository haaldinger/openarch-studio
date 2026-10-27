import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { LibraryPage } from "../src/pages/LibraryPage";

function mockApi(docs: unknown[]) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    if (url.includes("/api/documents") && method === "POST") {
      return new Response(JSON.stringify({ sys_id: "new" }), { status: 201 });
    }
    if (url.includes("/api/documents")) {
      return new Response(JSON.stringify({ parentId: "root", documents: docs }), { status: 200 });
    }
    return new Response("{}", { status: 200 });
  });
}

beforeEach(() => vi.stubGlobal("fetch", mockApi([])));
afterEach(() => vi.unstubAllGlobals());

function renderLibrary() {
  return render(
    <MemoryRouter>
      <LibraryPage />
    </MemoryRouter>,
  );
}

describe("Library", () => {
  it("shows the empty state and a dropzone when the corpus is empty", async () => {
    renderLibrary();
    await waitFor(() => screen.getByText(/this folder is empty/i));
    expect(screen.getByText(/choose a file/i)).toBeInTheDocument();
    expect(screen.getByText(/PDF, DOCX, TXT/i)).toBeInTheDocument();
  });

  it("lists documents returned by the API with a readiness chip", async () => {
    vi.stubGlobal(
      "fetch",
      mockApi([
        {
          id: "d1",
          title: "Policy.pdf",
          name: "Policy.pdf",
          primaryType: "SysFile",
          isFolderish: false,
          mixinTypes: ["SysHasEmbeddings"],
          parentId: "root",
        },
      ]),
    );
    renderLibrary();
    await waitFor(() => screen.getByText("Policy.pdf"));
    expect(screen.getByText("Enriched")).toBeInTheDocument();
  });

  it("shows a type chip when the summary has a document type", async () => {
    vi.stubGlobal(
      "fetch",
      mockApi([
        {
          id: "d1",
          title: "Invoice.pdf",
          name: "Invoice.pdf",
          primaryType: "SysFile",
          isFolderish: false,
          mixinTypes: [],
          documentType: "invoice",
          parentId: "root",
        },
      ]),
    );
    renderLibrary();
    await waitFor(() => screen.getByText("Invoice.pdf"));
    expect(screen.getByText("invoice")).toBeInTheDocument();
  });

  it("uploads a chosen file and refreshes", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi([]);
    vi.stubGlobal("fetch", fetchMock);
    const { container } = renderLibrary();
    await waitFor(() => screen.getByText(/this folder is empty/i));

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["%PDF-1.4"], "a.pdf", { type: "application/pdf" });
    await user.upload(input, file);

    await waitFor(() => {
      const posted = fetchMock.mock.calls.some(
        ([, init]) => (init as RequestInit | undefined)?.method === "POST",
      );
      expect(posted).toBe(true);
    });
  });
});
