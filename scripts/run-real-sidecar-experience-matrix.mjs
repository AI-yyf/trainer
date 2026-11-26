import path from "node:path";
import { fileURLToPath } from "node:url";

import { runServerCommand } from "./run-server-tests.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const serverRoot = path.resolve(__dirname, "..", "server");

export function runRealSidecarExperienceMatrix(options = {}) {
  return runServerCommand({
    serverRoot: options.serverRoot ?? serverRoot,
    args: ["tests/sidecar_experience_matrix_runner.py"],
    label: "Real Sidecar Experience Matrix (12 end-to-end ASGI + SQLite + Sandbox scenarios)",
  });
}

if (process.argv[1] && path.resolve(process.argv[1]) === __filename) {
  runRealSidecarExperienceMatrix();
}
