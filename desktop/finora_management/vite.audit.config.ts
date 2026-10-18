import { defineConfig, mergeConfig } from "vite";
import config from "./vite.config";
import { fileURLToPath } from "node:url";

export default mergeConfig(
  config,
  defineConfig({
    base: "/static/finora-inventory-audit/",
    build: {
      outDir: fileURLToPath(new URL("../../static/finora-inventory-audit", import.meta.url)),
      emptyOutDir: true,
      rollupOptions: { input: fileURLToPath(new URL("./audit.html", import.meta.url)) },
    },
  }),
);
