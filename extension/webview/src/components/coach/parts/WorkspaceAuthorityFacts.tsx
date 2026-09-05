import type { ComposerLanguage } from "../../../lib/types";
import type { WorkspaceAuthoritySummaryView } from "../../../../../../shared/src/workspaceAuthority";

function text(language: ComposerLanguage, zh: string, en: string): string {
  return language === "zh-CN" ? zh : en;
}

export interface WorkspaceAuthorityFactsProps {
  language: ComposerLanguage;
  summary: WorkspaceAuthoritySummaryView;
  sandboxRootPath?: string | null;
  className?: string;
  fallbackText?: string;
}

export function WorkspaceAuthorityFacts({
  language,
  summary,
  sandboxRootPath,
  className,
  fallbackText,
}: WorkspaceAuthorityFactsProps) {
  return (
    <div className={["sandbox-panel__guide-facts", className].filter(Boolean).join(" ")}>
      <span>{summary.root}</span>
      <span>{summary.sourceDetail || summary.source}</span>
      <span>
        {summary.permission}
        {summary.permissionDetail ? ` · ${summary.permissionDetail}` : ""}
      </span>
      <span>{summary.countsText}</span>
      <span>{sandboxRootPath || fallbackText || text(language, "未配置", "Unconfigured")}</span>
      <span>{summary.trashRoot || fallbackText || text(language, "未配置", "Unconfigured")}</span>
    </div>
  );
}
