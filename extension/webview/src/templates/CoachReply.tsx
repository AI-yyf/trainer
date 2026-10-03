import type { ReactNode } from "react";

/** Reply order is stable; only the next action competes for attention. */
export function CoachReply({ body, evidence, nextAction, tools }: {
  body: ReactNode;
  evidence?: ReactNode;
  nextAction?: ReactNode;
  tools?: ReactNode;
}) {
  return <div data-template="CoachReply">{body}{evidence}{nextAction}{tools}</div>;
}
