import { useMemo, useState } from "react";

import { SystemState } from "../../templates/SystemState";

import { CheckMarkIcon, RefreshIcon } from "../icons";
import type { CoachSessionSummary, ComposerLanguage } from "../../lib/types";

const HISTORY_COPY: Record<ComposerLanguage, Record<"title" | "newChat" | "refresh" | "search" | "untitled" | "messages" | "loading" | "error" | "empty" | "noMatches" | "current" | "today" | "yesterday" | "last7" | "earlier", string>> = {
  "zh-CN": {
    "title": "历史会话",
    "newChat": "+ 新对话",
    "refresh": "刷新会话列表",
    "search": "搜索会话",
    "untitled": "未命名会话",
    "messages": "{n} 条消息",
    "loading": "正在读取会话…",
    "error": "暂时读不到会话，稍后再试。",
    "empty": "还没有历史会话。新的对话会出现在这里。",
    "noMatches": "没有匹配的会话。",
    "current": "当前会话",
    "today": "今天",
    "yesterday": "昨天",
    "last7": "过去 7 天",
    "earlier": "更早"
  },
  "en-US": {
    "title": "Conversations",
    "newChat": "+ New chat",
    "refresh": "Refresh conversation list",
    "search": "Search chats",
    "untitled": "Untitled conversation",
    "messages": "{n} messages",
    "loading": "Loading conversations…",
    "error": "Couldn’t load conversations. Try again.",
    "empty": "No past conversations yet. New chats will appear here.",
    "noMatches": "No matching conversations.",
    "current": "Current",
    "today": "Today",
    "yesterday": "Yesterday",
    "last7": "Last 7 Days",
    "earlier": "Earlier"
  },
  "es-ES": {
    "title": "Conversaciones",
    "newChat": "+ Nuevo chat",
    "refresh": "Actualizar conversaciones",
    "search": "Buscar chats",
    "untitled": "Conversación sin título",
    "messages": "{n} mensajes",
    "loading": "Cargando conversaciones…",
    "error": "No se pudieron cargar las conversaciones. Inténtalo de nuevo.",
    "empty": "Todavía no hay conversaciones anteriores.",
    "noMatches": "No hay conversaciones coincidentes.",
    "current": "Actual",
    "today": "Hoy",
    "yesterday": "Ayer",
    "last7": "Últimos 7 días",
    "earlier": "Anterior"
  },
  "fr-FR": {
    "title": "Conversations",
    "newChat": "+ Nouvelle discussion",
    "refresh": "Actualiser les conversations",
    "search": "Rechercher des discussions",
    "untitled": "Conversation sans titre",
    "messages": "{n} messages",
    "loading": "Chargement des conversations…",
    "error": "Impossible de charger les conversations. Réessayez.",
    "empty": "Aucune conversation précédente.",
    "noMatches": "Aucune conversation correspondante.",
    "current": "Actuelle",
    "today": "Aujourd’hui",
    "yesterday": "Hier",
    "last7": "7 derniers jours",
    "earlier": "Plus anciennes"
  },
  "de-DE": {
    "title": "Unterhaltungen",
    "newChat": "+ Neuer Chat",
    "refresh": "Unterhaltungen aktualisieren",
    "search": "Chats suchen",
    "untitled": "Unbenannte Unterhaltung",
    "messages": "{n} Nachrichten",
    "loading": "Unterhaltungen werden geladen…",
    "error": "Unterhaltungen konnten nicht geladen werden. Erneut versuchen.",
    "empty": "Noch keine früheren Unterhaltungen.",
    "noMatches": "Keine passenden Unterhaltungen.",
    "current": "Aktuell",
    "today": "Heute",
    "yesterday": "Gestern",
    "last7": "Letzte 7 Tage",
    "earlier": "Früher"
  },
  "ja-JP": {
    "title": "会話履歴",
    "newChat": "+ 新しい対話",
    "refresh": "会話一覧を更新",
    "search": "会話を検索",
    "untitled": "無題の会話",
    "messages": "{n} 件のメッセージ",
    "loading": "会話を読み込み中…",
    "error": "会話を読み込めません。再試行してください。",
    "empty": "過去の会話はまだありません。",
    "noMatches": "一致する会話はありません。",
    "current": "現在の会話",
    "today": "今日",
    "yesterday": "昨日",
    "last7": "過去7日間",
    "earlier": "それ以前"
  },
  "ko-KR": {
    "title": "대화 기록",
    "newChat": "+ 새 대화",
    "refresh": "대화 목록 새로고침",
    "search": "대화 검색",
    "untitled": "제목 없는 대화",
    "messages": "메시지 {n}개",
    "loading": "대화 불러오는 중…",
    "error": "대화를 불러올 수 없습니다. 다시 시도하세요.",
    "empty": "이전 대화가 없습니다.",
    "noMatches": "일치하는 대화가 없습니다.",
    "current": "현재 대화",
    "today": "오늘",
    "yesterday": "어제",
    "last7": "최근 7일",
    "earlier": "이전"
  },
  "pt-BR": {
    "title": "Conversas",
    "newChat": "+ Nova conversa",
    "refresh": "Atualizar conversas",
    "search": "Buscar conversas",
    "untitled": "Conversa sem título",
    "messages": "{n} mensagens",
    "loading": "Carregando conversas…",
    "error": "Não foi possível carregar as conversas. Tente novamente.",
    "empty": "Ainda não há conversas anteriores.",
    "noMatches": "Nenhuma conversa correspondente.",
    "current": "Atual",
    "today": "Hoje",
    "yesterday": "Ontem",
    "last7": "Últimos 7 dias",
    "earlier": "Anteriores"
  }
};

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
    return stamp.toLocaleString(language, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  return (
    <>
      <div className="composer-menu-panel__header">
        <span className="eyebrow">{copy.title}</span>
        <div className="composer-menu-panel__header-actions">
          <button className="composer-history-new" type="button" onClick={onNewChat}>
            {copy.newChat}
          </button>
          <button
            type="button"
            aria-label={copy.refresh}
            title={copy.refresh}
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
          placeholder={`${copy.search}…`}
          aria-label={copy.search}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>
      <div className="composer-menu-panel__section">
        {status === "loading" ? (
          <SystemState kind="loading" title={copy.loading} />
        ) : status === "error" ? (
          <SystemState kind="recoverable-error" title={statusMessage ?? copy.error} action={{ label: copy.refresh, onClick: onRefresh }} />
        ) : sessions.length === 0 ? (
          <SystemState kind="empty" title={copy.empty} />
        ) : groups.length === 0 ? (
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
                        {active ? (
                          <span className="composer-provider-list__state">
                            <CheckMarkIcon size={12} />
                            <span className="sr-only">{copy.current}</span>
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
