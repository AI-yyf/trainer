export interface GoalTitleConversationItem {
  id: string;
  role: string;
  body?: string;
}

/**
 * The learner's preceding turn is the goal; the assistant reply is the answer.
 * Fall back to the reply only when the thread has no prior user turn.
 */
export function goalTitleFromConversation(
  conversation: readonly GoalTitleConversationItem[],
  messageId: string,
): string {
  const index = conversation.findIndex((item) => item.id === messageId);
  let source = (index >= 0 ? conversation[index]?.body : "") ?? "";
  for (let cursor = index - 1; cursor >= 0; cursor -= 1) {
    const candidate = conversation[cursor];
    if (candidate?.role === "user" && (candidate.body ?? "").trim()) {
      source = candidate.body ?? "";
      break;
    }
  }
  return (
    source
      .split("\n")
      .map((line) => line.trim())
      .find(Boolean)
      ?.replace(/^[#>*\-\s]+/, "")
      .slice(0, 80) ?? ""
  );
}
