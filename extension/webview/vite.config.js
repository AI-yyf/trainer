var __assign = (this && this.__assign) || function () {
    __assign = Object.assign || function(t) {
        for (var s, i = 1, n = arguments.length; i < n; i++) {
            s = arguments[i];
            for (var p in s) if (Object.prototype.hasOwnProperty.call(s, p))
                t[p] = s[p];
        }
        return t;
    };
    return __assign.apply(this, arguments);
};
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
var rootDir = fileURLToPath(new URL(".", import.meta.url));
export default defineConfig(function (_a) {
    var _b;
    var mode = _a.mode;
    return ({
        base: "./",
        plugins: [react()],
        build: {
            outDir: (_b = process.env.TRAINER_WEBVIEW_OUT_DIR) !== null && _b !== void 0 ? _b : "dist",
            sourcemap: false,
            emptyOutDir: true,
            rollupOptions: {
                input: __assign({ main: resolve(rootDir, "index.html"), preview: resolve(rootDir, "vscode-preview.html") }, (process.env.TRAINER_WEBVIEW_INCLUDE_TEST_ENTRY !== "0"
                    ? { browserSidecarTest: resolve(rootDir, "src/browserSidecar.test-entry.ts") }
                    : {})),
                output: {
                    preserveModules: false,
                    minifyInternalExports: false,
                    entryFileNames: function (chunk) {
                        return chunk.name === "browserSidecarTest"
                            ? "browserSidecar-test.js"
                            : "assets/[name]-[hash].js";
                    },
                    manualChunks: function (id) {
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
    });
});
