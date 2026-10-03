export interface ActivityHeaderProps {
  parent: string;
  title: string;
  phase?: string;
  onBack: () => void;
}

export function ActivityHeader({ parent, title, phase, onBack }: ActivityHeaderProps) {
  return (
    <header className="template-activity-header">
      <button type="button" className="template-back" onClick={onBack}>‹ {parent}</button>
      <h2>{title}</h2>
      {phase ? <p className="template-metadata template-activity-header__phase">{phase}</p> : null}
    </header>
  );
}
