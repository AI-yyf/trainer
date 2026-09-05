import type { ReactNode } from "react";

import {
  deriveTrainerToolActivity,
  findCoachVisibleStatusPart,
  describeTrainerStopReason,
} from "../../../../../shared/src/protocol";
import type { ComposerLanguage, ConversationMessage } from "../../lib/types";
import { AgentActivityStrip } from "./AgentActivityStripSmart";
import { CoachArtifactBlock, type CoachArtifactBlockData } from "./CoachArtifactBlock";
import { CoachMessageParts } from "./CoachMessageParts";
import { CollapsibleBlock } from "./CollapsibleBlock";
import { MessageRichContent } from "./MessageRichContent";

export interface CoachMessageBubbleProps {
  message: ConversationMessage;
  className?: string;
  userLabel?: string;
  assistantLabel?: string;
  systemLabel?: string;
  roleLabel?: string;
  openArtifactLabel?: string;
  language?: ComposerLanguage;
  streaming?: boolean;
  onArtifactOpen?: (artifact: CoachArtifactBlockData, message: ConversationMessage) => void;
}

function fallbackRoleLabel(message: ConversationMessage): string {
  if (message.role === "user") {
    return "You";
  }
  if (message.role === "system") {
    return "System";
  }
  return "Trainer";
}

function supportPreview(message: ConversationMessage): string | undefined {
  if (message.support?.preview) {
    return message.support.preview;
  }
  if (message.contextNote) {
    return message.contextNote;
  }
  if (message.attachments?.length) {
    return message.attachments[0]?.value;
  }
  return undefined;
}

function supportDetailLines(
  message: ConversationMessage,
  language: ComposerLanguage,
): string[] {
  const lines: string[] = [];
  const seen = new Set<string>();
  const push = (value: string | undefined) => {
    const normalized = value?.trim();
    if (!normalized || seen.has(normalized)) {
      return;
    }
    seen.add(normalized);
    lines.push(normalized);
  };

  if (message.support?.lines?.length) {
    for (const line of message.support.lines) {
      push(line);
    }
  }

  if (!message.support?.lines?.length && message.attachments?.length) {
    for (const attachment of message.attachments) {
      push(
        language === "zh-CN"
          ? `${attachment.label}：${attachment.value}`
          : `${attachment.label}: ${attachment.value}`,
      );
    }
  }

  if (message.contextNote && !message.support?.preview) {
    push(message.contextNote);
  }

  return lines;
}

function compactTimestamp(value: string): string {
  return value.trim();
}

function shortenPreview(value: string, limit = 22): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (normalized.length <= limit) {
    return normalized;
  }
  return `${normalized.slice(0, Math.max(0, limit - 1)).trimEnd()}…`;
}
function normalizeStatusComparisonText(value: string | undefined): string {
  return value?.replace(/\s+/g, " ").trim().toLowerCase() ?? "";
}

function isStatusResumeThreadRedundant(
  resumeThread: string | undefined,
  summary: string | undefined,
  nextStep: string | undefined,
): boolean {
  const normalizedResumeThread = normalizeStatusComparisonText(resumeThread);
  const normalizedSummary = normalizeStatusComparisonText(summary);
  const normalizedNextStep = normalizeStatusComparisonText(nextStep);

  if (!normalizedResumeThread) {
    return false;
  }
  if (normalizedSummary && normalizedResumeThread === normalizedSummary) {
    return true;
  }
  if (normalizedNextStep && normalizedResumeThread === normalizedNextStep) {
    return true;
  }
  return Boolean(
    normalizedSummary &&
      normalizedNextStep &&
      normalizedResumeThread.includes(normalizedSummary) &&
      normalizedResumeThread.includes(normalizedNextStep),
  );
}

