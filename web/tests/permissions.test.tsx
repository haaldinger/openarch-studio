import { describe, it, expect, vi, afterEach } from "vitest";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { PermissionsPanel } from "../src/components/PermissionsPanel";
import type { AccessInfo, AccessRule } from "../src/types";

const LOCAL_FIONA: AccessRule = {
  principal: { kind: "user", id: "u-fiona", name: "fiona", label: "Finance analyst" },
  permission: "Read",
  granted: true,
  begin: null,
  end: null,
  status: "EFFECTIVE",
  source: { kind: "local" },
};

const INHERITED_SALES: AccessRule = {
  principal: { kind: "group", id: "g-sales", name: "sales" },
  permission: "Read",
  granted: true,
  begin: null,
  end: null,
  status: "EFFECTIVE",
  source: { kind: "inherited", id: "f-sales", title: "Sales" },
};

function access(overrides: Partial<AccessInfo> = {}): AccessInfo {
  return {
    canManage: true,
    rules: [LOCAL_FIONA, INHERITED_SALES],
    effective: [
      { userId: "u-fiona", username: "fiona", label: "Finance analyst", permissions: ["Read"] },
      { userId: "u-erin", username: "erin", label: "Executive", permissions: ["Everything"] },
      { userId: "u-sam", username: "sam", label: "Sales rep", permissions: ["ReadWrite"] },
    ],
    ...overrides,
  };
}

type Handler = (url: string, init?: RequestInit) => Response | undefined;

function stubFetch(initial: AccessInfo, extra?: Handler) {
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const custom = extra?.(url, init);
    if (custom) return custom;
    if (url.endsWith("/access")) {
      return new Response(JSON.stringify(initial), { status: 200 });
    }
    return new Response("{}", { status: 200 });
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

function renderPanel() {
  return render(
    <MemoryRouter>
      <PermissionsPanel docId="d1" />
    </MemoryRouter>,
  );
}

function accessCalls(mock: ReturnType<typeof stubFetch>, method: string) {
  return mock.mock.calls.filter(
    ([url, init]) => String(url).endsWith("/access") && (init?.method ?? "GET") === method,
  );
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("PermissionsPanel", () => {
  it("renders a grid of effective permissions per person", async () => {
    stubFetch(access());
    renderPanel();
    const grid = within(await screen.findByRole("table", { name: "Who can access" }));
    const fiona = grid.getByText("Finance analyst").closest("tr")!;
    const erin = grid.getByText("Executive").closest("tr")!;
    const sam = grid.getByText("Sales rep").closest("tr")!;
    const yes = (row: HTMLElement) => within(row).queryAllByRole("img", { name: "Yes" }).length;
    expect(yes(fiona)).toBe(1);
    expect(yes(sam)).toBe(2);
    expect(yes(erin)).toBe(3);
    expect(screen.getByRole("columnheader", { name: "Manage security" })).toBeInTheDocument();
  });

  it("lets local rules be removed and links inherited rules to their folder", async () => {
    const mock = stubFetch(access(), (_url, init) =>
      init?.method === "PUT"
        ? new Response(JSON.stringify(access({ rules: [INHERITED_SALES] })), { status: 200 })
        : undefined,
    );
    const user = userEvent.setup();
    renderPanel();
    const link = await screen.findByRole("link", { name: "Inherited from Sales" });
    expect(link).toHaveAttribute("href", "/documents/f-sales");
    expect(screen.getAllByRole("button", { name: /^Remove/ })).toHaveLength(1);
    expect(
      screen.getByText("To restrict one document in a shared folder, move it to a restricted folder."),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^Remove/ }));
    await waitFor(() => expect(accessCalls(mock, "PUT")).toHaveLength(1));
    expect(JSON.parse(String(accessCalls(mock, "PUT")[0][1]?.body))).toEqual({ rules: [] });
    await waitFor(() => expect(screen.queryByRole("button", { name: /^Remove/ })).toBeNull());
  });

  it("counts down a time-limited rule and refetches once it has passed", async () => {
    vi.useFakeTimers();
    const now = Date.now();
    const timed: AccessRule = {
      ...LOCAL_FIONA,
      end: new Date(now + 90_000).toISOString(),
    };
    const mock = stubFetch(access({ rules: [timed] }));
    renderPanel();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByText("expires in 1:30")).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(screen.getByText("expires in 1:29")).toBeInTheDocument();
    expect(accessCalls(mock, "GET")).toHaveLength(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(92_000);
    });
    expect(accessCalls(mock, "GET").length).toBeGreaterThanOrEqual(2);
  });

  it("explains that only managers see the rules", async () => {
    stubFetch(
      access({
        canManage: false,
        rules: [],
        effective: [{ userId: null, username: "cory", permissions: ["Read"] }],
      }),
    );
    renderPanel();
    expect(
      await screen.findByText("Only users with Manage security can see the rules"),
    ).toBeInTheDocument();
    expect(screen.getByText("cory")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add rule" })).toBeNull();
  });

  it("adds a 2 minute rule alongside the existing local rules", async () => {
    const created: AccessInfo = access({
      rules: [LOCAL_FIONA, { ...LOCAL_FIONA, principal: { kind: "user", id: "u-cory", name: "cory" } }],
    });
    const mock = stubFetch(access(), (url, init) => {
      if (url.includes("/api/principals")) {
        return new Response(JSON.stringify([{ kind: "user", id: "u-cory", name: "cory", label: "Contractor" }]));
      }
      if (init?.method === "PUT") return new Response(JSON.stringify(created), { status: 200 });
      return undefined;
    });
    const user = userEvent.setup();
    renderPanel();
    await user.click(await screen.findByRole("button", { name: "Choose person or group" }));
    await user.type(screen.getByRole("searchbox"), "cor");
    await user.click(await screen.findByRole("button", { name: /cory/ }));
    await user.click(screen.getByRole("button", { name: "2 min" }));
    const before = Date.now();
    await user.click(screen.getByRole("button", { name: "Add rule" }));

    await waitFor(() => expect(accessCalls(mock, "PUT")).toHaveLength(1));
    const body = JSON.parse(String(accessCalls(mock, "PUT")[0][1]?.body));
    expect(body.rules).toHaveLength(2);
    expect(body.rules[0]).toEqual({
      principal: { kind: "user", id: "u-fiona" },
      permission: "Read",
    });
    expect(body.rules[1].principal).toEqual({ kind: "user", id: "u-cory" });
    expect(body.rules[1].permission).toBe("Read");
    const end = new Date(body.rules[1].end).getTime();
    expect(Math.abs(end - (before + 120_000))).toBeLessThan(5000);
  });

  it("shows the permission error when the change is refused", async () => {
    stubFetch(access(), (_url, init) =>
      init?.method === "PUT"
        ? new Response(JSON.stringify({ detail: "You don't have permission to change access here" }), {
            status: 403,
          })
        : undefined,
    );
    const user = userEvent.setup();
    renderPanel();
    await user.click(await screen.findByRole("button", { name: /^Remove/ }));
    expect(
      await screen.findByText("You don't have permission to change access here"),
    ).toBeInTheDocument();
  });
});
