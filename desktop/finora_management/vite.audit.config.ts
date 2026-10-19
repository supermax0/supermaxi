import { defineConfig, mergeConfig } from "vite";
import config from "./vite.config";
import { fileURLToPath } from "node:url";

export default mergeConfig(
  config,
  defineConfig({
    plugins: [{
      name: "finora-shared-workspace-design",
      transformIndexHtml: {
        order: "post",
        handler: (html) => html.replace("</head>", '<link rel="stylesheet" href="/static/css/workspace-design.css?v=20261019a"><script defer src="/static/js/workspace-design.js?v=20261019a"></script></head>').replace("<body>", '<body class="finora-unified finora-audit">'),
      },
    }],
    base: "/static/finora-inventory-audit/",
    build: {
      outDir: fileURLToPath(new URL("../../static/finora-inventory-audit", import.meta.url)),
      emptyOutDir: true,
      rollupOptions: { input: fileURLToPath(new URL("./audit.html", import.meta.url)) },
    },
  }),
);
