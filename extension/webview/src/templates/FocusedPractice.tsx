import type { ReactNode } from "react";
import { ActivityHeader } from "./ActivityHeader";

export type PracticePhase = "learn" | "try" | "verify" | "reflect" | "return";
const PHASE_ORDER: PracticePhase[] = ["learn", "try", "verify", "reflect", "return"];

/** The current governed phase owns the content and its action, never all five. */
export function FocusedPractice({ parent, title, label, phase, phaseLabel, onBack, children, details }: {
  parent: string;
  title: string;
  label?: string;
  phase: PracticePhase;
  phaseLabel: string;
  onBack?: () => void;
  children: ReactNode;
  details?: ReactNode;
}) {
  return <section className="template-focused-practice" role="group" aria-label={label ?? title} data-template="FocusedPractice" data-training-phase={phase}>
    <ActivityHeader parent={parent} title={title} phase={`${phaseLabel} · ${PHASE_ORDER.indexOf(phase) + 1}/5`} onBack={() => onBack?.()} />
    <div className="template-focused-practice__phase">{children}</div>
    {details}
  </section>;
}
