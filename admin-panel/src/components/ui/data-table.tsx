"use client"

import * as React from "react"
import {
  ColumnDef,
  ColumnFiltersState,
  SortingState,
  VisibilityState,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table"
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight, Search, ArrowUpDown, ArrowUp, ArrowDown } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { SearchX } from "lucide-react"

interface DataTableProps<TData, TValue> {
  columns: ColumnDef<TData, TValue>[]
  data: TData[]
  searchKey?: string
  searchPlaceholder?: string
  isLoading?: boolean
  pageSize?: number
  totalItems?: number
  onPageChange?: (page: number) => void
  currentPage?: number
  serverSidePagination?: boolean
}

export function DataTable<TData, TValue>({
  columns,
  data,
  searchKey,
  searchPlaceholder = "Buscar...",
  isLoading = false,
  pageSize = 10,
  totalItems,
  onPageChange,
  currentPage = 0,
  serverSidePagination = false,
}: DataTableProps<TData, TValue>) {
  const [sorting, setSorting] = React.useState<SortingState>([])
  const [columnFilters, setColumnFilters] = React.useState<ColumnFiltersState>([])
  const [columnVisibility, setColumnVisibility] = React.useState<VisibilityState>({})
  const [rowSelection, setRowSelection] = React.useState({})

  const table = useReactTable({
    data,
    columns,
    onSortingChange: setSorting,
    onColumnFiltersChange: setColumnFilters,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: serverSidePagination ? undefined : getPaginationRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    onColumnVisibilityChange: setColumnVisibility,
    onRowSelectionChange: setRowSelection,
    state: {
      sorting,
      columnFilters,
      columnVisibility,
      rowSelection,
    },
    initialState: {
      pagination: {
        pageSize,
      },
    },
  })

  const totalPages = serverSidePagination
    ? Math.ceil((totalItems || 0) / pageSize)
    : table.getPageCount()

  const canPreviousPage = serverSidePagination
    ? currentPage > 0
    : table.getCanPreviousPage()

  const canNextPage = serverSidePagination
    ? currentPage < totalPages - 1
    : table.getCanNextPage()

  const handlePreviousPage = () => {
    if (serverSidePagination && onPageChange) {
      onPageChange(currentPage - 1)
    } else {
      table.previousPage()
    }
  }

  const handleNextPage = () => {
    if (serverSidePagination && onPageChange) {
      onPageChange(currentPage + 1)
    } else {
      table.nextPage()
    }
  }

  const handleFirstPage = () => {
    if (serverSidePagination && onPageChange) {
      onPageChange(0)
    } else {
      table.setPageIndex(0)
    }
  }

  const handleLastPage = () => {
    if (serverSidePagination && onPageChange) {
      onPageChange(totalPages - 1)
    } else {
      table.setPageIndex(totalPages - 1)
    }
  }

  const displayedPage = serverSidePagination
    ? currentPage
    : table.getState().pagination.pageIndex

  return (
    <div className="w-full">
      {searchKey && (
        <div className="flex items-center py-4">
          <div className="relative max-w-sm">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder={searchPlaceholder}
              value={(table.getColumn(searchKey)?.getFilterValue() as string) ?? ""}
              onChange={(event) =>
                table.getColumn(searchKey)?.setFilterValue(event.target.value)
              }
              className="pl-8"
            />
          </div>
        </div>
      )}
      <div className="rounded-md border">
        <Table>
          <TableHeader>
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map((header) => {
                  return (
                    <TableHead key={header.id}>
                      {header.isPlaceholder
                        ? null
                        : flexRender(
                            header.column.columnDef.header,
                            header.getContext()
                          )}
                    </TableHead>
                  )
                })}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {isLoading ? (
              Array.from({ length: pageSize > 5 ? 5 : pageSize }).map((_, i) => (
                <TableRow key={`skeleton-${i}`}>
                  {columns.map((_, j) => (
                    <TableCell key={`skeleton-cell-${j}`} className="py-3">
                      <Skeleton className="h-4 w-full" style={{ opacity: 1 - j * 0.05 }} />
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : table.getRowModel().rows?.length ? (
              table.getRowModel().rows.map((row) => (
                <TableRow
                  key={row.id}
                  data-state={row.getIsSelected() && "selected"}
                >
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id}>
                      {flexRender(
                        cell.column.columnDef.cell,
                        cell.getContext()
                      )}
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : (
              <TableRow>
                <TableCell colSpan={columns.length} className="p-0">
                  <div className="flex flex-col items-center justify-center py-12 text-center">
                    <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-muted/60 text-muted-foreground">
                      <SearchX className="h-6 w-6" strokeWidth={1.5} />
                    </div>
                    <p className="text-sm font-medium text-foreground">Sin resultados</p>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      No se encontraron registros para los filtros actuales.
                    </p>
                  </div>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
      <div className="flex items-center justify-between space-x-2 py-4">
        <div className="text-sm text-muted-foreground">
          {serverSidePagination ? (
            `Mostrando ${data.length} de ${totalItems || 0} registros`
          ) : (
            `${table.getFilteredRowModel().rows.length} registro(s)`
          )}
        </div>
        <div className="flex items-center space-x-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleFirstPage}
            disabled={!canPreviousPage}
          >
            <ChevronsLeft className="h-4 w-4" />
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={handlePreviousPage}
            disabled={!canPreviousPage}
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <span className="text-sm text-muted-foreground">
            Pagina {displayedPage + 1} de {totalPages || 1}
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={handleNextPage}
            disabled={!canNextPage}
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={handleLastPage}
            disabled={!canNextPage}
          >
            <ChevronsRight className="h-4 w-4" />
          </Button>
        </div>
      </div>
    </div>
  )
}

// Helper component for sortable column headers
interface SortableHeaderProps {
  column: {
    getIsSorted: () => false | "asc" | "desc"
    toggleSorting: (desc?: boolean) => void
  }
  children: React.ReactNode
}

export function SortableHeader({ column, children }: SortableHeaderProps) {
  const sorted = column.getIsSorted()
  return (
    <Button
      variant="ghost"
      onClick={() => column.toggleSorting(sorted === "asc")}
      className="-ml-4"
    >
      {children}
      {sorted === "asc" ? (
        <ArrowUp className="ml-2 h-4 w-4" />
      ) : sorted === "desc" ? (
        <ArrowDown className="ml-2 h-4 w-4" />
      ) : (
        <ArrowUpDown className="ml-2 h-4 w-4" />
      )}
    </Button>
  )
}
