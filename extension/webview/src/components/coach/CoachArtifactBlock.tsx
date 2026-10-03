import { NextAction } from "../../templates/NextAction";
import type { ReactNode } from "react";

import type { ComposerLanguage } from "../../lib/types";
import { artifactBlockCopy, artifactInlineLeadCopy } from "./coachArtifactBlockCopy";
import { reviewConceptLabel } from "../../lib/reviewLabel";
import { MessageRichContent } from "./MessageRichContent";

export type CoachArtifactKind =
  | "task"
  | "plan"
  | "evaluation"
  | "note"
  | (string & {});

export interface CoachArtifactBlockData {
  kind: CoachArtifactKind;
  title: string;
  summary?: string;
  content?: string;
  bullets?: string[];
  recommendedAction?: "plan" | "next_task" | "review" | "hint" | "retry_review" | "task";
  rationale?: string;
  focusArea?: string;
  verification?: string[];
  metadata?: Record<string, unknown>;
  teaser?: string;
}

export interface CoachArtifactBlockProps {
  artifact: CoachArtifactBlockData;
  /** Replies with a readable body only need an actionable attachment. */
  compact?: boolean;
  className?: string;
  openLabel?: string;
  language?: ComposerLanguage;
  icon?: ReactNode;
  interactive?: boolean;
  onOpen?: (artifact: CoachArtifactBlockData) => void;
}

function artifactInlineLead(
  kind: CoachArtifactKind,
  language: ComposerLanguage,
): string | undefined {
  if (kind === "principle") {
    return artifactInlineLeadCopy(language, "原理");
  }
  if (kind === "review") {
    return artifactInlineLeadCopy(language, "先看这个判断点");
  }
  return undefined;
}

const ACTION_LABEL_KEYS = {
  plan: "打开计划",
  next_task: "给我下一题",
  review: "开始检查",
  hint: "给我更小提示",
  retry_review: "再次检查",
  task: "设为练习",
} as const;

function artifactActionLabel(
  action: NonNullable<CoachArtifactBlockData["recommendedAction"]>,
  language: ComposerLanguage,
): string {
  return artifactBlockCopy(language, ACTION_LABEL_KEYS[action]);
}

const META_LABEL_KEYS = {
  focus: "重点",
  why: "原因",
  verify: "验证",
  decision: "决策",
  blocker: "卡点",
  resumeThread: "续接",
  teachingNote: "教学提示",
  confidence: "把握",
  evidence: "证据",
} as const;

function artifactMetaLabel(
  key: "focus" | "why" | "verify" | "decision" | "blocker" | "resumeThread" | "teachingNote" | "confidence" | "evidence",
  language: ComposerLanguage,
): string {
  return artifactBlockCopy(language, META_LABEL_KEYS[key]);
}

function artifactMetadataRecord(artifact: CoachArtifactBlockData): Record<string, unknown> | undefined {
  const metadata = artifact.metadata;
  if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) {
    return undefined;
  }
  return metadata;
}

