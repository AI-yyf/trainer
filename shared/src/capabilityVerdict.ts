import type { ProviderCapabilityTruth } from "./providerTest";

export interface TrainerCapabilityVerdict {
  chat: boolean;
  streaming: boolean;
  verifiedTools: boolean;
  imageInput: boolean;
  formalPlan: boolean;
  resourceWrite: boolean;
  reason: string;
}

export interface TrainerCapabilityVerdictInput {
  connectionState?: string;
  providerConfigured?: boolean;
  apiKeyConfigured?: boolean;
  sendBlocked?: boolean;
  lastTestOk?: boolean;
  capabilityTruth?: Partial<ProviderCapabilityTruth>;
  imageProtocolSupported?: boolean;
  authority?: {
    authorityScope?: string;
    resourceWriteAllowed?: boolean;
    resourceWriteEvidence?: {
      operation?: string;
      scope?: string;
      allowed?: boolean;
    };
  };
  workspaceManaged?: boolean;
  workspaceReadOnly?: boolean;
}

/**
 * Single conservative capability contract shared by all workbench surfaces.
 * Declared provider flags never promote a capability to usable without a live observation.
 */
export function deriveTrainerCapabilityVerdict(
  input: TrainerCapabilityVerdictInput,
): TrainerCapabilityVerdict {
  const configured = input.providerConfigured === true;
  const credentials = input.apiKeyConfigured === true;
  const connected = input.connectionState === "connected";
  const lastTestOk = input.lastTestOk === true;
  const connectedTransport =
    configured && credentials && connected && input.sendBlocked !== true && lastTestOk;
  const chat = connectedTransport;
  const streaming = connectedTransport && input.capabilityTruth?.streamingReady === true;
  const verifiedTools = connectedTransport && input.capabilityTruth?.toolsReady === true;
  const imageInput =
    connectedTransport &&
    input.capabilityTruth?.visionReady === true &&
    input.imageProtocolSupported === true;
  const authorityEvidence = input.authority?.resourceWriteEvidence;
  const resourceWrite =
    input.authority?.authorityScope === "trainer_sandbox" &&
    input.authority.resourceWriteAllowed === true &&
    authorityEvidence?.operation === "write" &&
    authorityEvidence.scope === "trainer_sandbox" &&
    authorityEvidence.allowed === true;
  const workspaceWritable = resourceWrite;
  const formalPlan = connectedTransport && verifiedTools && workspaceWritable;

  return {
    chat,
    streaming,
    verifiedTools,
    imageInput,
    formalPlan,
    resourceWrite,
    reason: !configured
      ? "provider_not_configured"
      : !credentials
        ? "provider_api_key_missing"
        : !connected
          ? "provider_not_connected"
          : input.sendBlocked
            ? "provider_send_blocked"
            : !lastTestOk
              ? "provider_not_tested"
              : !verifiedTools
                ? "tools_not_verified"
                : !workspaceWritable
                  ? "workspace_not_admitted"
                  : "ready",
  };
}
