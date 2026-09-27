/**
 * Share utilities for coach messages (§四十八: extracted from App.tsx).
 * Pure functions — no React or state dependencies.
 */

import type { ComposerLanguage, ConversationMessage } from "./types";

export function coachReplyTitle(
  message: ConversationMessage,
  language: ComposerLanguage,
): string {
  const firstLine = message.body
    .split("\n")
    .map((line) => line.replace(/^[#>*`\-\s]+/, "").trim())
    .find((line) => line.length > 0);
  const fallback = language === "zh-CN" ? "\u6559\u7ec3\u56de\u590d" : "Coach reply";
  if (!firstLine) {
    return fallback;
  }
  return firstLine.length > 48 ? `${firstLine.slice(0, 48)}\u2026` : firstLine;
}

export function coachReplyMarkdown(
  message: ConversationMessage,
  language: ComposerLanguage,
): { title: string; markdown: string } {
  const zh = language === "zh-CN";
  const title = coachReplyTitle(message, language);
  const sections = [`# ${title}`, ""];
  if (message.body.trim()) {
    sections.push(message.body.trim(), "");
  }
  const artifacts = message.artifacts ?? [];
  if (artifacts.length > 0) {
    sections.push(zh ? "## \u4ea7\u7269" : "## Artifacts");
    for (const artifact of artifacts) {
      const detail = artifact.summary ?? artifact.teaser ?? "";
      sections.push(`- **${artifact.title}**${detail ? ` \u2014 ${detail}` : ""}`);
    }
    sections.push("");
  }
  const attachments = message.attachments ?? [];
  if (attachments.length > 0) {
    sections.push(zh ? "## \u5f15\u7528" : "## References");
    for (const attachment of attachments) {
      sections.push(`- ${attachment.label}: ${attachment.value}`);
    }
    sections.push("");
  }
  return { title, markdown: sections.join("\n").trim() };
}
