import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Local dev outside Compose proxies the BFF directly.
    proxy: {
      "/api": "http://localhost:8800",
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    css: true,
    // Playwright specs live in e2e/ and run via `npm run e2e`, not Vitest.
    include: ["tests/**/*.{test,spec}.{ts,tsx}"],
  },
});
