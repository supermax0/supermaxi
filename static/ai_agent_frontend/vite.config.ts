import { defineConfig } from "vite";

export default defineConfig({
  plugins: [],
  root: ".",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      input: "index.html",
      output: {
        entryFileNames: "assets/ai-agent.js",
        chunkFileNames: "assets/[name].js",
        assetFileNames: "assets/[name].[ext]"
      }
    }
  }
});

