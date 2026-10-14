import { templateCopy } from "../../templates/templateCopy";
import { CoachReply } from "../../templates/CoachReply";
import { memo, useState, type ReactNode } from "react";

import { TrainerIconBase } from "../icons/TrainerIconBase";

// Premium action glyphs: 24-grid geometry rendered on the unified
// TrainerIconBase grammar (1.4 currentColor stroke) at optical 15px.
function ActionGlyph({ glyphs }: { glyphs: ReactNode }) {
  return (
    <TrainerIconBase viewBox="0 0 24 24" size={15}>
      {glyphs}
    </TrainerIconBase>
  );
}

const GLYPH_COPY = (
  <>
    <rect x="9" y="9" width="12" height="12" rx="2.2" />
    <path d="M5 15c-1.1 0-2-.9-2-2V5c0-1.1.9-2 2-2h8c1.1 0 2 .9 2 2" />
  </>
);
const GLYPH_SHARE = (
  <>
    <path d="M4 12v7a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-7" />
    <path d="m16 6-4-4-4 4" />
    <path d="M12 2v13" />
  </>
);
const GLYPH_LIBRARY = (
  <path d="m19 21-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16z" />
);
const GLYPH_CARD = (
  <>
    <rect x="8" y="2" width="8" height="4" rx="1" />
    <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" />
    <path d="m9 14 2 2 4-4" />
  </>
);
const GLYPH_RETRY = (
  <>
    <path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8" />
    <path d="M21 3v5h-5" />
  </>
);
const GLYPH_NEXT = <path d="M5 12h14" />;

import {
  deriveTrainerToolActivity,
  findCoachVisibleStatusPart,
} from "../../../../../shared/src/protocol";
import { sanitizeErrorSurfaceText } from "../../../../../shared/src/errorSurfaceSanitizer";
import type { ComposerLanguage, ConversationMessage } from "../../lib/types";
import { nextStepRequiresConfirmationFromArtifacts } from "../../lib/nextStepConfirmation";
import { CoachArtifactBlock, type CoachArtifactBlockData } from "./CoachArtifactBlock";
import { artifactBlockCopy } from "../../lib/i18n/segments/coachArtifactBlockCopy";
import { coachMessageBubbleCopy, COACH_MESSAGE_ACTION_LABELS } from "../../lib/i18n/segments/coachMessageBubbleCopy";
import { CoachMessageParts } from "./CoachMessageParts";
import { MessageRichContent } from "./MessageRichContent";

export type CoachMessageAction = "copy" | "share" | "save-resource" | "training-card" | "retry";

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
  /** Only the latest assistant reply offers regenerate. */
  isLatestAssistant?: boolean;
  /** Optional trailing node (e.g. streaming dots) rendered inside the body. */
  children?: ReactNode;
  /**
   * r2-g0-0: live run meta ("正在进行") rendered inside the container head,
   * next to the speaker label — never as a floating strip above the message.
   */
  headNote?: ReactNode;
  onArtifactOpen?: (artifact: CoachArtifactBlockData, message: ConversationMessage) => void;
  /** Quick actions under an assistant reply: share / save to library / create a training card. */
  onMessageAction?: (action: CoachMessageAction, message: ConversationMessage) => void;
  /** In-flight action key, formatted `${message.id}:${action}`; matching buttons disable. */
  pendingMessageAction?: string | null;
  /**
   * Grounding downgrade for this turn (DESIGN.md §2.5): when set, the visible
   * status next-step line renders a "confirm before acting" marker. The bubble
   * also derives the flag from its own next_step artifacts' metadata.
   */
  nextStepRequiresConfirmation?: boolean;
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
  if (message.role === "user") {
    return (message.attachments ?? []).map((attachment) =>
      coachMessageBubbleCopy(language, "{label}：{value}")
        .replace("{label}", attachment.label)
        .replace("{value}", attachment.value),
    );
  }
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
        coachMessageBubbleCopy(language, "{label}：{value}")
          .replace("{label}", attachment.label)
          .replace("{value}", attachment.value),
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

/** Part kinds that are agent-run bookkeeping, never part of the readable reply. */
const HIDDEN_ASSISTANT_PART_TYPES = new Set([
  "coach_visible_status",
  "tool_call",
  "tool_result",
  "reasoning",
]);

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

/** Quiet one-line summary for the post-run tool trail. */
function toolTrailSummary(
  activities: Array<{ status: string }>,
  language: ComposerLanguage,
): string {
  const failed = activities.filter((activity) => activity.status === "failed").length;
  const base = coachMessageBubbleCopy(language, "已核对 {n} 项上下文")
    .replace("{n}", String(activities.length))
    .replace("{s}", activities.length === 1 ? "" : "s");
  if (failed > 0) {
    return (
      base +
      coachMessageBubbleCopy(language, "，其中 {f} 步需要重试")
        .replace("{f}", String(failed))
        .replace("{s}", failed === 1 ? "s" : "")
    );
  }
  return base;
}

