/**
 * Checklist Renderer
 *
 * Task checklist with completion state.
 * Reference: docs/open-source-fit-and-provider-strategy.md §10
 */

import React from "react";

export interface ChecklistRendererProps {
  items: Array<{ label: string; done: boolean }>;
  onToggle?: (index: number) => void;
}

export const ChecklistRenderer: React.FC<ChecklistRendererProps> = ({
  items,
  onToggle,
}) => {
  const completedCount = items.filter((item) => item.done).length;
  const totalCount = items.length;
  const progressPercent = totalCount > 0 ? (completedCount / totalCount) * 100 : 0;

  return (
    <div className="trainer-checklist">
      <div className="checklist-header">
        <span className="checklist-progress">
          {completedCount}/{totalCount} completed
        </span>
        <div className="checklist-progress-bar">
          <div
            className="checklist-progress-fill"
            style={{ width: `${progressPercent}%` }}
          />
        </div>
      </div>
      <ul className="checklist-items">
        {items.map((item, index) => (
          <li
            key={index}
            className={`checklist-item ${item.done ? "item-done" : ""}`}
            onClick={() => onToggle?.(index)}
          >
            <span className="item-checkbox">
              {item.done ? "☑️" : "☐"}
            </span>
            <span className="item-label">{item.label}</span>
          </li>
        ))}
      </ul>
    </div>
  );
};

export default ChecklistRenderer;