/**
 * Table Renderer
 *
 * Structured data table display using TanStack Table patterns.
 * Supports sorting, filtering, column resize, and pagination.
 * Reference: docs/open-source-fit-and-provider-strategy.md §7.7
 */

import React, { useMemo, useState, useCallback } from "react";

export interface TableRendererProps {
  columns: string[];
  rows: unknown[][];
  /** Maximum rows to show before truncation */
  maxRows?: number;
  /** Enable sorting */
  sortable?: boolean;
  /** Enable filtering */
  filterable?: boolean;
  /** Show zebra striping */
  striped?: boolean;
  /** Enable pagination */
  paginate?: boolean;
  /** Rows per page when paginated */
  pageSize?: number;
}

type SortDirection = "asc" | "desc" | null;

export const TableRenderer: React.FC<TableRendererProps> = ({
  columns,
  rows,
  maxRows = 100,
  sortable = false,
  filterable = false,
  striped = true,
  paginate = false,
  pageSize = 20,
}) => {
  // Filter state
  const [filterText, setFilterText] = useState("");
  const [activeColumnFilter, setActiveColumnFilter] = useState<number | null>(null);

  // Sort state
  const [sortedColumn, setSortedColumn] = useState<number | null>(null);
  const [sortDirection, setSortDirection] = useState<SortDirection>(null);

  // Pagination state
  const [currentPage, setCurrentPage] = useState(0);

  // Apply filter
  const filteredRows = useMemo(() => {
    if (!filterText.trim()) return rows;

    const lowerFilter = filterText.toLowerCase();
    return rows.filter((row) =>
      row.some((cell) => {
        if (cell === null || cell === undefined) return false;
        return String(cell).toLowerCase().includes(lowerFilter);
      })
    );
  }, [rows, filterText]);

  // Apply sort
  const sortedFilteredRows = useMemo(() => {
    if (sortedColumn === null || sortDirection === null) return filteredRows;

    return [...filteredRows].sort((a, b) => {
      const aVal = a[sortedColumn];
      const bVal = b[sortedColumn];

      // Handle null/undefined
      if (aVal === null || aVal === undefined) return sortDirection === "asc" ? 1 : -1;
      if (bVal === null || bVal === undefined) return sortDirection === "asc" ? -1 : 1;

      // Compare values
      let comparison = 0;
      if (typeof aVal === "number" && typeof bVal === "number") {
        comparison = aVal - bVal;
      } else {
        comparison = String(aVal).localeCompare(String(bVal));
      }

      return sortDirection === "asc" ? comparison : -comparison;
    });
  }, [filteredRows, sortedColumn, sortDirection]);

  // Apply pagination
  const paginatedRows = useMemo(() => {
    if (!paginate) return sortedFilteredRows.slice(0, maxRows);
    const start = currentPage * pageSize;
    return sortedFilteredRows.slice(start, start + pageSize);
  }, [sortedFilteredRows, paginate, currentPage, pageSize, maxRows]);

  const totalPages = paginate ? Math.ceil(sortedFilteredRows.length / pageSize) : 1;
  const isTruncated = !paginate && sortedFilteredRows.length > maxRows;

  const handleHeaderClick = (colIndex: number) => {
    if (!sortable) return;
    if (sortedColumn === colIndex) {
      if (sortDirection === "asc") {
        setSortDirection("desc");
      } else if (sortDirection === "desc") {
        setSortedColumn(null);
        setSortDirection(null);
      } else {
        setSortDirection("asc");
      }
    } else {
      setSortedColumn(colIndex);
      setSortDirection("asc");
    }
  };

  const handleFilterChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setFilterText(e.target.value);
    setCurrentPage(0); // Reset to first page when filtering
  }, []);

  const getSortIndicator = (colIndex: number) => {
    if (sortedColumn !== colIndex) return null;
    return sortDirection === "asc" ? "▲" : "▼";
  };

  return (
    <div className="trainer-table-renderer">
      {filterable && (
        <div className="table-filter-bar">
          <input
            type="text"
            className="table-filter-input"
            placeholder="Filter rows..."
            value={filterText}
            onChange={handleFilterChange}
          />
          {filterText && (
            <span className="table-filter-count">
              {filteredRows.length} / {rows.length} rows
            </span>
          )}
        </div>
      )}

      <div className="table-wrapper">
        <table className={`trainer-table ${striped ? "striped" : ""} ${sortable ? "sortable" : ""}`}>
          <thead>
            <tr>
              {columns.map((col, index) => (
                <th
                  key={index}
                  className={sortable ? "sortable-header" : ""}
                  onClick={() => handleHeaderClick(index)}
                  title={sortable ? "Click to sort" : undefined}
                >
                  <span className="header-text">{col}</span>
                  {sortable && (
                    <span className="sort-indicator">
                      {getSortIndicator(index) || "⇅"}
                    </span>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {paginatedRows.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="table-empty">
                  No matching rows
                </td>
              </tr>
            ) : (
              paginatedRows.map((row, rowIndex) => (
                <tr key={rowIndex} className={striped && rowIndex % 2 === 1 ? "odd" : ""}>
                  {row.map((cell, cellIndex) => (
                    <td key={cellIndex}>
                      <CellValue value={cell} />
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {isTruncated && (
        <div className="table-truncation-notice">
          <span className="truncation-text">
            Showing {maxRows} of {sortedFilteredRows.length} rows. Use filter or download for full data.
          </span>
        </div>
      )}

      {paginate && totalPages > 1 && (
        <div className="table-pagination">
          <button
            className="pagination-btn"
            onClick={() => setCurrentPage(0)}
            disabled={currentPage === 0}
          >
            ⏮
          </button>
          <button
            className="pagination-btn"
            onClick={() => setCurrentPage((p) => Math.max(0, p - 1))}
            disabled={currentPage === 0}
          >
            ◀
          </button>
          <span className="pagination-info">
            Page {currentPage + 1} of {totalPages}
          </span>
          <button
            className="pagination-btn"
            onClick={() => setCurrentPage((p) => Math.min(totalPages - 1, p + 1))}
            disabled={currentPage >= totalPages - 1}
          >
            ▶
          </button>
          <button
            className="pagination-btn"
            onClick={() => setCurrentPage(totalPages - 1)}
            disabled={currentPage >= totalPages - 1}
          >
            ⏭
          </button>
        </div>
      )}
    </div>
  );
};

/**
 * Render a cell value with appropriate formatting
 */
const CellValue: React.FC<{ value: unknown }> = ({ value }) => {
  if (value === null || value === undefined) {
    return <span className="cell-null">—</span>;
  }

  if (typeof value === "string") {
    // Check for URLs
    if (/^https?:\/\//.test(value)) {
      return (
        <a href={value} className="cell-link" target="_blank" rel="noopener noreferrer">
          {value.length > 50 ? `${value.slice(0, 50)}...` : value}
        </a>
      );
    }
    // Check for code-like values
    if (/^[{[\(`]/.test(value)) {
      return <code className="cell-code">{value}</code>;
    }
    return <span className="cell-text">{value}</span>;
  }

  if (typeof value === "number") {
    return <span className="cell-number">{formatNumber(value)}</span>;
  }

  if (typeof value === "boolean") {
    return (
      <span className={`cell-boolean ${value ? "true" : "false"}`}>
        {value ? "✓" : "✗"}
      </span>
    );
  }

  if (typeof value === "object") {
    return <code className="cell-json">{JSON.stringify(value)}</code>;
  }

  return <span className="cell-text">{String(value)}</span>;
};

/**
 * Format numbers with appropriate precision
 */
function formatNumber(num: number): string {
  if (Number.isInteger(num)) {
    return num.toLocaleString();
  }
  // Show up to 4 significant digits
  return num.toPrecision(4);
}

export default TableRenderer;