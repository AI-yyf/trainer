const authoredTextFields = [
  "title", "whyNow", "targetSkill", "focusArea", "scenarioPack", "scenario",
  "problemStatement", "suggestedWorkspaceAction", "deliverable",
  "validationMethod", "verificationMethod", "successSignal", "returnWith",
  "nextAfterCompletion", "fallbackAction", "stuckRecovery", "reflectionPrompt",
] as const;

const authoredListFields = [
  "apiHints", "constraints", "selfCheck", "filesToTouch", "learnerDeliverables",
  "verificationSteps", "acceptanceCriteria", "hintLadder", "commonMistakes",
  "expectedSymbols",
] as const;

type TextField = typeof authoredTextFields[number];
type ListField = typeof authoredListFields[number];

export type BoundTrainingCardSource = Readonly<{ cardId?: string }> &
  Readonly<Partial<Record<TextField, string>>> &
  Readonly<Partial<Record<ListField, readonly string[]>>>;

export interface BoundTrainingCardFacts {
  readonly cardId: string;
  readonly text: Readonly<Partial<Record<TextField, string>>>;
  readonly lists: Readonly<Partial<Record<ListField, string[]>>>;
}

function nonblank(value: string | undefined): string | undefined {
  // Whitespace is only an eligibility check; authored content stays intact.
  return value?.trim() ? value : undefined;
}

function nonempty(value: readonly string[] | undefined): string[] | undefined {
  return value?.some(item => item.trim()) ? [...value] : undefined;
}

/**
 * Presentation facts from an already eligible active card. The caller owns
 * runtime/restore/review freshness; this helper never infers identity from a
 * title, ambient focus, or a legacy selected-card scalar. Authored content is
 * independent of the UI locale. Each field uses the matching candidate first,
 * then the matching route card, without mixing in foreign card facts. A
 * returned object remains authoritative even when all its fields are absent;
 * absence of a field never permits borrowing from an unbound card.
 */
export function resolveBoundTrainingCardFacts(input: {
  eligible: boolean;
  activeCardId?: string;
  candidate?: BoundTrainingCardSource;
  routeCard?: BoundTrainingCardSource;
}): BoundTrainingCardFacts | undefined {
  const { activeCardId } = input;
  if (!input.eligible || !activeCardId?.trim()) return undefined;
  const candidate = input.candidate?.cardId === activeCardId ? input.candidate : undefined;
  const routeCard = input.routeCard?.cardId === activeCardId ? input.routeCard : undefined;
  if (!candidate && !routeCard) return undefined;

  const text: Partial<Record<TextField, string>> = {};
  const lists: Partial<Record<ListField, string[]>> = {};
  for (const field of authoredTextFields) {
    const value = nonblank(candidate?.[field]) ?? nonblank(routeCard?.[field]);
    if (value !== undefined) text[field] = value;
  }
  for (const field of authoredListFields) {
    const value = nonempty(candidate?.[field]) ?? nonempty(routeCard?.[field]);
    if (value !== undefined) lists[field] = value;
  }
  return { cardId: activeCardId, text, lists };
}

/** Missing fields on a bound card stay missing; legacy sources are lazy. */
export function readTrainingCardText(
  facts: BoundTrainingCardFacts | undefined,
  field: TextField,
  legacy: () => string | undefined,
): string | undefined {
  return facts ? facts.text[field] : legacy();
}

export function readTrainingCardList(
  facts: BoundTrainingCardFacts | undefined,
  field: ListField,
  legacy: () => string[],
): string[] {
  return facts ? facts.lists[field] ?? [] : legacy();
}
