import type { ComposerLanguage } from "./types";
import {
  compactNarrowSidebarList,
  compactNarrowSidebarText,
  normalizeNarrowSidebarCopy,
  summarizeNarrowSidebarLead,
} from "./trainingCardCopy";

export interface CoachReturnCopy {
  title?: string;
  detail?: string;
  summaryLines: string[];
}

export function normalizeCoachReturnCopy(
  language: ComposerLanguage,
  input: {
    title?: string;
    detail?: string;
    summaryLines?: readonly string[];
  },
): CoachReturnCopy {
  const title =
    compactNarrowSidebarText(language, input.title, { maxLength: 54 }) ??
    normalizeNarrowSidebarCopy(language, input.title);
  const detail = summarizeNarrowSidebarLead(language, input.detail, { maxLength: 86 });
  const summaryLines = compactNarrowSidebarList(language, input.summaryLines, {
    maxItems: 3,
    maxLength: 72,
  });
  return { title, detail, summaryLines };
}
