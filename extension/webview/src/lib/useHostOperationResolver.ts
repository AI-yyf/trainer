import { useCallback, useEffect, useRef } from "react";

/**
 * Host operation correlation.
 *
 * The webview asks the host to run something and waits for the host's
 * correlated answer: the request carries an operationId, and the host's reply
 * carries the same one. A request that never gets an answer inside its bounded
 * window resolves as *unconfirmed* instead of inventing a result, and every
 * pending operation is settled when the surface goes away.
 *
 * The library folder space, the Markdown-only migration and the resource
 * handoff all use this pattern, so it lives here instead of being
 * re-implemented per feature inside the app shell.
 */
export interface HostOperationRequest {
  /** The correlation id carried by both the request and the host's answer. */
  operationId: string;
  /** How long the answer may take before the operation resolves unconfirmed. */
  timeoutMs: number;
  /** Sends the request to the host. A throw settles the operation unconfirmed. */
  send: () => void;
}

export interface HostOperationResolver<T> {
  /** Ask the host to run something and await its correlated answer. */
  request: (options: HostOperationRequest) => Promise<T>;
  /** Settle one pending operation with the host's answer. */
  resolve: (operationId: string, answer: T) => boolean;
  /** How many operations are still waiting for an answer. */
  pendingCount: () => number;
}

/**
 * @param unresolved The answer used when the host never replies, the request
 * cannot be sent, or the surface goes away.
 */
export function useHostOperationResolver<T>(unresolved: T): HostOperationResolver<T> {
  const pendingRef = useRef(
    new Map<string, { timeoutId: number; resolve: (answer: T) => void }>(),
  );
  // The fallback is read through a ref: an inline object would otherwise be a
  // new value on every render and would settle pending operations early.
  const unresolvedRef = useRef(unresolved);
  unresolvedRef.current = unresolved;

  const resolve = useCallback((operationId: string, answer: T) => {
    const pending = pendingRef.current.get(operationId);
    if (!pending) {
      return false;
    }
    pendingRef.current.delete(operationId);
    window.clearTimeout(pending.timeoutId);
    pending.resolve(answer);
    return true;
  }, []);

  const request = useCallback(({ operationId, timeoutMs, send }: HostOperationRequest) => {
    return new Promise<T>((settle) => {
      const timeoutId = window.setTimeout(() => {
        pendingRef.current.delete(operationId);
        settle(unresolvedRef.current);
      }, timeoutMs);
      pendingRef.current.set(operationId, { timeoutId, resolve: settle });
      try {
        send();
      } catch {
        pendingRef.current.delete(operationId);
        window.clearTimeout(timeoutId);
        settle(unresolvedRef.current);
      }
    });
  }, []);

  const pendingCount = useCallback(() => pendingRef.current.size, []);

  useEffect(() => {
    return () => {
      for (const pending of pendingRef.current.values()) {
        window.clearTimeout(pending.timeoutId);
        pending.resolve(unresolvedRef.current);
      }
      pendingRef.current.clear();
    };
  }, []);

  return { request, resolve, pendingCount };
}
