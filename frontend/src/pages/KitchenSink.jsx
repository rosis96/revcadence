/* /dev/kitchen-sink — every design-system component in every state.
   Dev QA page: if a component drifts visually, it shows up here first. */
import { useMemo, useState } from "react";
import { AnimatePresence } from "framer-motion";
import { Download, Mail, Plus, Trash2 } from "lucide-react";
import {
  ActivityFeed, Avatar, Badge, Breadcrumbs, Button, Card, ConfirmDialog, DataTable,
  Drawer, EmptyState, FilterPanel, IconButton, Modal, PageHeader, Pager, SearchInput,
  Skeleton, StatCard, StatusPill, Tabs, Timeline, Tooltip, useToast,
} from "../components";

const NAMES = ["Cleo Murnane", "Nick Balster", "Craig Shimahara", "Jane Doe", "Sam Roy", "Ana Villa", "Leo Park", "Mia Chen"];
const STATUSES = [["green", "Active"], ["blue", "In review"], ["amber", "Waiting"], ["red", "Stopped"], ["gray", "Draft"]];

function demoRows(n) {
  return [...Array(n)].map((_, i) => ({
    id: i + 1,
    name: NAMES[i % NAMES.length],
    company: ["Studio Murnane", "Custom Electric", "Shimahara Illustration", "Acme Co"][i % 4],
    email: `person${i + 1}@example.com`,
    status: STATUSES[i % STATUSES.length],
    value: Math.round(1000 + (i * 937) % 9000),
  }));
}

