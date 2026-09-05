import type { ReactNode } from "react";

import { CollapseSection } from "../common/CollapseSection";
import type { ComposerLanguage } from "../../lib/types";
import { resolveCopy } from "../../lib/i18n/copy";
import { CollapsibleBlock } from "./CollapsibleBlock";
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
  className?: string;
  openLabel?: string;
  language?: ComposerLanguage;
  icon?: ReactNode;
  interactive?: boolean;
  /**
   * Stable "messageId:kind" identity of the hosting message. Used to
   * persist the open/closed state of the long-content CollapseSection.
   */
  collapseKey?: string;
  onOpen?: (artifact: CoachArtifactBlockData) => void;
}

function artifactInlineLead(
  kind: CoachArtifactKind,
  language: ComposerLanguage,
): string | undefined {
  if (language === "zh-CN") {
    if (kind === "principle") {
      return "原理";
    }
    if (kind === "review") {
      return "先看这个判断点";
    }
  }

  if (kind === "principle") {
    return "The principle here is";
  }
  if (kind === "review") {
    return "Check this first";
  }
  return undefined;
}

function artifactActionLabel(
  action: NonNullable<CoachArtifactBlockData["recommendedAction"]>,
  language: ComposerLanguage,
): string {
  const zh = {
    plan: "打开计划",
    next_task: "给我下一题",
    review: "开始检查",
    hint: "给我更小提示",
    retry_review: "再次检查",
    task: "设为练习",
  } as const;
  const en = {
    plan: "Open plan",
    next_task: "Next task",
    review: "Run review",
    hint: "Smaller hint",
    retry_review: "Review again",
    task: "Turn into practice",
  } as const;
  return (language === "zh-CN" ? zh : en)[action];
}

function artifactMetaLabel(
  key: "focus" | "why" | "verify" | "decision" | "blocker" | "resumeThread" | "teachingNote" | "confidence" | "evidence",
  language: ComposerLanguage,
): string {
  if (language === "zh-CN") {
    return {
      focus: "重点",
      why: "原因",
      verify: "验证",
      decision: "决策",
      blocker: "卡点",
      resumeThread: "续接",
      teachingNote: "教学提示",
      confidence: "把握",
      evidence: "证据",
    }[key];
  }

  return {
    focus: "Focus",
    why: "Why",
    verify: "Check",
    decision: "Decision",
    blocker: "Blocker",
    resumeThread: "Resume",
    teachingNote: "Teaching note",
    confidence: "Confidence",
    evidence: "Evidence",
  }[key];
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
  if (language === "zh-CN") {
    return `下一步：${artifactActionLabel(action, language)}。`;
  }
  return `Next: ${artifactActionLabel(action, language)}.`;
}

function actionButtonLabel(
  action: NonNullable<CoachArtifactBlockData["recommendedAction"]>,
  language: ComposerLanguage,
): string {
  if (language === "zh-CN") {
    return `下一步：${artifactActionLabel(action, language)}`;
  }
  return `Next: ${artifactActionLabel(action, language)}`;
}

function contentSummaryLabel(kind: CoachArtifactKind, language: ComposerLanguage): string {
  if (language === "zh-CN") {
    if (kind === "review" || kind === "evaluation") {
      return "看看判断依据";
    }
    if (kind === "plan_update" || kind === "next_step") {
      return "看看展开说明";
    }
    return "看看补充内容";
  }

  if (kind === "review" || kind === "evaluation") {
    return "See why";
  }
  if (kind === "plan_update" || kind === "next_step") {
    return "See the note";
  }
  return "See more";
}

function verificationLead(
  items: string[],
  language: ComposerLanguage,
): string {
  if (items.length === 0) {
    return "";
  }
  if (language === "zh-CN") {
    return `做完先看 ${items.join("；")}。`;
  }
  return `Check this first after: ${items.join("; ")}.`;
}

function artifactKindLabel(
  kind: CoachArtifactKind,
  language: ComposerLanguage,
): string | undefined {
  const zh: Partial<Record<CoachArtifactKind, string>> = {
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
  const en: Partial<Record<CoachArtifactKind, string>> = {
    task: "Practice",
    evaluation: "Check",
    idea_implementation: "Implementation",
    project_idea: "Idea",
    project_adaptation: "Adaptation",
    project_source: "Source",
    principle: "Principle",
    review: "Review",
    plan_update: "Plan",
    next_step: "Next step",
  };

  return (language === "zh-CN" ? zh : en)[kind];
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
    return language === "zh-CN" ? `先盯住 ${artifact.focusArea}` : `Stay with ${artifact.focusArea}`;
  }
  return undefined;
}

/**
 * Detail prose above this many characters is hosted in a persisted
 * CollapseSection (level 2) instead of being rendered flat.
 */
