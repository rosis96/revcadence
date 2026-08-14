import { promptDialog } from "./dialogs";
import { Select } from "./Select";
/* THE DataTable (DESIGN_SYSTEM.md Part 3). One table for every list in RevCadence.
   TanStack Table (headless) + TanStack Virtual. Features: search, sorting, column
   chooser (persisted), saved views (persisted), bulk actions, sticky header,
   resizable columns, pagination OR virtualized infinite scroll, skeletons, empty state. */
import { useEffect, useMemo, useRef, useState } from "react";
import {
  flexRender, getCoreRowModel, getFilteredRowModel, getPaginationRowModel,
  getSortedRowModel, useReactTable,
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ArrowDown, ArrowUp, Bookmark, ChevronDown, Columns3, Inbox, Search, Trash2 } from "lucide-react";
import { EmptyState, useClickOutside } from "./index";

const store = {
  get(key, fallback) {
    try { const v = JSON.parse(localStorage.getItem(key)); return v ?? fallback; } catch { return fallback; }
  },
  set(key, val) { try { localStorage.setItem(key, JSON.stringify(val)); } catch { /* ignore */ } },
};

function ColumnChooser({ table }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useClickOutside(ref, () => setOpen(false));
  const cols = table.getAllLeafColumns().filter((c) => c.id !== "__select");
  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button className="dt-tool" onClick={() => setOpen((v) => !v)}><Columns3 size={15} /> Columns</button>
      {open && (
        <div className="dt-pop">
          {cols.map((c) => (
            <label key={c.id} className="dt-pop-row">
              <input type="checkbox" checked={c.getIsVisible()} onChange={c.getToggleVisibilityHandler()} />
              <span>{typeof c.columnDef.header === "string" ? c.columnDef.header : c.id}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

function ViewsMenu({ views, current, onSave, onApply, onDelete }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useClickOutside(ref, () => setOpen(false));
  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button className="dt-tool" onClick={() => setOpen((v) => !v)}>
        <Bookmark size={15} /> {current || "Views"} <ChevronDown size={13} />
      </button>
      {open && (
        <div className="dt-pop">
          {Object.keys(views).length === 0 && <div className="dt-pop-empty">No saved views yet</div>}
          {Object.keys(views).map((name) => (
            <div key={name} className="dt-pop-row view">
              <button className="apply" onClick={() => { onApply(name); setOpen(false); }}>{name}</button>
              <button className="del" title="Delete view" onClick={() => onDelete(name)}><Trash2 size={13} /></button>
            </div>
          ))}
          <button className="dt-pop-save" onClick={async () => {
            const name = await promptDialog("Save current view as:");
            if (name) { onSave(name); setOpen(false); }
          }}>+ Save current view</button>
        </div>
      )}
    </div>
  );
}

export function DataTable({
  id,                       // stable key: persists columns + views per table
  columns, data, loading = false,
  searchable = true, searchPlaceholder = "Search…",
  tools,                    // extra toolbar node (right side)
  leftTools,                // extra toolbar node (left side, e.g. a server-side search input)
  manual,                   // {page, pages, total, onPage}: server-side pagination (disables client paging/virtualization)
  onRowClick,
  bulkActions,              // [{label, icon, onClick(selectedOriginals)}] -> adds checkbox column
  getRowId,
  emptyTitle = "Nothing here yet", emptyHint, emptyAction, emptyIcon = Inbox,
  pageSize: pageSizeDefault = 50,
  virtualizeOver = 200,     // above this row count: virtualized infinite scroll instead of pagination
  maxHeight,                // optional fixed scroll height
}) {
  const [globalFilter, setGlobalFilter] = useState("");
  const [sorting, setSorting] = useState([]);
  const [rowSelection, setRowSelection] = useState({});
  const [columnVisibility, setColumnVisibility] = useState(() => store.get(`dt:${id}:cols`, {}));
  const [views, setViews] = useState(() => store.get(`dt:${id}:views`, {}));
  const [currentView, setCurrentView] = useState("");
  const [pagination, setPagination] = useState({ pageIndex: 0, pageSize: pageSizeDefault });

  useEffect(() => { store.set(`dt:${id}:cols`, columnVisibility); }, [id, columnVisibility]);
  useEffect(() => { store.set(`dt:${id}:views`, views); }, [id, views]);

  const rows = data || [];
  const virtual = !manual && rows.length > virtualizeOver;

  const allColumns = useMemo(() => {
    if (!bulkActions?.length) return columns;
    return [{
      id: "__select", size: 36, enableResizing: false, enableSorting: false,
      header: ({ table }) => (
        <input type="checkbox" checked={table.getIsAllRowsSelected()}
          ref={(el) => el && (el.indeterminate = table.getIsSomeRowsSelected())}
          onChange={table.getToggleAllRowsSelectedHandler()} />
      ),
      cell: ({ row }) => (
        <input type="checkbox" checked={row.getIsSelected()} onClick={(e) => e.stopPropagation()}
          onChange={row.getToggleSelectedHandler()} />
      ),
    }, ...columns];
  }, [columns, bulkActions]);

  const table = useReactTable({
    data: rows, columns: allColumns, getRowId,
    state: { globalFilter, sorting, rowSelection, columnVisibility, pagination },
    onGlobalFilterChange: setGlobalFilter, onSortingChange: setSorting,
    onRowSelectionChange: setRowSelection, onColumnVisibilityChange: setColumnVisibility,
    onPaginationChange: setPagination,
    columnResizeMode: "onChange",
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getSortedRowModel: getSortedRowModel(),
    ...(virtual || manual ? {} : { getPaginationRowModel: getPaginationRowModel() }),
    enableRowSelection: !!bulkActions?.length,
  });

  const tableRows = table.getRowModel().rows;
  const selected = table.getSelectedRowModel().rows.map((r) => r.original);

  /* virtualizer (infinite-scroll mode) */
  const scrollRef = useRef(null);
  const virtualizer = useVirtualizer({
    count: virtual ? tableRows.length : 0,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 44,
    overscan: 12,
  });

  const saveView = (name) => {
    setViews((v) => ({ ...v, [name]: { globalFilter, sorting, columnVisibility } }));
    setCurrentView(name);
  };
  const applyView = (name) => {
    const v = views[name]; if (!v) return;
    setGlobalFilter(v.globalFilter || ""); setSorting(v.sorting || []);
    setColumnVisibility(v.columnVisibility || {}); setCurrentView(name);
  };
  const deleteView = (name) => {
    setViews((v) => { const n = { ...v }; delete n[name]; return n; });
    if (currentView === name) setCurrentView("");
  };

  const header = (
    <thead>
      {table.getHeaderGroups().map((hg) => (
        <tr key={hg.id}>
          {hg.headers.map((h) => (
            <th key={h.id} style={{ width: h.getSize() }}
              className={h.column.getCanSort() ? "sortable" : ""}
              onClick={h.column.getToggleSortingHandler()}>
              <span className="th-in">
                {flexRender(h.column.columnDef.header, h.getContext())}
                {{ asc: <ArrowUp size={12} />, desc: <ArrowDown size={12} /> }[h.column.getIsSorted()] || null}
              </span>
              {h.column.getCanResize() && (
                <span className="th-resize" onMouseDown={h.getResizeHandler()} onTouchStart={h.getResizeHandler()}
                  onClick={(e) => e.stopPropagation()} />
              )}
            </th>
          ))}
        </tr>
      ))}
    </thead>
  );

  const renderRow = (row) => (
    <tr key={row.id} className={`${row.getIsSelected() ? "sel" : ""} ${onRowClick ? "click" : ""}`}
      onClick={onRowClick ? () => onRowClick(row.original) : undefined}>
      {row.getVisibleCells().map((cell) => (
        <td key={cell.id} style={{ width: cell.column.getSize() }}>
          {flexRender(cell.column.columnDef.cell, cell.getContext())}
        </td>
      ))}
    </tr>
  );

  const colCount = table.getVisibleLeafColumns().length || 1;

  return (
    <div className="surface dtc">
      <div className="dt-toolbar">
        {leftTools}
        {searchable && (
          <div className="dt-search">
            <Search size={15} />
            <input type="text" value={globalFilter} placeholder={searchPlaceholder}
              onChange={(e) => setGlobalFilter(e.target.value)} />
          </div>
        )}
        <div className="spacer" style={{ flex: 1 }} />
        {tools}
        <ViewsMenu views={views} current={currentView} onSave={saveView} onApply={applyView} onDelete={deleteView} />
        <ColumnChooser table={table} />
      </div>

      {selected.length > 0 && (
        <div className="bulkbar">
          <b>{selected.length} selected</b>
          {bulkActions.map((a, i) => (
            <button key={i} className="dt-tool" onClick={() => { a.onClick(selected); setRowSelection({}); }}>
              {a.icon && <a.icon size={14} />}{a.label}
            </button>
          ))}
          <button className="dt-tool pill" onClick={() => setRowSelection({})}>Clear</button>
        </div>
      )}

      <div className="dt-scroll" ref={scrollRef} style={maxHeight ? { maxHeight } : undefined}>
        <table className="dt" style={{ minWidth: table.getTotalSize() }}>
          {header}
          <tbody>
            {loading ? (
              [...Array(8)].map((_, r) => (
                <tr key={r}>{[...Array(colCount)].map((_, c) => (
                  <td key={c}><div className="sk" style={{ width: c === 0 ? "70%" : `${40 + ((r + c) % 4) * 12}%` }} /></td>
                ))}</tr>
              ))
            ) : tableRows.length === 0 ? (
              <tr><td colSpan={colCount} style={{ padding: 0, borderBottom: "none" }}>
                <EmptyState icon={emptyIcon} title={emptyTitle} hint={emptyHint} action={emptyAction} />
              </td></tr>
            ) : virtual ? (
              <>
                {virtualizer.getVirtualItems().length > 0 && (
                  <tr style={{ height: virtualizer.getVirtualItems()[0].start }} aria-hidden="true"><td colSpan={colCount} style={{ padding: 0, border: "none", height: "inherit" }} /></tr>
                )}
                {virtualizer.getVirtualItems().map((vi) => renderRow(tableRows[vi.index]))}
                <tr style={{ height: Math.max(0, virtualizer.getTotalSize() - (virtualizer.getVirtualItems().at(-1)?.end || 0)) }} aria-hidden="true">
                  <td colSpan={colCount} style={{ padding: 0, border: "none", height: "inherit" }} />
                </tr>
              </>
            ) : (
              tableRows.map(renderRow)
            )}
          </tbody>
        </table>
      </div>

      {manual && manual.total != null && (
        /* stays visible during reloads/live refresh so paging never disappears */
        <div className="pager">
          <span>{(manual.total ?? 0).toLocaleString()} rows</span>
          <div className="pr">
            <span>Page {manual.page} of {Math.max(manual.pages, 1)}</span>
            <button className="pgbtn" disabled={manual.page <= 1} onClick={() => manual.onPage(manual.page - 1)}>‹</button>
            <button className="pgbtn" disabled={manual.page >= manual.pages} onClick={() => manual.onPage(manual.page + 1)}>›</button>
          </div>
        </div>
      )}
      {!manual && !virtual && !loading && tableRows.length > 0 && (
        <div className="pager">
          <span>{table.getFilteredRowModel().rows.length.toLocaleString()} rows</span>
          <div className="pr">
            <Select size="sm" value={pagination.pageSize}
              onChange={(e) => setPagination((p) => ({ ...p, pageSize: Number(e.target.value), pageIndex: 0 }))}>
              {[25, 50, 100].map((s) => <option key={s} value={s}>{s} / page</option>)}
            </Select>
            <span>Page {pagination.pageIndex + 1} of {Math.max(table.getPageCount(), 1)}</span>
            <button className="pgbtn" disabled={!table.getCanPreviousPage()} onClick={() => table.previousPage()}>‹</button>
            <button className="pgbtn" disabled={!table.getCanNextPage()} onClick={() => table.nextPage()}>›</button>
          </div>
        </div>
      )}
      {virtual && !loading && (
        <div className="pager"><span>{tableRows.length.toLocaleString()} rows · scrolling</span><span /></div>
      )}
    </div>
  );
}
