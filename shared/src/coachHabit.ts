export interface CoachHabit {
  text: string;
  enabled: boolean;
  source: "learner" | "settings";
}

export type CoachHabitChange =
  | { action: "save"; text: string }
  | { action: "enable" | "disable" | "forget" };

export function readCoachHabit(value: unknown): CoachHabit | null | undefined {
  if (value === null) return null;
  if (!value || typeof value !== "object") return undefined;
  const record = value as Record<string, unknown>;
  if (
    typeof record.text !== "string" || !record.text.trim() ||
    typeof record.enabled !== "boolean" ||
    (record.source !== "learner" && record.source !== "settings")
  ) return undefined;
  return { text: record.text, enabled: record.enabled, source: record.source };
}

export function readCoachHabitChange(value: unknown): CoachHabitChange | undefined {
  if (!value || typeof value !== "object") return undefined;
  const record = value as Record<string, unknown>;
  const { action } = record;
  if (action === "save" && typeof record.text === "string") {
    const text = record.text.trim();
    if (text && Array.from(text).length <= 240) return { action, text };
  }
  if (action === "enable" || action === "disable" || action === "forget") return { action };
  return undefined;
}
