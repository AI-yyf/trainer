/**
 * Humanized Empty States
 *
 * Welcoming, instructive empty states that guide users through the application.
 * These states provide context, encourage action, and celebrate progress.
 */

import type { ReactNode } from "react";
import {
  SparklesIcon,
  SearchIcon,
  BookOpenIcon,
  SettingsIcon,
  LightBulbIcon,
  CompassIcon,
  TrophyIcon,
} from "../icons";

export interface EmptyStateProps {
  icon?: ReactNode;
  iconType?: "sparkles" | "search" | "book" | "settings" | "lightbulb" | "compass" | "trophy";
  title: string;
  description?: string;
  actions?: ReactNode;
  suggestions?: ReactNode;
  className?: string;
}

export interface WelcomeEmptyStateProps {
  onGetStarted?: () => void;
  onOpenSettings?: () => void;
  language: "zh-CN" | "en-US";
  className?: string;
}

export interface SearchEmptyStateProps {
  query?: string;
  onClearSearch?: () => void;
  onTryDifferentSearch?: () => void;
  language: "zh-CN" | "en-US";
  className?: string;
}

export interface LearningEmptyStateProps {
  onImportResources?: () => void;
  onStartLearning?: () => void;
  language: "zh-CN" | "en-US";
  className?: string;
}

export interface SettingsEmptyStateProps {
  onConfigure?: () => void;
  language: "zh-CN" | "en-US";
  className?: string;
}

export interface ProgressiveHintProps {
  message: string;
  type?: "info" | "warning" | "tip" | "success";
  onDismiss?: () => void;
  onAction?: () => void;
  actionLabel?: string;
  className?: string;
}

/**
 * Main empty state component with flexible customization
 */
export function HumanizedEmptyState({
  icon,
  iconType,
  title,
  description,
  actions,
  suggestions,
  className,
}: EmptyStateProps) {
  const getDefaultIcon = (type?: string): ReactNode => {
    const iconMap: Record<string, ReactNode> = {
      sparkles: <SparklesIcon size={28} />,
      search: <SearchIcon size={28} />,
      book: <BookOpenIcon size={28} />,
      settings: <SettingsIcon size={28} />,
      lightbulb: <LightBulbIcon size={28} />,
      compass: <CompassIcon size={28} />,
      trophy: <TrophyIcon size={28} />,
    };
    return type ? iconMap[type] : <SparklesIcon size={28} />;
  };

  return (
    <div className={`humanized-empty-state ${className ?? ""}`}>
      <div className="humanized-empty-state__icon-container">
        {icon ?? getDefaultIcon(iconType)}
      </div>
      <h3 className="humanized-empty-state__title">{title}</h3>
      {description && (
        <p className="humanized-empty-state__description">{description}</p>
      )}
      {actions && (
        <div className="humanized-empty-state__actions">
          {actions}
        </div>
      )}
      {suggestions && (
        <ul className="humanized-empty-state__suggestions">
          {suggestions}
        </ul>
      )}
    </div>
  );
}

/**
 * Welcome empty state for first-time users
 */
export function WelcomeEmptyState({
  onGetStarted,
  onOpenSettings,
  language,
  className,
}: WelcomeEmptyStateProps) {
  const isZh = language === "zh-CN";

  return (
    <HumanizedEmptyState
      iconType="sparkles"
      title={isZh ? "准备开始" : "Ready to start"}
      description={isZh
        ? "先连接模型，然后发送一个目标。"
        : "Connect a model, then send a goal."
      }
      className={`humanized-empty-state--welcome ${className ?? ""}`}
      actions={
        <div className="humanized-empty-state__button-group">
          {onOpenSettings && (
            <button
              className="humanized-empty-state__action-btn secondary"
              onClick={onOpenSettings}
            >
              {isZh ? "配置模型" : "Configure Model"}
            </button>
          )}
          {onGetStarted && (
            <button
              className="humanized-empty-state__action-btn primary"
              onClick={onGetStarted}
            >
              {isZh ? "开始" : "Start"}
            </button>
          )}
        </div>
      }
    />
  );
}

/**
 * Search empty state for when no results are found
 */
