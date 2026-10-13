import { createContext, useContext } from "react";

import type { ProviderConnectionController } from "./useProviderConnectionController";

/**
 * Publishes App's single provider-connection controller instance to the tree
 * (props-debt round: settings boundary).
 *
 * App keeps instantiating `useProviderConnectionController` exactly once, so
 * every owner of the interaction state is unchanged: the editable draft still
 * lives for the whole session (a Settings unmount cannot lose it), the
 * composer model switch reads the same draft fields, deep links still bump the
 * API-key focus counter, and the host-message pump still consumes speed-test
 * acks. Settings reads the SAME instance through this context instead of
 * receiving its fields as loose props, so a keystroke in Settings and a
 * keystroke in the composer observe one another within the same render pass —
 * identical to the previous prop delivery, with no second instance anywhere.
 */
export const ProviderConnectionContext = createContext<ProviderConnectionController | undefined>(
  undefined,
);

/** Reads the App-owned connection controller (throws on a missing provider). */
export function useProviderConnection(): ProviderConnectionController {
  const connection = useContext(ProviderConnectionContext);
  if (!connection) {
    throw new Error(
      "ProviderConnectionContext is missing the App-owned provider-connection controller.",
    );
  }
  return connection;
}
