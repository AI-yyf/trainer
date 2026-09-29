import type { ComposerLanguage } from "../../../lib/types";
import type { WorkspaceAuthoritySummaryView } from "../../../../../../shared/src/workspaceAuthority";

/** §十五: facts-row copy in eight languages (no zh/en binary); zh-CN string is the key. */
const WORKSPACE_AUTHORITY_FACTS_TEXT: Record<string, Record<string, string>> = {
  "未配置": {
    "en-US": "Unconfigured",
    "es-ES": "Sin configurar",
    "fr-FR": "Non configuré",
    "de-DE": "Nicht konfiguriert",
    "ja-JP": "未設定",
    "ko-KR": "미설정",
    "pt-BR": "Não configurado",
  },
};

function text(language: ComposerLanguage, key: string): string {
  return WORKSPACE_AUTHORITY_FACTS_TEXT[key]?.[language] ?? key;
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
      <span>{sandboxRootPath || fallbackText || text(language, "未配置")}</span>
      <span>{summary.trashRoot || fallbackText || text(language, "未配置")}</span>
    </div>
  );
}
