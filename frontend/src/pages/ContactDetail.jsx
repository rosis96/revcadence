// Contact detail, Calendly-style: header actions, All/Meetings/Emails/Notes tabs,
// an activity timeline grouped by date, and a right sidebar with Upcoming meetings
// (only future ones, auto-dropping as time passes) and a clean Details block.
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft, Briefcase, Building2, Calendar, Clock, FileText, Link2, Mail,
  MapPin, Phone, Plus,
} from "lucide-react";
import { api } from "../api";
import { useAppPath } from "../clientspace/appPath";
import { Area, Avatar, Button, ErrorBox, Spinner, useApi, useToast } from "../components";

const CAL = "https://calendly.com/rosis/new-meeting";
const dnum = (iso) => (iso ? new Date(iso) : null);
const dayKey = (d) => d.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
const isToday = (d) => d.toDateString() === new Date().toDateString();
const clock = (d) => d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
const kindIcon = (k = "") => (/meeting/.test(k) ? Calendar : /email|reply/.test(k) ? Mail : /note/.test(k) ? FileText : Clock);

const TABS = [["all", "All"], ["meetings", "Meetings"], ["emails", "Emails"], ["notes", "Notes"]];
const matchTab = (tab, k = "") =>
  tab === "all" ? true : tab === "meetings" ? /meeting/.test(k) : tab === "emails" ? /email|reply/.test(k) : /note/.test(k);

