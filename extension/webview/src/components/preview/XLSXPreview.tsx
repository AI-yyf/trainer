/**
 * XLSXPreview Component
 *
 * Rich preview for XLSX files showing worksheets with switching support.
 * Reference: docs/open-source-fit-and-provider-strategy.md §7.7
 */

import React, { useState, useMemo } from "react";
import { CSVPreview } from "../parts/CSVPreview";

export interface XLSXSheet {
  name: string;
  columns: string[];
  rows: string[][];
  rowCount: number;
  columnCount: number;
}

export interface XLSXPreviewProps {
  /** Structured data from server */
  structured: {
    sheetName: string;
    sheetCount: number;
    columns: string[];
    rows: string[][];
    rowCount: number;
    columnCount: number;
  };
  /** All sheets data (if provided) */
  allSheets?: XLSXSheet[];
  /** File name for title display */
  filename?: string;
}

/** Detect delimiter from column count */
function detectDelimiter(rows: string[][], headers: string[]): string {
  if (headers.length > 10) return "\t";
  if (headers.some(h => h.includes(","))) return "\t";
  return ",";
}

export const XLSXPreview: React.FC<XLSXPreviewProps> = ({
  structured,
  allSheets,
  filename = "workbook.xlsx",
}) => {
  const [selectedSheetIndex, setSelectedSheetIndex] = useState(0);

  const sheets = useMemo((): XLSXSheet[] => {
    if (allSheets && allSheets.length > 0) {
      return allSheets;
    }
    // Build single-sheet view from structured data
    return [{
      name: structured.sheetName,
      columns: structured.columns,
      rows: structured.rows,
      rowCount: structured.rowCount,
      columnCount: structured.columnCount,
    }];
  }, [allSheets, structured]);

  const currentSheet = sheets[selectedSheetIndex] ?? sheets[0];

  if (!currentSheet) {
    return (
      <div className="trainer-xlsx-preview">
        <div className="xlsx-header">
          <span className="xlsx-icon">XLS</span>
          <span className="xlsx-filename">{filename}</span>
        </div>
        <div className="xlsx-empty">No data available</div>
      </div>
    );
  }

  const delimiter = detectDelimiter(currentSheet.rows, currentSheet.columns);
  const csvContent = [
    currentSheet.columns.join(delimiter),
    ...currentSheet.rows.map(row => row.join(delimiter)),
  ].join("\n");

  return (
    <div className="trainer-xlsx-preview">
      <div className="xlsx-header">
        <div className="xlsx-title">
          <span className="xlsx-icon">XLS</span>
          <span className="xlsx-filename">{filename}</span>
        </div>
        <div className="xlsx-stats">
          <span className="xlsx-stat">{currentSheet.rowCount} rows</span>
          <span className="xlsx-stat">{currentSheet.columnCount} columns</span>
          {sheets.length > 1 && (
            <span className="xlsx-stat">{sheets.length} sheets</span>
          )}
        </div>
      </div>

      {sheets.length > 1 && (
        <div className="xlsx-tabs">
          {sheets.map((sheet, idx) => (
            <button
              key={sheet.name}
              className={`xlsx-tab ${idx === selectedSheetIndex ? "active" : ""}`}
              onClick={() => setSelectedSheetIndex(idx)}
            >
              {sheet.name}
            </button>
          ))}
        </div>
      )}

      <div className="xlsx-content">
        <CSVPreview
          content={csvContent}
          filename={currentSheet.name}
          delimiter={delimiter}
          maxRows={500}
          showRowNumbers
        />
      </div>
    </div>
  );
};
