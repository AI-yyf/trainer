/**
 * Plan Update Renderer
 *
 * Plan change artifact display.
 * Reference: docs/open-source-fit-and-provider-strategy.md §10
 */

import React from "react";
import type { PlanUpdatePart } from "@trainer/shared";

export interface PlanUpdateRendererProps {
  planId: string;
  changes: unknown[];
}

export const PlanUpdateRenderer: React.FC<PlanUpdateRendererProps> = ({
  planId,
  changes,
}) => {
  return (
    <div className="trainer-plan-update" data-plan-id={planId}>
      <div className="plan-update-header">
        <span className="plan-icon">PLAN</span>
        <span className="plan-label">Plan Update</span>
        <span className="plan-id">#{planId}</span>
      </div>
      <div className="plan-changes">
        <span className="changes-label">Changes:</span>
        <ul className="changes-list">
          {changes.map((change, index) => (
            <li key={index} className="change-item">
              {typeof change === "string" ? (
                change
              ) : (
                <code className="change-json">
                  {JSON.stringify(change, null, 2)}
                </code>
              )}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
};

export default PlanUpdateRenderer;
