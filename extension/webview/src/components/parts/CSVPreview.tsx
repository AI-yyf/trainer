/**
 * CSVPreview Component
 *
 * Rich data table preview for CSV/TSV files using TanStack Table.
 * Reference: docs/open-source-fit-and-provider-strategy.md §7.7
 */

import React, { useState, useMemo } from "react";
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  type ColumnDef,
  type SortingState,
  type ColumnFiltersState,
} from "@tanstack/react-table";

export interface CSVPreviewProps {
  /** Raw CSV/TSV content */
  content: string;
  /** File name for title display */
  filename?: string;
  /** Delimiter (comma, tab, semicolon) */
  delimiter?: string;
  /** Maximum rows to display */
  maxRows?: number;
  /** Show row numbers column */
  showRowNumbers?: boolean;
}

interface ParsedRow {
  [key: string]: string;
}

function parseCSV(content: string, delimiter: string): { headers: string[]; rows: ParsedRow[] } {
  const lines = content.split(/\r?\n/).filter((line) => line.trim());
  if (lines.length === 0) return { headers: [], rows: [] };

  const delimiterChar = delimiter === "\t" ? "\t" : delimiter || ",";
  const headers = lines[0].split(delimiterChar).map((h) => h.trim().replace(/^["']|["']$/g, ""));

  const rows: ParsedRow[] = [];
  for (let i = 1; i < lines.length; i++) {
    const values = lines[i].split(delimiterChar).map((v) => v.trim().replace(/^["']|["']$/g, ""));
    const row: ParsedRow = {};
    headers.forEach((header, idx) => {
      row[header] = values[idx] ?? "";
    });
    rows.push(row);
  }

  return { headers, rows };
}

export const CSVPreview: React.FC<CSVPreviewProps> = ({
  content,
  filename = "data",
  delimiter = ",",
  maxRows = 100,
  showRowNumbers = false,
}) => {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [globalFilter, setGlobalFilter] = useState("");
  const [pageIndex, setPageIndex] = useState(0);

  const { headers, rows } = useMemo(() => parseCSV(content, delimiter), [content, delimiter]);
  const displayRows = useMemo(() => rows.slice(0, maxRows), [rows, maxRows]);

  const columns = useMemo<ColumnDef<ParsedRow>[]>(
    () => {
      const cols: ColumnDef<ParsedRow>[] = [];

      if (showRowNumbers) {
        cols.push({
          id: "row-number",
          header: "#",
          size: 50,
          cell: ({ row }) => (
            <span className="csv-row-number">{row.index + 1}</span>
          ),
          enableSorting: false,
          enableGlobalFilter: false,
        });
      }

      headers.forEach((header) => {
        cols.push({
          id: header,
          accessorKey: header,
          header: header,
          enableSorting: true,
          enableGlobalFilter: true,
          cell: ({ getValue }) => (
            <span className="csv-cell" title={String(getValue())}>
              {String(getValue())}
            </span>
          ),
        });
      });

      return cols;
    },
    [headers, showRowNumbers]
  );

  const table = useReactTable({
    data: displayRows,
    columns,
    state: {
      sorting,
      columnFilters,
      globalFilter,
      pagination: { pageIndex, pageSize: 20 },
    },
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    onGlobalFilterChange: setGlobalFilter,
    onPaginationChange: (updater) => {
      const newPagination = typeof updater === "function" ? updater({ pageIndex, pageSize: 20 }) : updater;
      setPageIndex(newPagination.pageIndex);
    },
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    autoResetPageIndex: true,
  });

  const totalRows = rows.length;
  const shownRows = Math.min(20, displayRows.length);
  const startRow = pageIndex * 20 + 1;
  const endRow = Math.min(startRow + shownRows - 1, totalRows);

  return (
    <div className="trainer-csv-preview">
      <div className="csv-header">
        <div className="csv-title">
          <span className="csv-icon">CSV</span>
          <span className="csv-filename">{filename}</span>
        </div>
        <div className="csv-stats">
          <span className="csv-stat">{headers.length} columns</span>
          <span className="csv-stat-sep">•</span>
          <span className="csv-stat">{totalRows} rows</span>
          {totalRows > maxRows && (
            <>
              <span className="csv-stat-sep">•</span>
              <span className="csv-stat csv-limited">showing first {maxRows}</span>
            </>
          )}
        </div>
      </div>

      <div className="csv-controls">
        <input
          type="text"
          className="csv-search"
          placeholder="Filter rows..."
          value={globalFilter}
          onChange={(e) => setGlobalFilter(e.target.value)}
        />
      </div>

      <div className="csv-table-wrapper">
        <table className="csv-table">
          <thead>
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <th
                    key={header.id}
                    className="csv-th"
                    onClick={header.column.getToggleSortingHandler()}
                    style={{ cursor: header.column.getCanSort() ? "pointer" : "default" }}
                  >
                    <div className="csv-th-content">
                      <span className="csv-th-label">{header.column.columnDef.header as string}</span>
                      {header.column.getCanSort() && (
                        <span className="csv-sort-icon">
                          {{
                            asc: " ↑",
                            desc: " ↓",
                          }[header.column.getIsSorted() as string] ?? ""}
                        </span>
                      )}
                    </div>
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.length === 0 ? (
              <tr>
                <td colSpan={headers.length} className="csv-empty">
                  No data to display
                </td>
              </tr>
            ) : (
              table.getRowModel().rows.map((row) => (
                <tr key={row.id} className="csv-row">
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="csv-td">
                      {cell.getValue() as string}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="csv-pagination">
        <span className="csv-pagination-info">
          Showing {startRow}-{endRow} of {totalRows}
        </span>
        <div className="csv-pagination-controls">
          <button
            className="csv-page-btn"
            onClick={() => table.setPageIndex(0)}
            disabled={!table.getCanPreviousPage()}
          >
            ⟪
          </button>
          <button
            className="csv-page-btn"
            onClick={() => table.previousPage()}
            disabled={!table.getCanPreviousPage()}
          >
            ←
          </button>
          <span className="csv-page-number">
            Page {pageIndex + 1} of {table.getPageCount()}
          </span>
          <button
            className="csv-page-btn"
            onClick={() => table.nextPage()}
            disabled={!table.getCanNextPage()}
          >
            →
          </button>
          <button
            className="csv-page-btn"
            onClick={() => table.setPageIndex(table.getPageCount() - 1)}
            disabled={!table.getCanNextPage()}
          >
            ⟫
          </button>
        </div>
      </div>
    </div>
  );
};
