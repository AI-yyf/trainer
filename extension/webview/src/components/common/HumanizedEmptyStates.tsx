/**
 * Humanized Empty States
 *
 * Welcoming, instructive empty states that guide users through the application.
 * These states provide context, encourage action, and celebrate progress.
 */

import type { ReactNode } from "react";
import type { ComposerLanguage } from "../../lib/types";
import { humanizedEmptyStatesCopy } from "./humanizedEmptyStatesCopy";
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
  language: ComposerLanguage;
  className?: string;
}

export interface SearchEmptyStateProps {
  query?: string;
  onClearSearch?: () => void;
  onTryDifferentSearch?: () => void;
  language: ComposerLanguage;
  className?: string;
}

export interface LearningEmptyStateProps {
  onImportResources?: () => void;
  onStartLearning?: () => void;
  language: ComposerLanguage;
  className?: string;
}

export interface SettingsEmptyStateProps {
  onConfigure?: () => void;
  language: ComposerLanguage;
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
  return (
    <HumanizedEmptyState
      iconType="sparkles"
      title={humanizedEmptyStatesCopy(language, "准备开始")}
      description={humanizedEmptyStatesCopy(language, "先连接模型，然后发送一个目标。")}
      className={`humanized-empty-state--welcome ${className ?? ""}`}
      actions={
        <div className="humanized-empty-state__button-group">
          {onOpenSettings && (
            <button
              className="humanized-empty-state__action-btn secondary"
              onClick={onOpenSettings}
            >
              {humanizedEmptyStatesCopy(language, "配置模型")}
            </button>
          )}
          {onGetStarted && (
            <button
              className="humanized-empty-state__action-btn primary"
              onClick={onGetStarted}
            >
              {humanizedEmptyStatesCopy(language, "开始")}
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
  return (
    <HumanizedEmptyState
      iconType="search"
      title={humanizedEmptyStatesCopy(language, "没有找到相关结果")}
      description={query
        ? humanizedEmptyStatesCopy(
            language,
            "没有找到与\"{q}\"相关的资料。尝试其他关键词或调整搜索范围。",
          ).replace("{q}", query)
        : humanizedEmptyStatesCopy(language, "试试输入关键词，或者浏览现有的资料库。")
      }
      className={`humanized-empty-state--search ${className ?? ""}`}
      actions={
        <div className="humanized-empty-state__button-group">
          {onClearSearch && (
            <button
              className="humanized-empty-state__action-btn secondary"
              onClick={onClearSearch}
            >
              {humanizedEmptyStatesCopy(language, "清除搜索")}
            </button>
          )}
          {onTryDifferentSearch && (
            <button
              className="humanized-empty-state__action-btn primary"
              onClick={onTryDifferentSearch}
            >
              {humanizedEmptyStatesCopy(language, "尝试其他关键词")}
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
  return (
    <HumanizedEmptyState
      iconType="book"
      title={humanizedEmptyStatesCopy(language, "还没有学习资料")}
      description={humanizedEmptyStatesCopy(language, "导入代码、文档或网页。")}
      className={`humanized-empty-state--learning ${className ?? ""}`}
      actions={
        <div className="humanized-empty-state__button-group">
          {onImportResources && (
            <button
              className="humanized-empty-state__action-btn secondary"
              onClick={onImportResources}
            >
              {humanizedEmptyStatesCopy(language, "导入资料")}
            </button>
          )}
          {onStartLearning && (
            <button
              className="humanized-empty-state__action-btn primary"
              onClick={onStartLearning}
            >
              {humanizedEmptyStatesCopy(language, "开始学习")}
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
  return (
    <HumanizedEmptyState
      iconType="settings"
      title={humanizedEmptyStatesCopy(language, "需要配置")}
      description={humanizedEmptyStatesCopy(
        language,
        "在使用 Trainer 之前，需要先配置你的 provider。请设置 provider、model 和 API key。",
      )}
      className={`humanized-empty-state--settings ${className ?? ""}`}
      actions={
        <div className="humanized-empty-state__button-group">
          {onConfigure && (
            <button
              className="humanized-empty-state__action-btn primary"
              onClick={onConfigure}
            >
              {humanizedEmptyStatesCopy(language, "去配置")}
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
