import * as React from 'react';

/**
 * CollapseSection — the single multi-level folding primitive for the whole
 * workbench. All collapsible regions (Plan stages/materials, Resources,
 * Training card details, Coach artifacts, Settings sections) must render
 * through this component so nesting depth never multiplies visual styles.
 *
 * Animation contract: chevron rotation and body height share
 * var(--motion-base) with var(--ease-out); the body animates via the
 * grid-template-rows 0fr→1fr technique (no height JS, no layout thrash).
 * `prefers-reduced-motion: reduce` collapses the transitions to instant.
 */
export interface CollapseSectionProps {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  badge?: React.ReactNode;
  /** Nesting depth (1 = outermost). Drives the surface token: deeper is darker. */
  level?: 1 | 2 | 3;
  defaultOpen?: boolean;
  open?: boolean;
  onToggle?: (open: boolean) => void;
  /** Stable key for open-state persistence across reloads. */
  persistenceKey?: string;
  /** Right-aligned header slot (e.g. a primary action). Stays outside the toggle. */
  actions?: React.ReactNode;
  children: React.ReactNode;
}

const PERSISTENCE_PREFIX = 'trainer.collapse.';

function readPersistedOpen(persistenceKey: string, defaultOpen: boolean): boolean {
  try {
    const stored = window.localStorage.getItem(PERSISTENCE_PREFIX + persistenceKey);
    if (stored === '1') {
      return true;
    }
    if (stored === '0') {
      return false;
    }
  } catch {
    // Webview storage can be unavailable; fall back to the default.
  }
  return defaultOpen;
}

function writePersistedOpen(persistenceKey: string, open: boolean): void {
  try {
    window.localStorage.setItem(PERSISTENCE_PREFIX + persistenceKey, open ? '1' : '0');
  } catch {
    // Ignore persistence failures — collapsible state is best-effort.
  }
}

export function CollapseSection(props: CollapseSectionProps): JSX.Element {
  const {
    title,
    subtitle,
    badge,
    level = 1,
    defaultOpen = false,
    open,
    onToggle,
    persistenceKey = '',
    actions,
    children,
  } = props;
  const isControlled = typeof open === 'boolean';
  const [uncontrolledOpen, setUncontrolledOpen] = React.useState<boolean>(() =>
    isControlled ? (open as boolean) : persistenceKey
      ? readPersistedOpen(persistenceKey, defaultOpen)
      : defaultOpen,
  );
  const isOpen = isControlled ? (open as boolean) : uncontrolledOpen;
  const bodyId = React.useId();

  const setOpen = React.useCallback(
    (next: boolean) => {
      if (!isControlled) {
        setUncontrolledOpen(next);
      }
      if (persistenceKey) {
        writePersistedOpen(persistenceKey, next);
      }
      onToggle?.(next);
    },
    [isControlled, onToggle, persistenceKey],
  );

  const levelClass = `collapse-section--level-${Math.min(Math.max(level, 1), 3)}`;
  return (
    <section className={`collapse-section ${levelClass} ${isOpen ? 'is-open' : ''}`}>
      <div className="collapse-section__header-row">
        <button
          type="button"
          className="collapse-section__header"
          aria-expanded={isOpen}
          aria-controls={bodyId}
          onClick={() => setOpen(!isOpen)}
        >
          <svg
            className="collapse-section__chevron"
            width="12"
            height="12"
            viewBox="0 0 12 12"
            aria-hidden="true"
          >
            <path d="M4 2l4 4-4 4" fill="none" stroke="currentColor" strokeWidth="1.5" />
          </svg>
          <span className="collapse-section__title">{title}</span>
          {badge ? <span className="collapse-section__badge">{badge}</span> : null}
          {subtitle ? <span className="collapse-section__subtitle">{subtitle}</span> : null}
        </button>
        {actions ? (
          <span
            className="collapse-section__actions"
            onClick={(event) => event.stopPropagation()}
            onKeyDown={(event) => event.stopPropagation()}
          >
            {actions}
          </span>
        ) : null}
      </div>
      <div id={bodyId} className="collapse-section__body-wrap" aria-hidden={!isOpen}>
        <div className="collapse-section__body">{children}</div>
      </div>
    </section>
  );
}
