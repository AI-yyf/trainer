import { useMemo, useState } from "react";

import { SystemState } from "../../templates/SystemState";

import { PlusIcon, SearchIcon } from "../icons";
import type { CoachSessionSummary, ComposerLanguage } from "../../lib/types";
import { HISTORY_COPY } from "../../lib/i18n/segments/coachInlineText";

export type CoachHistoryGroupKey = "today" | "yesterday" | "last7" | "earlier";

export interface CoachHistoryGroup {
  key: CoachHistoryGroupKey;
  label: string;
  sessions: CoachSessionSummary[];
}

const GROUP_ORDER: CoachHistoryGroupKey[] = ["today", "yesterday", "last7", "earlier"];

function dayStart(value: Date): number {
  return new Date(value.getFullYear(), value.getMonth(), value.getDate()).getTime();
}

/**
 * ChatGPT-style recency buckets (spec §63): Today / Yesterday / Last 7 Days /
 * Earlier. Sessions without a parseable timestamp land in "earlier" so nothing
 * silently disappears.
 */
export function groupSessionsByRecency(
  sessions: CoachSessionSummary[],
  zh: boolean,
  now: Date = new Date(),
): CoachHistoryGroup[] {
  const labels: Record<CoachHistoryGroupKey, string> = zh
    ? { today: "今天", yesterday: "昨天", last7: "过去 7 天", earlier: "更早" }
    : { today: "Today", yesterday: "Yesterday", last7: "Last 7 Days", earlier: "Earlier" };
  const todayStart = dayStart(now);
  const yesterdayStart = todayStart - 86_400_000;
  const last7Start = todayStart - 7 * 86_400_000;
  const buckets: Record<CoachHistoryGroupKey, CoachSessionSummary[]> = {
    today: [],
    yesterday: [],
    last7: [],
    earlier: [],
  };
  for (const session of sessions) {
    const stamp = session.updated_at ? new Date(session.updated_at) : undefined;
    const time = stamp && !Number.isNaN(stamp.getTime()) ? stamp.getTime() : Number.NEGATIVE_INFINITY;
    if (time >= todayStart) {
      buckets.today.push(session);
    } else if (time >= yesterdayStart) {
      buckets.yesterday.push(session);
    } else if (time >= last7Start) {
      buckets.last7.push(session);
    } else {
      buckets.earlier.push(session);
    }
  }
  return GROUP_ORDER.filter((key) => buckets[key].length > 0).map((key) => ({
    key,
    label: labels[key],
    sessions: buckets[key],
  }));
}

/** Case-insensitive substring match over the user-visible session text. */
export function filterSessions(
  sessions: CoachSessionSummary[],
  query: string,
  untitledLabel: string,
): CoachSessionSummary[] {
  const needle = query.trim().toLocaleLowerCase();
  if (!needle) {
    return sessions;
  }
  return sessions.filter((session) => {
    const haystack = [session.summary, session.latest_user_message, untitledLabel]
      .map((part) => (part ?? "").toLocaleLowerCase())
      .join("\n");
    return haystack.includes(needle);
  });
}

export function sessionTitle(session: CoachSessionSummary, untitledLabel: string): string {
  return (
    session.summary?.trim() || session.latest_user_message?.trim() || untitledLabel
  );
}

export interface CoachHistoryDrawerProps {
  zh: boolean;
  language?: ComposerLanguage;
  sessions: CoachSessionSummary[];
  status: "idle" | "loading" | "ready" | "error";
  statusMessage?: string;
  onActivate: (sessionId: string) => void;
  onRefresh: () => void;
  onNewChat: () => void;
  onClose: () => void;
}

