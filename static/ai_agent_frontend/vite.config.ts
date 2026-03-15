import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  root: ".",
  cacheDir: "node_modules/.vite-cache",
  build: {
    target: "es2020",
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: mode !== "production",
    reportCompressedSize: false,
    chunkSizeWarningLimit: 1000,
    rollupOptions: {
      input: "index.html",
      output: {
        entryFileNames: "assets/ai-agent.js",
        chunkFileNames: "assets/[name]-[hash].js",
        assetFileNames: "assets/[name]-[hash].[ext]",
        manualChunks: {
          reactVendor: ["react", "react-dom"],
          flowVendor: ["reactflow", "zustand"],
        },
      }
    }
  }
}));