function artifactMetadataText(
  metadata: Record<string, unknown> | undefined,
  keys: string[],
): string | undefined {
  if (!metadata) {
    return undefined;
  }
  for (const key of keys) {
    const value = metadata[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return undefined;
}

function artifactMetadataList(
  metadata: Record<string, unknown> | undefined,
  keys: string[],
): string[] {
  if (!metadata) {
    return [];
  }
  for (const key of keys) {
    const value = metadata[key];
    if (!Array.isArray(value)) {
      continue;
    }
    const items = value
      .map((item) => (typeof item === "string" ? item.trim() : ""))
      .filter(Boolean);
    if (items.length > 0) {
      return items;
    }
  }
  return [];
}

function actionSentence(
  action: NonNullable<CoachArtifactBlockData["recommendedAction"]>,
  language: ComposerLanguage,
): string {
  return artifactBlockCopy(language, "下一步：{action}。").replace(
    "{action}",
    artifactActionLabel(action, language),
  );
}

function actionButtonLabel(
  action: NonNullable<CoachArtifactBlockData["recommendedAction"]>,
  language: ComposerLanguage,
): string {
  return artifactBlockCopy(language, "下一步：{action}").replace(
    "{action}",
    artifactActionLabel(action, language),
  );
}

function contentSummaryLabel(kind: CoachArtifactKind, language: ComposerLanguage): string {
  if (kind === "review" || kind === "evaluation") {
    return artifactBlockCopy(language, "判断依据");
  }
  return artifactBlockCopy(language, "补充说明");
}

function verificationLead(
  items: string[],
  language: ComposerLanguage,
): string {
  if (items.length === 0) {
    return "";
  }
  return artifactBlockCopy(language, "做完先看 {items}。").replace(
    "{items}",
    items.join(artifactBlockCopy(language, "；")),
  );
}

const KIND_LABEL_KEYS: Partial<Record<CoachArtifactKind, string>> = {
  task: "练习题",
  evaluation: "检查",
  idea_implementation: "实现",
  project_idea: "练习想法",
  project_adaptation: "改造",
  project_source: "来源",
  principle: "原理",
  review: "回看",
  plan_update: "计划",
  next_step: "下一步",
};

function artifactKindLabel(
  kind: CoachArtifactKind,
  language: ComposerLanguage,
): string | undefined {
  const key = KIND_LABEL_KEYS[kind];
  return key ? artifactBlockCopy(language, key) : undefined;
}

function artifactTeaser(
  artifact: CoachArtifactBlockData,
  language: ComposerLanguage,
): string | undefined {
  if (typeof artifact.teaser === "string" && artifact.teaser.trim()) {
    return artifact.teaser.trim();
  }
  if (artifact.bullets?.length) {
    return artifact.bullets[0];
  }
  if (artifact.focusArea) {
    return artifactBlockCopy(language, "先盯住 {area}").replace("{area}", artifact.focusArea);
  }
  return undefined;
}

/**
 * Artifact details render flat: folding supplementary reasoning away hid the
 * coach's actual answer and read as broken/empty cards.
 */

export function CoachArtifactBlock({
  artifact,
  compact = false,
  className,
  openLabel = "Open",
  language = "en-US",
  icon,
  interactive =
    Boolean(artifact.recommendedAction) ||
    !["note", "idea_implementation", "project_idea", "project_adaptation", "principle", "review", "plan_update", "next_step"].includes(artifact.kind),
  onOpen,
}: CoachArtifactBlockProps) {
  const classes = [
    "artifact-card",
    "coach-artifact-card",
    `artifact-card--${artifact.kind}`,
    className,
  ]
    .filter(Boolean)
    .join(" ");
  const actionLabel = artifact.recommendedAction
    ? actionButtonLabel(artifact.recommendedAction, language)
    : openLabel;
  const metadata = artifactMetadataRecord(artifact);
  const isRecallReview = artifact.kind === "review" &&
    metadata?.evidence_scope === "self_reported_recall";
  const displayFocus = isRecallReview && artifact.focusArea
    ? reviewConceptLabel(artifact.focusArea) : artifact.focusArea;
  const displayTitle = isRecallReview && artifact.focusArea && displayFocus
    ? artifact.title.replace(artifact.focusArea, displayFocus) : artifact.title;
  if (compact) {
    if (["evaluation", "review"].includes(artifact.kind) && !artifact.recommendedAction) return null;
    if (!onOpen || (!interactive && !artifact.recommendedAction)) return null;
    return (
      <NextAction
        label={artifactBlockCopy(language, "下一步")}
        title={displayTitle}
        detail={artifact.verification?.[0]}
        action={{ label: actionLabel, onClick: () => onOpen(artifact) }}
      />
    );
  }
  const decision = artifactMetadataText(metadata, ["decision"]);
  const blocker = artifactMetadataText(metadata, ["blocker"]);
  const resumeThread = artifactMetadataText(metadata, ["resumeThread", "resume_thread"]);
  const teachingNote = artifactMetadataText(metadata, ["teachingNote", "teaching_note"]);
  const confidence = artifactMetadataText(metadata, ["confidence"]);
  const evidence = artifact.verification?.length
    ? artifact.verification
    : artifactMetadataList(metadata, ["evidence"]);
  const showDetailBlock = Boolean(
    artifact.rationale ||
      artifact.focusArea ||
      artifact.content ||
      decision ||
      blocker ||
      resumeThread ||
      teachingNote ||
      confidence ||
      evidence.length,
  );
  const inlineLead = artifactInlineLead(artifact.kind, language);
  const isPrimaryLaneArtifact =
    artifact.kind === "idea_implementation" ||
    artifact.kind === "project_idea" ||
    artifact.kind === "project_adaptation" ||
    artifact.kind === "next_step";
  const kindLabel = artifactKindLabel(artifact.kind, language);
  const showKindLabel = Boolean(kindLabel) && !isPrimaryLaneArtifact;
  const detailSummary = contentSummaryLabel(artifact.kind, language);
  const teaser = artifactTeaser({ ...artifact, focusArea: displayFocus }, language);
  const showInlineDetails = isPrimaryLaneArtifact;
  const showTeaser =
    Boolean(teaser) &&
    teaser?.trim() !== artifact.summary?.trim() &&
    teaser?.trim() !== displayTitle.trim();
  const detailBody: ReactNode = (
    <>
      {artifact.focusArea ? (
        <p className="artifact-card__detail-note">
          <strong>{artifactMetaLabel("focus", language)}</strong>
          {artifactBlockCopy(language, "：")}
          {displayFocus}
        </p>
      ) : null}
      {artifact.content ? (
        <MessageRichContent body={artifact.content} language={language} />
      ) : null}
      {artifact.rationale ? (
        <>
          <p className="artifact-card__detail-note">
            <strong>{artifactMetaLabel("why", language)}</strong>
            {artifactBlockCopy(language, "：")}
          </p>
          <MessageRichContent body={artifact.rationale} language={language} />
        </>
      ) : null}
      {decision ? (
        <p className="artifact-card__detail-note">
            <strong>{artifactMetaLabel("decision", language)}</strong>
            {artifactBlockCopy(language, "：")}
            {decision}
        </p>
      ) : null}
      {blocker ? (
        <p className="artifact-card__detail-note">
            <strong>{artifactMetaLabel("blocker", language)}</strong>
            {artifactBlockCopy(language, "：")}
            {blocker}
        </p>
      ) : null}
      {resumeThread ? (
        <p className="artifact-card__detail-note">
            <strong>{artifactMetaLabel("resumeThread", language)}</strong>
            {artifactBlockCopy(language, "：")}
            {resumeThread}
        </p>
      ) : null}
      {teachingNote ? (
        <p className="artifact-card__detail-note">
            <strong>{artifactMetaLabel("teachingNote", language)}</strong>
            {artifactBlockCopy(language, "：")}
            {teachingNote}
        </p>
      ) : null}
      {confidence ? (
        <p className="artifact-card__detail-note">
            <strong>{artifactMetaLabel("confidence", language)}</strong>
            {artifactBlockCopy(language, "：")}
            {confidence}
        </p>
      ) : null}
      {evidence.length ? (
        <>
          <p className="artifact-card__detail-note">
            <strong>{artifactMetaLabel("verify", language)}</strong>
            {artifactBlockCopy(language, "：")}
          </p>
          <ul>
            {evidence.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </>
      ) : null}
    </>
  );

  return (
    <article className={classes} data-artifact-kind={artifact.kind} data-artifact-primary={isPrimaryLaneArtifact ? "true" : "false"}>
      <div className="artifact-card__header">
        <div className="artifact-card__header-main">
          {showKindLabel ? <span className="artifact-card__kind">{kindLabel}</span> : null}
          <strong>{displayTitle}</strong>
        </div>
        {icon ? <span className="artifact-card__icon">{icon}</span> : null}
      </div>
      {inlineLead ? <p className="artifact-card__lead">{inlineLead}</p> : null}
      {artifact.summary ? (
        <div className="artifact-card__summary">
          <MessageRichContent body={artifact.summary} language={language} />
        </div>
      ) : null}
      {showTeaser && teaser ? <p className="artifact-card__teaser">{teaser}</p> : null}
      {artifact.bullets?.length ? (
        <ul>
          {artifact.bullets
            .filter((bullet) => bullet !== teaser)
            .slice(0, 1)
            .map((bullet) => (
            <li key={bullet}>{bullet}</li>
          ))}
        </ul>
      ) : null}
      {showDetailBlock ? (
        <div
          className={`artifact-card__details-body${showInlineDetails ? " artifact-card__details-body--inline" : ""}${
            showInlineDetails ? " coach-artifact-details" : ""
          }`}
          aria-label={detailSummary}
        >
          {detailBody}
        </div>
      ) : null}
      {!showDetailBlock && evidence.length ? (
        <p className="artifact-card__next-note">
          {verificationLead(evidence, language)}
        </p>
      ) : null}
      {artifact.recommendedAction && onOpen ? (
        <button className="artifact-card__next-action" type="button" onClick={() => onOpen(artifact)}>
          {actionLabel}
        </button>
      ) : artifact.recommendedAction ? (
        <p className="artifact-card__next-note">{actionSentence(artifact.recommendedAction, language)}</p>
      ) : null}
      {interactive && !artifact.recommendedAction ? (
        onOpen ? (
          <button className="artifact-card__action" type="button" onClick={() => onOpen(artifact)}>
            {actionLabel}
          </button>
        ) : (
          <span className="artifact-card__action">{actionLabel}</span>
        )
      ) : null}
    </article>
  );
}
