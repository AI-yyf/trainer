import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import http from "node:http";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { resolveVsixE2EProviderConfiguration } from "./vsix-e2e-provider-config.mjs";
import {
  VSIX_E2E_FIXTURE_PROVIDER_MODEL,
  VSIX_E2E_FIXTURE_PROVIDER_PROTOCOL,
} from "./vsix-e2e-fixture-provider.mjs";

const fixtureScriptPath = fileURLToPath(new URL("./vsix-e2e-fixture-provider.mjs", import.meta.url));
const READY_TYPE = "trainer-vsix-e2e-fixture-ready";

export function readVsixE2EExternalProviderOverride(env = process.env) {
  const baseUrl = readEnvValue(env, "TRAINER_E2E_PROVIDER_BASE_URL");
  const apiKey = readEnvValue(env, "TRAINER_E2E_PROVIDER_API_KEY");
  const model = readEnvValue(env, "TRAINER_E2E_PROVIDER_MODEL");
  return {
    baseUrl,
    apiKey,
    model,
    complete: Boolean(baseUrl && apiKey && model),
    partial: Boolean(baseUrl || apiKey || model) && !(baseUrl && apiKey && model),
  };
}

export function withVsixE2EFixtureLoopbackBypass(env = process.env) {
  const existing = [env?.NO_PROXY, env?.no_proxy]
    .filter((value) => typeof value === "string")
    .flatMap((value) => value.split(","))
    .map((value) => value.trim())
    .filter(Boolean);
  const hosts = [...existing, "127.0.0.1", "localhost"].filter(
    (value, index, values) =>
      values.findIndex((candidate) => candidate.toLowerCase() === value.toLowerCase()) === index,
  );
  const noProxy = hosts.join(",");
  return { ...env, NO_PROXY: noProxy, no_proxy: noProxy };
}

export async function resolveVsixE2EProviderRuntime({
  extensionDir,
  requestedProtocol,
  env = process.env,
  startFixture = startVsixE2EFixtureProviderProcess,
} = {}) {
  if (!extensionDir) {
    throw new Error("resolveVsixE2EProviderRuntime requires extensionDir.");
  }

  const external = readVsixE2EExternalProviderOverride(env);
  if (external.complete) {
    return {
      source: "external",
      baseUrl: external.baseUrl,
      apiKey: external.apiKey,
      model: external.model,
      configuration: resolveVsixE2EProviderConfiguration({ extensionDir, requestedProtocol }),
      usedPartialExternalOverride: false,
      async stop() {},
      async readFixtureStats() {
        return null;
      },
    };
  }

  const fixture = await startFixture();
  if (!fixture || !fixture.baseUrl || !fixture.apiKey || !fixture.model) {
    throw new Error("VSIX E2E fixture provider did not return a complete local connection.");
  }
  return {
    source: "fixture",
    baseUrl: fixture.baseUrl,
    apiKey: fixture.apiKey,
    model: fixture.model,
    configuration: resolveVsixE2EProviderConfiguration({
      extensionDir,
      requestedProtocol: fixture.protocol ?? VSIX_E2E_FIXTURE_PROVIDER_PROTOCOL,
    }),
    usedPartialExternalOverride: external.partial,
    stop: fixture.stop,
    readFixtureStats: fixture.readStats,
  };
}

export async function startVsixE2EFixtureProviderProcess({ startupTimeoutMs = 15_000 } = {}) {
  const apiKey = `trainer-vsix-e2e-${randomUUID()}`;
  const child = spawn(process.execPath, [fixtureScriptPath], {
    cwd: path.dirname(fixtureScriptPath),
    env: {
      ...process.env,
      TRAINER_VSIX_E2E_FIXTURE_API_KEY: apiKey,
    },
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
  });

  const readiness = await waitForFixtureReadiness(child, startupTimeoutMs);
  const baseUrl = typeof readiness.baseUrl === "string" ? readiness.baseUrl.trim() : "";
  const model = typeof readiness.model === "string" ? readiness.model.trim() : "";
  const protocol = typeof readiness.protocol === "string" ? readiness.protocol.trim() : "";
  if (!baseUrl || !model || !protocol) {
    await stopFixtureProcess(child);
    throw new Error("VSIX E2E fixture provider sent an incomplete readiness message.");
  }

  return {
    baseUrl,
    apiKey,
    model,
    protocol,
    stop: () => stopFixtureProcess(child),
    readStats: () => getFixtureStats(baseUrl, apiKey),
  };
}