const COACH_ARTIFACT_COLLAPSE_THRESHOLD = 400;

function artifactDetailLength(artifact: CoachArtifactBlockData, evidence: string[]): number {
  return [
    artifact.summary,
    artifact.content,
    artifact.rationale,
    ...(artifact.bullets ?? []),
    ...evidence,
  ]
    .map((value) => (typeof value === "string" ? value.trim() : ""))
    .filter(Boolean)
    .join(" ").length;
}

export function CoachArtifactBlock({
  artifact,
  className,
  openLabel = "Open",
  language = "en-US",
  icon,
  collapseKey,
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
  const detailSummary =
    artifact.recommendedAction && !artifact.content
      ? actionButtonLabel(artifact.recommendedAction, language)
      : contentSummaryLabel(artifact.kind, language);
  const teaser = artifactTeaser(artifact, language);
  const showInlineDetails = isPrimaryLaneArtifact;
  const showTeaser =
    Boolean(teaser) &&
    teaser?.trim() !== artifact.summary?.trim() &&
    teaser?.trim() !== artifact.title.trim();
  // Long artifact prose folds into a persisted CollapseSection (level 2)
  // keyed by the hosting message id + artifact kind.
  const useCollapseSection =
    artifactDetailLength(artifact, evidence) > COACH_ARTIFACT_COLLAPSE_THRESHOLD;
  const detailsTitle = resolveCopy(language).coachArtifactFullDetails;
  const detailsPersistenceKey = collapseKey ? `coach-artifact:${collapseKey}` : "";
  const detailBody: ReactNode = (
    <>
      {artifact.focusArea ? (
        <p className="artifact-card__detail-note">
          <strong>{artifactMetaLabel("focus", language)}</strong>
          {language === "zh-CN" ? "：" : ": "}
          {artifact.focusArea}
        </p>
      ) : null}
      {artifact.content ? (
        <MessageRichContent body={artifact.content} language={language} />
      ) : null}
      {artifact.rationale ? (
        <>
          <p className="artifact-card__detail-note">
            <strong>{artifactMetaLabel("why", language)}</strong>
            {language === "zh-CN" ? "：" : ": "}
          </p>
          <MessageRichContent body={artifact.rationale} language={language} />
        </>
      ) : null}
      {decision ? (
        <p className="artifact-card__detail-note">
          <strong>{artifactMetaLabel("decision", language)}</strong>
          {language === "zh-CN" ? "：" : ": "}
          {decision}
        </p>
      ) : null}
      {blocker ? (
        <p className="artifact-card__detail-note">
          <strong>{artifactMetaLabel("blocker", language)}</strong>
          {language === "zh-CN" ? "：" : ": "}
          {blocker}
        </p>
      ) : null}
      {resumeThread ? (
        <p className="artifact-card__detail-note">
          <strong>{artifactMetaLabel("resumeThread", language)}</strong>
          {language === "zh-CN" ? "：" : ": "}
          {resumeThread}
        </p>
      ) : null}
      {teachingNote ? (
        <p className="artifact-card__detail-note">
          <strong>{artifactMetaLabel("teachingNote", language)}</strong>
          {language === "zh-CN" ? "：" : ": "}
          {teachingNote}
        </p>
      ) : null}
      {confidence ? (
        <p className="artifact-card__detail-note">
          <strong>{artifactMetaLabel("confidence", language)}</strong>
          {language === "zh-CN" ? "：" : ": "}
          {confidence}
        </p>
      ) : null}
      {evidence.length ? (
        <>
          <p className="artifact-card__detail-note">
            <strong>{artifactMetaLabel("verify", language)}</strong>
            {language === "zh-CN" ? "：" : ": "}
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
          <strong>{artifact.title}</strong>
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
      {showDetailBlock && showInlineDetails ? (
        useCollapseSection ? (
          <CollapseSection level={2} title={detailsTitle} persistenceKey={detailsPersistenceKey}>
            <div className="artifact-card__details-body artifact-card__details-body--inline coach-artifact-details">
              {detailBody}
            </div>
          </CollapseSection>
        ) : (
          <div className="artifact-card__details-body artifact-card__details-body--inline">
            {detailBody}
          </div>
        )
      ) : null}
      {showDetailBlock && !showInlineDetails ? (
        useCollapseSection ? (
          <CollapseSection level={2} title={detailsTitle} persistenceKey={detailsPersistenceKey}>
            <div className="artifact-card__details-body coach-artifact-details">{detailBody}</div>
          </CollapseSection>
        ) : (
          <CollapsibleBlock
            className="artifact-card__details"
            summary={detailSummary}
          >
            <div className="artifact-card__details-body">{detailBody}</div>
          </CollapsibleBlock>
        )
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
