// @ts-check
/** @type {import('@playwright/test').Config} */
const DEFAULT_E2E_PORT = 4175;

function resolveE2ePort() {
  const configuredPort = String(process.env.TRAINER_E2E_PORT ?? "").trim();
  if (!configuredPort) {
    return DEFAULT_E2E_PORT;
  }

  const port = Number(configuredPort);
  if (!Number.isInteger(port) || port < 1024 || port > 65535) {
    throw new Error("TRAINER_E2E_PORT must be a valid local TCP port.");
  }
  return port;
}

const e2ePort = resolveE2ePort();
const e2eBaseUrl = `http://127.0.0.1:${e2ePort}`;

module.exports = {
  testDir: "./e2e",
  testMatch: "**/*.spec.js",
  timeout: 30000,
  use: {
    baseURL: e2eBaseUrl,
    headless: true,
    channel: process.env.TRAINER_E2E_CHANNEL || undefined,
  },
  webServer: {
    command: `cd extension/webview && npm run build:preview && npm run preview -- --host 127.0.0.1 --port ${e2ePort} --strictPort`, 
    url: e2eBaseUrl,
    reuseExistingServer: process.env.TRAINER_E2E_REUSE_EXISTING_SERVER === "1",
    timeout: 120000,
  },
};
