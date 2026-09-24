import { useMemo, useState } from "react";

import { CheckMarkIcon, RefreshIcon } from "../icons";
import type { CoachSessionSummary } from "../../lib/types";

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
  sessions,
  status,
  statusMessage,
  onActivate,
  onRefresh,
  onNewChat,
}: CoachHistoryDrawerProps) {
  const [query, setQuery] = useState("");
  const untitledLabel = zh ? "未命名会话" : "Untitled conversation";
  const visible = useMemo(
    () => filterSessions(sessions, query, untitledLabel),
    [sessions, query, untitledLabel],
  );
  const groups = useMemo(() => groupSessionsByRecency(visible, zh), [visible, zh]);
  const messageCountLabel = (count: number) =>
    zh ? `${count} 条消息` : `${count} message${count === 1 ? "" : "s"}`;
  const formatSessionTime = (value?: string | null) => {
    if (!value) {
      return "";
    }
    const stamp = new Date(value);
    if (Number.isNaN(stamp.getTime())) {
      return "";
    }
    return stamp.toLocaleString(zh ? "zh-CN" : undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  return (
    <>
      <div className="composer-menu-panel__header">
        <span className="eyebrow">{zh ? "历史会话" : "Conversations"}</span>
        <div className="composer-menu-panel__header-actions">
          <button className="composer-history-new" type="button" onClick={onNewChat}>
            {zh ? "+ 新对话" : "+ New chat"}
          </button>
          <button
            type="button"
            aria-label={zh ? "刷新会话列表" : "Refresh conversation list"}
            title={zh ? "刷新会话列表" : "Refresh conversation list"}
            disabled={status === "loading"}
            onClick={onRefresh}
          >
            <RefreshIcon size={14} />
          </button>
        </div>
      </div>
      <div className="composer-history-search">
        <input
          type="text"
          value={query}
          placeholder={zh ? "搜索会话…" : "Search chats…"}
          aria-label={zh ? "搜索会话" : "Search chats"}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>
      <div className="composer-menu-panel__section">
        {status === "loading" ? (
          <p className="composer-menu-panel__hint">{zh ? "正在读取会话…" : "Loading conversations…"}</p>
        ) : status === "error" ? (
          <p className="composer-menu-panel__hint">
            {statusMessage ?? (zh ? "暂时读不到会话，稍后再试。" : "Couldn't load conversations. Try again.")}
          </p>
        ) : sessions.length === 0 ? (
          <p className="composer-menu-panel__hint">
            {zh ? "还没有历史会话。新的对话会出现在这里。" : "No past conversations yet. New chats will appear here."}
          </p>
        ) : groups.length === 0 ? (
          <p className="composer-menu-panel__hint">
            {zh ? "没有匹配的会话。" : "No matching conversations."}
          </p>
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
                        {active ? (
                          <span className="composer-provider-list__state">
                            <CheckMarkIcon size={12} />
                            <span className="sr-only">{zh ? "当前会话" : "Current"}</span>
                          </span>
                        ) : null}
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          ))
        )}
      </div>
    </>
  );
}
