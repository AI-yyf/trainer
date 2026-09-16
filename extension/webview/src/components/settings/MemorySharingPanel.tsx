/**
 * MemorySharingPanel — the settings memory & privacy disclosure (batch 7).
 * Extracted verbatim from CoachSettingsView to shrink the settings surface's
 * render body; behavior and copy are unchanged.
 */

import { ActionButton } from "../common";
import { FolderIcon, TrashIcon } from "../icons";
import type { CoachSettingsLabels } from "./CoachSettingsView";
import type { MemoryShareGrant } from "../../lib/types";

interface MemorySharingPanelProps {
  copy: CoachSettingsLabels;
  canManageMemoryShares: boolean;
  memorySharingSummary: string;
  memoryShareGrants: MemoryShareGrant[];
  memoryShareSourceLabel: (sourceWorkspaceId: string) => string;
  personalAccountTrusted: boolean;
  onSetPersonalAccountTrust?: (enabled: boolean) => void;
  onGrantMemoryShare?: () => void;
  onRevokeMemoryShare?: (sourceWorkspaceId: string) => void;
}

export function MemorySharingPanel({
  copy,
  canManageMemoryShares,
  memorySharingSummary,
  memoryShareGrants,
  memoryShareSourceLabel,
  personalAccountTrusted,
  onSetPersonalAccountTrust,
  onGrantMemoryShare,
  onRevokeMemoryShare,
}: MemorySharingPanelProps) {
  return (
      <details className="settings-sheet__minor-panel settings-memory-sharing">
    <summary className="settings-memory-sharing__summary">
      <span className="eyebrow">{copy.memorySharing}</span>
      <span className="settings-sheet__remembered-preview">{memorySharingSummary}</span>
    </summary>
    <div className="settings-sheet__minor-body settings-memory-sharing__body">
      <p className="settings-sheet__note settings-sheet__note--compact">
        {canManageMemoryShares ? copy.memorySharingDetail : copy.memorySharingUnavailable}
      </p>
      {canManageMemoryShares && onSetPersonalAccountTrust ? (
        <button
          type="button"
          className={`settings-memory-sharing__trust ${
            personalAccountTrusted ? "is-on" : "is-off"
          }`}
          data-personal-account-trust={personalAccountTrusted ? "on" : "off"}
          aria-pressed={personalAccountTrusted === true}
          onClick={() => onSetPersonalAccountTrust(!personalAccountTrusted)}
        >
          <span>
            <strong>{copy.memoryPersonalTrustTitle}</strong>
            <small>{copy.memoryPersonalTrustDetail}</small>
          </span>
          <em>{personalAccountTrusted ? copy.memoryPersonalTrustDisable : copy.memoryPersonalTrustEnable}</em>
        </button>
      ) : null}
      {memoryShareGrants.length > 0 ? (
        <ul className="settings-memory-sharing__list">
          {memoryShareGrants.map((grant) => (
            <li
              key={`${grant.sourceWorkspaceId}:${grant.targetWorkspaceId}`}
              className="settings-memory-sharing__item"
            >
              <span className="settings-memory-sharing__source">
                <strong>{memoryShareSourceLabel(grant.sourceWorkspaceId)}</strong>
                <small>
                  {grant.categories
                    .map((category) =>
                      category === "preferences"
                        ? copy.memorySharePreferences
                        : copy.memoryShareMastery,
                    )
                    .join(" · ")}
                </small>
              </span>
              <button
                className="settings-memory-sharing__revoke"
                type="button"
                disabled={!onRevokeMemoryShare}
                title={copy.memoryShareRevoke}
                aria-label={`${copy.memoryShareRevoke}: ${memoryShareSourceLabel(
                  grant.sourceWorkspaceId,
                )}`}
                onClick={() => onRevokeMemoryShare?.(grant.sourceWorkspaceId)}
              >
                <TrashIcon size={14} />
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <div className="empty-state settings-memory-sharing__empty">
          <span className="empty-state__icon" aria-hidden="true">
            <FolderIcon size={16} />
          </span>
          <span className="empty-state__title">{copy.memorySharingNone}</span>
          {canManageMemoryShares ? (
            <span className="empty-state__action">
              <ActionButton
                fullWidth={false}
                icon={<FolderIcon size={14} />}
                label={copy.memoryShareGrant}
                detail={copy.memorySharingDetail}
                onClick={onGrantMemoryShare}
              />
            </span>
          ) : null}
        </div>
      )}
      {memoryShareGrants.length > 0 && canManageMemoryShares ? (
        <div className="settings-actions settings-actions--compact">
          <ActionButton
            fullWidth={false}
            icon={<FolderIcon size={14} />}
            label={copy.memoryShareGrant}
            detail={copy.memorySharingDetail}
            onClick={onGrantMemoryShare}
          />
        </div>
      ) : null}
    </div>
  </details>
  );
}
