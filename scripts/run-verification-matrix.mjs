import { spawnSync } from "node:child_process";
import process from "node:process";

const layers = [
  {
    id: "preview",
    label: "200 experience scenarios / Preview",
    command: process.execPath,
    args: ["node_modules/playwright/cli.js", "test", "e2e/trainer-experience-matrix.spec.js", "--workers=4", "--reporter=line"],
    cwd: process.cwd(),
    external: false,
  },
  {
    id: "sidecar",
    label: "200 experience scenarios / real sidecar with scripted provider",
    command: process.platform === "win32" ? "python" : "python3",
    args: ["-m", "pytest", "tests/test_real_sidecar_experience_matrix.py", "-q"],
    cwd: "server",
    external: false,
    limitation: "The provider is scripted; this is not live Provider or model evidence.",
  },
  {
    id: "provider",
    label: "Provider live smoke",
    command: "npm",
    args: ["run", "smoke:provider"],
    external: true,
    envKeys: ["TRAINER_PROVIDER_SMOKE_API_KEY", "TRAINER_PROVIDER_SMOKE_BASE_URL", "TRAINER_PROVIDER_SMOKE_MODEL"],
  },
  {
    id: "host-vsix",
    label: "VS Code Host / VSIX",
    command: "npm",
    args: ["run", "verify:delivery"],
    external: true,
    envKeys: ["TRAINER_E2E_PROVIDER_API_KEY", "TRAINER_E2E_PROVIDER_BASE_URL", "TRAINER_E2E_PROVIDER_MODEL"],
  },
];

function runLayer(layer) {
  const missing = (layer.envKeys ?? []).filter((key) => !String(process.env[key] ?? "").trim());
  if (layer.external && missing.length > 0) {
    return { id: layer.id, label: layer.label, status: "external_blocked", reason: `missing secure environment: ${missing.join(", ")}` };
  }

  const result = spawnSync(layer.command, layer.args, {
    cwd: layer.cwd,
    env: process.env,
    encoding: "utf8",
    timeout: 900_000,
    maxBuffer: 2 * 1024 * 1024,
  });
  const output = `${result.stdout ?? ""}\n${result.stderr ?? ""}`.trim();
  return {
    id: layer.id,
    label: layer.label,
    status: result.status === 0 ? "passed" : "failed",
    exitCode: result.status,
    limitation: layer.limitation,
    evidence: output.split("\n").slice(-8).join("\n"),
    reason: result.error?.message,
  };
}

const results = layers.map(runLayer);
const report = {
  generatedAt: new Date().toISOString(),
  policy: "Fixture and Preview evidence never closes Provider, sidecar, Host, or VSIX layers.",
  passed: results.filter((item) => item.status === "passed"),
  failed: results.filter((item) => item.status === "failed"),
  externalBlocked: results.filter((item) => item.status === "external_blocked"),
};
process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
if (report.failed.length > 0) process.exitCode = 1;
