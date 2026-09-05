/**
 * Quick Actions Panel - Easy access to common actions
 *
 * Provides a convenient way for users to access frequently used actions
 * without having to navigate through menus or remember keyboard shortcuts.
 */

import type { ReactNode } from "react";
import {
  SearchIcon,
  SettingsIcon,
  SparklesIcon,
  BookOpenIcon,
  FolderIcon,
  LightningIcon,
  GearIcon,
  PlanIcon,
  ResourcesIcon,
} from "../icons";

export interface QuickActionItem {
  id: string;
  icon?: ReactNode;
  label: string;
  description?: string;
  shortcut?: string[];
  onClick: () => void;
  disabled?: boolean;
  variant?: "default" | "primary" | "danger";
}

export interface QuickActionsPanelProps {
  actions: QuickActionItem[];
  title?: string;
  language: "zh-CN" | "en-US";
  className?: string;
}

export function QuickActionsPanel({
  actions,
  title,
  language,
  className,
}: QuickActionsPanelProps) {
  const isZh = language === "zh-CN";

  return (
    <div className={`quick-actions-panel ${className ?? ""}`}>
      {title && <div className="quick-actions-panel__title">{title}</div>}
      <div className="quick-actions-panel__grid">
        {actions.map((action) => (
          <button
            key={action.id}
            className={`quick-action-btn ${
              action.variant === "primary" ? "quick-action-btn--primary" : ""
            } ${action.disabled ? "quick-action-btn--disabled" : ""}`}
            onClick={action.onClick}
            disabled={action.disabled}
            title={
              action.shortcut
                ? `${action.label}${action.description ? ` - ${action.description}` : ""} [${
                    action.shortcut.join("+")
                  }]`
                : action.label
            }
          >
            {action.icon && <span className="quick-action-btn__icon">{action.icon}</span>}
            <span className="quick-action-btn__label">{action.label}</span>
            {action.shortcut && action.shortcut.length > 0 && (
              <span className="quick-action-btn__shortcut">
                {action.shortcut.map((key, i) => (
                  <kbd key={i} className="quick-action-btn__kbd">
                    {key}
                  </kbd>
                ))}
              </span>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}

/**
 * Pre-defined quick actions for common scenarios
 */
export function getCoachQuickActions(config: {
  language: "zh-CN" | "en-US";
  hasProviderSetup: boolean;
  hasActivePlan: boolean;
  onOpenSettings: () => void;
  onStartChat: () => void;
  onGenerateTraining: () => void;
  onViewResources: () => void;
  onViewPlan: () => void;
}): QuickActionItem[] {
  const { language, hasProviderSetup, hasActivePlan, onOpenSettings, onStartChat, onGenerateTraining, onViewResources, onViewPlan } = config;
  const isZh = language === "zh-CN";

  const actions: QuickActionItem[] = [];

  // Settings (always available)
  actions.push({
    id: "quick-settings",
    icon: <SettingsIcon size={16} />,
    label: isZh ? "设置" : "Settings",
    onClick: onOpenSettings,
  });

  // Start chat (only when provider is set up)
  actions.push({
    id: "quick-chat",
    icon: <SparklesIcon size={16} />,
    label: isZh ? "开始对话" : "Chat",
    onClick: onStartChat,
    disabled: !hasProviderSetup,
    variant: hasProviderSetup ? "primary" : "default",
  });

  // View plan (if there's an active plan)
  if (hasActivePlan) {
    actions.push({
      id: "quick-plan",
      icon: <PlanIcon size={16} />,
      label: isZh ? "查看计划" : "Plan",
      onClick: onViewPlan,
    });
  }

  // Generate training (only when there's a plan)
  actions.push({
    id: "quick-training",
    icon: <LightningIcon size={16} />,
    label: isZh ? "生成训练" : "Train",
    onClick: onGenerateTraining,
    disabled: !hasActivePlan,
  });

  // View resources
  actions.push({
    id: "quick-resources",
    icon: <FolderIcon size={16} />,
    label: isZh ? "资料库" : "Resources",
    onClick: onViewResources,
  });

  return actions;
}

/**
 * Search quick action with integrated search input
 */
export interface SearchQuickActionProps {
  value: string;
  onChange: (value: string) => void;
  onSearch: (query: string) => void;
  placeholder?: string;
  language: "zh-CN" | "en-US";
  className?: string;
}

export function SearchQuickAction({
  value,
  onChange,
  onSearch,
  placeholder,
  language,
  className,
}: SearchQuickActionProps) {
  const isZh = language === "zh-CN";
  const defaultPlaceholder = isZh ? "搜索资料..." : "Search resources...";

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (value.trim()) {
      onSearch(value.trim());
    }
  };

  return (
    <form className={`search-quick-action ${className ?? ""}`} onSubmit={handleSubmit}>
      <div className="search-quick-action__input-wrapper">
        <SearchIcon size={14} className="search-quick-action__icon" />
        <input
          type="text"
          className="search-quick-action__input"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder ?? defaultPlaceholder}
        />
        {value && (
          <button
            type="button"
            className="search-quick-action__clear"
            onClick={() => onChange("")}
            aria-label={isZh ? "清除搜索" : "Clear search"}
          >
            ×
          </button>
        )}
      </div>
    </form>
  );
}

/**
 * Floating action button for mobile/compact views
 */
export interface FloatingActionButtonProps {
  icon?: ReactNode;
  label: string;
  onClick: () => void;
  expanded?: boolean;
  className?: string;
}

export function FloatingActionButton({
  icon,
  label,
  onClick,
  expanded = false,
  className,
}: FloatingActionButtonProps) {
  // Default add icon SVG
  const defaultIcon = (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M10 4v12M4 10h12" />
    </svg>
  );

  return (
    <button
      className={`fab ${expanded ? "fab--expanded" : ""} ${className ?? ""}`}
      onClick={onClick}
      aria-label={label}
    >
      {icon ?? defaultIcon}
      {expanded && <span className="fab__label">{label}</span>}
    </button>
  );
}