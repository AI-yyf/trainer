export interface SearchHitTeachingSummary {
  title: string;
  source?: string;
  projectScope?: string;
  sourceType?: string;
  indexState?: string;
  trustState?: string;
  trustScore?: number;
  freshness?: string;
  citationId?: string;
  rankScore?: number;
  matchSummary?: string;
  previewTier?: "rich" | "converted" | "metadata";
  previewKind?: string;
  matchedFields?: string[];
  canInjectTrainingCard: boolean;
  reasons: string[];
}

export type ResourceSearchMode = "lexical" | "trusted";

export interface ResourceSearchModeRequest {
  trustState?: string;
  indexState?: string;
}

export function normalizeResourceSearchMode(
  value: unknown,
  fallback: ResourceSearchMode = "lexical",
): ResourceSearchMode {
  if (value === "trusted" || value === "lexical") {
    return value;
  }
  if (value === "semantic" || value === "coach") {
    return "lexical";
  }
  return fallback;
}

type UnknownRecord = Record<string, unknown>;

export function resourceSearchModeRequest(mode: ResourceSearchMode): ResourceSearchModeRequest {
  switch (mode) {
    case "trusted":
      return {
        trustState: "trusted",
        indexState: "indexed",
      };
    case "lexical":
    default:
      return {};
  }
}

export function resourceSearchModeLabel(
  mode: ResourceSearchMode,
  language: "en" | "zh" = "en",
): string {
  if (language === "zh") {
    switch (mode) {
      case "trusted":
        return "可信且已索引";
      case "lexical":
      default:
        return "全文检索";
    }
  }

  switch (mode) {
    case "trusted":
      return "Trusted and indexed";
    case "lexical":
    default:
      return "Full-text search";
  }
}

export function resourceSearchModeHint(
  mode: ResourceSearchMode,
  language: "en" | "zh" = "en",
): string {
  if (language === "zh") {
    switch (mode) {
      case "trusted":
        return "只搜索已索引且标记为可信的资料。";
      case "lexical":
      default:
        return "在已索引资料中执行全文检索，并使用可用的元数据排序。";
    }
  }

  switch (mode) {
    case "trusted":
      return "Search only material that is indexed and marked trusted.";
    case "lexical":
    default:
      return "Search indexed resource text and use available metadata for ranking.";
  }
}

export function summarizeSearchHitTeachingSignal(hit: unknown): SearchHitTeachingSummary | undefined {
  const record = asRecord(hit);
  if (!record) {
    return undefined;
  }

  const title =
    asString(record.title) ??
    asString(record.name) ??
    asString(record.resource_title) ??
    asString(record.resourceTitle);
  if (!title) {
    return undefined;
  }

  const projectScope =
    asString(record.project_scope) ??
    asString(record.projectScope) ??
    asString(record.workspace_id) ??
    asString(record.workspaceId);
  const source = asString(record.source) ?? asString(record.path) ?? asString(record.sourcePath);
  const sourceType = asString(record.source_type) ?? asString(record.sourceType);
  const indexState = asString(record.index_state) ?? asString(record.indexState);
  const trustState = asString(record.trust_state) ?? asString(record.trustState);
  const trustScore = asNumber(record.trust_score) ?? asNumber(record.trustScore);
  const freshness = asString(record.freshness);
  const citationId = asString(record.citation_id) ?? asString(record.citationId);
  const rankScore = asNumber(record.rank_score) ?? asNumber(record.rankScore);
  const matchSummary = asString(record.match_summary) ?? asString(record.matchSummary);
  const previewTier = asPreviewTier(record.preview_tier) ?? asPreviewTier(record.previewTier);
  const previewKind = asString(record.preview_kind) ?? asString(record.previewKind);
  const matchedFields = asStringArray(record.matched_fields ?? record.matchedFields);
  const canInjectTrainingCard =
    asBoolean(record.can_inject_training_card) ?? asBoolean(record.canInjectTrainingCard) ?? false;
  const reasons = asStringArray(record.rank_reasons ?? record.rankReasons ?? record.reasons);

  return {
    title,
    source: source || undefined,
    projectScope: projectScope || undefined,
    sourceType: sourceType || undefined,
    indexState: indexState || undefined,
    trustState: trustState || undefined,
    trustScore,
    freshness: freshness || undefined,
    citationId: citationId || undefined,
    rankScore,
    matchSummary: matchSummary || undefined,
    previewTier,
    previewKind,
    matchedFields: matchedFields.length > 0 ? matchedFields : undefined,
    canInjectTrainingCard,
    reasons,
  };
}

