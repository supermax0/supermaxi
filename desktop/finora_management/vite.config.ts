import { fileURLToPath, URL } from "node:url";
import react from "@vitejs/plugin-react";
import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";
import pkg from "./package.json";

/** Strict CSP for the packaged renderer; dev additionally needs Vite's HMR socket and React Refresh preamble. */
function contentSecurityPolicy(): Plugin {
  return {
    name: "finora-csp",
    transformIndexHtml(html, ctx) {
      const dev = Boolean(ctx.server);
      const policy = [
        "default-src 'self'",
        dev ? "script-src 'self' 'unsafe-inline'" : "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob: finora-media:",
        "font-src 'self' data:",
        "media-src 'self' blob:",
        dev ? "connect-src 'self' ws://localhost:*" : "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
        "frame-src 'none'",
      ].join("; ");
      return html.replace("%FINORA_CSP%", policy);
    },
  };
}

export default defineConfig({
  base: "./",
  define: { __APP_VERSION__: JSON.stringify(pkg.version) },
  plugins: [react(), contentSecurityPolicy()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
      "@shared": fileURLToPath(new URL("./shared", import.meta.url)),
    },
  },
  server: { port: 5181, strictPort: true },
  build: { outDir: "dist", emptyOutDir: true, target: "chrome108", sourcemap: false },
  test: {
    globals: true,
    // Keep jsdom workers bounded alongside the backend and Electron suites.
    maxWorkers: 2,
    minWorkers: 1,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}", "shared/**/*.test.ts", "electron/**/*.test.ts"],
    css: false,
  },
});
