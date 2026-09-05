import type { ReactNode } from "react";

import type { ConversationMessage } from "../../lib/types";
import type { ComposerLanguage } from "../../lib/types";
import type { AgentToolActivity } from "../../app/useWorkbenchState";
import type { CoachArtifactBlockData } from "./CoachArtifactBlock";
import { AgentActivityStrip } from "./AgentActivityStripSmart";
import { CoachMessageBubble } from "./CoachMessageBubble";

export interface StreamingMessageState {
  body: string;
  author?: string;
  timestamp?: string;
  role?: ConversationMessage["role"];
  roleLabel?: string;
  note?: string;
}

export interface CoachConversationViewProps {
  messages: ConversationMessage[];
  className?: string;
  surfaceTone?: "thread" | "quiet";
  eyebrow?: string;
  title?: string;
  subtitle?: string;
  summaryBar?: ReactNode;
  emptyState?: ReactNode;
  footer?: ReactNode;
  openArtifactLabel?: string;
  userLabel?: string;
  assistantLabel?: string;
  systemLabel?: string;
  language?: ComposerLanguage;
  streamingMessage?: StreamingMessageState | null;
  agentActivity?: AgentToolActivity[];
  agentStep?: number;
  onArtifactOpen?: (artifact: CoachArtifactBlockData, message: ConversationMessage) => void;
  renderMessageSupplement?: (message: ConversationMessage) => ReactNode;
}

export function CoachConversationView({
  messages,
  className,
  surfaceTone = "thread",
  eyebrow,
  title,
  subtitle,
  summaryBar,
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
  renderMessageSupplement,
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
  const latestMessage = messages[messages.length - 1];
  const latestAssistantHasStatus = Boolean(
    latestMessage?.role === "assistant" &&
      latestMessage.parts?.some(
        (part) =>
          part.type === "coach_visible_status" ||
          part.type === "tool_call" ||
          part.type === "tool_result",
      ),
  );
  const showSummaryBar = Boolean(summaryBar) && (Boolean(streamingMessage) || !latestAssistantHasStatus);
  const items = messages.map((message) => {
    const supplement = renderMessageSupplement ? renderMessageSupplement(message) : null;
    return { message, supplement };
  });

  return (
    <section
      className={classes}
      aria-labelledby={showHeader ? "coach-conversation-view-title" : undefined}
      data-language={language}
    >
      {showHeader ? (
        <div className="section-block__header">
          <div className="coach-conversation-view__heading">
            {eyebrow ? <span className="eyebrow">{eyebrow}</span> : null}
            {title ? <h2 id="coach-conversation-view-title">{title}</h2> : null}
            {subtitle ? <p className="coach-conversation-view__subtitle">{subtitle}</p> : null}
          </div>
        </div>
      ) : null}

      {showSummaryBar ? (
        <div
          className="coach-conversation-view__summary coach-conversation-view__summary--context"
          role="status"
          aria-live={streamingMessage ? "polite" : undefined}
        >
          {summaryBar}
        </div>
      ) : null}

      <div
        className={`message-list coach-conversation-view__list ${
          hasMessages ? "coach-conversation-view__list--active" : "coach-conversation-view__list--empty"
        }`}
      >
        {messages.length === 0 && emptyState ? emptyState : null}

        {items.map(({ message, supplement }) => (
          <div
            key={message.id}
            className={`coach-conversation-view__item coach-conversation-view__item--${
              message.role === "user" ? "user" : message.role === "system" ? "system" : "assistant"
            }`}
          >
            <div className="coach-conversation-view__message-lane">
              <CoachMessageBubble
                assistantLabel={assistantLabel}
                message={message}
                openArtifactLabel={openArtifactLabel}
                systemLabel={systemLabel}
                userLabel={userLabel}
                language={language}
                onArtifactOpen={onArtifactOpen}
              />
            </div>
            {supplement ? <div className="coach-conversation-view__supplement">{supplement}</div> : null}
          </div>
        ))}

        {streamingMessage ? (
          <div className="coach-conversation-view__item coach-conversation-view__item--assistant">
            <div className="coach-conversation-view__message-lane">
              {agentActivity && agentActivity.length > 0 ? (
                <AgentActivityStrip
                  activities={agentActivity}
                  collapsible
                  step={agentStep}
                  language={language}
                />
              ) : null}
              <CoachMessageBubble
                assistantLabel={streamingMessage.roleLabel ?? assistantLabel}
                className="message-bubble--streaming"
                message={{
                  id: "streaming",
                  role: streamingMessage.role ?? "assistant",
                  author: streamingMessage.author ?? "Trainer",
                  body: streamingMessage.body,
                  timestamp: streamingMessage.timestamp ?? "Streaming...",
                  contextNote: streamingMessage.note,
                }}
                systemLabel={systemLabel}
                userLabel={userLabel}
                language={language}
                streaming
              />
            </div>
          </div>
        ) : null}
      </div>

      {footer ? <div className="coach-conversation-view__footer">{footer}</div> : null}
    </section>
  );
}