export function SearchEmptyState({
  query,
  onClearSearch,
  onTryDifferentSearch,
  language,
  className,
}: SearchEmptyStateProps) {
  const isZh = language === "zh-CN";

  return (
    <HumanizedEmptyState
      iconType="search"
      title={isZh ? "没有找到相关结果" : "No results found"}
      description={query
        ? isZh
          ? `没有找到与"${query}"相关的资料。尝试其他关键词或调整搜索范围。`
          : `No results for "${query}". Try different keywords or adjust your search.`
        : isZh
        ? "试试输入关键词，或者浏览现有的资料库。"
        : "Try searching for a keyword, or browse your existing resources."
      }
      className={`humanized-empty-state--search ${className ?? ""}`}
      actions={
        <div className="humanized-empty-state__button-group">
          {onClearSearch && (
            <button
              className="humanized-empty-state__action-btn secondary"
              onClick={onClearSearch}
            >
              {isZh ? "清除搜索" : "Clear Search"}
            </button>
          )}
          {onTryDifferentSearch && (
            <button
              className="humanized-empty-state__action-btn primary"
              onClick={onTryDifferentSearch}
            >
              {isZh ? "尝试其他关键词" : "Try Different Keywords"}
            </button>
          )}
        </div>
      }
    />
  );
}

/**
 * Learning empty state for when no resources are imported
 */
export function LearningEmptyState({
  onImportResources,
  onStartLearning,
  language,
  className,
}: LearningEmptyStateProps) {
  const isZh = language === "zh-CN";

  return (
    <HumanizedEmptyState
      iconType="book"
      title={isZh ? "还没有学习资料" : "No learning materials yet"}
      description={isZh
        ? "导入代码、文档或网页。"
        : "Import code, docs, or web pages."
      }
      className={`humanized-empty-state--learning ${className ?? ""}`}
      actions={
        <div className="humanized-empty-state__button-group">
          {onImportResources && (
            <button
              className="humanized-empty-state__action-btn secondary"
              onClick={onImportResources}
            >
              {isZh ? "导入资料" : "Import Resources"}
            </button>
          )}
          {onStartLearning && (
            <button
              className="humanized-empty-state__action-btn primary"
              onClick={onStartLearning}
            >
              {isZh ? "开始学习" : "Start Learning"}
            </button>
          )}
        </div>
      }
    />
  );
}

/**
 * Settings empty state for when provider is not configured
 */
export function SettingsEmptyState({
  onConfigure,
  language,
  className,
}: SettingsEmptyStateProps) {
  const isZh = language === "zh-CN";

  return (
    <HumanizedEmptyState
      iconType="settings"
      title={isZh ? "需要配置" : "Configuration Required"}
      description={isZh
        ? "在使用 Trainer 之前，需要先配置你的 provider。请设置 provider、model 和 API key。"
        : "Before using Trainer, you need to configure your provider. Please set up your provider, model, and API key."
      }
      className={`humanized-empty-state--settings ${className ?? ""}`}
      actions={
        <div className="humanized-empty-state__button-group">
          {onConfigure && (
            <button
              className="humanized-empty-state__action-btn primary"
              onClick={onConfigure}
            >
              {isZh ? "去配置" : "Configure"}
            </button>
          )}
        </div>
      }
    />
  );
}

/**
 * Progressive hint component for contextual tips
 */
export function ProgressiveHint({
  message,
  type = "info",
  onDismiss,
  onAction,
  actionLabel,
  className,
}: ProgressiveHintProps) {
  const typeIcon: Record<string, ReactNode> = {
    info: <SparklesIcon size={14} />,
    warning: <LightBulbIcon size={14} />,
    tip: <CompassIcon size={14} />,
    success: <TrophyIcon size={14} />,
  };

  return (
    <div className={`progressive-hint progressive-hint--${type} ${className ?? ""}`}>
      <span className="progressive-hint__icon">
        {typeIcon[type]}
      </span>
      <span className="progressive-hint__message">{message}</span>
      {onAction && actionLabel && (
        <button
          className="progressive-hint__action"
          onClick={onAction}
        >
          {actionLabel}
        </button>
      )}
      {onDismiss && (
        <button
          className="progressive-hint__dismiss"
          onClick={onDismiss}
          aria-label="Dismiss"
        >
          ×
        </button>
      )}
    </div>
  );
}
