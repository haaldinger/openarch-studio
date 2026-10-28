import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { App } from "../src/app";
import { PersonaPicker } from "../src/components/PersonaPicker";
import type { Persona } from "../src/types";

const PERSONAS: Persona[] = [
  { username: "fiona", label: "Finance analyst", groups: ["finance", "members"], available: true },
  { username: "sam", label: "Sales rep", groups: ["sales", "members"], available: true },
  { username: "cory", label: "Contractor", groups: ["members"], available: false },
];

const SAM = { username: "sam", label: "Sales rep", groups: ["sales", "members"] };

interface ApiOptions {
  demoMode?: boolean;
  demoAdmin?: boolean;
  actingAs?: typeof SAM | null;
}

function mockApi({ demoMode = true, demoAdmin = true, actingAs = null }: ApiOptions = {}) {
  let current = actingAs;
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    const json = (body: unknown, status = 200) =>
      new Response(JSON.stringify(body), { status });
    if (url.endsWith("/api/config")) return json({ baselineMode: false, demoMode });
    if (url.endsWith("/api/session/act-as")) {
      const { username } = JSON.parse(String(init?.body));
      current = username === "sam" ? SAM : null;
      return json({ username: "admin", actingAs: current, demoAdmin });
    }
    if (url.endsWith("/api/session") && method === "GET") {
      return json({ username: "admin", actingAs: current, demoAdmin });
    }
    if (url.endsWith("/api/demo/personas")) return json(PERSONAS);
    if (url.endsWith("/api/demo/setup")) return json({ folders: {}, jobs: [] });
    if (url.endsWith("/api/demo") && method === "DELETE") return new Response(null, { status: 204 });
    if (url.includes("/api/documents")) return json({ parentId: "root", documents: [] });
    if (url.endsWith("/api/jobs")) return json({ jobs: [] });
    return json({});
  });
}

function renderApp(initial = "/library") {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <App />
    </MemoryRouter>,
  );
}

function calls(fetchMock: ReturnType<typeof mockApi>, suffix: string, method?: string) {
  return fetchMock.mock.calls.filter(
    ([url, init]) =>
      String(url).endsWith(suffix) && (method === undefined || (init?.method ?? "GET") === method),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("PersonaPicker", () => {
  it("filters by typed text and shows labels and groups", async () => {
    const user = userEvent.setup();
    render(
      <PersonaPicker open onClose={() => {}} onPick={() => {}} personas={PERSONAS} current="admin" />,
    );
    expect(screen.getByText("Finance analyst")).toBeInTheDocument();
    expect(screen.getByText(/finance, members/)).toBeInTheDocument();

    await user.type(screen.getByRole("searchbox"), "sales");
    expect(screen.getByText("Sales rep")).toBeInTheDocument();
    expect(screen.queryByText("Finance analyst")).not.toBeInTheDocument();
  });

  it("disables unavailable personas", async () => {
    const onPick = vi.fn();
    const user = userEvent.setup();
    render(
      <PersonaPicker open onClose={() => {}} onPick={onPick} personas={PERSONAS} current="admin" />,
    );
    const cory = screen.getByRole("button", { name: /cory/i });
    expect(cory).toBeDisabled();
    await user.click(cory);
    expect(onPick).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: /sam/i }));
    expect(onPick).toHaveBeenCalledWith("sam");
  });
});

describe("persona switcher in the shell", () => {
  beforeEach(() => vi.stubGlobal("fetch", mockApi()));

  it("picking a persona calls act-as and shows the banner", async () => {
    const fetchMock = mockApi();
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderApp();

    await user.click(await screen.findByRole("button", { name: /acting as: admin/i }));
    await user.click(await screen.findByRole("button", { name: /sam/i }));

    expect(await screen.findByText(/You're seeing what Sam \(Sales rep\) can see/)).toBeInTheDocument();
    expect(JSON.parse(String(calls(fetchMock, "/api/session/act-as", "POST")[0][1]?.body))).toEqual({
      username: "sam",
    });
    expect(screen.getByRole("button", { name: /acting as: sam/i })).toBeInTheDocument();
  });

  it("Back to Admin acts as the signed-in user", async () => {
    const fetchMock = mockApi({ actingAs: SAM });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderApp();

    await screen.findByText(/You're seeing what Sam/);
    await user.click(screen.getByRole("button", { name: "Back to Admin" }));

    await waitFor(() => expect(calls(fetchMock, "/api/session/act-as", "POST")).toHaveLength(1));
    expect(JSON.parse(String(calls(fetchMock, "/api/session/act-as", "POST")[0][1]?.body))).toEqual({
      username: "admin",
    });
    await waitFor(() => expect(screen.queryByText(/You're seeing what/)).not.toBeInTheDocument());
  });

  it("Set up demo calls the API and opens Activity", async () => {
    const fetchMock = mockApi();
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderApp();

    await user.click(await screen.findByRole("button", { name: /^demo/i }));
    await user.click(screen.getByRole("button", { name: "Set up demo" }));

    await waitFor(() => expect(calls(fetchMock, "/api/demo/setup", "POST")).toHaveLength(1));
    expect(await screen.findByRole("heading", { name: "Activity", level: 1 })).toBeInTheDocument();
  });

  it("Reset demo asks for confirmation first", async () => {
    const fetchMock = mockApi();
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderApp();

    await user.click(await screen.findByRole("button", { name: /^demo/i }));
    await user.click(screen.getByRole("button", { name: "Reset demo" }));
    expect(calls(fetchMock, "/api/demo", "DELETE")).toHaveLength(0);

    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Reset demo" }));
    await waitFor(() => expect(calls(fetchMock, "/api/demo", "DELETE")).toHaveLength(1));
  });

  it("hides the switcher and Demo menu when demo mode is off", async () => {
    vi.stubGlobal("fetch", mockApi({ demoMode: false }));
    renderApp();
    await screen.findByRole("heading", { name: "Library", level: 1 });
    expect(screen.queryByRole("button", { name: /acting as/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^demo/i })).not.toBeInTheDocument();
  });

  it("hides the switcher and Demo menu for non-admin users", async () => {
    vi.stubGlobal("fetch", mockApi({ demoAdmin: false }));
    renderApp();
    await screen.findByRole("heading", { name: "Library", level: 1 });
    expect(screen.queryByRole("button", { name: /acting as/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^demo/i })).not.toBeInTheDocument();
  });
});
