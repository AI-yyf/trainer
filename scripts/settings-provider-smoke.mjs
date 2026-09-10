import process from "node:process";

/**
 * Settings / provider connection smoke (梅姐 knife).
 * Steps:
 *  1) Auth failure with FAKE key → authentication_failed (+ elapsedMs)
 *  2) Capability / connection-type failure → provider_capability_test_failed (or aligned)
 *  3) Optional live POST /provider/test success when TRAINER_PROVIDER_SMOKE_* is set
 *
 * Paste/newapi_channel_conn parse path is covered by
 * extension/tests/providerConnectionPaste.test.js (fixtures use sk-test-fixture-key only).
 *
 * Never echo real keys; reports redact sk-***.
 */

const defaultSidecarUrl = "http://127.0.0.1:8765";
const defaultModel = "MiniMax-M3";
const defaultProtocol = "openai_chat_completions_compatible";
const defaultResponseLanguage = "zh-CN";
const FAKE_AUTH_KEY = "sk-fake-settings-provider-auth-fail-000";

const sidecarUrl = (
  process.env.TRAINER_SETTINGS_PROVIDER_SMOKE_SIDECAR_URL ??
    process.env.TRAINER_PROVIDER_SMOKE_SIDECAR_URL ??
    defaultSidecarUrl
)
  .trim()
  .replace(/\/+$/, "");
const providerBaseUrl = (
  process.env.TRAINER_SETTINGS_PROVIDER_SMOKE_BASE_URL ??
    process.env.TRAINER_PROVIDER_SMOKE_BASE_URL ??
    ""
)
  .trim()
  .replace(/\/+$/, "");
const providerApiKey = (
  process.env.TRAINER_SETTINGS_PROVIDER_SMOKE_API_KEY ??
    process.env.TRAINER_PROVIDER_SMOKE_API_KEY ??
    ""
).trim();
const providerModel = (
  process.env.TRAINER_SETTINGS_PROVIDER_SMOKE_MODEL ??
    process.env.TRAINER_PROVIDER_SMOKE_MODEL ??
    defaultModel
).trim();
const providerProtocol = (
  process.env.TRAINER_SETTINGS_PROVIDER_SMOKE_PROTOCOL ??
    process.env.TRAINER_PROVIDER_SMOKE_PROTOCOL ??
    defaultProtocol
).trim() || defaultProtocol;
const responseLanguage = (
  process.env.TRAINER_SETTINGS_PROVIDER_SMOKE_RESPONSE_LANGUAGE ??
    defaultResponseLanguage
).trim();
const skipLive =
  String(process.env.TRAINER_SETTINGS_PROVIDER_SMOKE_SKIP_LIVE || "").trim() === "1";

const smokeStartedAt = Date.now();

function elapsedMs() {
  return Date.now() - smokeStartedAt;
}

function redactSecrets(value) {
  return String(value || "").replace(/sk-[A-Za-z0-9_-]+/g, "sk-***");
}

function redactDeep(value) {
  if (Array.isArray(value)) {
    return value.map(redactDeep);
  }
  if (value && typeof value === "object") {
    const out = {};
    for (const [key, entry] of Object.entries(value)) {
      if (
        typeof entry === "string" &&
        (/api[_-]?key/i.test(key) || entry.startsWith("sk-"))
      ) {
        out[key] = "sk-***";
      } else {
        out[key] = redactDeep(entry);
      }
    }
    return out;
  }
  if (typeof value === "string") {
    return redactSecrets(value);
  }
  return value;
}

async function emitJson(stream, report) {
  await new Promise((resolve, reject) => {
    stream.write(`${JSON.stringify(report)}\n`, (error) => {
      if (error) {
        reject(error);
        return;
      }
      resolve();
    });
  });
}

async function failure(report) {
  const payload = {
    ok: false,
    honest_failure: true,
    elapsedMs: elapsedMs(),
    ...redactDeep(report),
  };
  await emitJson(process.stdout, payload);
  process.exitCode = 1;
  return payload;
}

async function success(report) {
  const payload = {
    ok: true,
    elapsedMs: elapsedMs(),
    ...redactDeep(report),
  };
  await emitJson(process.stdout, payload);
  return payload;
}

