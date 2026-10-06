import type { ReactNode } from "react";
import type { ActiveWorkbenchView, ComposerLanguage } from "../lib/types";
import { viewLabels } from "../lib/viewLabels";
import { PRIMARY_DESTINATIONS, primaryDestinationForRoute } from "../lib/workbenchDestinations";
import { HistoryIcon, SettingsIcon } from "../components/icons";

const NAV_LABEL: Record<ComposerLanguage, string> = {
  "zh-CN": "主导航", "en-US": "Primary navigation", "es-ES": "Navegación principal", "fr-FR": "Navigation principale",
  "de-DE": "Hauptnavigation", "ja-JP": "メインナビゲーション", "ko-KR": "기본 탐색", "pt-BR": "Navegação principal",
};

const HISTORY_LABEL: Record<ComposerLanguage, string> = {
  "zh-CN": "会话历史", "en-US": "History", "es-ES": "Historial", "fr-FR": "Historique",
  "de-DE": "Verlauf", "ja-JP": "履歴", "ko-KR": "기록", "pt-BR": "Histórico",
};

export interface AppShellProps {
  language: ComposerLanguage;
  direction: "ltr" | "rtl";
  activeView: ActiveWorkbenchView;
  context?: string;
  historyOpen: boolean;
  onHistory: () => void;
  onNavigate: (view: ActiveWorkbenchView) => void;
  children: ReactNode;
}

/** One identity row, three stable destinations, then the owning surface. */
export function AppShell({ language, direction, activeView, context, historyOpen, onHistory, onNavigate, children }: AppShellProps) {
  const selected = primaryDestinationForRoute(activeView);
  // A workspace literally named "trainer" would read as "Trainer trainer" next
  // to the brand; same name (trimmed, case-insensitive) renders no context.
  const trimmedContext = context?.trim();
  const contextDistinctFromBrand =
    Boolean(trimmedContext) && trimmedContext!.toLowerCase() !== "trainer";
  return (
    <div className="trainer-shell" lang={language} dir={direction} data-text-direction={direction} data-template="AppShell">
      <header className="app-shell-header">
        <div className="app-shell-header__identity">
          <span className="app-shell-header__brand">Trainer</span>
          {contextDistinctFromBrand && trimmedContext ? <span className="app-shell-header__context" title={trimmedContext}>{trimmedContext}</span> : null}
          <div className="app-shell-header__utilities">
            <button type="button" className="app-shell-header__utility" data-testid="trainer-history-toggle" aria-label={HISTORY_LABEL[language]} title={HISTORY_LABEL[language]} aria-expanded={historyOpen} onClick={onHistory}>
              <HistoryIcon size={16} aria-hidden="true" />
            </button>
            <button type="button" className="app-shell-header__utility" data-testid="trainer-view-nav-settings" aria-label={viewLabels[language].settings} title={viewLabels[language].settings} aria-pressed={activeView === "settings"} aria-current={activeView === "settings" ? "page" : undefined} onClick={() => onNavigate("settings")}>
              <SettingsIcon size={16} aria-hidden="true" />
            </button>
          </div>
        </div>
        <nav className="app-shell-nav" aria-label={NAV_LABEL[language]}>
          {PRIMARY_DESTINATIONS.map((view) => (
            <button key={view} type="button" className="app-shell-nav__item" data-testid={`trainer-view-nav-${view}`} aria-label={viewLabels[language][view]} aria-pressed={selected === view} aria-current={selected === view ? "page" : undefined} onClick={() => onNavigate(view)}>
              {viewLabels[language][view]}
            </button>
          ))}
        </nav>
      </header>
      {children}
    </div>
  );
}
