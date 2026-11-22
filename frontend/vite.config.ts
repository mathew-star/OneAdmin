/// <reference types="vitest/config" />
import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

/**
 * Production: relative asset URLs (`base: "./"`). The server injects `<base href>` for the
 * mount prefix, so one build works under `/admin`, `/backoffice` or `/`.
 *
 * Development: the app is served under `/admin/` and API calls are proxied to a FastAPI app
 * running on :8000 with `admin.mount(app, "/admin")`. The proxy keeps the browser on one
 * origin, so the session cookie and the Origin check behave exactly as in production.
 */
export default defineConfig(({ command }) => ({
  base: command === "build" ? "./" : "/admin/",
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  build: {
    target: "es2022",
    sourcemap: false,
    // No inline <script>/<style>: the admin's CSP is `script-src 'self'; style-src 'self'`.
    assetsInlineLimit: 0,
    modulePreload: { polyfill: false },
  },
  server: {
    port: 5173,
    proxy: {
      "/admin/api": { target: process.env.ONEADMIN_DEV_API ?? "http://127.0.0.1:8000" },
    },
  },
  test: {
    environment: "happy-dom",
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["src/test/setup.ts"],
    restoreMocks: true,
  },
}));
