import { StatusPill } from "../StatusPill";

export type DeepAnalysisTone =
  | "pass"
  | "fail"
  | "warn"
  | "pending"
  | "connected"
  | "starting"
  | "offline";

export interface DeepAnalysisMetric {
  label: string;
  value: string | number;
}

export interface DeepAnalysisAction {
  id: string;
  label: string;
  disabled?: boolean;
  tone?: "accent" | "ghost";
  onClick?: () => void;
}

export interface CoachDeepAnalysisBlockProps {
  title: string;
  summary: string;
  eyebrow?: string;
  statusLabel?: string;
  statusTone?: DeepAnalysisTone;
  currentFocus?: string;
  decision?: string;
  nextStep?: string;
  bullets?: string[];
  metrics?: DeepAnalysisMetric[];
  actions?: DeepAnalysisAction[];
  footnote?: string;
  className?: string;
}

export function CoachDeepAnalysisBlock({
  title,
  summary,
  eyebrow = "Deep analysis",
  statusLabel,
  statusTone = "pending",
  currentFocus,
  decision,
  nextStep,
  bullets,
  metrics,
  actions,
  footnote,
  className,
}: CoachDeepAnalysisBlockProps) {
  const classes = ["research-intro-card", "coach-deep-analysis-block", className]
    .filter(Boolean)
    .join(" ");

  return (
    <article className={classes}>
      <div className="research-intro-card__header">
        <div>
          <span className="eyebrow">{eyebrow}</span>
          <strong>{title}</strong>
        </div>
        {statusLabel ? <StatusPill tone={statusTone}>{statusLabel}</StatusPill> : null}
      </div>

      <p>{summary}</p>

      {currentFocus ? (
        <div className="research-overview-card">
          <span className="eyebrow">Current focus</span>
          <p>{currentFocus}</p>
        </div>
      ) : null}

      {decision ? (
        <div className="research-overview-card">
          <span className="eyebrow">Decision</span>
          <p>{decision}</p>
        </div>
      ) : null}

      {nextStep ? (
        <div className="research-overview-card">
          <span className="eyebrow">Next step</span>
          <p>{nextStep}</p>
        </div>
      ) : null}

      {metrics?.length ? (
        <div className="research-meta-line research-meta-line--dense">
          {metrics.map((metric) => (
            <span key={metric.label}>
              {metric.label} <strong>{metric.value}</strong>
            </span>
          ))}
        </div>
      ) : null}

      {bullets?.length ? (
        <ul className="coach-deep-analysis-block__bullets">
          {bullets.map((bullet) => (
            <li key={bullet}>{bullet}</li>
          ))}
        </ul>
      ) : null}

      {footnote ? <p className="inline-note">{footnote}</p> : null}

      {actions?.length ? (
        <div className="settings-actions">
          {actions.map((action) => (
            <button
              key={action.id}
              className={`button ${action.tone === "accent" ? "button--accent" : "button--ghost"}`}
              type="button"
              disabled={action.disabled}
              onClick={action.onClick}
            >
              {action.label}
            </button>
          ))}
        </div>
      ) : null}
    </article>
  );
}
