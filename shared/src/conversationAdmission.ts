import { learnerActionText } from "./learnerInstructions";

/** First contact may read and discuss a project before the library is bound. */
export function canConverseBeforeAdmission(status: string | undefined, payload: unknown): boolean {
  if (status !== "root-missing" && status !== "project-found") return false;
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return false;
  const request = payload as Record<string, unknown>;
  if (typeof request.text !== "string" || !request.text.trim()) return false;
  if ((request.intent && request.intent !== "coach") || request.formalPlanMutation === true ||
      request.goalMode === true || request.resourceComposerIntent || request.activeView === "resources") return false;
  // Explicit asset writes still bind the library first. Quoted text and
  // questions about saving do not constitute a request to create an asset.
  return !/保存|存下|落盘|写入|记录|\b(?:save|persist|record|write)\b/iu.test(learnerActionText(request.text));
}
