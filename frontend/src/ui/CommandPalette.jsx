/* Global search / command palette (⌘K). Searches every entity via /api/search
   plus static navigation actions. Keyboard-first: arrows + Enter, Esc closes. */
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowRight, Building2, Contact as ContactIcon, FileText, Handshake, Inbox,
  Receipt, Rows3, ScrollText, Search,
} from "lucide-react";
import { api } from "../api";
import { useDebounced } from "./index";

const TYPE_META = {
  action:    { label: "Go to",      icon: ArrowRight },
  company:   { label: "Companies",  icon: Building2 },
  contact:   { label: "Contacts",   icon: ContactIcon },
  deal:      { label: "Deals",      icon: Handshake },
  blueprint: { label: "Blueprints", icon: FileText },
  agreement: { label: "Agreements", icon: ScrollText },
  invoice:   { label: "Invoices",   icon: Receipt },
  reply:     { label: "Replies",    icon: Inbox },
  document:  { label: "Documents",  icon: FileText },
};

const NAV_ACTIONS = [
  ["Master Dashboard", "/"], ["Pipeline", "/pipeline"], ["Companies", "/companies"],
  ["Contacts", "/contacts"], ["Clients", "/clients"], ["Enrichment Lists", "/enrichment"],
  ["Enrichment Database", "/enrichment/database"], ["Reply Inbox", "/reply/inbox"],
  ["Reply Dashboard", "/reply"], ["Blueprints & Agreements", "/blueprints"],
  ["Website Visitors", "/inbound"], ["Jobs", "/jobs"], ["Settings", "/settings"],
].map(([title, href]) => ({ type: "action", id: href, title, href }));

export function CommandPalette({ open, onClose }) {
  const [q, setQ] = useState("");
  const [remote, setRemote] = useState([]);
  const [busy, setBusy] = useState(false);
  const [idx, setIdx] = useState(0);
  const dq = useDebounced(q, 150);
  const nav = useNavigate();
  const inputRef = useRef(null);

  useEffect(() => { if (open) { setQ(""); setRemote([]); setIdx(0); setTimeout(() => inputRef.current?.focus(), 30); } }, [open]);

  useEffect(() => {
    if (!open || dq.trim().length < 2) { setRemote([]); return; }
    let dead = false;
    setBusy(true);
    api("/api/search", { params: { q: dq } })
      .then((r) => { if (!dead) setRemote(r.results || []); })
      .catch(() => { if (!dead) setRemote([]); })
      .finally(() => { if (!dead) setBusy(false); });
    return () => { dead = true; };
  }, [dq, open]);

  const items = useMemo(() => {
    const ql = q.trim().toLowerCase();
    const actions = ql
      ? NAV_ACTIONS.filter((a) => a.title.toLowerCase().includes(ql)).slice(0, 5)
      : NAV_ACTIONS.slice(0, 6);
    return [...actions, ...remote];
  }, [q, remote]);

  const grouped = useMemo(() => {
    const g = [];
    for (const it of items) {
      const last = g[g.length - 1];
      if (last && last.type === it.type) last.items.push(it);
      else g.push({ type: it.type, items: [it] });
    }
    return g;
  }, [items]);

  useEffect(() => { setIdx(0); }, [items.length, q]);

  const go = (it) => { if (!it) return; onClose(); nav(it.href); };

  const onKey = (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setIdx((i) => Math.min(i + 1, items.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setIdx((i) => Math.max(i - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); go(items[idx]); }
    else if (e.key === "Escape") onClose();
  };

  if (!open) return null;
  let flat = -1;
  return (
    <div className="cp-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="cp" role="dialog" aria-label="Global search">
        <div className="cp-in">
          <Search size={16} />
          <input ref={inputRef} value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={onKey}
            placeholder="Search companies, contacts, deals, replies, documents…" />
          {busy && <span className="ui-btn-spin dark" />}
          <kbd className="ui-kbd">esc</kbd>
        </div>
        <div className="cp-list">
          {items.length === 0 && (
            <div className="cp-none">{q.trim().length >= 2 ? "No results" : "Type to search everything, or jump to a page"}</div>
          )}
          {grouped.map((g) => {
            const meta = TYPE_META[g.type] || TYPE_META.document;
            return (
              <div key={g.type + g.items[0]?.id}>
                <div className="cp-gh">{meta.label}</div>
                {g.items.map((it) => {
                  flat += 1;
                  const i = flat;
                  const Icon = meta.icon;
                  return (
                    <button key={`${it.type}:${it.id}`} className={`cp-row ${i === idx ? "on" : ""}`}
                      onMouseEnter={() => setIdx(i)} onClick={() => go(it)}>
                      <span className="cp-ic"><Icon size={15} /></span>
                      <span className="cp-title">{it.title}</span>
                      {it.subtitle && <span className="cp-sub">{it.subtitle}</span>}
                    </button>
                  );
                })}
              </div>
            );
          })}
        </div>
        <div className="cp-foot"><span><kbd className="ui-kbd">↑↓</kbd> navigate</span><span><kbd className="ui-kbd">↵</kbd> open</span></div>
      </div>
    </div>
  );
}
