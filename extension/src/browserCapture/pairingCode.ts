import * as crypto from 'node:crypto';

import { BROWSER_CAPTURE } from '../core/constants';

/**
 * Host side of the browser pairing handshake.
 *
 * Contract (see the delivery notes for the full pair_api_contract):
 * - the host registers the just-generated code: POST /browser/pair-code {code, expires_in}
 * - the browser exchanges it for a credential:      POST /browser/pair {code} -> {credential}
 * - either side can drop the pairing:               DELETE /browser/pair
 *
 * The host only owns code *issuance*: crypto-random, 6 digits, 10-minute
 * window, and single-use on the host ledger. Redemption itself happens in the
 * browser against the sidecar, so the single-use guarantee is enforced there;
 * the host records consumption (and revocation) so a spent code is never
 * displayed again.
 */

export const PAIRING_CODE_LENGTH = 6;

export type BrowserPairingState = 'idle' | 'active' | 'expired' | 'consumed' | 'revoked';

export interface RegisterPairingCodeRequest {
  code: string;
  expires_in: number;
}

export interface BrowserPairingTransport {
  registerPairingCode(request: RegisterPairingCodeRequest): Promise<void>;
  revokePairing(): Promise<void>;
}

export interface BrowserPairingIssue {
  code: string;
  expiresAt: number;
  expiresInSeconds: number;
  expiresInMinutes: number;
  regenerated: boolean;
}

export function generatePairingCode(randomBytes: (size: number) => Buffer = crypto.randomBytes): string {
  // Uniform 0..999_999 draw: rejection sampling keeps the modulo unbiased.
  const ceiling = 1_000_000;
  const limit = Math.floor(0x1_0000_0000 / ceiling) * ceiling;
  for (let attempt = 0; attempt < 16; attempt += 1) {
    const draw = randomBytes(4).readUInt32BE(0);
    if (draw < limit) {
      return String(draw % ceiling).padStart(PAIRING_CODE_LENGTH, '0');
    }
  }
  // 16 consecutive rejections are astronomically unlikely; fall back to the
  // low digits so the code is always a valid 6-digit string.
  return String(randomBytes(4).readUInt32BE(0) % ceiling).padStart(PAIRING_CODE_LENGTH, '0');
}

export function isPairingCodeShape(code: string | undefined): boolean {
  return typeof code === 'string' && /^[0-9]{6}$/.test(code);
}

interface PairingLedgerEntry {
  code: string;
  expiresAt: number;
}

export interface BrowserPairingSessionOptions {
  transport: BrowserPairingTransport;
  now?: () => number;
  generateCode?: () => string;
  ttlMs?: number;
}

export class BrowserPairingSession {
  private readonly transport: BrowserPairingTransport;
  private readonly now: () => number;
  private readonly generateCode: () => string;
  private readonly ttlMs: number;
  private entry?: PairingLedgerEntry;
  private consumedAt?: number;
  private revokedAt?: number;

  constructor(options: BrowserPairingSessionOptions) {
    this.transport = options.transport;
    this.now = options.now ?? (() => Date.now());
    this.generateCode = options.generateCode ?? (() => generatePairingCode());
    this.ttlMs = options.ttlMs ?? BROWSER_CAPTURE.pairingCodeTtlMs;
  }

  state(at: number = this.now()): BrowserPairingState {
    if (!this.entry) {
      return this.revokedAt !== undefined ? 'revoked' : 'idle';
    }
    if (this.consumedAt !== undefined) {
      return 'consumed';
    }
    if (at >= this.entry.expiresAt) {
      return 'expired';
    }
    return 'active';
  }

  /** The code currently displayed to the user, if it is still live. */
  activeCode(at: number = this.now()): string | undefined {
    return this.state(at) === 'active' ? this.entry?.code : undefined;
  }

  /** Single-use check: a code is valid exactly once, before its expiry. */
  isCodeActive(code: string | undefined, at: number = this.now()): boolean {
    return isPairingCodeShape(code) && this.state(at) === 'active' && this.entry?.code === code;
  }

  /**
   * Spend the displayed code. The sidecar enforces single-use at redemption;
   * this ledger transition is what lets the host stop re-displaying a spent
   * code after it learns the redemption happened.
   */
  consumePairingCode(code: string | undefined, at: number = this.now()): boolean {
    if (!this.isCodeActive(code, at)) {
      return false;
    }
    this.consumedAt = at;
    return true;
  }

  /**
   * Mint and register a fresh pairing code. Every invocation rotates: any
   * previous registration is deleted first (best-effort — it may already be
   * expired or spent server-side) so exactly one code is live at a time. This
   * also keeps the displayed code honest across a sidecar restart, which
   * forgets in-memory codes.
   */
  async issuePairingCode(): Promise<BrowserPairingIssue> {
    const at = this.now();
    const previousRegistration = this.entry;
    this.entry = undefined;
    this.consumedAt = undefined;
    this.revokedAt = undefined;
    if (previousRegistration) {
      await this.safeRevokeRegistration();
    }

    const code = this.generateCode();
    const expiresAt = at + this.ttlMs;
    await this.transport.registerPairingCode({
      code,
      expires_in: Math.max(1, Math.round(this.ttlMs / 1_000)),
    });
    this.entry = { code, expiresAt };
    return this.describe(this.entry, previousRegistration !== undefined);
  }

  /**
   * Drop the pairing both remotely (DELETE /browser/pair) and locally. Local
   * state is cleared even when the remote delete fails, so a code whose
   * registration could not be confirmed as gone is never displayed again.
   */
  async revokePairing(): Promise<{ revoked: boolean; hadRegistration: boolean; error?: string }> {
    const hadRegistration = this.entry !== undefined;
    let error: string | undefined;
    try {
      await this.transport.revokePairing();
    } catch (caught) {
      error = caught instanceof Error ? caught.message : String(caught);
    }
    this.entry = undefined;
    this.consumedAt = undefined;
    this.revokedAt = this.now();
    return error === undefined
      ? { revoked: true, hadRegistration }
      : { revoked: false, hadRegistration, error };
  }

  private async safeRevokeRegistration(): Promise<void> {
    try {
      await this.transport.revokePairing();
    } catch {
      // The previous code may already be expired or consumed server-side; the
      // new registration below is what makes the replacement authoritative.
    }
  }

  private describe(entry: PairingLedgerEntry, regenerated: boolean): BrowserPairingIssue {
    const remainingMs = Math.max(0, entry.expiresAt - this.now());
    return {
      code: entry.code,
      expiresAt: entry.expiresAt,
      expiresInSeconds: Math.ceil(remainingMs / 1_000),
      expiresInMinutes: Math.max(1, Math.ceil(remainingMs / 60_000)),
      regenerated,
    };
  }
}
