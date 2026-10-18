// Bundles the main process and the sandboxed preload (which cannot require local files).
import { build } from "esbuild";
import { copyFile, mkdir } from "node:fs/promises";

const watch = process.argv.includes("--watch");
const common = {
  bundle: true,
  platform: "node",
  format: "cjs",
  // Node 16 = Electron 22 (Windows 7/8 build); also valid for current Electron.
  target: "node16",
  external: ["electron"],
  sourcemap: watch ? "inline" : false,
  logLevel: "warning",
};

await Promise.all([
  build({ ...common, entryPoints: ["electron/main/index.ts"], outfile: "dist-electron/main/index.js" }),
  build({ ...common, entryPoints: ["electron/preload/index.ts"], outfile: "dist-electron/preload/index.js" }),
]);
await mkdir("dist-electron/main", { recursive: true });
await copyFile("node_modules/sql.js/dist/sql-wasm.wasm", "dist-electron/main/sql-wasm.wasm");
console.log("electron bundles written to dist-electron/");
