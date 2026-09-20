import { memo, type ReactNode } from "react";

import {
  deriveTrainerToolActivity,
  findCoachVisibleStatusPart,
} from "../../../../../shared/src/protocol";
import { sanitizeErrorSurfaceText } from "../../../../../shared/src/errorSurfaceSanitizer";
import type { ComposerLanguage, ConversationMessage } from "../../lib/types";
import {
  RefreshIcon,
  ResourcesIcon,
  ShareIcon,
  TrainingIcon,
} from "../icons/CoachIcons";
import { AgentActivityStrip } from "./AgentActivityStripSmart";
import { CoachArtifactBlock, type CoachArtifactBlockData } from "./CoachArtifactBlock";
import { CoachMessageParts } from "./CoachMessageParts";
import { MessageRichContent } from "./MessageRichContent";

export type CoachMessageAction = "share" | "save-resource" | "training-card" | "retry";

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
  onArtifactOpen?: (artifact: CoachArtifactBlockData, message: ConversationMessage) => void;
  /** Quick actions under an assistant reply: share / save to library / create a training card. */
  onMessageAction?: (action: CoachMessageAction, message: ConversationMessage) => void;
  /** In-flight action key, formatted `${message.id}:${action}`; matching buttons disable. */
  pendingMessageAction?: string | null;
}

const COACH_MESSAGE_ACTION_LABELS: Record<
  ComposerLanguage,
  Record<CoachMessageAction, string>
> = {
  "zh-CN": { share: "分享", "save-resource": "加入资料库", "training-card": "加入训练卡片", retry: "重新生成" },
  "en-US": { share: "Share", "save-resource": "Save to Resources", "training-card": "Create training card", retry: "Regenerate" },
  "es-ES": { share: "Compartir", "save-resource": "Guardar en Recursos", "training-card": "Crear tarjeta", retry: "Regenerar" },
  "fr-FR": { share: "Partager", "save-resource": "Ajouter aux Ressources", "training-card": "Créer une carte", retry: "Régénérer" },
  "de-DE": { share: "Teilen", "save-resource": "In Bibliothek speichern", "training-card": "Karte erstellen", retry: "Neu generieren" },
  "ja-JP": { share: "共有", "save-resource": "ライブラリに保存", "training-card": "カードを作成", retry: "再生成" },
  "ko-KR": { share: "공유", "save-resource": "라이브러리에 저장", "training-card": "카드 만들기", retry: "다시 생성" },
  "pt-BR": { share: "Compartilhar", "save-resource": "Salvar na Biblioteca", "training-card": "Criar cartão", retry: "Regenerar" },
};

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
  if (language === "zh-CN") {
    const base = `已核对 ${activities.length} 项上下文`;
    return failed > 0 ? `${base}，其中 ${failed} 步需要重试` : base;
  }
  const base = `Checked ${activities.length} ${activities.length === 1 ? "item" : "items"}`;
  return failed > 0
    ? `${base}, ${failed} ${failed === 1 ? "needs" : "need"} a retry`
    : base;
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
  onArtifactOpen,
  onMessageAction,
  pendingMessageAction,
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

  if (message.artifacts?.length) {
    detailBlocks.push(
      <div key="artifacts" className="message-bubble__artifacts">
        {message.artifacts.map((artifact, index) => (
          <CoachArtifactBlock
            key={`${artifact.kind}:${artifact.title}:${index}`}
            artifact={artifact}
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

  // `detailBlocks` is only fed by these two sources, and a support block can be
  // pushed while still empty (e.g. a preview without lines), so the gate reads
  // the sources rather than the array.
  const hasSupplementMaterial = messageHasArtifacts || supportDetails.length > 0;
  const showSystemMeta = message.role === "system";
  // Feed chrome stays out of the way: user turns render without a repeated
  // author/timestamp row; the timestamp remains available as a tooltip.
  const showUserMeta = false;
  const showAssistantRail = false;
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
      ? message.parts.filter((part) => !HIDDEN_ASSISTANT_PART_TYPES.has(part.type))
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
        {hasRunningActivities ? (
          <p className="message-bubble__agent-status message-bubble__agent-status--working" role="status">
            {language === "zh-CN" ? "正在核对上下文…" : "Checking context…"}
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
        {hasParts ? <CoachMessageParts parts={visibleParts ?? []} language={language} /> : null}
        {children}
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

      {hasSupplementMaterial ? (
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

      {toolTrailActivities.length > 0 ? (
        <details className="message-bubble__tool-trail">
          <summary>{toolTrailSummary(toolTrailActivities, language)}</summary>
          <AgentActivityStrip activities={toolTrailActivities} language={language} />
        </details>
      ) : null}

      {showAssistantActions ? (
        <div
          className="message-bubble__actions"
          role="group"
          aria-label={
            language === "zh-CN" ? "这条回复的快捷操作" : "Quick actions for this reply"
          }
        >
          {isLatestAssistant ? (
            <button
              type="button"
              className="message-bubble__action"
              disabled={pendingAssistantAction === "retry"}
              aria-label={messageActionLabels.retry}
              title={messageActionLabels.retry}
              onClick={() => onMessageAction?.("retry", message)}
            >
              <RefreshIcon size={13} aria-hidden="true" />
              <span>{messageActionLabels.retry}</span>
            </button>
          ) : null}
          <button
            type="button"
            className="message-bubble__action"
            disabled={pendingAssistantAction === "share"}
            aria-label={messageActionLabels.share}
            title={messageActionLabels.share}
            onClick={() => onMessageAction?.("share", message)}
          >
            <ShareIcon size={13} aria-hidden="true" />
            <span>{messageActionLabels.share}</span>
          </button>
          <button
            type="button"
            className="message-bubble__action"
            disabled={pendingAssistantAction === "save-resource"}
            aria-label={messageActionLabels["save-resource"]}
            title={messageActionLabels["save-resource"]}
            onClick={() => onMessageAction?.("save-resource", message)}
          >
            <ResourcesIcon size={13} aria-hidden="true" />
            <span>{messageActionLabels["save-resource"]}</span>
          </button>
          <button
            type="button"
            className="message-bubble__action"
            disabled={pendingAssistantAction === "training-card"}
            aria-label={messageActionLabels["training-card"]}
            title={messageActionLabels["training-card"]}
            onClick={() => onMessageAction?.("training-card", message)}
          >
            <TrainingIcon size={13} aria-hidden="true" />
            <span>{messageActionLabels["training-card"]}</span>
          </button>
        </div>
      ) : null}
    </article>
  );
}

export const CoachMessageBubble = memo(CoachMessageBubbleImpl);
