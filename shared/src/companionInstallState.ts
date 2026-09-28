/**
 * Companion install state machine (§十一).
 *
 * One function answers "what should the settings panel show" from the facts
 * the host can observe, so the UI never has to guess or keep its own copy of
 * the rules. Precedence: transient progress first (installing → awaiting
 * reload → preparing), then readiness, then the failure/upgrade states.
 */
import type { RemoteCompanionCapabilities } from './remoteProtocol';

/** The protocol version this build of Trainer speaks. */
export const TRAINER_REMOTE_PROTOCOL_VERSION = 2;

export type CompanionInstallState =
  | 'not_installed'
  | 'installing'
  | 'await_reload'
  | 'preparing'
  | 'ready'
  | 'version_incompatible'
  | 'connection_lost'
  | 'upgrade_available';

export type CompanionInstallFacts = {
  /** Companion capabilities from the last handshake; undefined = none yet. */
  capabilities?: RemoteCompanionCapabilities;
  /** The user asked for an install and VS Code has not finished/asked for reload yet. */
  installing?: boolean;
  /** VS Code asked for a reload after installFromVSIX. */
  reloadPending?: boolean;
  /** Companion answered capabilities but the workspace handshake is still warming up. */
  preparing?: boolean;
  /** The last bridge call failed because the remote connection dropped. */
  connectionLost?: boolean;
  /** Companion-reported build; a mismatch with the main extension flags re-install. */
  companionVersion?: string;
  mainVersion?: string;
};

export function deriveCompanionInstallState(
  facts: CompanionInstallFacts,
): CompanionInstallState {
  if (facts.installing) {
    return 'installing';
  }
  if (facts.reloadPending) {
    return 'await_reload';
  }
  const capabilities = facts.capabilities;
  if (capabilities?.available && capabilities.protocol_version === TRAINER_REMOTE_PROTOCOL_VERSION) {
    if (facts.preparing) {
      return 'preparing';
    }
    if (
      facts.companionVersion !== undefined &&
      facts.mainVersion !== undefined &&
      facts.companionVersion !== facts.mainVersion
    ) {
      return 'upgrade_available';
    }
    return 'ready';
  }
  if (
    capabilities?.available &&
    capabilities.protocol_version !== TRAINER_REMOTE_PROTOCOL_VERSION
  ) {
    return 'version_incompatible';
  }
  if (facts.connectionLost) {
    return 'connection_lost';
  }
  return 'not_installed';
}

export function isCompanionReady(state: CompanionInstallState): boolean {
  return state === 'ready' || state === 'upgrade_available';
}