export default function KitchenSink() {
  const toast = useToast();
  const [tab, setTab] = useState("a");
  const [drawer, setDrawer] = useState(false);
  const [modal, setModal] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState({ status: ["active"] });
  const [big, setBig] = useState(false);

  const rows = useMemo(() => demoRows(big ? 1000 : 12), [big]);
  const columns = useMemo(() => [
    { accessorKey: "name", header: "Name", size: 200,
      cell: ({ row }) => (
        <div className="co"><Avatar name={row.original.name} size={26} />
          <div><div className="lead-nm">{row.original.name}</div><div className="lead-sub">{row.original.email}</div></div>
        </div>) },
    { accessorKey: "company", header: "Company", size: 180 },
    { accessorKey: "status", header: "Status", size: 130,
      cell: ({ getValue }) => { const [tone, label] = getValue(); return <StatusPill tone={tone}>{label}</StatusPill>; },
      sortingFn: (a, b) => a.original.status[1].localeCompare(b.original.status[1]) },
    { accessorKey: "value", header: "Value", size: 100, cell: ({ getValue }) => `$${getValue().toLocaleString()}` },
  ], []);

  return (
    <>
      <Breadcrumbs items={[{ label: "Dev", href: "/" }, { label: "Kitchen sink" }]} />
      <PageHeader title="Kitchen sink" desc="Every design-system component in every state. If it looks wrong here, it is wrong everywhere." />

      <section className="section"><h2>Buttons</h2>
        <Card style={{ padding: 20, display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
          <Button icon={Plus}>Primary</Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="danger" icon={Trash2}>Danger</Button>
          <Button loading>Loading</Button>
          <Button disabled>Disabled</Button>
          <Button size="sm">Small</Button>
          <IconButton icon={Mail} label="Mail" />
          <Tooltip tip="Tooltips are pure CSS"><Button variant="ghost">Hover me</Button></Tooltip>
        </Card>
      </section>

      <section className="section"><h2>Pills, badges, avatars</h2>
        <Card style={{ padding: 20, display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
          {STATUSES.map(([t, l]) => <StatusPill key={t} tone={t}>{l}</StatusPill>)}
          <Badge>default</Badge><Badge tone="indigo">indigo</Badge><Badge tone="green">green</Badge>
          <Avatar name="Cleo Murnane" /><Avatar name="Rosis Sitoula" size={36} />
        </Card>
      </section>

      <section className="section"><h2>Stat cards</h2>
        <div className="metrics">
          <StatCard label="Revenue" value="$36,000" delta={12} sub="vs last month" />
          <StatCard label="Meetings booked" value="14" delta={-8} sub="vs last month" />
          <StatCard label="Replies" value="312" sub="30 days" />
          <StatCard label="Open pipeline" value="$120k" />
        </div>
      </section>

      <section className="section"><h2>Tabs, search, pagination</h2>
        <Card style={{ padding: 20, display: "grid", gap: 16 }}>
          <Tabs value={tab} onChange={setTab} tabs={[
            { key: "a", label: "Needs review", count: 4 }, { key: "b", label: "Replied", count: 41 }, { key: "c", label: "Stopped" }]} />
          <SearchInput value={search} onChange={setSearch} placeholder="Search anything…" kbd="⌘K" />
          <Pager page={2} pages={9} total={412} pageSize={50} onPage={() => {}} onPageSize={() => {}} />
        </Card>
      </section>

      <section className="section"><h2>Overlays & feedback</h2>
        <Card style={{ padding: 20, display: "flex", gap: 10, flexWrap: "wrap" }}>
          <Button variant="secondary" onClick={() => setDrawer(true)}>Open drawer</Button>
          <Button variant="secondary" onClick={() => setModal(true)}>Open modal</Button>
          <Button variant="secondary" onClick={() => setConfirm(true)}>Confirm dialog</Button>
          <Button variant="secondary" onClick={() => toast("Saved successfully")}>Toast · ok</Button>
          <Button variant="secondary" onClick={() => toast("Something went wrong", "bad")}>Toast · error</Button>
        </Card>
      </section>

      <section className="section"><h2>Loading & empty</h2>
        <div className="grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
          <Card style={{ padding: 20, display: "grid", gap: 10 }}>
            <Skeleton w="60%" /><Skeleton /><Skeleton w="80%" /><Skeleton w="40%" h={28} />
          </Card>
          <Card><EmptyState title="No agreements yet" hint="When a client signs, the agreement shows up here."
            action={<Button icon={Plus}>New agreement</Button>} /></Card>
        </div>
      </section>

      <section className="section"><h2>Filter panel + timeline + feed</h2>
        <div className="grid" style={{ gridTemplateColumns: "260px 1fr 1fr", alignItems: "start" }}>
          <FilterPanel
            groups={[
              { key: "status", label: "Status", options: [
                { value: "active", label: "Active", count: 12 }, { value: "draft", label: "Draft", count: 4 },
                { value: "stopped", label: "Stopped", count: 2 }] },
              { key: "owner", label: "Owner", options: [
                { value: "me", label: "Me" }, { value: "team", label: "Team" }] },
            ]}
            values={filters}
            onChange={(k, v) => setFilters((f) => ({ ...f, [k]: v }))}
            onClear={() => setFilters({})} />
          <Card style={{ padding: 20 }}>
            <Timeline items={[
              { id: 1, title: "Blueprint viewed by client", kind: "view", at: "2026-07-15T10:00:00" },
              { id: 2, title: "Agreement signed", kind: "signature", at: "2026-07-14T18:30:00" }]} />
          </Card>
          <Card style={{ padding: 20 }}>
            <ActivityFeed items={[
              { id: 1, actor: "Cleo Murnane", title: "Replied: interested", subtitle: "Reply", at: "2026-07-15T10:00:00" },
              { id: 2, actor: "System", title: "Follow-up 2 queued", subtitle: "Automation", at: "2026-07-15T08:00:00" }]} />
          </Card>
        </div>
      </section>

      <section className="section">
        <h2>THE DataTable {" "}
          <label style={{ fontWeight: 400, textTransform: "none", letterSpacing: 0 }}>
            <input type="checkbox" checked={big} onChange={(e) => setBig(e.target.checked)} /> 1,000 rows (virtualized)
          </label>
        </h2>
        <DataTable
          id="kitchen-sink" columns={columns} data={rows}
          searchPlaceholder="Search people…"
          onRowClick={(r) => toast(`Opened ${r.name}`)}
          bulkActions={[
            { label: "Export", icon: Download, onClick: (sel) => toast(`Exported ${sel.length} rows`) },
            { label: "Delete", icon: Trash2, onClick: (sel) => toast(`Deleted ${sel.length} rows`, "bad") },
          ]}
          emptyTitle="No people found" emptyHint="Try clearing the search."
          maxHeight={480}
        />
      </section>

      <AnimatePresence>
      {drawer && <Drawer key="drawer" title="Drawer title" onClose={() => setDrawer(false)}>
        <p style={{ color: "var(--muted)", fontSize: 13.5 }}>Right-side drawer: the default for quick views. 480px, Esc to close.</p>
      </Drawer>}
      </AnimatePresence>
      <AnimatePresence>
      {modal && <Modal key="modal" title="Modal title" onClose={() => setModal(false)}>
        <p style={{ color: "var(--muted)", fontSize: 13.5 }}>Use sparingly; prefer the Drawer.</p>
        <div className="actions"><Button variant="ghost" onClick={() => setModal(false)}>Close</Button></div>
      </Modal>}
      </AnimatePresence>
      <AnimatePresence>
      {confirm && <ConfirmDialog key="confirm" danger title="Delete 3 contacts?" message="This can't be undone. The contacts and their activity history will be removed."
        confirmLabel="Delete" onConfirm={() => toast("Deleted", "bad")} onClose={() => setConfirm(false)} />}
      </AnimatePresence>
    </>
  );
}
