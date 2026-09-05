import type { ReactNode } from "react";

interface StatusPillProps {
  tone: "pass" | "fail" | "warn" | "pending" | "connected" | "starting" | "offline";
  children: ReactNode;
}

export function StatusPill({ tone, children }: StatusPillProps) {
  return (
    <span className={`status-pill status-pill--${tone}`}>
      {children}
    </span>
  );
}
