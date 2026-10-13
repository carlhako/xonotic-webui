/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The build emits the static bundle straight into the Python package so the FastAPI
// process can serve it (design D11). `npm run dev` proxies API and SSE calls to a
// locally running `python -m xonotic_webui`.
//
// The panel's default port is 80, which a dev machine usually will not grant. Run the
// backend on an unprivileged port and point the proxy at it with the same variable:
//   XONOTIC_WEBUI_PORT=8000 python -m xonotic_webui
//   XONOTIC_WEBUI_PORT=8000 npm run dev
const backend = `http://127.0.0.1:${process.env.XONOTIC_WEBUI_PORT ?? "80"}`;

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../src/xonotic_webui/static",
    emptyOutDir: true,
  },
  server: {
    proxy: {
      "/api": { target: backend, changeOrigin: true },
      "/health": backend,
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});
