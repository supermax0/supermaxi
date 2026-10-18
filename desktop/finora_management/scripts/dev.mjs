// Development runner: Vite dev server for the renderer + Electron pointing at it.
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { createServer } from "vite";

const require = createRequire(import.meta.url);
const electronBinary = require("electron");

const server = await createServer({ configFile: "vite.config.ts" });
await server.listen();
const url = server.resolvedUrls?.local[0];
if (!url) throw new Error("vite dev server did not report a URL");

await new Promise((resolve, reject) => {
  const child = spawn(process.execPath, ["scripts/build-electron.mjs"], { stdio: "inherit" });
  child.on("exit", (code) => (code === 0 ? resolve(undefined) : reject(new Error(`electron build failed (${code})`))));
});

const electron = spawn(electronBinary, ["."], {
  stdio: "inherit",
  env: {
    ...process.env,
    VITE_DEV_SERVER_URL: url,
    FINORA_SERVER_URL: process.env.FINORA_SERVER_URL ?? "http://localhost:5008",
  },
});
electron.on("exit", async (code) => {
  await server.close();
  process.exit(code ?? 0);
});