/** ChatGPT-style history: new chat on top, search, grouped by recency. */
export function CoachHistoryDrawer({
  zh,
  language = zh ? "zh-CN" : "en-US",
  sessions,
  status,
  statusMessage,
  onActivate,
  onRefresh,
  onNewChat,
}: CoachHistoryDrawerProps) {
  const [query, setQuery] = useState("");
  const copy = HISTORY_COPY[language];
  const untitledLabel = copy.untitled;
  const visible = useMemo(
    () => filterSessions(sessions, query, untitledLabel),
    [sessions, query, untitledLabel],
  );
  const groups = useMemo(() => groupSessionsByRecency(visible, zh).map(group => ({ ...group, label: copy[group.key] })), [visible, zh, copy]);
  const messageCountLabel = (count: number) =>
    copy.messages.replace("{n}", String(count));
  const formatSessionTime = (value?: string | null) => {
    if (!value) {
      return "";
    }
    const stamp = new Date(value);
    if (Number.isNaN(stamp.getTime())) {
      return "";
    }
    const now = new Date();
    const sameDay =
      stamp.getFullYear() === now.getFullYear() &&
      stamp.getMonth() === now.getMonth() &&
      stamp.getDate() === now.getDate();
    if (sameDay) {
      return stamp.toLocaleTimeString(language, { hour: "2-digit", minute: "2-digit" });
    }
    return stamp.toLocaleDateString(language, { month: "short", day: "numeric" });
  };

  return (
    <>
      <div className="composer-menu-panel__header">
        <span className="composer-history-title eyebrow">{copy.title}</span>
      </div>
      <div className="composer-history-search">
        <SearchIcon size={14} />
        <input
          type="text"
          value={query}
          placeholder={`${copy.search}…`}
          aria-label={copy.search}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>
      <button className="composer-history-new" type="button" onClick={onNewChat}>
        <PlusIcon size={14} />
        {copy.newChat.replace(/^\+\s*/, "")}
      </button>
      <div className="composer-menu-panel__section">
        {status === "error" && sessions.length === 0 ? (
          <SystemState kind="recoverable-error" title={statusMessage ?? copy.error} action={{ label: copy.refresh, onClick: onRefresh }} />
        ) : sessions.length === 0 && status !== "loading" ? (
          <SystemState kind="empty" title={copy.empty} />
        ) : groups.length === 0 && status !== "loading" ? (
          <SystemState kind="empty" title={copy.noMatches} />
        ) : (
          groups.map((group) => (
            <div key={group.key} className="composer-history-group" role="group">
              <p className="composer-history-group__label">{group.label}</p>
              <div className="composer-provider-list composer-session-list" role="list">
                {group.sessions.map((session) => {
                  const active = session.is_active === true;
                  const title = sessionTitle(session, untitledLabel);
                  const time = formatSessionTime(session.updated_at);
                  return (
                    <button
                      key={session.session_id}
                      className={`composer-provider-list__item composer-session-list__item ${
                        active ? "is-active" : ""
                      }`}
                      type="button"
                      disabled={active}
                      aria-current={active ? "true" : undefined}
                      title={title}
                      onClick={() => onActivate(session.session_id)}
                    >
                      <div className="composer-provider-list__row">
                        <span className="composer-provider-list__stack">
                          <span className="composer-provider-list__model composer-session-list__title">
                            {title}
                          </span>
                          <span className="composer-provider-list__label">
                            {[messageCountLabel(session.message_count), time].filter(Boolean).join(" · ")}
                          </span>
                        </span>
                        {active ? <span className="sr-only">{copy.current}</span> : null}
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          ))
        )}
        {status === "loading" ? (
          <div className="composer-history-loading" role="status" aria-live="polite">
            <p className="composer-history-loading__label">{copy.loading}</p>
            <div className="composer-history-skeleton" aria-hidden="true">
              {Array.from({ length: sessions.length > 0 ? 2 : 3 }, (_, index) => (
                <span key={index} className="skeleton composer-history-skeleton__row" />
              ))}
            </div>
          </div>
        ) : null}
        {status === "error" && sessions.length > 0 ? (
          <p className="composer-history-error">
            <span>{statusMessage ?? copy.error}</span>
            <button type="button" onClick={onRefresh}>{copy.refresh}</button>
          </p>
        ) : null}
      </div>
    </>
  );
}
