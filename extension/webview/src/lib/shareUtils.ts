/**
 * Share utilities for coach messages (§四十八: extracted from App.tsx).
 * Pure functions — no React or state dependencies.
 */

import type { ComposerLanguage, ConversationMessage } from "./types";

/** §十五: share/export copy in eight languages (no zh/en binary). */
const SHARE_TEXT: Record<ComposerLanguage, { titleFallback: string; artifactsHeading: string; referencesHeading: string }> = {
  "zh-CN": { titleFallback: "教练回复", artifactsHeading: "## 产物", referencesHeading: "## 引用" },
  "en-US": { titleFallback: "Coach reply", artifactsHeading: "## Artifacts", referencesHeading: "## References" },
  "es-ES": { titleFallback: "Respuesta del coach", artifactsHeading: "## Productos", referencesHeading: "## Referencias" },
  "fr-FR": { titleFallback: "Réponse du coach", artifactsHeading: "## Produits", referencesHeading: "## Références" },
  "de-DE": { titleFallback: "Coach-Antwort", artifactsHeading: "## Artefakte", referencesHeading: "## Referenzen" },
  "ja-JP": { titleFallback: "コーチの回答", artifactsHeading: "## 生成物", referencesHeading: "## 参照" },
  "ko-KR": { titleFallback: "코치 답변", artifactsHeading: "## 산출물", referencesHeading: "## 참조" },
  "pt-BR": { titleFallback: "Resposta do coach", artifactsHeading: "## Produtos", referencesHeading: "## Referências" },
};

function shareCopy(language: ComposerLanguage) {
  return SHARE_TEXT[language] ?? SHARE_TEXT["en-US"];
}

export function coachReplyTitle(
  message: ConversationMessage,
  language: ComposerLanguage,
): string {
  const firstLine = message.body
    .split("\n")
    .map((line) => line.replace(/^[#>*`\-\s]+/, "").trim())
    .find((line) => line.length > 0);
  const fallback = shareCopy(language).titleFallback;
  if (!firstLine) {
    return fallback;
  }
  return firstLine.length > 48 ? `${firstLine.slice(0, 48)}\u2026` : firstLine;
}

export function coachReplyMarkdown(
  message: ConversationMessage,
  language: ComposerLanguage,
): { title: string; markdown: string } {
  const copy = shareCopy(language);
  const title = coachReplyTitle(message, language);
  const sections = [`# ${title}`, ""];
  if (message.body.trim()) {
    sections.push(message.body.trim(), "");
  }
  const artifacts = message.artifacts ?? [];
  if (artifacts.length > 0) {
    sections.push(copy.artifactsHeading);
    for (const artifact of artifacts) {
      const detail = artifact.summary ?? artifact.teaser ?? "";
      sections.push(`- **${artifact.title}**${detail ? ` \u2014 ${detail}` : ""}`);
    }
    sections.push("");
  }
  const attachments = message.attachments ?? [];
  if (attachments.length > 0) {
    sections.push(copy.referencesHeading);
    for (const attachment of attachments) {
      sections.push(`- ${attachment.label}: ${attachment.value}`);
    }
    sections.push("");
  }
  return { title, markdown: sections.join("\n").trim() };
}
