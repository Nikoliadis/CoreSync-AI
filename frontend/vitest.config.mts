import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";


export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    // Playwright owns `e2e/`; running its specs here would start a browser inside a
    // jsdom worker and fail in a confusing way.
    include: ["src/**/*.test.{ts,tsx}"],
  },
  resolve: {
    // fileURLToPath, not URL.pathname: on Windows the latter yields "/C:/..." with a
    // leading slash, which Vite cannot resolve.
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
});
