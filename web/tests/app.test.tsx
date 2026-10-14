import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { App } from "../src/app";
import { NAV_ITEMS } from "../src/nav";

// Minimal in-memory stand-in for the session API the shell talks to.
function mockSessionApi() {
  let session: { username: string } | null = null;
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    if (url.endsWith("/api/session") && method === "POST") {
      session = { username: "admin" };
      return new Response(JSON.stringify(session), { status: 200 });
    }
    if (url.endsWith("/api/session") && method === "DELETE") {
      session = null;
      return new Response(null, { status: 204 });
    }
    if (url.endsWith("/api/session")) {
      return session
        ? new Response(JSON.stringify(session), { status: 200 })
        : new Response(JSON.stringify({ detail: "Not signed in" }), { status: 401 });
    }
    if (url.includes("/api/documents")) {
      return new Response(JSON.stringify({ parentId: "root", documents: [] }), { status: 200 });
    }
    return new Response("{}", { status: 200 });
  });
}

beforeEach(() => {
  vi.stubGlobal("fetch", mockSessionApi());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderApp(initial = "/") {
  return render(
    <MemoryRouter initialEntries={[initial]}>
      <App />
    </MemoryRouter>,
  );
}

async function signIn(user: ReturnType<typeof userEvent.setup>) {
  await waitFor(() => screen.getByRole("heading", { name: /sign in/i }));
  await user.type(screen.getByLabelText(/username/i), "admin");
  await user.click(screen.getByRole("button", { name: /enter studio/i }));
  await waitFor(() => screen.getByRole("heading", { name: "Library", level: 1 }));
}

describe("OpenArch Studio shell", () => {
  it("shows the sign-in screen before authentication", async () => {
    renderApp();
    await waitFor(() => screen.getByRole("heading", { name: /sign in/i }));
    expect(screen.getByRole("heading", { name: /sign in/i })).toBeInTheDocument();
    expect(screen.queryByText(/get started/i)).not.toBeInTheDocument();
  });

  it("enters the workspace and exposes every primary route", async () => {
    const user = userEvent.setup();
    renderApp();
    await signIn(user);

    expect(screen.getByRole("heading", { name: "Library", level: 1 })).toBeInTheDocument();
    for (const item of NAV_ITEMS) {
      expect(screen.getByRole("link", { name: new RegExp(item.label, "i") })).toBeInTheDocument();
    }
    expect(screen.getByText("admin")).toBeInTheDocument();
  });

  it("states the native-vs-extension attribution up front", async () => {
    const user = userEvent.setup();
    renderApp();
    await signIn(user);

    const provenance = screen.getByLabelText("Provenance");
    expect(provenance).toHaveTextContent(/OpenArch record/i);
    expect(provenance).toHaveTextContent(/Studio enrichment/i);
  });

  it("signs out back to the login screen", async () => {
    const user = userEvent.setup();
    renderApp();
    await signIn(user);

    await user.click(screen.getByRole("button", { name: /sign out/i }));
    await waitFor(() => screen.getByRole("heading", { name: /sign in/i }));
    expect(screen.getByRole("heading", { name: /sign in/i })).toBeInTheDocument();
  });

  it("navigation targets match the declared routes", () => {
    const paths = NAV_ITEMS.map((i) => i.path);
    expect(new Set(paths).size).toBe(paths.length);
    expect(paths).toContain("/capabilities");
  });
});