function CoachMessageBubbleImpl({
  message,
  children,
  className,
  userLabel,
  assistantLabel,
  systemLabel,
  roleLabel,
  openArtifactLabel = "Open",
  language = "en-US",
  streaming = false,
  isLatestAssistant = false,
  headNote,
  onArtifactOpen,
  onMessageAction,
  pendingMessageAction,
  nextStepRequiresConfirmation = false,
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

  const primaryArtifact = message.artifacts?.find((artifact) => Boolean(artifact.recommendedAction));
  // 弹出式：最新回复的主操作默认隐藏，由图标排末尾的下一步按钮展开——
  // 展开后动作条出现在消息底部，正好位于输入框上方。
  const [nextActionRevealed, setNextActionRevealed] = useState(false);
  const primaryNextAction = primaryArtifact && onArtifactOpen && !streaming && isLatestAssistant ? (
    <CoachArtifactBlock
      artifact={primaryArtifact}
      compact
      slim
      language={language}
      onOpen={(artifact) => onArtifactOpen(artifact, message)}
    />
  ) : null;
  if (message.artifacts?.length) {
    detailBlocks.push(
      <details key="artifacts" className="template-reply-evidence">
        <summary>{templateCopy[language].evidence}</summary>
        <div className="message-bubble__artifacts">
          {message.artifacts.map((artifact, index) => (
            <CoachArtifactBlock key={`${artifact.kind}:${index}`} artifact={artifact} language={language} openLabel={openArtifactLabel} onOpen={onArtifactOpen ? (current) => onArtifactOpen(current, message) : undefined} />
          ))}
        </div>
      </details>,
    );
  }

  if (hasSupportDetails && message.role !== "assistant") {
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

  // `detailBlocks` is only fed by these two sources, and a support block can be
  // pushed while still empty (e.g. a preview without lines), so the gate reads
  // the sources rather than the array.
  const hasSupplementMaterial = messageHasArtifacts || (message.role !== "assistant" && supportDetails.length > 0);
  const showSystemMeta = message.role === "system";
  // Feed chrome stays out of the way: user turns render without a repeated
  // author/timestamp row; the timestamp remains available as a tooltip.
  // Coach replies carry the one identity line (r1-g0-0): a small name above
  // the body plus the lane hairline styled in the conversation CSS.
  const showUserMeta = false;
  const showAssistantRail = message.role === "assistant";
  const visibleBody = message.body;
  const hasBody = visibleBody.trim().length > 0;
  const pendingAssistantAction = pendingMessageAction?.startsWith(`${message.id}:`)
    ? (pendingMessageAction.slice(message.id.length + 1) as CoachMessageAction)
    : null;
  const showAssistantActions =
    message.role === "assistant" &&
    !streaming &&
    Boolean(onMessageAction) &&
    (hasBody || messageHasArtifacts || isLatestAssistant);
  const messageActionLabels = COACH_MESSAGE_ACTION_LABELS[language] ?? COACH_MESSAGE_ACTION_LABELS["en-US"];
  const shouldShowUserContextInline =
    message.role === "user" && !messageHasArtifacts && supportDetails.length === 1 && attachmentCount <= 1;
  const visibleParts =
    message.role === "assistant" && message.parts?.length
      ? message.parts.filter((part) => !HIDDEN_ASSISTANT_PART_TYPES.has(part.type) &&
          !(hasBody && ["training_card", "plan_update", "test_result"].includes(part.type)))
      : message.parts;
  const hasParts = (visibleParts?.length ?? 0) > 0;
  const hasRunningActivities =
    message.role === "assistant" &&
    (message.parts ?? []).some(
      (part) =>
        (part.type === "tool_call" || part.type === "tool_result") && part.status === "running",
    );
  // After the run finishes, keep the tool trail inspectable but quiet: one
  // muted line that expands to the per-step strip. Nothing disappears.
  const toolTrailActivities =
    message.role === "assistant" && !streaming
      ? deriveTrainerToolActivity(message.parts)
      : [];
  // Degraded turns may carry only a status part with no readable body; keep a
  // quiet one-line summary so the bubble never renders as an empty card.
  const fallbackStatusSummary =
    message.role === "assistant" && !hasBody && !hasParts && !hasRunningActivities
      ? findCoachVisibleStatusPart(message.parts)?.summary?.trim()
      : undefined;

  return (
    <article
      className={classes}
      data-message-id={message.id}
      data-role={message.role}
      data-has-artifacts={messageHasArtifacts ? "true" : "false"}
      data-has-support={hasSupportDetails ? "true" : "false"}
      title={message.role === "user" && message.timestamp ? message.timestamp : undefined}
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

      <CoachReply
        body={(
      <div className="message-bubble__body">
        {showAssistantRail ? (
          <div className="message-bubble__assistant-rail">
            <span className="message-bubble__assistant-label">{resolvedRoleLabel}</span>
            {headNote}
            {streaming ? (
              <span className="message-bubble__assistant-time">…</span>
            ) : timestamp ? (
              <span className="message-bubble__assistant-time">{timestamp}</span>
            ) : null}
          </div>
        ) : null}
        {hasRunningActivities ? (
          <p className="message-bubble__agent-status message-bubble__agent-status--working" role="status">
            {coachMessageBubbleCopy(language, "正在核对上下文…")}
          </p>
        ) : null}
        {!hasBody && fallbackStatusSummary ? (
          <p className="message-bubble__agent-status-summary">
            {sanitizeErrorSurfaceText(fallbackStatusSummary, language)}
          </p>
        ) : null}
        {hasBody ? (
          <MessageRichContent
            body={visibleBody}
            language={language}
            streaming={streaming}
          />
        ) : null}
        {hasParts ? (
          <CoachMessageParts
            parts={visibleParts ?? []}
            language={language}
            nextStepRequiresConfirmation={
              nextStepRequiresConfirmation ||
              nextStepRequiresConfirmationFromArtifacts(message.artifacts)
            }
          />
        ) : null}
        {children}
        {streaming ? (
          hasBody || hasParts ? (
            <span className="coach-cursor" aria-hidden="true" />
          ) : children ? null : (
            // §四十八: one loading idiom per bubble. When the caller supplies
            // children (`.coach-streaming-dots`), the pending skeleton stays
            // off so the dots are the only idiom; the dots CSS carries the
            // `prefers-reduced-motion` fallback.
            <div className="coach-msg-pending" aria-hidden="true">
              <div className="skeleton coach-msg-pending__line coach-msg-pending__line--long" />
              <div className="skeleton coach-msg-pending__line coach-msg-pending__line--mid" />
              <div className="skeleton coach-msg-pending__line coach-msg-pending__line--short" />
            </div>
          )
        ) : null}
      </div>
        )}
        evidence={hasSupplementMaterial ? (
        shouldShowUserContextInline ? (
          <p className={`message-bubble__context ${message.role === "user" ? "message-bubble__context--user" : ""}`}>
            {supportDetails[0]}
          </p>
        ) : (
          <div className="message-bubble__details">
            <div className="message-bubble__details-body">{detailBlocks}</div>
          </div>
        )
      ) : null}
        nextAction={isLatestAssistant ? null : primaryNextAction}
        tools={showAssistantActions ? (
          // Every delivered assistant message carries its shortcuts as small
          // icon buttons pinned to the message's bottom-left: learning-value
          // actions first (training card / save to library), then the
          // utilities (copy / share), then regenerate on the latest reply
          // only. No overflow menu — nothing hides behind "···".
          <div className="message-bubble__tools">
            <div className="message-bubble__quick-tools" role="group" aria-label={coachMessageBubbleCopy(language, "这条回复的快捷操作")}>
              <button
                type="button"
                className="message-bubble__icon-action"
                data-message-quick-action="copy"
                aria-label={messageActionLabels.copy}
                disabled={Boolean(pendingAssistantAction)}
                onClick={() => onMessageAction?.("copy", message)}
              >
                <ActionGlyph glyphs={GLYPH_COPY} />
              </button>
              <button
                type="button"
                className="message-bubble__icon-action"
                data-message-quick-action="share"
                aria-label={messageActionLabels.share}
                disabled={Boolean(pendingAssistantAction)}
                onClick={() => onMessageAction?.("share", message)}
              >
                <ActionGlyph glyphs={GLYPH_SHARE} />
              </button>
              <button
                type="button"
                className="message-bubble__icon-action"
                data-message-quick-action="save-resource"
                aria-label={messageActionLabels["save-resource"]}
                disabled={Boolean(pendingAssistantAction)}
                onClick={() => onMessageAction?.("save-resource", message)}
              >
                <ActionGlyph glyphs={GLYPH_LIBRARY} />
              </button>
              <button
                type="button"
                className="message-bubble__icon-action"
                data-message-quick-action="training-card"
                aria-label={messageActionLabels["training-card"]}
                disabled={Boolean(pendingAssistantAction)}
                onClick={() => onMessageAction?.("training-card", message)}
              >
                <ActionGlyph glyphs={GLYPH_CARD} />
              </button>
              {isLatestAssistant ? (
                <button
                  type="button"
                  className="message-bubble__icon-action"
                  data-message-quick-action="retry"
                  aria-label={messageActionLabels.retry}
                  disabled={Boolean(pendingAssistantAction)}
                  onClick={() => onMessageAction?.("retry", message)}
                >
                  <ActionGlyph glyphs={GLYPH_RETRY} />
                </button>
              ) : null}
              {isLatestAssistant && primaryNextAction ? (
                <button
                  type="button"
                  className="message-bubble__icon-action"
                  data-message-quick-action="next-action"
                  aria-label={artifactBlockCopy(language, "下一步")}
                  aria-pressed={nextActionRevealed}
                  onClick={() => setNextActionRevealed((value) => !value)}
                >
                  <ActionGlyph glyphs={GLYPH_NEXT} />
                </button>
              ) : null}
            </div>
            {isLatestAssistant && nextActionRevealed && primaryNextAction ? primaryNextAction : null}
          </div>
        ) : null}
      />
    </article>
  );
}

export const CoachMessageBubble = memo(CoachMessageBubbleImpl);
