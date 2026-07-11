import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table"
import { useMemo } from "react"

import type { Segment } from "@/api/client"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

interface SegmentPreviewProps {
  segments: Segment[]
}

const columnHelper = createColumnHelper<Segment>()

const columns = [
  columnHelper.accessor((segment) => segment.character_name ?? "Unknown", {
    id: "speaker",
    header: "Speaker",
  }),
  columnHelper.accessor("text", {
    id: "text",
    header: "Text",
  }),
]

/** D-15: read-only preview only — no inline edit, dropdowns, row
 * selection, or bulk actions. The full editable segment table is Phase
 * 3's TBL-01..04, not this phase's scope. */
export function SegmentPreview({ segments }: SegmentPreviewProps) {
  const data = useMemo(
    () => [...segments].sort((a, b) => a.order - b.order),
    [segments]
  )

  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
  })

  return (
    <div>
      <h2 className="mb-3 text-lg font-semibold">Segments</h2>
      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <TableHead
                  key={header.id}
                  className={header.column.id === "speaker" ? "w-40" : undefined}
                >
                  {flexRender(header.column.columnDef.header, header.getContext())}
                </TableHead>
              ))}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {table.getRowModel().rows.map((row, index) => (
            <TableRow
              key={row.id}
              className={index % 2 === 1 ? "bg-secondary" : undefined}
            >
              {row.getVisibleCells().map((cell) => (
                <TableCell
                  key={cell.id}
                  className={
                    cell.column.id === "speaker"
                      ? "align-top py-3 text-sm font-medium whitespace-nowrap"
                      : "align-top py-3 text-base whitespace-normal break-words"
                  }
                >
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
