import { useEffect, useState, type ReactNode } from "react";

export interface CollapsibleBlockProps {
  summary: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  className?: string;
}

export function CollapsibleBlock({
  summary,
  children,
  defaultOpen = false,
  className,
}: CollapsibleBlockProps) {
  const classes = ["collapsible-block", className].filter(Boolean).join(" ");
  const [open, setOpen] = useState(defaultOpen);

  useEffect(() => {
    setOpen(defaultOpen);
  }, [defaultOpen]);

  return (
    <details
      className={classes}
      open={open}
      onToggle={(event) => {
        setOpen(event.currentTarget.open);
      }}
    >
      <summary>{summary}</summary>
      <div className="collapsible-block__body">{children}</div>
    </details>
  );
}
