import { Conversation } from "../../templates/Conversation";
import { memo } from "react";

import type { ConversationMessage, ResourceRecord } from "../../lib/types";
import type { ComposerLanguage } from "../../lib/types";
import type { AgentToolActivity } from "../../app/useWorkbenchState";
import { useWorkbenchState } from "../../app/useWorkbenchState";
import type { CoachArtifactBlockData } from "./CoachArtifactBlock";
import { AgentActivityStrip } from "./AgentActivityStripSmart";
import { CoachWorkingIndicator } from "./CoachWorkingIndicator";
import { currentTrainerStage, trainerStageLabel } from "../../lib/trainerStage";
import { CoachMessageBubble, type CoachMessageAction } from "./CoachMessageBubble";

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
  emptyState?: React.ReactNode;
  /** Renders inside the list before every entry (e.g. the in-progress-card resume line). */
  listHead?: React.ReactNode;
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
  /**
   * Turn-level grounding downgrade for the message being rendered (the latest
   * assistant reply / the streaming slot). Applied only to that item.
   */
  turnNextStepRequiresConfirmation?: boolean;
  /**
   * When true the in-flight reply body, agent activity and step come from the
   * store subscription below instead of App props: per-chunk streaming content
   * re-renders this view only, never the whole workbench (DESIGN.md §3 R3).
   */
  liveContentFromStore?: boolean;
  /** Current library records for live citation invalidation. */
  resources?: ResourceRecord[];
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
  listHead,
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
  turnNextStepRequiresConfirmation = false,
  liveContentFromStore = false,
  resources,
}: CoachConversationViewProps) {
  // Per-chunk streaming content lives here, not in App: the workbench shell
  // stays put while the in-flight reply grows (DESIGN.md §3 R3).
  const storeStreamedContent = useWorkbenchState((state) => state.streaming.streamedContent);
  const storeStreamMessageId = useWorkbenchState((state) => state.streaming.streamMessageId);
  const storeStreamIncomplete = useWorkbenchState((state) =>
    !state.streaming.isStreaming && Boolean(state.streaming.streamError ||
      state.streaming.completionStopReason === "cancelled" || state.streaming.reliabilityOutcome === "failure" ||
      state.streaming.reliabilityOutcome === "timeout" || state.streaming.reliabilityOutcome === "cancelled"),
  );
  const storeAgentActivity = useWorkbenchState((state) => state.streaming.agentActivity);
  const storeAgentStep = useWorkbenchState((state) => state.streaming.agentStep);
  const resolvedAgentActivity = liveContentFromStore ? storeAgentActivity : agentActivity;
  const resolvedAgentStep = liveContentFromStore ? storeAgentStep : agentStep;
  const resolvedStreamingBody = streamingMessage
    ? liveContentFromStore
      ? streamingMessage.body?.trim()
        ? streamingMessage.body
        : storeStreamMessageId?.startsWith("training_")
          ? ""
          : storeStreamedContent || ""
      : streamingMessage.body
    : undefined;
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
  const partialReply = liveContentFromStore && !streamingMessage && storeStreamIncomplete &&
    Boolean(storeStreamMessageId && !storeStreamMessageId.startsWith("training_") && storeStreamedContent.trim());
  const hasMessages = messages.length > 0 || Boolean(streamingMessage || partialReply);

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
  if (streamingMessage || partialReply) {
    items.push({
      key: items.length,
      streaming: Boolean(streamingMessage),
      isLatestAssistant: false,
      message: {
        // Canonical streaming bubble id: the webview-recovery contract and
        // host tooling locate the in-flight reply by it.
        id: "streaming",
        role: streamingMessage?.role ?? "assistant",
        author: streamingMessage?.author ?? "Trainer",
        body: partialReply ? storeStreamedContent : resolvedStreamingBody ?? "",
        timestamp: streamingMessage?.timestamp ?? "",
        contextNote: streamingMessage?.note,
      },
    });
  }
  const streamingStripVisible = Boolean(
    streamingMessage && resolvedAgentActivity && resolvedAgentActivity.length > 0,
  );
  const activeTrainerStage = resolvedStreamingBody?.trim()
    ? { kind: "responding" as const, label: trainerStageLabel("responding", language) }
    : currentTrainerStage(resolvedAgentActivity, language);

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
        {listHead}
        {!hasMessages && emptyState ? emptyState : null}

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
                onMessageAction={partialReply && item.message.id === "streaming" ? undefined : onMessageAction}
                pendingMessageAction={pendingMessageAction}
                nextStepRequiresConfirmation={
                  item.isLatestAssistant || item.streaming
                    ? turnNextStepRequiresConfirmation
                    : false
                }
                resources={resources}
                headNote={
                  item.streaming && streamingStripVisible ? (
                    <AgentActivityStrip
                      activities={resolvedAgentActivity ?? []}
                      step={resolvedAgentStep}
                      language={language}
                    />
                  ) : partialReply && item.message.id === "streaming" ? (
                    <span className="message-bubble__assistant-time" data-partial-reply="true">
                      {trainerStageLabel("interrupted", language)}
                    </span>
                  ) : undefined
                }
              >
                {item.streaming && !streamingStripVisible ? <CoachWorkingIndicator language={language} messageId={storeStreamMessageId ?? undefined} stage={activeTrainerStage} /> : null}
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
