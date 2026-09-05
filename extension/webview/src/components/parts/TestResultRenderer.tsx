/**
 * Test Result Renderer
 *
 * Test execution result display.
 * Reference: docs/open-source-fit-and-provider-strategy.md §10
 */

import React from "react";

export interface TestResultRendererProps {
  command: string;
  status: "pass" | "fail" | "unknown";
  outputRef?: string;
  detail?: string;
}

export const TestResultRenderer: React.FC<TestResultRendererProps> = ({
  command,
  status,
  outputRef,
  detail,
}) => {
  const statusConfig = {
    pass: { icon: "OK", className: "test-pass" },
    fail: { icon: "ERR", className: "test-fail" },
    unknown: { icon: "?", className: "test-unknown" },
  };
  const config = statusConfig[status] ?? statusConfig.unknown;

  return (
    <div className={`trainer-test-result ${config.className}`}>
      <div className="test-result-header">
        <span className="test-status-icon">{config.icon}</span>
        <code className="test-command">{command}</code>
        <span className={`test-status-badge ${config.className}`}>
          {status.toUpperCase()}
        </span>
      </div>
      {detail && <div className="test-result-detail">{detail}</div>}
      {outputRef && (
        <div className="test-output-ref">
          <span className="output-ref-label">Output:</span>
          <code className="output-ref-id">{outputRef}</code>
        </div>
      )}
    </div>
  );
};

export default TestResultRenderer;