export function formatSearchHitTeachingSummary(
  hit: unknown,
  language: "en" | "zh" = "en",
): string | undefined {
  const summary = summarizeSearchHitTeachingSignal(hit);
  if (!summary) {
    return undefined;
  }

  const evidenceParts: string[] = [];
  if (summary.source) {
    evidenceParts.push(language === "zh" ? `来源 ${summary.source}` : `source ${summary.source}`);
  }
  if (summary.projectScope) {
    evidenceParts.push(language === "zh" ? `项目 ${summary.projectScope}` : `project ${summary.projectScope}`);
  }
  if (summary.sourceType) {
    evidenceParts.push(language === "zh" ? `来源类型 ${summary.sourceType}` : `source type ${summary.sourceType}`);
  }
  if (summary.trustState) {
    const trustLabel =
      summary.trustState +
      (typeof summary.trustScore === "number" ? ` ${Math.round(summary.trustScore * 100)}%` : "");
    evidenceParts.push(language === "zh" ? `信任 ${trustLabel}` : `trust ${trustLabel}`);
  }
  if (summary.indexState) {
    evidenceParts.push(language === "zh" ? `索引 ${summary.indexState}` : `index ${summary.indexState}`);
  }
  if (summary.freshness) {
    evidenceParts.push(language === "zh" ? `新鲜度 ${summary.freshness}` : `freshness ${summary.freshness}`);
  }
  const previewSummary = formatPreviewTeachingSummary(summary.previewTier, summary.previewKind, language);
  if (previewSummary) {
    evidenceParts.push(previewSummary);
  }
  if (summary.citationId) {
    evidenceParts.push(language === "zh" ? `引用 ${summary.citationId}` : `citation ${summary.citationId}`);
  }
  if (typeof summary.rankScore === "number") {
    evidenceParts.push(language === "zh" ? `排序 ${summary.rankScore.toFixed(2)}` : `rank ${summary.rankScore.toFixed(2)}`);
  }
  if (summary.canInjectTrainingCard) {
    evidenceParts.push(language === "zh" ? "可注入训练卡" : "injectable training card");
  }
  if (summary.matchedFields && summary.matchedFields.length > 0) {
    const matchedFields = summary.matchedFields.slice(0, 4);
    evidenceParts.push(language === "zh" ? `命中 ${matchedFields.join(", ")}` : `matched ${matchedFields.join(", ")}`);
  }

  const reasons = summary.reasons.slice(0, 3);
  const prefix = language === "zh" ? `命中首项: ${summary.title}` : `Top hit: ${summary.title}`;
  const evidence =
    evidenceParts.length > 0 ? ` [${evidenceParts.join(language === "zh" ? " · " : " · ")}]` : "";
  const matchSummaryText = summary.matchSummary
    ? language === "zh"
      ? `; 命中摘要: ${summary.matchSummary}`
      : `; match summary: ${summary.matchSummary}`
    : "";
  const reasonText =
    reasons.length > 0
      ? language === "zh"
        ? `; 原因: ${reasons.join(", ")}`
        : `; reasons: ${reasons.join(", ")}`
      : "";

  return `${prefix}${evidence}${matchSummaryText}${reasonText}`;
}

export function formatResourceSearchStatusSummary(
  params: {
    hitCount: number;
    mode: ResourceSearchMode;
    topHit?: unknown;
  },
  language: "en" | "zh" = "en",
): string {
  const countLabel =
    language === "zh"
      ? `全文检索命中 ${params.hitCount} 条 · ${resourceSearchModeLabel(params.mode, "zh")}`
      : `${params.hitCount} full-text hits · ${resourceSearchModeLabel(params.mode, "en")}`;
  const topHitSummary = params.topHit ? formatSearchHitTeachingSummary(params.topHit, language) : undefined;
  return topHitSummary ? `${countLabel} · ${topHitSummary}` : countLabel;
}

function asRecord(value: unknown): UnknownRecord | undefined {
  return value && typeof value === "object" ? (value as UnknownRecord) : undefined;
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function asBoolean(value: unknown): boolean | undefined {
  return typeof value === "boolean" ? value : undefined;
}

function asNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string" && item.trim().length > 0)
    : [];
}

function asPreviewTier(value: unknown): "rich" | "converted" | "metadata" | undefined {
  const tier = asString(value);
  return tier === "rich" || tier === "converted" || tier === "metadata" ? tier : undefined;
}

function formatPreviewTeachingSummary(
  previewTier: "rich" | "converted" | "metadata" | undefined,
  previewKind: string | undefined,
  language: "en" | "zh",
): string | undefined {
  const parts: string[] = [];
  if (previewTier) {
    parts.push(language === "zh" ? previewTierLabelZh(previewTier) : previewTierLabelEn(previewTier));
  }
  if (previewKind) {
    parts.push(language === "zh" ? previewKindLabelZh(previewKind) : previewKindLabelEn(previewKind));
  }
  if (!parts.length) {
    return undefined;
  }
  return language === "zh" ? `预览 ${parts.join(" · ")}` : `preview ${parts.join(" · ")}`;
}

function previewTierLabelEn(tier: "rich" | "converted" | "metadata"): string {
  if (tier === "rich") {
    return "Tier A";
  }
  if (tier === "converted") {
    return "Tier B";
  }
  return "Tier C";
}

function previewTierLabelZh(tier: "rich" | "converted" | "metadata"): string {
  if (tier === "rich") {
    return "Tier A · 富预览";
  }
  if (tier === "converted") {
    return "Tier B · 转换预览";
  }
  return "Tier C · 元数据回退";
}

function previewKindLabelEn(kind: string): string {
  const labels: Record<string, string> = {
    markdown: "Markdown",
    code: "Code",
    table: "Table",
    document: "Document",
    notebook: "Notebook",
    image: "Image",
    audio: "Audio",
    video: "Video",
    archive: "Archive",
    "structured-text": "Structured text",
    markup: "Markup",
    text: "Text",
    directory: "Directory",
  };
  return labels[kind] ?? kind;
}

function previewKindLabelZh(kind: string): string {
  const labels: Record<string, string> = {
    markdown: "Markdown",
    code: "代码",
    table: "表格",
    document: "文档",
    notebook: "Notebook",
    image: "图片",
    audio: "音频",
    video: "视频",
    archive: "压缩包",
    "structured-text": "结构化文本",
    markup: "标记文本",
    text: "文本",
    directory: "目录",
  };
  return labels[kind] ?? kind;
}
