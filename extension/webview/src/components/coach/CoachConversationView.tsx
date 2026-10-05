import { Conversation } from "../../templates/Conversation";
import { memo } from "react";

import type { ConversationMessage } from "../../lib/types";
import type { ComposerLanguage } from "../../lib/types";
import type { AgentToolActivity } from "../../app/useWorkbenchState";
import type { CoachArtifactBlockData } from "./CoachArtifactBlock";
import { AgentActivityStrip } from "./AgentActivityStripSmart";
import { CoachMessageBubble, type CoachMessageAction } from "./CoachMessageBubble";

export interface StreamingMessageState {
  body: string;
  author?: string;
  timestamp?: string;
  role?: ConversationMessage["role"];
  roleLabel?: string;
  note?: string;
}

/** In-message typing label: text carries the state, the dots only decorate it. */
const COACH_TYPING_LABELS: Record<ComposerLanguage, string> = {
  "zh-CN": "教练正在输入…",
  "en-US": "Coach is typing…",
  "es-ES": "El entrenador está escribiendo…",
  "fr-FR": "Le coach écrit…",
  "de-DE": "Coach schreibt…",
  "ja-JP": "コーチが入力中…",
  "ko-KR": "코치가 입력 중…",
  "pt-BR": "O coach está digitando…",
};

export interface CoachConversationViewProps {
  messages: ConversationMessage[];
  className?: string;
  surfaceTone?: "thread" | "quiet";
  eyebrow?: string;
  title?: string;
  subtitle?: string;
  emptyState?: React.ReactNode;
  footer?: React.ReactNode;
  openArtifactLabel?: string;
  userLabel?: string;
  assistantLabel?: string;
  systemLabel?: string;
  language?: ComposerLanguage;
  streamingMessage?: StreamingMessageState | null;
  agentActivity?: AgentToolActivity[];
  agentStep?: number;
  onArtifactOpen?: (artifact: CoachArtifactBlockData, message: ConversationMessage) => void;
  onMessageAction?: (action: CoachMessageAction, message: ConversationMessage) => void;
  pendingMessageAction?: string | null;
}

interface CoachConversationItem {
  key: number;
  message: ConversationMessage;
  streaming: boolean;
  isLatestAssistant: boolean;
}

function CoachConversationViewImpl({
  messages,
  className,
  surfaceTone = "thread",
  eyebrow,
  title,
  subtitle,
  emptyState,
  footer,
  openArtifactLabel,
  userLabel,
  assistantLabel,
  systemLabel,
  language = "en-US",
  streamingMessage,
  agentActivity,
  agentStep,
  onArtifactOpen,
  onMessageAction,
  pendingMessageAction,
}: CoachConversationViewProps) {
  const classes = [
    surfaceTone === "thread" ? "section-block" : "coach-conversation-view--open",
    "coach-conversation-view",
    surfaceTone === "thread" ? "section-block--chat" : "coach-conversation-view--quiet-surface",
    surfaceTone === "thread"
      ? "coach-conversation-view--codex coach-conversation-view--dense"
      : "coach-conversation-view--quiet",
    className,
  ]
    .filter(Boolean)
    .join(" ");
  const showHeader = Boolean(eyebrow || title || subtitle);
  const hasMessages = messages.length > 0 || Boolean(streamingMessage);

  // One flat, append-only list. Keys are positional so the streaming slot and
  // the server-confirmed assistant message that later lands at the same index
  // share one React instance: the reply finishes in place, with no remount and
  // no entrance-animation replay.
  const items: CoachConversationItem[] = messages.map((message, index) => ({
    key: index,
    message,
    streaming: false,
    isLatestAssistant: false,
  }));
  for (let index = items.length - 1; index >= 0; index--) {
    if (items[index].message.role === "assistant") {
      items[index].isLatestAssistant = true;
      break;
    }
  }
  if (streamingMessage) {
    items.push({
      key: items.length,
      streaming: true,
      isLatestAssistant: false,
      message: {
        // Canonical streaming bubble id: the webview-recovery contract and
        // host tooling locate the in-flight reply by it.
        id: "streaming",
        role: streamingMessage.role ?? "assistant",
        author: streamingMessage.author ?? "Trainer",
        body: streamingMessage.body,
        timestamp: streamingMessage.timestamp ?? "Streaming...",
        contextNote: streamingMessage.note,
      },
    });
  }
  const streamingStripVisible = Boolean(streamingMessage && agentActivity && agentActivity.length > 0);

  return (
    <Conversation className={classes} label={title}>
      {showHeader ? (
        <div className="section-block__header">
          <div className="coach-conversation-view__heading">
            {eyebrow ? <span className="eyebrow">{eyebrow}</span> : null}
            {title ? <h2 id="coach-conversation-view-title">{title}</h2> : null}
            {subtitle ? <p className="coach-conversation-view__subtitle">{subtitle}</p> : null}
          </div>
        </div>
      ) : null}

      <div
        className={`message-list coach-conversation-view__list ${
          hasMessages ? "coach-conversation-view__list--active" : "coach-conversation-view__list--empty"
        }`}
      >
        {messages.length === 0 && emptyState ? emptyState : null}

        {items.map((item, itemIndex) => (
          <div
            key={item.key}
            className={`coach-conversation-view__item coach-conversation-view__item--${
              item.message.role === "user" ? "user" : item.message.role === "system" ? "system" : "assistant"
            }`}
          >
            <div className="coach-conversation-view__message-lane">
              <CoachMessageBubble
                assistantLabel={
                  item.streaming ? streamingMessage?.roleLabel ?? assistantLabel : assistantLabel
                }
                className={item.streaming ? "message-bubble--streaming" : undefined}
                message={item.message}
                systemLabel={systemLabel}
                userLabel={userLabel}
                language={language}
                streaming={item.streaming}
                isLatestAssistant={item.isLatestAssistant}
                onArtifactOpen={onArtifactOpen}
                onMessageAction={onMessageAction}
                pendingMessageAction={pendingMessageAction}
                headNote={
                  item.streaming && streamingStripVisible ? (
                    <AgentActivityStrip
                      activities={agentActivity ?? []}
                      step={agentStep}
                      language={language}
                    />
                  ) : undefined
                }
              >
                {item.streaming ? (
                  <div className="coach-streaming-dots" role="status" aria-live="polite">
                    <span className="coach-streaming-dots__label">
                      {COACH_TYPING_LABELS[language] ?? COACH_TYPING_LABELS["en-US"]}
                    </span>
                    <span className="coach-streaming-dots__dots" aria-hidden="true">
                      <span /><span /><span />
                    </span>
                  </div>
                ) : null}
              </CoachMessageBubble>
            </div>
          </div>
        ))}
      </div>

      {footer ? <div className="coach-conversation-view__footer">{footer}</div> : null}
    </Conversation>
  );
}

export const CoachConversationView = memo(CoachConversationViewImpl);
