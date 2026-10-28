import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
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

function renderLibrary(baselineMode = false) {
  return render(
    <MemoryRouter>
      <LibraryPage baselineMode={baselineMode} />
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

  it("renders without a chip when documentType is not a string", async () => {
    vi.stubGlobal(
      "fetch",
      mockApi([
        {
          id: "d1",
          title: "Odd.pdf",
          name: "Odd.pdf",
          primaryType: "SysFile",
          isFolderish: false,
          mixinTypes: [],
          documentType: { a: 1 },
          parentId: "root",
        },
      ]),
    );
    const { container } = renderLibrary();
    await waitFor(() => screen.getByText("Odd.pdf"));
    expect(container.querySelector(".chip-type")).toBeNull();
  });

  it("hides the type chip in baseline mode", async () => {
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
    const { container } = renderLibrary(true);
    await waitFor(() => screen.getByText("Invoice.pdf"));
    expect(container.querySelector(".chip-type")).toBeNull();
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
    const [, init] = fetchMock.mock.calls.find(
      ([, i]) => (i as RequestInit | undefined)?.method === "POST",
    )!;
    expect((init!.body as FormData).has("access")).toBe(false);
  });
});

const FINANCE = { kind: "group", id: "g-finance", name: "finance", label: "Group" };

function accessApi(handler?: (url: string, init?: RequestInit) => Response | undefined) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    const custom = handler?.(url, init);
    if (custom) return custom;
    if (url.includes("/api/principals")) return new Response(JSON.stringify([FINANCE]));
    if (method === "POST") return new Response(JSON.stringify({ sys_id: "new" }), { status: 201 });
    return new Response(JSON.stringify({ parentId: "root", documents: [] }), { status: 200 });
  });
}

async function chooseFinance(user: ReturnType<typeof userEvent.setup>, scope: Pick<typeof screen, "getByRole" | "findByRole">) {
  await user.click(scope.getByRole("button", { name: "Choose person or group" }));
  await user.type(screen.getByRole("searchbox"), "fin");
  await user.click(await screen.findByRole("button", { name: /finance/ }));
}

const posts = (m: ReturnType<typeof accessApi>) =>
  m.mock.calls.filter(([, i]) => (i as RequestInit | undefined)?.method === "POST");

describe("Library access on create", () => {
  it("defaults to Same as folder", async () => {
    vi.stubGlobal("fetch", accessApi());
    renderLibrary();
    await waitFor(() => screen.getByText(/this folder is empty/i));
    expect(screen.getByRole("button", { name: "Same as folder" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("sends the shared rule with every file of a multi-file upload", async () => {
    const user = userEvent.setup();
    const mock = accessApi();
    vi.stubGlobal("fetch", mock);
    const { container } = renderLibrary();
    await waitFor(() => screen.getByText(/this folder is empty/i));

    await user.click(screen.getByRole("button", { name: "Also share with…" }));
    await chooseFinance(user, screen);
    await user.click(screen.getByRole("button", { name: "Read & write" }));

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(input, [
      new File(["a"], "a.pdf", { type: "application/pdf" }),
      new File(["b"], "b.pdf", { type: "application/pdf" }),
    ]);

    await waitFor(() => expect(posts(mock)).toHaveLength(2));
    for (const [, init] of posts(mock)) {
      const form = init!.body as FormData;
      expect(JSON.parse(String(form.get("access")))).toEqual([
        { principal: { kind: "group", id: "g-finance" }, permission: "ReadWrite" },
      ]);
    }
  });

  it("sends access in the new-folder request body", async () => {
    const user = userEvent.setup();
    const mock = accessApi();
    vi.stubGlobal("fetch", mock);
    renderLibrary();
    await waitFor(() => screen.getByText(/this folder is empty/i));

    await user.click(screen.getByRole("button", { name: /new folder/i }));
    const dialog = screen.getByRole("dialog", { name: "New folder" });
    await user.type(within(dialog).getByLabelText("Folder name"), "Shared");
    await user.click(within(dialog).getByRole("button", { name: "Also share with…" }));
    await chooseFinance(user, within(dialog));
    await user.click(within(dialog).getByRole("button", { name: "Create folder" }));

    await waitFor(() => expect(posts(mock)).toHaveLength(1));
    const body = JSON.parse(String(posts(mock)[0][1]?.body));
    expect(body.title).toBe("Shared");
    expect(body.access).toEqual([
      { principal: { kind: "group", id: "g-finance" }, permission: "Read" },
    ]);
  });

  it("creates a folder without access by default", async () => {
    const user = userEvent.setup();
    const mock = accessApi();
    vi.stubGlobal("fetch", mock);
    renderLibrary();
    await waitFor(() => screen.getByText(/this folder is empty/i));
    await user.click(screen.getByRole("button", { name: /new folder/i }));
    await user.type(screen.getByLabelText("Folder name"), "Plain");
    await user.click(screen.getByRole("button", { name: "Create folder" }));
    await waitFor(() => expect(posts(mock)).toHaveLength(1));
    expect(JSON.parse(String(posts(mock)[0][1]?.body))).toEqual({ title: "Plain" });
  });

  it("shows the API's message when access can't be set in the folder", async () => {
    const user = userEvent.setup();
    const mock = accessApi((url, init) =>
      init?.method === "POST" && url.includes("/api/documents")
        ? new Response(JSON.stringify({ detail: "You can't set access in this folder" }), {
            status: 403,
          })
        : undefined,
    );
    vi.stubGlobal("fetch", mock);
    const { container } = renderLibrary();
    await waitFor(() => screen.getByText(/this folder is empty/i));
    await user.click(screen.getByRole("button", { name: "Also share with…" }));
    await chooseFinance(user, screen);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(input, new File(["a"], "a.pdf", { type: "application/pdf" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("You can't set access in this folder");
  });
});
