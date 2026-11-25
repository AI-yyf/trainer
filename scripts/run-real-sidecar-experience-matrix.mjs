import { fileURLToPath } from "node:url";

import { runServerTests } from "./run-server-tests.mjs";

const __filename = fileURLToPath(import.meta.url);

export function runRealSidecarExperienceMatrix() {
  return runServerTests();
}

if (process.argv[1] && fileURLToPath(import.meta.url) === __filename) {
  runRealSidecarExperienceMatrix();
}
