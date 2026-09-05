/**
 * Alert Renderer
 *
 * Info/Warn/Error alert display.
 * Reference: docs/open-source-fit-and-provider-strategy.md §10
 */

import React from "react";

export interface AlertRendererProps {
  level: "info" | "warn" | "error";
  title: string;
  detail?: string;
}

export const AlertRenderer: React.FC<AlertRendererProps> = ({
  level,
  title,
  detail,
}) => {
  const levelConfig = {
    info: { icon: "i", className: "alert-info" },
    warn: { icon: "!", className: "alert-warning" },
    error: { icon: "ERR", className: "alert-error" },
  };
  const config = levelConfig[level] ?? levelConfig.info;

  return (
    <div className={`trainer-alert ${config.className}`}>
      <div className="alert-header">
        <span className="alert-icon">{config.icon}</span>
        <span className="alert-title">{title}</span>
      </div>
      {detail && <div className="alert-detail">{detail}</div>}
    </div>
  );
};

export default AlertRenderer;
