import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";

const require = createRequire(import.meta.url);
const DEFAULT_PROVIDER_PROTOCOL = "openai_chat_completions_compatible";

function loadProviderProtocolHelpers(extensionDir) {
  const modulePath = path.join(extensionDir, "dist", "shared", "src", "providerProtocols.js");
  if (!fs.existsSync(modulePath)) {
    throw new Error(
      `VSIX E2E requires compiled provider protocol helpers at ${modulePath}. Build the extension first.`,
    );
  }

  const helpers = require(modulePath);
  if (
    !Array.isArray(helpers.SUPPORTED_PROVIDER_PROTOCOLS) ||
    typeof helpers.normalizeProviderProtocol !== "function" ||
    typeof helpers.defaultCapabilitiesForProtocol !== "function"
  ) {
    throw new Error("Compiled provider protocol helpers are incomplete for VSIX E2E.");
  }
  return helpers;
}

function requestDefaultsForProtocol(protocol) {
  if (
    protocol === "openai_responses" ||
    protocol === "openai_chat_completions" ||
    protocol === "openai_chat_completions_compatible"
  ) {
    return {
      extra_body: {
        thinking: {
          type: "disabled",
        },
      },
    };
  }
  return undefined;
}

function providerNameForProtocol(protocol) {
  return protocol === DEFAULT_PROVIDER_PROTOCOL
    ? "trainer-e2e-openai-compatible"
    : `trainer-e2e-${protocol.replace(/_/g, "-")}`;
}

export function resolveVsixE2EProviderConfiguration({ extensionDir, requestedProtocol } = {}) {
  if (!extensionDir) {
    throw new Error("resolveVsixE2EProviderConfiguration requires extensionDir.");
  }

  const {
    SUPPORTED_PROVIDER_PROTOCOLS,
    defaultCapabilitiesForProtocol,
    normalizeProviderProtocol,
  } = loadProviderProtocolHelpers(extensionDir);
  const normalizedProtocol =
    normalizeProviderProtocol(
      typeof requestedProtocol === "string" ? requestedProtocol.trim() : undefined,
    ) ?? DEFAULT_PROVIDER_PROTOCOL;
  if (!SUPPORTED_PROVIDER_PROTOCOLS.includes(normalizedProtocol)) {
    throw new Error(`VSIX E2E resolved an unsupported provider protocol: ${normalizedProtocol}.`);
  }

  return {
    name: providerNameForProtocol(normalizedProtocol),
    protocol: normalizedProtocol,
    capabilities: defaultCapabilitiesForProtocol(normalizedProtocol),
    requestDefaults: requestDefaultsForProtocol(normalizedProtocol),
  };
}

export function buildVsixE2EProviderSavePayloadTemplate(configuration) {
  const payload = {
    name: configuration.name,
    protocol: configuration.protocol,
    capabilities: configuration.capabilities,
  };
  if (configuration.requestDefaults) {
    payload.requestDefaults = configuration.requestDefaults;
  }
  return payload;
}
