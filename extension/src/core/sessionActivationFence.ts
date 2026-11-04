/**
 * Session activation identity fence.
 *
 * A stored-session restore (`/session/activate`) can be in flight while the
 * user starts a new chat or selects another conversation. The request that
 * started first must never overwrite the newer user decision. This module is
 * the single generation counter shared by the restore path and the commands
 * that own the visible session.
 */
const generations = new WeakMap<object, { latest: number }>();

export function bumpSessionActivationGeneration(context: object): number {
  const state = generations.get(context) ?? { latest: 0 };
  state.latest += 1;
  generations.set(context, state);
  return state.latest;
}

export function currentSessionActivationGeneration(context: object): number {
  return generations.get(context)?.latest ?? 0;
}

export function isCurrentSessionActivation(context: object, generation: number): boolean {
  return currentSessionActivationGeneration(context) === generation;
}
