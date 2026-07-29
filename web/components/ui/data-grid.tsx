"use client";
import { ReactNode, useMemo, useState } from "react";
import { ChevronUp, ChevronDown, ChevronsUpDown } from "lucide-react";
import { cn } from "@/lib/utils";

// ponytail: hand-rolled sortable grid instead of TanStack Table. Rows are
// static mock data — no virtualization/pagination needed yet. Swap to TanStack
// when row counts pass a few thousand or server-side sort/filter is required.

export type Column<T> = {
  key: string;
  header: ReactNode;
  align?: "left" | "right" | "center";
  width?: string;
  sortable?: boolean;
  sortValue?: (row: T) => number | string | null | undefined;
  cell: (row: T) => ReactNode;
};

export function DataGrid<T>({
  columns, rows, rowKey, onRowClick, dense = false, pinnedFirstCol = true,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  dense?: boolean;
  pinnedFirstCol?: boolean;
}) {
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null);

  const sorted = useMemo(() => {
    if (!sort) return rows;
    const col = columns.find((c) => c.key === sort.key);
    if (!col?.sortValue) return rows;
    return [...rows].sort((a, b) => {
      const av = col.sortValue!(a), bv = col.sortValue!(b);
      // Rows with no value for this column always sink to the bottom, in both
      // directions — otherwise null/undefined compares as 0 and a stock with
      // no P/E at all would rank as the "cheapest" in an ascending sort.
      const aMissing = av === null || av === undefined;
      const bMissing = bv === null || bv === undefined;
      if (aMissing && bMissing) return 0;
      if (aMissing) return 1;
      if (bMissing) return -1;
      if (av < bv) return -1 * sort.dir;
      if (av > bv) return 1 * sort.dir;
      return 0;
    });
  }, [rows, sort, columns]);

  const toggle = (key: string) =>
    setSort((s) => (s?.key === key ? (s.dir === -1 ? null : { key, dir: -1 }) : { key, dir: 1 }));

  return (
    <div className="overflow-x-auto scrollbar-slim rounded-[var(--radius-lg)] hairline bg-elevated">
      <table className="w-full border-collapse text-[13px]">
        <thead className="sticky top-0 z-10">
          <tr className="bg-surface/95 backdrop-blur">
            {columns.map((c, i) => (
              <th
                key={c.key}
                style={{ width: c.width, textAlign: c.align ?? "left" }}
                className={cn(
                  "select-none px-3.5 py-2.5 text-[11px] font-semibold uppercase tracking-wide text-muted border-b border-line",
                  c.sortable && "cursor-pointer hover:text-mist",
                  pinnedFirstCol && i === 0 && "sticky left-0 bg-surface/95 z-20"
                )}
                onClick={() => c.sortable && toggle(c.key)}
              >
                <span className={cn("inline-flex items-center gap-1", c.align === "right" && "flex-row-reverse")}>
                  {c.header}
                  {c.sortable && (
                    sort?.key === c.key
                      ? sort.dir === 1 ? <ChevronUp size={12} /> : <ChevronDown size={12} />
                      : <ChevronsUpDown size={12} className="opacity-40" />
                  )}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => (
            <tr
              key={rowKey(row)}
              onClick={() => onRowClick?.(row)}
              className={cn(
                "group border-b border-line/60 transition-colors hover:bg-raised/60",
                onRowClick && "cursor-pointer"
              )}
            >
              {columns.map((c, i) => (
                <td
                  key={c.key}
                  style={{ textAlign: c.align ?? "left" }}
                  className={cn(
                    dense ? "px-3.5 py-1.5" : "px-3.5 py-2.5",
                    "text-frost",
                    pinnedFirstCol && i === 0 && "sticky left-0 bg-elevated group-hover:bg-raised/60 z-10"
                  )}
                >
                  {c.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
