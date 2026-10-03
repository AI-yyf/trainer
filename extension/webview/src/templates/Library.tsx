import type { ReactNode } from "react";

/** Search/add precede the library; a reader temporarily takes the whole surface. */
export function Library({ title, hidden, toolbar, children }: { title: string; hidden?: boolean; toolbar: ReactNode; children: ReactNode }) {
  return <section className="template-library" data-template="Library" aria-label={title} hidden={hidden}><div>{toolbar}</div><div>{children}</div></section>;
}