export default function ContactDetail() {
  const appTo = useAppPath();
  const { id } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const { data: c, error, loading, reload } = useApi(`/api/contacts/${id}`);
  const { data: tl, reload: reloadTl } = useApi(`/api/contacts/${id}/timeline`);
  const [tab, setTab] = useState("all");
  const [note, setNote] = useState("");
  const [det, setDet] = useState(null);

  useEffect(() => { if (c) setDet(c); }, [c]);
  if (loading || !c) return <Spinner />;
  if (error) return <ErrorBox msg={error} retry={reload} />;

  const items = (tl || []).filter((a) => matchTab(tab, a.kind));
  const groups = [];
  for (const a of items) {
    const d = dnum(a.at || a.occurred_at);
    const key = d ? (isToday(d) ? "Today" : dayKey(d)) : "Earlier";
    let g = groups.find((x) => x.key === key);
    if (!g) { g = { key, items: [] }; groups.push(g); }
    g.items.push(a);
  }

  const now = new Date();
  const upcoming = (c.meetings || [])
    .map((m) => ({ ...m, d: dnum(m.at) }))
    .filter((m) => m.d && m.d >= now)
    .sort((a, b) => a.d - b.d);

  const saveField = async (k, v) => {
    try { setDet(await api(`/api/contacts/${id}`, { method: "PUT", body: { [k]: v } })); }
    catch (e) { toast(e.message, "bad"); }
  };
  const addNote = async () => {
    if (!note.trim()) return;
    try {
      await api(`/api/activities`, { method: "POST", body: { contact_id: Number(id), kind: "note", title: "Note", body: note.trim() } });
      setNote(""); reloadTl(); toast("Note added");
    } catch (e) { toast(e.message, "bad"); }
  };

  const Row = ({ icon: Icon, label, value, field, placeholder, href }) => (
    <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 0", fontSize: 13.5 }}>
      <Icon size={15} style={{ color: "var(--muted)", flex: "0 0 auto" }} />
      <span style={{ color: "var(--muted)", width: 96, flex: "0 0 auto" }}>{label}</span>
      {field ? (
        <input defaultValue={value || ""} placeholder={placeholder || "Add"} key={value}
          onBlur={(e) => e.target.value !== (value || "") && saveField(field, e.target.value)}
          style={{ border: "1px solid transparent", borderRadius: 6, padding: "3px 6px", flex: 1, font: "inherit", fontSize: 13.5, background: "transparent" }}
          onFocus={(e) => (e.target.style.border = "1px solid var(--line-2,#d5d9e2)")}
          onBlurCapture={(e) => (e.target.style.border = "1px solid transparent")} />
      ) : href && value ? <a href={href} target="_blank" rel="noopener" style={{ flex: 1 }}>{value}</a>
        : <span style={{ flex: 1, color: value ? "var(--ink)" : "var(--blue-ink,#1d4ed8)" }}>{value || "+ Add"}</span>}
    </div>
  );

  return (
    <>
      <div className="page-head">
        <div style={{ flex: 1, minWidth: 0 }}>
          <button onClick={() => nav(appTo("/contacts"))} style={{ border: 0, background: "none", color: "var(--blue-ink,#1d4ed8)", cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 5, fontSize: 13, padding: 0, marginBottom: 8 }}>
            <ArrowLeft size={15} /> Contacts</button>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <Avatar name={c.name || c.email} size={40} />
            <h1 style={{ fontSize: 24, fontWeight: 700, margin: 0 }}>{c.name || c.email || "Contact"}</h1>
          </div>
        </div>
        <div className="acts">
          <Button variant="secondary" icon={Calendar} onClick={() => window.open(CAL, "_blank")}>Schedule</Button>
          <Button icon={Mail} onClick={() => (window.location.href = `mailto:${c.email || ""}`)}>Email</Button>
        </div>
      </div>

      <div className="doc-split">
        <div style={{ display: "grid", gap: 12 }}>
          <div style={{ display: "flex", gap: 4, borderBottom: "1px solid var(--line)", marginBottom: 2 }}>
            {TABS.map(([k, label]) => (
              <button key={k} onClick={() => setTab(k)}
                style={{ border: 0, background: "none", cursor: "pointer", padding: "10px 12px", fontSize: 14, fontWeight: 600,
                  color: tab === k ? "var(--ink)" : "var(--muted)", borderBottom: tab === k ? "2px solid var(--blue,#2563eb)" : "2px solid transparent" }}>
                {label}</button>
            ))}
          </div>

          {tab === "notes" && (
            <div className="card" style={{ padding: 16 }}>
              <Area size="md" value={note} onChange={(e) => setNote(e.target.value)} placeholder={`Write a note about ${c.name || "this contact"}...`}
                style={{ width: "100%", font: "inherit", fontSize: 14, border: "1px solid var(--line-2,#d5d9e2)", borderRadius: 8, padding: 10, resize: "vertical" }} />
              <div style={{ textAlign: "right", marginTop: 8 }}><Button size="sm" icon={Plus} onClick={addNote} disabled={!note.trim()}>Add note</Button></div>
            </div>
          )}

          {groups.length === 0 ? (
            <div className="card" style={{ padding: 40, textAlign: "center", color: "var(--muted)" }}>
              <FileText size={26} style={{ opacity: .4 }} /><div style={{ marginTop: 8 }}>Nothing here yet.</div>
            </div>
          ) : groups.map((g) => (
            <div key={g.key}>
              <div style={{ fontSize: 12.5, fontWeight: 700, color: "var(--muted)", margin: "8px 2px" }}>
                {g.key === "Today" && <span style={{ background: "var(--blue-soft,#eef3ff)", color: "var(--blue-ink,#1d4ed8)", borderRadius: 6, padding: "2px 8px", marginRight: 8 }}>Today</span>}
                {g.key === "Today" ? new Date().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" }) : g.key}
              </div>
              {g.items.map((a) => {
                const Ic = kindIcon(a.kind); const d = dnum(a.at || a.occurred_at);
                return (
                  <div key={a.id} className="card" style={{ padding: "12px 14px", marginBottom: 8, display: "flex", gap: 12, alignItems: "flex-start" }}>
                    <Ic size={16} style={{ color: "var(--muted)", marginTop: 2, flex: "0 0 auto" }} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
                        <div style={{ fontWeight: 600, fontSize: 14 }}>{a.title || a.kind?.replaceAll("_", " ")}</div>
                        {d && <div style={{ color: "var(--muted)", fontSize: 12.5, flex: "0 0 auto" }}>{clock(d)}</div>}
                      </div>
                      {a.body && <div style={{ color: "var(--ink-2,#3b4557)", fontSize: 13.5, marginTop: 4, whiteSpace: "pre-wrap" }}>{a.body}</div>}
                    </div>
                  </div>
                );
              })}
            </div>
          ))}
        </div>

        <div className="doc-side" style={{ display: "grid", gap: 12 }}>
          <div className="card" style={{ padding: 16 }}>
            <h3 style={{ fontSize: 13, margin: "0 0 10px" }}>Upcoming meetings</h3>
            {upcoming.length === 0 ? (
              <div style={{ border: "1px dashed var(--line-2,#d5d9e2)", borderRadius: 8, padding: 18, textAlign: "center", color: "var(--muted)", fontSize: 13 }}>
                No upcoming meetings</div>
            ) : upcoming.map((m) => (
              <div key={m.id} style={{ padding: "8px 0", borderTop: "1px solid var(--line)", fontSize: 13.5 }}>
                <div style={{ fontWeight: 600 }}>{m.title}</div>
                <div style={{ color: "var(--muted)", fontSize: 12.5 }}>{m.d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" })} · {clock(m.d)}</div>
              </div>
            ))}
          </div>

          <div className="card" style={{ padding: 16 }}>
            <h3 style={{ fontSize: 13, margin: "0 0 6px" }}>Details</h3>
            <Row icon={Mail} label="Email" value={c.email} />
            <Row icon={Phone} label="Phone" field="phone" value={det?.phone} />
            <Row icon={Clock} label="Time zone" field="timezone" value={det?.timezone} />
            <Row icon={Building2} label="Company" value={c.company_name} href={c.company_id ? `#/companies/${c.company_id}` : undefined} />
            <Row icon={Briefcase} label="Job title" field="title" value={det?.title} />
            <Row icon={Link2} label="LinkedIn" field="linkedin_url" value={det?.linkedin_url} />
            <Row icon={MapPin} label="Location" field="location" value={det?.location} />
          </div>
        </div>
      </div>
    </>
  );
}