function normalizeMessageBlock(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function compactAssistantBody(
  body: string,
  statusLines: Array<string | undefined>,
  hasAgentStatus: boolean,
): string {
  const excludedStatusLines = new Set(
    statusLines.map((line) => normalizeMessageBlock(line ?? "")).filter(Boolean),
  );
  const blocks = body
    .trim()
    .split(/\n\s*\n/)
    .map((block) => block.trim())
    .filter(Boolean);
  const compacted: string[] = [];
  let previousBlock = "";

  for (const block of blocks) {
    const normalizedBlock = normalizeMessageBlock(block);
    if (!normalizedBlock || normalizedBlock === previousBlock) {
      continue;
    }
    // The visible status rail already carries these facts. Keeping them in
    // the answer body creates the repeated, log-like flow seen in degraded runs.
    if (hasAgentStatus && excludedStatusLines.has(normalizedBlock)) {
      continue;
    }
    compacted.push(block);
    previousBlock = normalizedBlock;
  }

  return compacted.join("\n\n").trim();
}

function supportSummaryLabel(
  language: ComposerLanguage,
  attachmentCount: number,
  artifactCount: number,
  hasNote: boolean,
): string {
  if (language === "zh-CN") {
    if (artifactCount > 0) {
      return artifactCount > 1 ? `这次我还参考了 ${artifactCount} 条补充` : "这次我还参考了这些";
    }
    if (attachmentCount > 0) {
      return attachmentCount > 1 ? `这次一起带上的上下文（${attachmentCount}）` : "这次一起带上的上下文";
    }
    return hasNote ? "补充说明" : "再补一句";
  }

  if (artifactCount > 0) {
    return artifactCount > 1 ? `I also used ${artifactCount} extra references` : "I also used this";
  }
  if (attachmentCount > 0) {
    return attachmentCount > 1 ? `Attached context (${attachmentCount})` : "Attached context";
  }
  return hasNote ? "A quick note" : "One more note";
}

function coachVisibleStatusToneLabel(
  status: "working" | "done" | "blocked" | "degraded",
  language: ComposerLanguage,
): string {
  if (language === "zh-CN") {
    switch (status) {
      case "working":
        return "进行中";
      case "blocked":
        return "受阻";
      case "degraded":
        return "降级";
      default:
        return "已完成";
    }
  }

  switch (status) {
    case "working":
      return "Working";
    case "blocked":
      return "Blocked";
    case "degraded":
      return "Degraded";
    default:
      return "Done";
  }
}

function coachVisibleStatusSourceLabel(
  source: "agent_loop" | "coach" | "system" | undefined,
  language: ComposerLanguage,
): string | undefined {
  if (!source) {
    return undefined;
  }

  if (language === "zh-CN") {
    if (source === "agent_loop") {
      return "Agent 循环";
    }
    if (source === "system") {
      return "系统";
    }
    return "教练";
  }

  if (source === "agent_loop") {
    return "Agent loop";
  }
  if (source === "system") {
    return "System";
  }
  return "Coach";
}

function countLabel(
  count: number,
  language: ComposerLanguage,
  zhUnit: string,
  enSingular: string,
  enPlural: string,
): string {
  if (language === "zh-CN") {
    return `${count} ${zhUnit}`;
  }
  return `${count} ${count === 1 ? enSingular : enPlural}`;
}

function coachVisibleStatusDetailsTitle(
  status: "working" | "done" | "blocked" | "degraded",
  language: ComposerLanguage,
): string {
  if (language === "zh-CN") {
    if (status === "blocked") {
      return "查看阻塞与恢复路径";
    }
    if (status === "working") {
      return "查看本轮进度";
    }
    return "查看本轮结论";
  }

  if (status === "blocked") {
    return "See blocker and recovery path";
  }
  if (status === "working") {
    return "See live run details";
  }
  return "See run details";
}

function coachVisibleStatusDetailsPreview(
  language: ComposerLanguage,
  values: {
    blocker?: string;
    nextStep?: string;
    resumeThread?: string;
    decision?: string;
    evidenceCount: number;
    toolCount: number;
  },
): string | undefined {
  if (values.blocker) {
    return shortenPreview(values.blocker, 54);
  }
  if (values.nextStep) {
    return shortenPreview(values.nextStep, 54);
  }
  if (values.resumeThread) {
    return shortenPreview(values.resumeThread, 54);
  }
  if (values.decision) {
    return shortenPreview(values.decision, 54);
  }
  if (values.evidenceCount > 0) {
    return language === "zh-CN"
      ? `包含 ${values.evidenceCount} 条证据`
      : `Includes ${values.evidenceCount} evidence references`;
  }
  if (values.toolCount > 0) {
    return language === "zh-CN"
      ? `${values.toolCount} 个工具步骤`
      : `${values.toolCount} tool activities`;
  }
  return undefined;
}

function assistantDetailsSummary(
  language: ComposerLanguage,
  message: ConversationMessage,
  attachmentCount: number,
  artifactCount: number,
): string {
  const firstArtifact = message.artifacts?.[0];
  const supportPreviewText = supportPreview(message)?.trim();
  if (language === "zh-CN") {
    if (artifactCount > 0 && firstArtifact?.title) {
      return `这次我还参考了：${shortenPreview(firstArtifact.title, 20)}`;
    }
    if (attachmentCount > 0) {
      return attachmentCount > 1 ? `这次一起带上的上下文（${attachmentCount}）` : "这次一起带上的上下文";
    }
    if (supportPreviewText) {
      return `补充说明：${shortenPreview(supportPreviewText, 18)}`;
    }
    return "这次我还参考了这些";
  }
  if (artifactCount > 0 && firstArtifact?.title) {
    return `Ref: ${shortenPreview(firstArtifact.title, 26)}`;
  }
  if (attachmentCount > 0) {
    return attachmentCount > 1 ? `Context (${attachmentCount})` : "Context";
  }
  if (supportPreviewText) {
    return `Note: ${shortenPreview(supportPreviewText, 24)}`;
  }
  return "Ref";
}

function avatarGlyph(message: ConversationMessage): string {
  if (message.role === "user") {
    return "我";
  }
  if (message.role === "system") {
    return "S";
  }
  return "教";
}

function shouldShowAvatar(message: ConversationMessage): boolean {
  return message.role === "system";
}

export function CoachMessageBubble({
  message,
  className,
  userLabel,
  assistantLabel,
  systemLabel,
  roleLabel,
  openArtifactLabel = "Open",
  language = "en-US",
  streaming = false,
  onArtifactOpen,
}: CoachMessageBubbleProps) {
  const resolvedRoleLabel =
    roleLabel ??
    (message.role === "user" ? userLabel : message.role === "system" ? systemLabel : assistantLabel) ??
    fallbackRoleLabel(message);

  const variant = message.role === "user" ? "user" : message.role === "system" ? "system" : "assistant";
  const classes = [
    `message-bubble`,
    `message-bubble--${variant}`,
    // W2 polish: shared entrance animation; while streaming, the legacy
    // blinking body caret is suppressed in favor of the breathing
    // `.coach-cursor` element rendered at the end of the body.
    "coach-msg-enter",
    streaming ? "coach-msg-streaming" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");
  const attachmentCount = message.attachments?.length ?? 0;
  const artifactCount = message.artifacts?.length ?? 0;
  const hasSupportDetails =
    attachmentCount > 0 || Boolean(message.contextNote) || Boolean(message.support?.preview) || Boolean(message.support?.lines?.length);
  const showAuthor = message.role !== "assistant" && message.author.trim() !== resolvedRoleLabel.trim();
  const timestamp = compactTimestamp(message.timestamp);
  const showTimestampInline = !streaming && message.role !== "assistant" && timestamp.length > 0;
  const supportDetails = supportDetailLines(message, language);
  const detailBlocks: ReactNode[] = [];
  const messageHasArtifacts = artifactCount > 0;
  const hasSupplementMaterial = detailBlocks.length > 0 || messageHasArtifacts || supportDetails.length > 0;

  if (message.artifacts?.length) {
    detailBlocks.push(
      <div key="artifacts" className="message-bubble__artifacts">
        {message.artifacts.map((artifact, index) => (
          <CoachArtifactBlock
            key={`${artifact.kind}:${artifact.title}:${index}`}
            artifact={artifact}
            collapseKey={`${message.id}:${artifact.kind}`}
            language={language}
            openLabel={openArtifactLabel}
            onOpen={
              onArtifactOpen
                ? (currentArtifact) => {
                    onArtifactOpen(currentArtifact, message);
                  }
                : undefined
            }
          />
        ))}
      </div>,
    );
  }

  if (hasSupportDetails) {
    detailBlocks.push(
      <div key="support" className="message-support-list message-support-list--compact">
        {supportDetails.map((line) => (
          <p key={line} className="message-support-line">
            {line}
          </p>
        ))}
      </div>,
    );
  }

  const showSystemMeta = message.role === "system";
  const showUserMeta = message.role === "user" && (showAuthor || showTimestampInline);
  const showAssistantRail = false;
  const coachVisibleStatus =
    message.role === "assistant" ? findCoachVisibleStatusPart(message.parts) : undefined;
  const agentActivities =
    message.role === "assistant" ? deriveTrainerToolActivity(message.parts) : [];
  const statusSummary = coachVisibleStatus?.summary?.trim();
  const statusDetailCandidate = coachVisibleStatus?.detail?.trim();
  const statusDetail =
    normalizeStatusComparisonText(statusDetailCandidate) === normalizeStatusComparisonText(statusSummary)
      ? undefined
      : statusDetailCandidate;
  const statusDecision = coachVisibleStatus?.decision?.trim();
  const statusBlocker = coachVisibleStatus?.blocker?.trim();
  const statusTeachingNote = coachVisibleStatus?.teachingNote?.trim();
  const statusConfidence = coachVisibleStatus?.confidence?.trim();
  const statusEvidence = coachVisibleStatus?.evidence?.map((item) => item.trim()).filter(Boolean) ?? [];
  const hasAgentStatus = Boolean(statusSummary || agentActivities.length > 0);
  const statusNextStep = coachVisibleStatus?.nextStep?.trim();
  const statusResumeThreadCandidate = coachVisibleStatus?.resumeThread?.trim();
  const statusResumeThread = isStatusResumeThreadRedundant(
    statusResumeThreadCandidate,
    statusSummary,
    statusNextStep,
  )
    ? undefined
    : statusResumeThreadCandidate;
  const visibleBody =
    message.role === "assistant"
      ? compactAssistantBody(
          message.body,
          [
            statusSummary,
            statusDetailCandidate,
            statusNextStep,
            statusResumeThreadCandidate,
            statusBlocker,
            statusDecision,
          ],
          hasAgentStatus,
        )
      : message.body;
  const hasBody = visibleBody.trim().length > 0;
  const shouldShowUserContextInline =
    message.role === "user" && !messageHasArtifacts && supportDetails.length === 1 && attachmentCount <= 1;
  const shouldCollapseDetails =
    !shouldShowUserContextInline &&
    ((message.role === "assistant" && hasBody) ||
      artifactCount > 1 ||
      attachmentCount > 0 ||
      supportDetails.length > 1);
  const detailSummary =
    message.role === "assistant"
      ? assistantDetailsSummary(language, message, attachmentCount, artifactCount)
      : supportSummaryLabel(language, attachmentCount, artifactCount, Boolean(message.contextNote || message.support?.preview || message.support?.lines?.length));
  const visibleParts =
    message.role === "assistant" && message.parts?.length
      ? message.parts.filter((part) => {
          if (part.type === "coach_visible_status") {
            return false;
          }
          if (
            hasAgentStatus &&
            (part.type === "tool_call" || part.type === "tool_result")
          ) {
            return false;
          }
          return true;
        })
      : message.parts;
  const hasParts = (visibleParts?.length ?? 0) > 0;
  const stopReasonLabel = describeTrainerStopReason(coachVisibleStatus?.stopReason, language);
  const hasEvidenceFacts = statusEvidence.length > 0;
  const hasRunningActivities = agentActivities.some((activity) => activity.status === "running");
  const hasFailedActivities = agentActivities.some((activity) => activity.status === "failed");
  const statusTone =
    coachVisibleStatus?.status ??
    (hasRunningActivities ? "working" : hasFailedActivities ? "degraded" : "done");
  const statusToneLabel = coachVisibleStatusToneLabel(statusTone, language);
  const statusSourceLabel = coachVisibleStatusSourceLabel(coachVisibleStatus?.source, language);
  const statusInlineSummary =
    statusTone === "blocked"
      ? statusBlocker ?? statusSummary ?? statusNextStep
      : statusTone === "working"
        ? statusSummary ?? statusDetail
        : !hasBody
          ? statusSummary ?? statusDetail
          : undefined;
  const statusInlineResume = !hasBody && statusResumeThread ? statusResumeThread : undefined;
  const statusCounters = [
    coachVisibleStatus?.stepCount
      ? countLabel(coachVisibleStatus.stepCount, language, "步", "step", "steps")
      : null,
    agentActivities.length > 0
      ? countLabel(agentActivities.length, language, "个工具", "tool", "tools")
      : null,
    hasEvidenceFacts
      ? countLabel(statusEvidence.length, language, "条证据", "evidence ref", "evidence refs")
      : null,
  ].filter((value): value is string => Boolean(value));
  const statusFacts = [
    statusSourceLabel
      ? {
          key: "source",
          label: language === "zh-CN" ? "来源" : "Source",
          value: statusSourceLabel,
        }
      : null,
    stopReasonLabel
      ? {
          key: "stopReason",
          label: language === "zh-CN" ? "结束原因" : "Stop reason",
          value: stopReasonLabel,
        }
      : null,
    statusBlocker
      ? {
          key: "blocker",
          label: language === "zh-CN" ? "阻塞" : "Blocker",
          value: statusBlocker,
        }
      : null,
    statusDecision
      ? {
          key: "decision",
          label: language === "zh-CN" ? "决策" : "Decision",
          value: statusDecision,
        }
      : null,
    statusTeachingNote
      ? {
          key: "teachingNote",
          label: language === "zh-CN" ? "教学提示" : "Teaching note",
          value: statusTeachingNote,
        }
      : null,
    statusConfidence
      ? {
          key: "confidence",
          label: language === "zh-CN" ? "把握" : "Confidence",
          value: statusConfidence,
        }
      : null,
  ].filter((item): item is { key: string; label: string; value: string } => Boolean(item));
  const statusDetailsPreview = coachVisibleStatusDetailsPreview(language, {
    blocker: statusBlocker,
    nextStep: statusNextStep,
    resumeThread: statusResumeThread,
    decision: statusDecision,
    evidenceCount: statusEvidence.length,
    toolCount: agentActivities.length,
  });
  const hasStatusDetails =
    Boolean(statusDecision) ||
    Boolean(statusBlocker) ||
    Boolean(statusTeachingNote) ||
    Boolean(statusConfidence) ||
    hasEvidenceFacts ||
    agentActivities.length > 0;

  return (
    <article
      className={classes}
      data-message-id={message.id}
      data-role={message.role}
      data-has-artifacts={messageHasArtifacts ? "true" : "false"}
      data-has-support={hasSupportDetails ? "true" : "false"}
    >
      {showSystemMeta || showUserMeta ? (
        <div className="message-bubble__meta coach-meta-nums">
          <div className="message-bubble__identity">
            {shouldShowAvatar(message) ? (
              <span className="message-bubble__avatar" aria-hidden="true">{avatarGlyph(message)}</span>
            ) : null}
            {showSystemMeta ? <span className="message-bubble__role">{resolvedRoleLabel}</span> : null}
            {showAuthor ? <strong>{message.author}</strong> : null}
            {streaming ? <span className="message-bubble__status">…</span> : null}
            {showTimestampInline ? <span className="message-bubble__timestamp">{timestamp}</span> : null}
          </div>
        </div>
      ) : null}

      <div className="message-bubble__body">
        {showAssistantRail ? (
          <div className="message-bubble__assistant-rail">
            <span className="message-bubble__assistant-label">{resolvedRoleLabel}</span>
            {streaming ? (
              <span className="message-bubble__assistant-time">…</span>
            ) : timestamp ? (
              <span className="message-bubble__assistant-time">{timestamp}</span>
            ) : null}
          </div>
        ) : null}
        {hasAgentStatus ? (
          <div
            className={`message-bubble__agent-status message-bubble__agent-status--${statusTone}`}
            title={statusDetail && statusDetail !== statusSummary ? statusDetail : undefined}
          >
            <div className="message-bubble__agent-status-head">
              <div className="message-bubble__agent-status-meta">
                <span
                  className={`message-bubble__agent-status-tone message-bubble__agent-status-tone--${statusTone}`}
                >
                  {statusToneLabel}
                </span>
              </div>
              {statusCounters.length > 0 ? (
                <div className="message-bubble__agent-status-counts coach-meta-nums">
                  {statusCounters.map((item) => (
                    <span key={item} className="message-bubble__agent-status-count">
                      {item}
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
            {statusInlineSummary ? (
              <p className="message-bubble__agent-status-summary">{statusInlineSummary}</p>
            ) : null}
            {statusInlineResume ? (
              <p className="message-bubble__agent-status-resume">{statusInlineResume}</p>
            ) : null}
            {hasStatusDetails ? (
              <CollapsibleBlock
                className="message-bubble__agent-status-disclosure"
                defaultOpen={statusTone === "blocked"}
                summary={
                  <div className="message-bubble__agent-status-disclosure-summary">
                    <span className="message-bubble__agent-status-disclosure-title">
                      {coachVisibleStatusDetailsTitle(statusTone, language)}
                    </span>
                    {statusDetailsPreview ? (
                      <span className="message-bubble__agent-status-disclosure-preview">
                        {statusDetailsPreview}
                      </span>
                    ) : null}
                  </div>
                }
              >
                <div className="message-bubble__agent-status-details-body">
                  {!statusInlineSummary && statusSummary ? (
                    <p className="message-bubble__agent-status-summary">{statusSummary}</p>
                  ) : null}
                  {statusDetail ? (
                    <p className="message-bubble__agent-status-detail">{statusDetail}</p>
                  ) : null}
                  {statusNextStep && statusNextStep !== statusInlineSummary ? (
                    <p className="message-bubble__agent-status-next">
                      <strong>{language === "zh-CN" ? "\u4e0b\u4e00\u6b65" : "Next"}</strong>
                      <span>{statusNextStep}</span>
                    </p>
                  ) : null}
                  {statusResumeThread && statusResumeThread !== statusInlineResume ? (
                    <p className="message-bubble__agent-status-resume">{statusResumeThread}</p>
                  ) : null}
                  {statusFacts.length ? (
                    <div className="message-bubble__agent-status-facts">
                      {statusFacts.map((fact) => (
                        <span
                          key={fact.key}
                          className={`message-bubble__agent-status-fact message-bubble__agent-status-fact--${fact.key}`}
                        >
                          <strong>{fact.label}</strong>
                          <span>{fact.value}</span>
                        </span>
                      ))}
                    </div>
                  ) : null}
                  {hasEvidenceFacts ? (
                    <div className="message-bubble__agent-status-facts message-bubble__agent-status-facts--evidence">
                      <span className="message-bubble__agent-status-evidence-label">
                        {language === "zh-CN" ? "\u8bc1\u636e" : "Evidence"}
                      </span>
                      {statusEvidence.map((item) => (
                        <span
                          key={item}
                          className="message-bubble__agent-status-fact message-bubble__agent-status-fact--evidence"
                        >
                          {item}
                        </span>
                      ))}
                    </div>
                  ) : null}
                  {agentActivities.length > 0 ? (
                    <AgentActivityStrip
                      activities={agentActivities}
                      language={language}
                      stopReason={coachVisibleStatus?.stopReason}
                    />
                  ) : null}
                </div>
              </CollapsibleBlock>
            ) : null}
          </div>
        ) : null}
        {hasBody ? (
          <MessageRichContent
            body={visibleBody}
            language={language}
            streaming={streaming}
            preferCollapse={!hasAgentStatus && statusTone !== "working"}
            summaryOverride={undefined}
            suppressPreviewItems={message.role === "assistant" && artifactCount > 0}
          />
        ) : null}
        {hasParts ? <CoachMessageParts parts={visibleParts ?? []} language={language} /> : null}
        {streaming ? (
          hasBody || hasParts ? (
            <span className="coach-cursor" aria-hidden="true" />
          ) : (
            <div className="coach-msg-pending" aria-hidden="true">
              <div className="skeleton coach-msg-pending__line coach-msg-pending__line--long" />
              <div className="skeleton coach-msg-pending__line coach-msg-pending__line--mid" />
              <div className="skeleton coach-msg-pending__line coach-msg-pending__line--short" />
            </div>
          )
        ) : null}
      </div>

      {hasSupplementMaterial && detailBlocks.length > 0 ? (
        shouldCollapseDetails ? (
          <CollapsibleBlock
            className={`message-bubble__details ${message.role === "user" ? "message-bubble__details--user" : ""}`}
            summary={detailSummary}
            defaultOpen={false}
          >
            <div className="message-bubble__details-body">{detailBlocks}</div>
          </CollapsibleBlock>
        ) : shouldShowUserContextInline ? (
          <p className={`message-bubble__context ${message.role === "user" ? "message-bubble__context--user" : ""}`}>
            {supportDetails[0]}
          </p>
        ) : (
          <div className="message-bubble__details">
            <div className="message-bubble__details-body">{detailBlocks}</div>
          </div>
        )
      ) : null}
    </article>
  );
}
