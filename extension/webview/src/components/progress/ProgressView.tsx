import { GrowthEvidence } from "../../templates/GrowthEvidence";
import { SystemState } from "../../templates/SystemState";
import { planViewLabel } from "../../lib/viewLabels";
import { useState } from "react";

import { EvidenceIcon } from "../icons/brand/trainerBrand";
import type { ComposerLanguage } from "../../lib/types";
import type {
  TrainingSkillDimensionState,
  TrainingSkillEvidenceRow,
  TrainingSkillProjection,
} from "../../lib/types";
import {
  COPY,
  DIMENSION_LABELS,
  STATE_LABELS,
  type DimensionKey,
} from "../../lib/i18n/segments/progressInlineText";
import { dimensionKeysFor } from "../../lib/progressDimensions";

function dimensionState(
  projection: TrainingSkillProjection | undefined,
  key: DimensionKey,
): TrainingSkillDimensionState | undefined {
  return projection?.dimensions?.[key];
}

export interface ProgressViewProps {
  language: ComposerLanguage;
  projection?: TrainingSkillProjection;
  onOpenTraining: () => void;
  onBack: () => void;
}

/**
 * §十二: capability presentation. Calm text rows with evidence counts —
 * no score bars, no gamification. Every claim comes from the server-side
 * skill projection; empty state explains what will populate it.
 * §十五: all eight supported languages flow through the label maps —
 * no zh/en binaries in this surface.
 */
export function ProgressView({ language, projection, onOpenTraining, onBack }: ProgressViewProps) {
  const copy = COPY[language];
  const [expandedDimension, setExpandedDimension] = useState<DimensionKey | undefined>();
  const dimensionKeys = dimensionKeysFor(projection);
  const hasAnyEvidence = dimensionKeys.some((key) => {
    const state = dimensionState(projection, key);
    return Boolean(state && (state.verifiedCount ?? 0) > 0);
  });
  const updatedAt = projection?.updatedAt ? new Date(projection.updatedAt) : undefined;
  const updatedLabel =
    updatedAt && !Number.isNaN(updatedAt.getTime())
      ? updatedAt.toLocaleString(copy.localeTag, {
          month: "short",
          day: "numeric",
          hour: "2-digit",
          minute: "2-digit",
        })
      : "";

  return (
    <GrowthEvidence parent={planViewLabel(language)} title={copy.title} updated={updatedLabel ? copy.updated(updatedLabel) : undefined} onBack={onBack}>
      {hasAnyEvidence ? (
        <ul className="progress-view__dimensions">
          {dimensionKeys.map((key) => {
            const state = dimensionState(projection, key);
            const count = state?.verifiedCount ?? 0;
            const rows: TrainingSkillEvidenceRow[] = state?.evidence ?? [];
            const expanded = expandedDimension === key && rows.length > 0;
            return (
              <li key={key} className="progress-view__row">
                <button
                  type="button"
                  className="progress-view__row-toggle"
                  aria-expanded={expanded}
                  disabled={rows.length === 0}
                  onClick={() => setExpandedDimension((current) => (current === key ? undefined : key))}
                >
                  <div className="progress-view__row-main">
                    <span className="progress-view__dimension">{DIMENSION_LABELS[language][key]}</span>
                    <span className="progress-view__state">
                      {state ? STATE_LABELS[language][state.state] : copy.notVerified}
                    </span>
                  </div>
                  <span className="progress-view__evidence">
                    {count > 0 ? copy.evidenceCount(count) : copy.noEvidence}
                  </span>
                </button>
                {expanded ? (
                  <div className="progress-view__drilldown">
                    <p className="progress-view__drilldown-why">
                      <EvidenceIcon size={12} />
                      {copy.drilldownWhy}
                    </p>
                    <ul className="progress-view__drilldown-list">
                      {rows.map((row) => {
                        const recordedAt = row.timestamp ? new Date(row.timestamp) : undefined;
                        const day = recordedAt && !Number.isNaN(recordedAt.getTime())
                          ? recordedAt.toLocaleDateString(copy.localeTag)
                          : undefined;
                        const assistance =
                          row.assistanceLevel === "independent"
                            ? copy.drilldownIndependent
                            : copy.drilldownAssisted;
                        return (
                          <li key={row.evidenceId ?? `${day}-${row.scenario ?? ""}`}>
                            <span className="progress-view__drilldown-day">{day ?? ""}</span>
                            <span className="progress-view__drilldown-assistance">{assistance}</span>
                            <span className="progress-view__drilldown-scenario">
                              {row.scenario || copy.drilldownNoScenario}
                            </span>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                ) : null}
              </li>
            );
          })}
          {(() => {
            const transfer = dimensionState(projection, "transfer");
            if (transfer && transfer.verifiedCount && transfer.verifiedCount > 0) return null;
            const strongest = dimensionKeys
              .map((k) => dimensionState(projection, k))
              .filter((s) => s && (s.verifiedCount ?? 0) > 0);
            if (strongest.length < 2) return null;
            return (
              <li className="progress-view__row progress-view__nudge">
                {/* r1-g1-2/r3: the page's single primary action — verify transfer
                    with an unfamiliar exercise — states the invitation itself;
                    the former italic conclusion sentence above it was removed as
                    a same-meaning duplicate (subtraction discipline). */}
                <button
                  type="button"
                  className="button button--accent progress-view__nudge-action"
                  onClick={onOpenTraining}
                >
                  {copy.transferAction}
                </button>
              </li>
            );
          })()}
        </ul>
      ) : (
        <SystemState kind="empty" title={copy.empty} action={{ label: copy.startPracticing, onClick: onOpenTraining }} />
      )}
    </GrowthEvidence>
  );
}
