import { useMemo } from "react";
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";

type StructuredTableProps = {
  columns: string[];
  rows: string[][];
  rowCount?: number;
  columnCount?: number;
  truncated?: boolean;
  emptyLabel?: string;
  rowLabel?: string;
  columnLabel?: string;
  truncatedLabel?: string;
};

function buildColumnDefinitions(columns: string[]): ColumnDef<string[]>[] {
  const effectiveColumns = columns.length > 0 ? columns : ["Value"];
  return effectiveColumns.map((column, index) => ({
    id: `column-${index}`,
    header: column || `Column ${index + 1}`,
    accessorFn: (row) => row[index] ?? "",
    cell: (info) => info.getValue<string>() || " ",
  }));
}

export function StructuredTable({
  columns,
  rows,
  rowCount,
  columnCount,
  truncated,
  emptyLabel = "No rows available.",
  rowLabel = "rows",
  columnLabel = "columns",
  truncatedLabel = "Quick preview only",
}: StructuredTableProps) {
  const columnDefs = useMemo(() => buildColumnDefinitions(columns), [columns]);
  const table = useReactTable({
    data: rows,
    columns: columnDefs,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <div className="structured-table">
      <div className="structured-preview__meta">
        {typeof rowCount === "number" ? <span>{`${rowCount} ${rowLabel}`}</span> : null}
        {typeof columnCount === "number" ? <span>{`${columnCount} ${columnLabel}`}</span> : null}
        {truncated ? <span>{truncatedLabel}</span> : null}
      </div>
      <div className="message-table-wrap">
        <table>
          <thead>
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <th key={header.id}>
                    {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.length > 0 ? (
              table.getRowModel().rows.map((row) => (
                <tr key={row.id}>
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
                  ))}
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={Math.max(1, columns.length)}>{emptyLabel}</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
