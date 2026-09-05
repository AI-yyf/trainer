import { fileURLToPath } from "node:url";

import { runServerCommand } from "./run-server-tests.mjs";

const __filename = fileURLToPath(import.meta.url);

export function runRealSidecarExperienceMatrix() {
  return runServerCommand({
    args: ["-m", "pytest", "tests/test_real_sidecar_experience_matrix.py", "-q"],
    label: "Trainer real sidecar experience matrix",
  });
}

if (process.argv[1] && fileURLToPath(import.meta.url) === __filename) {
  runRealSidecarExperienceMatrix();
}