function readEnvValue(env, key) {
  const value = env && typeof env[key] === "string" ? env[key] : "";
  return value.trim();
}

function waitForFixtureReadiness(child, startupTimeoutMs) {
  return new Promise((resolve, reject) => {
    let settled = false;
    let stdoutBuffer = "";
    let stderr = "";
    const timeout = setTimeout(() => {
      settle(new Error("VSIX E2E fixture provider did not become ready in time."));
      void stopFixtureProcess(child);
    }, startupTimeoutMs);
    const appendStderr = (chunk) => {
      stderr = `${stderr}${String(chunk)}`.slice(-4000);
    };
    const settle = (error, value) => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timeout);
      child.stdout?.off("data", onStdout);
      child.stderr?.off("data", appendStderr);
      child.off("error", onError);
      child.off("exit", onExit);
      if (error) {
        const detail = stderr.trim();
        reject(detail ? new Error(`${error.message}\n${detail}`) : error);
      } else {
        resolve(value);
      }
    };
    const onError = (error) => settle(error);
    const onExit = (code, signal) => {
      settle(new Error(`VSIX E2E fixture provider exited before readiness (code=${code}, signal=${signal ?? "none"}).`));
    };
    const onStdout = (chunk) => {
      stdoutBuffer += String(chunk);
      const lines = stdoutBuffer.split(/\r?\n/);
      stdoutBuffer = lines.pop() ?? "";
      for (const line of lines) {
        try {
          const parsed = JSON.parse(line);
          if (parsed?.type === READY_TYPE) {
            settle(null, parsed);
            return;
          }
        } catch {
          // The fixture only emits a readiness JSON line; ignore unrelated child output.
        }
      }
    };
    child.once("error", onError);
    child.once("exit", onExit);
    child.stdout?.on("data", onStdout);
    child.stderr?.on("data", appendStderr);
  });
}

function stopFixtureProcess(child) {
  return new Promise((resolve) => {
    if (child.exitCode !== null || child.signalCode !== null) {
      resolve();
      return;
    }
    let finished = false;
    const finish = () => {
      if (finished) {
        return;
      }
      finished = true;
      clearTimeout(forceStopTimer);
      resolve();
    };
    const forceStopTimer = setTimeout(() => {
      if (child.exitCode === null && child.signalCode === null) {
        child.kill("SIGKILL");
      }
    }, 5_000);
    child.once("exit", finish);
    if (!child.kill()) {
      finish();
    }
  });
}

function getFixtureStats(baseUrl, apiKey) {
  const endpoint = new URL("/__trainer_fixture__/stats", baseUrl);
  return new Promise((resolve, reject) => {
    const request = http.request(
      endpoint,
      {
        method: "GET",
        headers: { authorization: `Bearer ${apiKey}` },
        timeout: 10_000,
      },
      (response) => {
        const chunks = [];
        response.on("data", (chunk) => chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk)));
        response.on("end", () => {
          const body = Buffer.concat(chunks).toString("utf8");
          if ((response.statusCode ?? 500) >= 400) {
            reject(new Error(`VSIX E2E fixture stats request failed (${response.statusCode}).`));
            return;
          }
          try {
            resolve(JSON.parse(body));
          } catch {
            reject(new Error("VSIX E2E fixture stats response was not valid JSON."));
          }
        });
      },
    );
    request.on("timeout", () => request.destroy(new Error("VSIX E2E fixture stats request timed out.")));
    request.on("error", reject);
    request.end();
  });
}
