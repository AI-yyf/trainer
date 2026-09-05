import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const rootDir = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig(({ mode }) => ({
  base: "./",
  plugins: [react()],
  build: {
    outDir: process.env.TRAINER_WEBVIEW_OUT_DIR ?? "dist",
    sourcemap: false,
    emptyOutDir: true,
    rollupOptions: {
      input: {
        main: resolve(rootDir, "index.html"),
        preview: resolve(rootDir, "vscode-preview.html"),
        ...(process.env.TRAINER_WEBVIEW_INCLUDE_TEST_ENTRY !== "0"
          ? { browserSidecarTest: resolve(rootDir, "src/browserSidecar.test-entry.ts") }
          : {}),
      },
      output: {
        preserveModules: false,
        minifyInternalExports: false,
        entryFileNames: (chunk) =>
          chunk.name === "browserSidecarTest"
            ? "browserSidecar-test.js"
            : "assets/[name]-[hash].js",
        manualChunks(id) {
          if (id.includes("node_modules/react") || id.includes("node_modules/react-dom")) {
            return "vendor-react";
          }
          if (id.includes("node_modules/zustand") || id.includes("node_modules/zod")) {
            return "vendor-state";
          }
          return undefined;
        },
      },
    },
  },
}));
