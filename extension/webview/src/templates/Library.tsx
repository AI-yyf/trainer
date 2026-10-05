import type { ReactNode } from "react";

/**
 * Search/add precede the library; a reader temporarily takes the whole surface.
 * The section carries no landmark name of its own: the hosting resources pane
 * is the stable "library" region so it stays labeled while this surface is
 * hidden behind the reader (trash guard dialogs stay reachable there).
 */
export function Library({ hidden, toolbar, children }: { hidden?: boolean; toolbar: ReactNode; children: ReactNode }) {
  return <section className="template-library" data-template="Library" hidden={hidden}><div>{toolbar}</div><div>{children}</div></section>;
}
