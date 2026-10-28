import { act, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DocumentRow } from "../src/components/DocumentRow";
import type { DocumentSummary } from "../src/types";

function doc(access: DocumentSummary["access"]): DocumentSummary {
  return {
    id: "d1",
    title: "q4-pricing.md",
    name: "q4-pricing.md",
    primaryType: "SysFile",
    isFolderish: false,
    modified: null,
    mixinTypes: [],
    parentId: "p1",
    access,
  };
}

function renderRow(d: DocumentSummary, onAccessExpired?: () => void) {
  return render(
    <MemoryRouter>
      <DocumentRow doc={d} onAccessExpired={onAccessExpired} />
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.useRealTimers();
});

describe("Access badges", () => {
  it("shows the reader's own access", () => {
    renderRow(doc({ mine: "read", sharedWith: null, expiresAt: null }));
    expect(screen.getByText("Read only")).toBeInTheDocument();
    expect(screen.queryByLabelText(/shared with/i)).not.toBeInTheDocument();
  });

  it("labels edit and manage access", () => {
    const { rerender } = renderRow(doc({ mine: "edit", sharedWith: [], expiresAt: null }));
    expect(screen.getByText("Can edit")).toBeInTheDocument();
    rerender(
      <MemoryRouter>
        <DocumentRow doc={doc({ mine: "manage", sharedWith: [], expiresAt: null })} />
      </MemoryRouter>,
    );
    expect(screen.getByText("Manage")).toBeInTheDocument();
  });

  it("lists up to three principals and a +N overflow", () => {
    renderRow(
      doc({
        mine: "manage",
        sharedWith: [
          { kind: "group", name: "sales" },
          { kind: "user", name: "cory" },
          { kind: "group", name: "hr" },
          { kind: "user", name: "erin" },
          { kind: "user", name: "fiona" },
        ],
        expiresAt: null,
      }),
    );
    const shared = screen.getByLabelText("Shared with sales, cory, hr, erin, fiona");
    expect(shared).toHaveTextContent("sales");
    expect(shared).toHaveTextContent("hr");
    expect(shared).not.toHaveTextContent("erin");
    expect(shared).toHaveTextContent("+2");
  });

  it("counts down a rule that ends soon and reports when it passes", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-28T18:00:00Z"));
    const onExpired = vi.fn();
    renderRow(doc({ mine: "manage", sharedWith: [], expiresAt: "2026-10-28T18:01:40Z" }), onExpired);
    expect(screen.getByText("expires in 1:40")).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(40_000);
    });
    expect(screen.getByText("expires in 1:00")).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(61_000);
    });
    expect(onExpired).toHaveBeenCalledTimes(1);
  });

  it("shows a date for rules ending more than a day away", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-28T18:00:00Z"));
    renderRow(doc({ mine: "manage", sharedWith: [], expiresAt: "2026-11-03T12:00:00Z" }));
    expect(screen.getByText(/^until /)).toBeInTheDocument();
  });

  it("renders nothing extra without access data", () => {
    renderRow(doc(undefined));
    expect(screen.queryByText("Read only")).not.toBeInTheDocument();
  });
});
