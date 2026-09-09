import type { ComposerLanguage } from "./types";

/**
 * Honest Resources failure categories (same bar as training-return send-state
 * and plan/FSRS explainability). Prefer specific categories over opaque host prose.
 */
export type ResourceFailureCategory =
  | "bad_file"
  | "no_content"
  | "missing"
  | "sidecar_down"
  | "corrupt_pdf"
  | "index_failed"
  | "unknown";

export interface ClassifyResourceFailureInput {
  statusCode?: number;
  message?: string;
  indexStatus?: string;
  qualityFlags?: readonly string[];
  connectionState?: string;
}

export interface ResourceFailureExplainExtras {
  detail?: string;
}

function compact(value?: string): string | undefined {
  const normalized = value?.replace(/\s+/g, " ").trim();
  return normalized ? normalized : undefined;
}

function normalizeFlags(flags: readonly string[] | undefined): string[] {
  return (flags ?? [])
    .map((flag) => flag.trim().toLowerCase())
    .filter((flag) => flag.length > 0);
}

function extractStatusCode(message: string | undefined, statusCode?: number): number | undefined {
  if (typeof statusCode === "number" && Number.isFinite(statusCode) && statusCode > 0) {
    return Math.floor(statusCode);
  }
  const match = message?.match(/\b(?:HTTP\s*)?([45]\d{2})\b/i);
  if (!match?.[1]) {
    return undefined;
  }
  const parsed = Number.parseInt(match[1], 10);
  return Number.isFinite(parsed) ? parsed : undefined;
}

/**
 * Classify a Resources load/index/upload/search failure into an honest category.
 * Specific signals (sidecar down, missing, corrupt/empty content) win over generic index_failed.
 */
export function classifyResourceFailure(
  input: ClassifyResourceFailureInput,
): ResourceFailureCategory {
  const message = compact(input.message) ?? "";
  const lower = message.toLowerCase();
  const flags = normalizeFlags(input.qualityFlags);
  const indexStatus = (input.indexStatus ?? "").trim().toLowerCase();
  const connection = (input.connectionState ?? "").trim().toLowerCase();
  const statusCode = extractStatusCode(message, input.statusCode);

  if (
    connection === "offline" ||
    /econnrefused|enotfound|ehostunreach|enetunreach|network unreachable|fetch failed|sidecar (is )?unavailable|backend is unavailable|trainer backend is unavailable/i.test(
      lower,
    )
  ) {
    return "sidecar_down";
  }

  if (
    flags.includes("corrupt_pdf") ||
    /corrupt(?:ed)?\s*pdf|pdf.{0,40}(corrupt|damaged|invalid|unreadable)|invalid pdf/i.test(message)
  ) {
    return "corrupt_pdf";
  }

  if (
    statusCode === 404 ||
    /could not be found|does not exist|not found|resource[_ -]?missing|missing (?:path|resource|file|id)/i.test(
      lower,
    )
  ) {
    return "missing";
  }

  if (statusCode === 400 && /missing|not found|does not exist/i.test(lower)) {
    return "missing";
  }

  const hasNoContent =
    flags.includes("no_content") ||
    /\bno_content\b|no usable content|empty content|empty file/i.test(lower);

  if (hasNoContent) {
    if (/bad[_ -]?file|empty (?:file|content)|unusable (?:file|content)/i.test(lower)) {
      return "bad_file";
    }
    // Empty / fail-closed corrupt content surfaces as no_content in smoke.
    return "no_content";
  }

  if (/bad[_ -]?file|empty (?:file|content)|unusable (?:file|content)/i.test(lower)) {
    return "bad_file";
  }

  if (indexStatus === "failed" || /index(?:ing)? failed|failed to index|index_status[=:]failed/i.test(lower)) {
    return "index_failed";
  }

  return "unknown";
}

/**
 * Localized, actionable Resources failure copy. Never claims the resource is available.
 */
export function describeResourceFailureState(
  language: ComposerLanguage,
  category: ResourceFailureCategory,
  extras?: ResourceFailureExplainExtras,
): { tone: "info" | "error"; message: string } {
  const zh = language === "zh-CN";
  const detail = compact(extras?.detail);
  const withDetail = (base: string): string => (detail ? `${base}${zh ? "" : " "}(${detail})` : base);

  switch (category) {
    case "bad_file":
      return {
        tone: "error",
        message: withDetail(
          zh
            ? "资料文件无效或内容为空，索引失败，没有可用内容。请检查文件后重新导入。"
            : "The resource file is empty or unusable. Indexing failed with no usable content. Check the file and import again.",
        ),
      };
    case "no_content":
      return {
        tone: "error",
        message: withDetail(
          zh
            ? "索引失败：没有可用内容。请打开来源检查，或刷新索引后重试。"
            : "Indexing failed: no usable content. Open the source to check it, or refresh the index and try again.",
        ),
      };
    case "missing":
      return {
        tone: "error",
        message: withDetail(
          zh
            ? "找不到这份资料（资源不存在）。请确认路径或编号后重试。"
            : "Resource not found. Confirm the path or id, then try again.",
        ),
      };
    case "sidecar_down":
      return {
        tone: "error",
        message: withDetail(
          zh
            ? "资料服务（sidecar）暂时连不上。请恢复或重启 sidecar 后再试。"
            : "The Resources sidecar is unreachable. Restore or restart the sidecar, then try again.",
        ),
      };
    case "corrupt_pdf":
      return {
        tone: "error",
        message: withDetail(
          zh
            ? "PDF 损坏或无法解析，索引失败，没有可用内容。请更换文件后重试。"
            : "The PDF is corrupt or unreadable. Indexing failed with no usable content. Replace the file and try again.",
        ),
      };
    case "index_failed":
      return {
        tone: "error",
        message: withDetail(
          zh
            ? "资料索引失败，还不能当成功来源使用。请刷新索引后重试。"
            : "Resource indexing failed. It is not a successful source yet. Refresh the index and try again.",
        ),
      };
    case "unknown":
    default:
      return {
        tone: "error",
        message: withDetail(
          zh
            ? "资料操作未完成。请检查文件与 sidecar 后重试。"
            : "The resource operation did not finish. Check the file and sidecar, then try again.",
        ),
      };
  }
}
