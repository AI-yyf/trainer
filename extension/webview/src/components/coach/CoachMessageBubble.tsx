import { memo,useEffect,useRef,useState,type ReactNode } from "react";
import { resolveCopy } from "../../lib/i18n/copy";
import { viewLabels } from "../../lib/viewLabels";
import { CoachReply } from "../../templates/CoachReply";

import { TrainerIconBase } from "../icons/TrainerIconBase";

// Premium action glyphs: 24-grid geometry rendered on the unified
// TrainerIconBase grammar (1.4 currentColor stroke) at optical 15px.
function ActionGlyph({ glyphs }: { glyphs: ReactNode }) {
  return (
    <TrainerIconBase viewBox="0 0 24 24" size={16}>
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
const GLYPH_BRIEF = (
  <>
    <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
    <path d="M14 3v5h5" />
    <path d="M9 13h6M9 17h4" />
  </>
);
// A flash (闪记) card reads as a bolt on a card, never as the same checklist
// card as the practice card.
const GLYPH_FLASH = (
  <>
    <rect x="3" y="4" width="18" height="16" rx="2.4" />
    <path d="M13 8.5 9.5 13H12l-1 3 3.5-4.5H12z" />
  </>
);
const GLYPH_RETRY = (
  <>
    <path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8" />
    <path d="M21 3v5h-5" />
  </>
);
const GLYPH_NEXT = <path d="M5 12h14" />;
const GLYPH_TARGET = (
  <>
    <circle cx="12" cy="12" r="7" />
    <circle cx="12" cy="12" r="3" />
  </>
);
const GLYPH_MORE = (
  <>
    <circle cx="5" cy="12" r="1.5" />
    <circle cx="12" cy="12" r="1.5" />
    <circle cx="19" cy="12" r="1.5" />
  </>
);

import { sanitizeErrorSurfaceText } from "../../../../../shared/src/errorSurfaceSanitizer";
import {
  deriveTrainerToolActivity,
  findCoachVisibleStatusPart,
} from "../../../../../shared/src/protocol";
import { resolveToolActivityLabel } from "../../lib/i18n/segments/agentActivityStripCopy";
import { artifactBlockCopy } from "../../lib/i18n/segments/coachArtifactBlockCopy";
import {
  COACH_MESSAGE_ACTION_LABELS,
  coachMessageBubbleCopy,
  MORE_ACTIONS_TEXT,
  OPEN_RESEARCH_PREPARATION_TEXT,
  RESEARCH_PREPARATION_TEXT,
} from "../../lib/i18n/segments/coachMessageBubbleCopy";
import {
  nextStepRequiresConfirmationFromArtifacts,
  resolveNextStepConfirmationOwner,
  statusNextStepPartIndex,
} from "../../lib/nextStepConfirmation";
import { currentTrainerStage } from "../../lib/trainerStage";
import type { ComposerLanguage,ConversationMessage,ResourceRecord } from "../../lib/types";
import { CoachArtifactBlock,type CoachArtifactBlockData } from "./CoachArtifactBlock";
import { CoachMessageParts } from "./CoachMessageParts";
import {
  resolveCoachToolResultCopy,
  summarizeSafeCoachToolResult,
} from "./coachToolResultCopy";
import { CoachWorkingIndicator } from "./CoachWorkingIndicator";
import { MessageImageGallery,MessageRichContent } from "./MessageRichContent";

export type CoachMessageAction =
  | "copy"
  | "share"
  | "save-resource"
  | "save-research-brief"
  | "open-research-brief"
  | "training-card"
  | "flash-card"
  | "set-goal"
  | "retry";

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
  /** Current library records for live citation invalidation. */
  resources?: ResourceRecord[];
}

const ROLE_FALLBACK_COPY: Record<ComposerLanguage, { you: string; system: string }> = {
  "zh-CN": { you: "你", system: "系统" },
  "en-US": { you: "You", system: "System" },
  "es-ES": { you: "Tú", system: "Sistema" },
  "fr-FR": { you: "Vous", system: "Système" },
  "de-DE": { you: "Du", system: "System" },
  "ja-JP": { you: "あなた", system: "システム" },
  "ko-KR": { you: "나", system: "시스템" },
  "pt-BR": { you: "Você", system: "Sistema" },
};

function fallbackRoleLabel(message: ConversationMessage, language: ComposerLanguage): string {
  const labels = ROLE_FALLBACK_COPY[language] ?? ROLE_FALLBACK_COPY["en-US"];
  if (message.role === "user") {
    return labels.you;
  }
  if (message.role === "system") {
    return labels.system;
  }
  return "Trainer";
}

function supportDetailLines(
  message: ConversationMessage,
  language: ComposerLanguage,
  resources?: ResourceRecord[],
): string[] {
  if (message.role === "user") {
    const lines = (message.attachments ?? []).map((attachment) =>
      coachMessageBubbleCopy(language, "{label}：{value}")
        .replace("{label}", attachment.label)
        .replace("{value}", attachment.value),
    );
    // The source belongs to the sent message, not to a pre-send chrome row:
    // keep it auditable after the composer has cleared it. `contextNote` is a
    // different channel — internal management context — and stays hidden.
    const sourceNote = message.sourceNote?.trim();
    if (sourceNote) {
      lines.push(sourceNote);
    }
    const resourceIds = message.sourceResourceIds ?? [];
    if (resourceIds.length > 0) {
      const titles = resourceIds.map((id) =>
        resources?.find((resource) => resource.id === id)?.title?.trim() || id,
      );
      lines.push(`${viewLabels[language].resources}: ${titles.join(", ")}`);
    }
    return [...new Set(lines.filter(Boolean))];
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

/**
 * Part kinds that are agent-run bookkeeping, never part of the readable reply.
 * training_card is rendered once as the live inline practice card in the
 * conversation footer; the raw part is not repeated in the message body.
 */
const HIDDEN_ASSISTANT_PART_TYPES = new Set([
  "coach_visible_status",
  "tool_call",
  "tool_result",
  "reasoning",
  "training_card",
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
  const failed = activities.filter(
    (activity) => activity.status === "failed" || activity.status === "running",
  ).length;
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

function humanizeToolName(name: string): string {
  const normalized = name.replace(/_/g, " ").trim();
  return normalized.length > 0 ? normalized : name;
}

function toolTrailLabel(
  activity: { name: string; args?: Record<string, unknown>; result?: unknown },
  language: ComposerLanguage,
): string {
  return (
    resolveToolActivityLabel(activity.name, language, activity.args, activity.result) ??
    humanizeToolName(activity.name)
  );
}

function toolTrailTarget(activity: { args?: Record<string, unknown> }): string {
  const args = activity.args;
  if (!args || typeof args !== "object") {
    return "";
  }
  const candidate =
    args.path ??
    args.new_path ??
    args.folder_path ??
    args.directory ??
    args.query ??
    args.pattern ??
    args.url ??
    args.symbol ??
    args.name ??
    args.skill_id ??
    args.skill_name ??
    args.module ??
    args.topic ??
    args.focus_area ??
    args.title ??
    args.folder ??
    args.natural_language_goal ??
    args.goal ??
    args.command;
  if (typeof candidate === "string") {
    let cleaned = candidate.replace(/\s+/g, " ").trim();
    if (/^https?:\/\//i.test(cleaned)) {
      try {
        const parsed = new URL(cleaned);
        const pathPart = parsed.pathname === "/" ? "" : parsed.pathname;
        cleaned = `${parsed.hostname}${pathPart}`.replace(/\/+$/, "");
      } catch {
        // Keep raw trimmed string if URL parsing fails
      }
    }
    return cleaned.length > 48 ? `${cleaned.slice(0, 47)}…` : cleaned;
  }
  if (Array.isArray(args.paths) && args.paths.length > 0) {
    return `${String(args.paths[0]).trim()} (+${args.paths.length - 1})`;
  }
  return "";
}

function toolTrailHint(
  activity: { status: string; result?: unknown },
  language: ComposerLanguage,
): string {
  const copy = resolveCoachToolResultCopy(language);
  if (activity.status === "failed") {
    return copy.needsRetry;
  }
  if (activity.status === "running") {
    // The trail only renders on a finished message, so a running row is an
    // interrupted step, not a live one.
    return copy.needsRetry;
  }
  return summarizeSafeCoachToolResult(activity.result, language) ?? copy.completed;
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
  resources,
}: CoachMessageBubbleProps) {
  const resolvedRoleLabel =
    roleLabel ??
    (message.role === "user" ? userLabel : message.role === "system" ? systemLabel : assistantLabel) ??
    fallbackRoleLabel(message, language);

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
  const showAuthor = message.role !== "assistant" && message.author.trim() !== resolvedRoleLabel.trim();
  const timestamp = compactTimestamp(message.timestamp);
  const showTimestampInline = !streaming && message.role !== "assistant" && timestamp.length > 0;
  const supportDetails = supportDetailLines(message, language, resources);
  const hasSupportDetails =
    supportDetails.length > 0 || Boolean(message.support?.preview);
  const detailBlocks: ReactNode[] = [];
  const messageHasArtifacts = artifactCount > 0;
  const visibleBody = message.body;
  const hasBody = visibleBody.trim().length > 0;
  const hasImagePreviews = (message.imagePreviews?.length ?? 0) > 0;

  const primaryArtifact = message.artifacts?.find((artifact) => Boolean(artifact.recommendedAction));
  const visibleParts =
    message.role === "assistant" && message.parts?.length
      ? message.parts.filter((part) => !HIDDEN_ASSISTANT_PART_TYPES.has(part.type) &&
          !(hasBody && ["training_card", "plan_update", "test_result"].includes(part.type)))
      : message.parts;
  // Grounding downgrade (DESIGN.md §2.5) stays honest but stops repeating: the
  // message renders its "confirm before acting" marker exactly once, owned by
  // the first surface that presents the next step — the visible-status
  // next-step line, or the next-step artifact's action surface when no such
  // line exists (`resolveNextStepConfirmationOwner`).
  const turnRequiresConfirmation =
    nextStepRequiresConfirmation || nextStepRequiresConfirmationFromArtifacts(message.artifacts);
  const confirmationOwner = resolveNextStepConfirmationOwner({
    requiresConfirmation: turnRequiresConfirmation,
    hasStatusNextStep: statusNextStepPartIndex(visibleParts) >= 0,
    hasArtifactNextStep: Boolean(primaryArtifact),
  });
  const artifactOwnsConfirmation = confirmationOwner === "artifact";
  // 弹出式：最新回复的主操作默认隐藏，由图标排末尾的下一步按钮展开——
  // 展开后动作条出现在消息底部，正好位于输入框上方。
  const [nextActionRevealed, setNextActionRevealed] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const [morePlacement, setMorePlacement] = useState<"below" | "above">("below");
  const moreMenuRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!moreOpen) {
      return undefined;
    }
    const handlePointerDown = (event: PointerEvent) => {
      if (moreMenuRef.current && !moreMenuRef.current.contains(event.target as Node)) {
        setMoreOpen(false);
      }
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMoreOpen(false);
      }
    };
    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [moreOpen]);
  const moreLabel = MORE_ACTIONS_TEXT[language] ?? MORE_ACTIONS_TEXT["en-US"];
  const primaryNextAction = primaryArtifact && onArtifactOpen && !streaming && isLatestAssistant ? (
    <CoachArtifactBlock
      artifact={primaryArtifact}
      compact
      slim
      language={language}
      // The artifact-owned confirmation note is carried by the always-visible
      // quiet line below (the disclosure is gone); the revealed action surface
      // must not render a second copy.
      nextStepConfirmation={false}
      onOpen={(artifact) => onArtifactOpen(artifact, message)}
    />
  ) : null;
  // 查看证据 disclosure removed (user request): artifacts surface only through
  // the primary next-action block — the thread stays one idea per bubble.
  // The grounding downgrade must still be visible (DESIGN.md §2.5), so when
  // the artifact surface owns the allocation the note renders as one quiet
  // inline line instead of living inside a disclosure.
  if (supportDetails.length > 0 && message.role !== "assistant") {
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

  // `detailBlocks` now only holds the non-assistant support block, and a
  // support block can be pushed while still empty (e.g. a preview without
  // lines), so the gate reads the sources rather than the array.
  const hasSupplementMaterial = message.role !== "assistant" && supportDetails.length > 0;
  const showSystemMeta = message.role === "system";
  // Feed chrome stays out of the way: user turns render without a repeated
  // author/timestamp row; the timestamp remains available as a tooltip.
  // Coach replies carry the one identity line (r1-g0-0): a small name above
  // the body plus the lane hairline styled in the conversation CSS.
  const showUserMeta = false;
  const showAssistantRail = message.role === "assistant";
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
      ? deriveTrainerToolActivity(message.parts).filter(
          (activity) => activity.name !== "coach_finalize",
        )
      : [];
  // Degraded turns may carry only a status part with no readable body; keep a
  // quiet one-line summary so the bubble never renders as an empty card.
  const fallbackStatusSummary =
    message.role === "assistant" && !hasBody && !hasParts && !hasRunningActivities
      ? findCoachVisibleStatusPart(message.parts)?.summary?.trim()
      : undefined;
  // A finished turn can arrive with no body, parts, or status (empty provider
  // completion). Never leave an empty card: the learner gets one honest line
  // they can act on instead of a blank reply area.
  const emptyReplyFallback =
    message.role === "assistant" &&
    !streaming &&
    !hasBody &&
    !hasParts &&
    !hasRunningActivities &&
    !fallbackStatusSummary &&
    !children;

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
            {showTimestampInline ? <span className="message-bubble__timestamp">{timestamp}</span> : null}
          </div>
        </div>
      ) : null}

      <CoachReply
        body={(
      <div className="message-bubble__body">
        {showAssistantRail ? (
          <div
            className={`message-bubble__assistant-rail${headNote ? " message-bubble__assistant-rail--with-activity" : ""}`}
          >
            <span className="message-bubble__assistant-label">{resolvedRoleLabel}</span>
            {headNote}
            {!streaming && timestamp ? (
              <span className="message-bubble__assistant-time">{timestamp}</span>
            ) : null}
          </div>
        ) : null}
        {hasRunningActivities && !children ? (
          // §四十八: one loading idiom per bubble. The conversation view owns
          // the working label for the live turn (children); this fallback is
          // only for bubbles rendered outside that list.
          <CoachWorkingIndicator language={language} messageId={message.id} stage={currentTrainerStage(toolTrailActivities, language)} />
        ) : null}
        {!streaming && toolTrailActivities.length > 0 ? (
          <details className="coach-work-trail">
            <summary>{toolTrailSummary(toolTrailActivities, language)}</summary>
            <ul className="coach-work-trail__rows">
              {toolTrailActivities.map((activity) => {
                const target = toolTrailTarget(activity);
                return (
                  <li key={activity.id} className="coach-work-trail__row">
                    <span>
                      <span>{toolTrailLabel(activity, language)}</span>
                      {target ? <code className="coach-work-trail__target">{target}</code> : null}
                    </span>
                    <span className="coach-work-trail__hint">
                      {toolTrailHint(activity, language)}
                    </span>
                  </li>
                );
              })}
            </ul>
          </details>
        ) : null}
        {!hasBody && fallbackStatusSummary ? (
          <p className="message-bubble__agent-status-summary">
            {sanitizeErrorSurfaceText(fallbackStatusSummary, language)}
          </p>
        ) : null}
        {emptyReplyFallback && !hasImagePreviews ? (
          <p className="message-bubble__agent-status-summary" data-empty-reply-fallback="true">
            {coachMessageBubbleCopy(
              language,
              "这一轮没有返回可显示的回复。可以重试或换一种问法。",
            )}
          </p>
        ) : null}
        {hasImagePreviews ? (
          <MessageImageGallery previews={message.imagePreviews} language={language} />
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
            nextStepRequiresConfirmation={confirmationOwner === "status-line"}
            resources={resources}
          />
        ) : null}
        {!streaming && message.researchPreparation ? (
          message.researchPreparation.status === "saved" && onMessageAction ? (
            <button type="button" className="template-back" data-research-preparation="saved"
              onClick={() => onMessageAction("open-research-brief", message)}>
              {OPEN_RESEARCH_PREPARATION_TEXT[language]}
            </button>
          ) : (
            <p className="template-metadata" data-research-preparation={message.researchPreparation.status}>
              {RESEARCH_PREPARATION_TEXT[language][message.researchPreparation.status]}
            </p>
          )
        ) : null}
        {artifactOwnsConfirmation && !streaming ? (
          // Single-shot allocation (see resolveNextStepConfirmationOwner): with
          // the artifacts disclosure gone, the artifact-owned downgrade renders
          // as this one always-visible quiet line — never inside a fold.
          <p
            className="message-part__confirm-note"
            data-next-step-confirm-note="true"
            data-next-step-requires-confirmation="true"
          >
            {resolveCopy(language).nextStepConfirmNote}
          </p>
        ) : null}
        {children}
        {streaming ? (
          hasBody || hasParts ? (
            <span className="coach-cursor" aria-hidden="true" />
          ) : children || headNote ? null : (
            // §四十八: one loading idiom per bubble. A supplied working line
            // or the live stage strip already carries the state, so the
            // pending skeleton stays off.
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
          // Keep the persistent reply bar calm: 3 visible actions (copy,
          // practice, more) and tuck secondary actions into the accessible menu.
          <div className="message-bubble__tools">
            <div className="message-bubble__quick-tools" role="group" aria-label={coachMessageBubbleCopy(language, "这条回复的快捷操作")}>
              <button
                type="button"
                className="message-bubble__icon-action"
                data-message-quick-action="copy"
                data-action-label={messageActionLabels.copy}
                aria-label={messageActionLabels.copy}
                disabled={Boolean(pendingAssistantAction)}
                onClick={() => onMessageAction?.("copy", message)}
              >
                <ActionGlyph glyphs={GLYPH_COPY} />
              </button>
              <button
                type="button"
                className="message-bubble__icon-action"
                data-message-quick-action="training-card"
                data-action-label={messageActionLabels["training-card"]}
                aria-label={messageActionLabels["training-card"]}
                disabled={Boolean(pendingAssistantAction)}
                onClick={() => onMessageAction?.("training-card", message)}
              >
                <ActionGlyph glyphs={GLYPH_CARD} />
              </button>
              <div className="message-bubble__more-wrap" ref={moreMenuRef}>
                <button
                  type="button"
                  className="message-bubble__icon-action"
                  data-message-quick-action="more"
                  data-action-label={moreLabel}
                  aria-label={moreLabel}
                  aria-haspopup="menu"
                  aria-expanded={moreOpen}
                  disabled={Boolean(pendingAssistantAction)}
                  onClick={(event) => {
                    const rect = event.currentTarget.getBoundingClientRect();
                    const viewportHeight =
                      typeof window !== "undefined" ? window.innerHeight : 800;
                    setMorePlacement(rect.bottom + 240 > viewportHeight ? "above" : "below");
                    setMoreOpen((open) => !open);
                  }}
                >
                  <ActionGlyph glyphs={GLYPH_MORE} />
                </button>
                {moreOpen ? (
                  <div
                    className="message-bubble__more-menu"
                    data-menu-placement={morePlacement}
                    role="menu"
                    aria-label={moreLabel}
                  >
                    <button
                      type="button"
                      role="menuitem"
                      className="message-bubble__more-item"
                      data-message-quick-action="flash-card"
                      disabled={Boolean(pendingAssistantAction)}
                      onClick={() => { setMoreOpen(false); onMessageAction?.("flash-card", message); }}
                    >
                      <ActionGlyph glyphs={GLYPH_FLASH} />
                      <span>{messageActionLabels["flash-card"]}</span>
                    </button>
                    {isLatestAssistant ? (
                      <button
                        type="button"
                        role="menuitem"
                        className="message-bubble__more-item"
                        data-message-quick-action="set-goal"
                        disabled={Boolean(pendingAssistantAction)}
                        onClick={() => { setMoreOpen(false); onMessageAction?.("set-goal", message); }}
                      >
                        <ActionGlyph glyphs={GLYPH_TARGET} />
                        <span>{messageActionLabels["set-goal"]}</span>
                      </button>
                    ) : null}
                    <button
                      type="button"
                      role="menuitem"
                      className="message-bubble__more-item"
                      data-message-quick-action="save-resource"
                      disabled={Boolean(pendingAssistantAction)}
                      onClick={() => { setMoreOpen(false); onMessageAction?.("save-resource", message); }}
                    >
                      <ActionGlyph glyphs={GLYPH_LIBRARY} />
                      <span>{messageActionLabels["save-resource"]}</span>
                    </button>
                    {message.researchPreparation?.status !== "saved" ? (
                      <button
                        type="button"
                        role="menuitem"
                        className="message-bubble__more-item"
                        data-message-quick-action="save-research-brief"
                        disabled={Boolean(pendingAssistantAction)}
                        onClick={() => { setMoreOpen(false); onMessageAction?.("save-research-brief", message); }}
                      >
                        <ActionGlyph glyphs={GLYPH_BRIEF} />
                        <span>{messageActionLabels["save-research-brief"]}</span>
                      </button>
                    ) : null}
                    <button
                      type="button"
                      role="menuitem"
                      className="message-bubble__more-item"
                      data-message-quick-action="share"
                      disabled={Boolean(pendingAssistantAction)}
                      onClick={() => { setMoreOpen(false); onMessageAction?.("share", message); }}
                    >
                      <ActionGlyph glyphs={GLYPH_SHARE} />
                      <span>{messageActionLabels.share}</span>
                    </button>
                    {isLatestAssistant ? (
                      <button
                        type="button"
                        role="menuitem"
                        className="message-bubble__more-item"
                        data-message-quick-action="retry"
                        disabled={Boolean(pendingAssistantAction)}
                        onClick={() => { setMoreOpen(false); onMessageAction?.("retry", message); }}
                      >
                        <ActionGlyph glyphs={GLYPH_RETRY} />
                        <span>{messageActionLabels.retry}</span>
                      </button>
                    ) : null}
                    {isLatestAssistant && primaryNextAction ? (
                      <button
                        type="button"
                        role="menuitem"
                        className="message-bubble__more-item"
                        data-message-quick-action="next-action"
                        aria-pressed={nextActionRevealed}
                        onClick={() => { setMoreOpen(false); setNextActionRevealed((value) => !value); }}
                      >
                        <ActionGlyph glyphs={GLYPH_NEXT} />
                        <span>{artifactBlockCopy(language, "下一步")}</span>
                      </button>
                    ) : null}
                  </div>
                ) : null}
              </div>
            </div>
            {isLatestAssistant && nextActionRevealed && primaryNextAction ? primaryNextAction : null}
          </div>
        ) : null}
      />
    </article>
  );
}

export const CoachMessageBubble = memo(CoachMessageBubbleImpl);