async function postJson(path, body, { baseUrl = sidecarUrl, timeoutMs = 120_000 } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const started = Date.now();
  try {
    const response = await fetch(`${baseUrl}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json; charset=utf-8" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    const text = await response.text();
    let json = null;
    try {
      json = text ? JSON.parse(text) : null;
    } catch {
      json = null;
    }
    return {
      response,
      json,
      text,
      stepElapsedMs: Date.now() - started,
    };
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Align sidecar categories with Settings / Coach failure vocabulary.
 * invalid_key_or_permission → authentication_failed (Settings accepts both).
 * Concrete transport categories stay concrete; everything else is
 * provider_capability_test_failed.
 */
function classifyProviderTestFailure(response, body) {
  const httpStatus = response?.status;
  const payload = body && typeof body === "object" ? body : {};
  const nestedStatus = Number(payload.status_code);
  const status =
    Number.isFinite(nestedStatus) && nestedStatus > 0 ? nestedStatus : httpStatus;
  const rawCategory = String(payload.error_category || payload.status || "")
    .trim()
    .toLowerCase();

  if (
    status === 401 ||
    status === 403 ||
    rawCategory === "authentication_failed" ||
    rawCategory === "invalid_key_or_permission" ||
    rawCategory === "invalid_api_key" ||
    rawCategory === "missing_api_key"
  ) {
    return {
      category: "authentication_failed",
      status: status || httpStatus || 401,
      rawCategory: rawCategory || null,
    };
  }
  if (status === 429 || rawCategory === "rate_limit") {
    return {
      category: "rate_limit",
      status: status || httpStatus || 429,
      rawCategory: rawCategory || null,
    };
  }
  if (status === 408 || status === 504 || rawCategory === "timeout") {
    return {
      category: "timeout",
      status: status || httpStatus || 408,
      rawCategory: rawCategory || null,
    };
  }
  if (rawCategory === "network" || rawCategory === "network_error") {
    return {
      category: "network",
      status: status || httpStatus,
      rawCategory: rawCategory || null,
    };
  }
  if (
    rawCategory === "unknown_protocol" ||
    rawCategory === "model_not_found" ||
    rawCategory === "model_unsupported" ||
    rawCategory === "model_not_supported" ||
    rawCategory === "model_not_tested" ||
    rawCategory === "empty_response" ||
    rawCategory === "malformed_response" ||
    rawCategory === "protocol_mismatch"
  ) {
    return {
      category: "provider_capability_test_failed",
      status: status || httpStatus,
      rawCategory: rawCategory || null,
    };
  }
  return {
    category: "provider_capability_test_failed",
    status: status || httpStatus,
    rawCategory: rawCategory || null,
  };
}

function providerPayload(overrides = {}) {
  return {
    name: "settings-provider-smoke",
    base_url: providerBaseUrl || "http://relay.example.test",
    model: providerModel,
    protocol: providerProtocol,
    ...overrides,
  };
}

async function main() {
  const checks = {};
  const stepTiming = {};

  // --- 1) Auth failure with FAKE key (never uses live key) ---
  const authBase =
    providerBaseUrl ||
    process.env.TRAINER_SETTINGS_PROVIDER_SMOKE_AUTH_BASE_URL ||
    "http://minimax.redfast.top";
  const authProbe = await postJson("/provider/test", {
    provider: providerPayload({
      base_url: String(authBase).replace(/\/+$/, ""),
      protocol: defaultProtocol,
    }),
    api_key: FAKE_AUTH_KEY,
    response_language: responseLanguage,
    probe_message: "settings-provider auth fail probe",
  });
  stepTiming.auth_failure = authProbe.stepElapsedMs;
  const authClassified = classifyProviderTestFailure(authProbe.response, authProbe.json);
  if (authClassified.category !== "authentication_failed" || authProbe.json?.ok === true) {
    return failure({
      step: "auth_failure",
      category: authClassified.category,
      detail: `Expected authentication_failed for fake key, got ${authClassified.category} (raw=${authClassified.rawCategory}).`,
      status: authClassified.status,
      rawCategory: authClassified.rawCategory,
      provider_ok: authProbe.json?.ok ?? null,
      stepTiming,
      checks,
    });
  }
  checks.auth_failure = "passed";

  // --- 2a) Capability: connection type misused as protocol ---
  const capabilityProbe = await postJson("/provider/test", {
    provider: {
      name: "settings-provider-smoke",
      base_url: "http://relay.example.test",
      model: providerModel,
      protocol: "newapi_channel_conn",
      connection_type: "newapi_channel_conn",
    },
    api_key: "sk-fake-settings-provider-capability-000",
    response_language: responseLanguage,
  });
  stepTiming.capability_unknown_protocol = capabilityProbe.stepElapsedMs;
  const capabilityClassified = classifyProviderTestFailure(
    capabilityProbe.response,
    capabilityProbe.json,
  );
  if (
    capabilityClassified.category !== "provider_capability_test_failed" ||
    capabilityProbe.json?.ok === true
  ) {
    return failure({
      step: "capability_unknown_protocol",
      category: capabilityClassified.category,
      detail: `Expected provider_capability_test_failed for newapi_channel_conn-as-protocol, got ${capabilityClassified.category} (raw=${capabilityClassified.rawCategory}).`,
      status: capabilityClassified.status,
      rawCategory: capabilityClassified.rawCategory,
      stepTiming,
      checks,
    });
  }
  checks.capability_unknown_protocol = "passed";

  // --- 2b) Unreachable host → network (aligned honest category) ---
  const networkProbe = await postJson("/provider/test", {
    provider: providerPayload({
      base_url: "http://127.0.0.1:1",
      protocol: defaultProtocol,
    }),
    api_key: "sk-fake-settings-provider-network-000",
    response_language: responseLanguage,
    probe_message: "settings-provider network fail probe",
  });
  stepTiming.capability_network = networkProbe.stepElapsedMs;
  const networkClassified = classifyProviderTestFailure(
    networkProbe.response,
    networkProbe.json,
  );
  if (networkClassified.category !== "network" || networkProbe.json?.ok === true) {
    return failure({
      step: "capability_network",
      category: networkClassified.category,
      detail: `Expected network for unreachable host, got ${networkClassified.category} (raw=${networkClassified.rawCategory}).`,
      status: networkClassified.status,
      rawCategory: networkClassified.rawCategory,
      provider_detail: networkProbe.json?.detail ?? null,
      stepTiming,
      checks,
    });
  }
  checks.capability_network = "passed";

  // --- 3) Optional live success ---
  let live = null;
  if (!skipLive && providerBaseUrl && providerApiKey) {
    const liveProbe = await postJson("/provider/test", {
      provider: providerPayload(),
      api_key: providerApiKey,
      response_language: responseLanguage,
      probe_message: "请用一句话确认当前 Settings provider 连接可用。",
    });
    stepTiming.live_provider_test = liveProbe.stepElapsedMs;
    if (!liveProbe.response.ok || liveProbe.json?.ok !== true) {
      const liveClassified = classifyProviderTestFailure(liveProbe.response, liveProbe.json);
      return failure({
        step: "live_provider_test",
        category: liveClassified.category,
        detail: `Live /provider/test failed: ${redactSecrets(liveProbe.json?.detail || liveClassified.category)}`,
        status: liveClassified.status,
        rawCategory: liveClassified.rawCategory,
        stepTiming,
        checks,
      });
    }
    checks.live_provider_test = "passed";
    live = {
      ok: true,
      status: liveProbe.json?.status ?? "connected",
      error_category: liveProbe.json?.error_category ?? null,
      tools_ready: liveProbe.json?.tools_ready ?? liveProbe.json?.toolsReady ?? null,
      streaming_ready:
        liveProbe.json?.streaming_ready ?? liveProbe.json?.streamingReady ?? null,
      model: providerModel,
      protocol: providerProtocol,
      base_url_host: (() => {
        try {
          return new URL(providerBaseUrl).host;
        } catch {
          return "redacted";
        }
      })(),
      api_key: "sk-***",
      stepElapsedMs: liveProbe.stepElapsedMs,
    };
  } else {
    checks.live_provider_test = "skipped";
  }

  return success({
    step: "settings_provider",
    checks,
    stepTiming,
    auth_failure: {
      category: "authentication_failed",
      rawCategory: authClassified.rawCategory,
      status: authClassified.status,
      elapsedMs: authProbe.stepElapsedMs,
      api_key: "sk-***",
    },
    capability_failure: {
      category: "provider_capability_test_failed",
      rawCategory: capabilityClassified.rawCategory,
      status: capabilityClassified.status,
      elapsedMs: capabilityProbe.stepElapsedMs,
    },
    network_failure: {
      category: "network",
      rawCategory: networkClassified.rawCategory,
      status: networkClassified.status,
      elapsedMs: networkProbe.stepElapsedMs,
    },
    live,
  });
}

main().catch(async (error) => {
  await failure({
    step: "unhandled",
    category: "smoke_crash",
    detail: redactSecrets(error?.stack || String(error)),
  });
});
