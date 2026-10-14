import { test, expect, type Route } from "@playwright/test";

// Stub the Studio API in the browser so the E2E exercises the full UI workflow
// deterministically, without a live OpenArch, Tika, or model.
async function stubApi(page: import("@playwright/test").Page) {
  let signedIn = false;
  await page.route("**/api/**", async (route: Route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const method = route.request().method();
    const json = (body: unknown, status = 200) =>
      route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

    if (path === "/api/session" && method === "POST") {
      signedIn = true;
      return json({ username: "admin" });
    }
    if (path === "/api/session" && method === "GET") {
      return signedIn ? json({ username: "admin" }) : json({ detail: "no" }, 401);
    }
    if (path === "/api/session" && method === "DELETE") {
      signedIn = false;
      return route.fulfill({ status: 204, body: "" });
    }
    if (path === "/api/documents" && method === "GET") {
      return json({
        parentId: "root",
        documents: [
          {
            id: "d1",
            title: "Handbook.pdf",
            name: "Handbook.pdf",
            primaryType: "SysFile",
            isFolderish: false,
            mixinTypes: ["SysHasEmbeddings"],
            parentId: "root",
          },
        ],
      });
    }
    if (path === "/api/capabilities") {
      return json({
        native: [{ name: "Document storage", owner: "OpenArch", description: "d", evidence: "e" }],
        extensions: [{ name: "Workspace", owner: "Studio", description: "d", evidence: "e" }],
        runtimes: [{ name: "OpenArch", role: "System of record" }],
        provenanceFlow: ["Question"],
      });
    }
    return json({});
  });
}

test("sign in and browse the enriched library", async ({ page }) => {
  await stubApi(page);
  await page.goto("/");

  await page.getByLabel(/username/i).fill("admin");
  await page.getByRole("button", { name: /enter studio/i }).click();

  await expect(page.getByRole("heading", { name: "Library", level: 1 })).toBeVisible();
  await expect(page.getByText("Handbook.pdf")).toBeVisible();
  await expect(page.getByText("Enriched")).toBeVisible();
});

test("capability map attributes native vs extension", async ({ page }) => {
  await stubApi(page);
  await page.goto("/");
  await page.getByLabel(/username/i).fill("admin");
  await page.getByRole("button", { name: /enter studio/i }).click();
  await page.getByRole("link", { name: /capabilities/i }).click();

  await expect(page.getByText("OpenArch native")).toBeVisible();
  await expect(page.getByText(/differs from the enterprise reference/i)).toBeVisible();
});
