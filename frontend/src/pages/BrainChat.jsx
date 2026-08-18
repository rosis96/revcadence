import { confirmDialog } from "../components";
// Ask the brain — a ChatGPT-style panel grounded in the workspace's Client Brain.
// Answers from the brain, and LEARNS new facts you tell it (saved + deduped).
import { useEffect, useRef, useState } from "react";
import { Send, Sparkles } from "lucide-react";
import { api } from "../api";
import { useAuth } from "../auth";
import { Area, ErrorBox, PageHeader, useToast } from "../components";

export default function BrainChat() {
  const { wsParam, me } = useAuth();
  const wsId = wsParam || (!me?.is_master ? me?.workspaces?.[0]?.id : null);
  const toast = useToast();
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef(null);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, busy]);
  // The composer is a fixed three rows and scrolls past that, like every other
  // textarea in the app — the hand-rolled auto-grow that used to live here is gone.

  if (!wsId) return <ErrorBox msg="Pick a specific workspace (top-left) — the brain is per client workspace." />;

  const send = async () => {
    const text = input.trim();
    if (!text || busy) return;
    const next = [...messages, { role: "user", content: text }];
    setMessages(next); setInput(""); setBusy(true);
    try {
      const r = await api(`/api/enrich-lists/config/${wsId}/brain-chat`, { method: "POST", body: { messages: next } });
      setMessages((m) => [...m, { role: "assistant", content: r.reply, learned: r.learned }]);
      if (r.learned?.length) toast(`Brain updated: ${r.learned.join(", ")}`);
    } catch (e) {
      setMessages((m) => [...m, { role: "assistant", content: `⚠️ ${e.message}` }]);
    } finally { setBusy(false); }
  };

  const saveToBrain = async () => {
    if (!messages.length || busy) return;
    setBusy(true);
    try {
      const r = await api(`/api/enrich-lists/config/${wsId}/brain-learn`, { method: "POST", body: { messages } });
      if (r.saved?.length) {
        toast(`Brain updated: ${r.saved.join(", ")}`);
        setMessages((m) => [...m, { role: "assistant", content: `✅ Updated the brain: ${r.saved.join(", ")}. New facts were added and matching saved records were enriched. It now has ${r.counts.case_studies} case studies, ${r.counts.services} services, ${r.counts.metrics} metrics.`, learned: r.saved }]);
      } else {
        toast("Nothing new to save from this conversation", "bad");
      }
    } catch (e) { toast(e.message, "bad"); } finally { setBusy(false); }
  };

  const buildFormats = async () => {
    if (busy) return;
    const instructions = messages.filter((m) => m.role === "user").map((m) => m.content).join("\n\n").trim();
    if (!instructions) { toast("Explain your formats in the chat first", "bad"); return; }
    if (!await confirmDialog("Apply this conversation to your formats? It updates the variables you described (e.g. value proposition) and keeps the rest. Review/edit on the Formats tab afterward.")) return;
    setBusy(true);
    try {
      // merge=true (default): revise only the variables discussed, keep everything else as saved
      const r = await api(`/api/enrich-lists/config/${wsId}/build-formats`, { method: "POST", body: { instructions } });
      await api(`/api/enrich-lists/config/${wsId}`, { method: "PUT", body: { formats: r.formats } });
      const did = r.merged ? `Updated ${r.updated.length} variable(s): ${r.updated.join(", ")}` : `Built ${r.count} format variables`;
      toast(`${did} — review on the Formats tab`);
      setMessages((m) => [...m, { role: "assistant", content: `✅ ${did} from what you explained${r.merged ? " (your other variables were kept)" : ""} and saved. Open the Formats tab to review and tweak.`, learned: ["formats"] }]);
    } catch (e) { toast(e.message, "bad"); } finally { setBusy(false); }
  };

  const saveAsRule = async () => {
    if (!messages.length || busy) return;
    setBusy(true);
    try {
      const r = await api(`/api/enrich-lists/config/${wsId}/append-rules`, { method: "POST", body: { messages } });
      if (r.added?.length) {
        toast(`Added ${r.added.length} global rule(s)`);
        setMessages((m) => [...m, { role: "assistant", content: `✅ Added to your global Rules — obeyed on every email:\n• ${r.added.join("\n• ")}`, learned: ["rules"] }]);
      } else { toast("No new global rules found in this chat", "bad"); }
    } catch (e) { toast(e.message, "bad"); } finally { setBusy(false); }
  };

  const updateIcp = async () => {
    if (!messages.length || busy) return;
    setBusy(true);
    try {
      const r = await api(`/api/enrich-lists/config/${wsId}/update-icp`, { method: "POST", body: { messages } });
      if (r.appended_prose) {
        toast("Added to your written ICP guidance");
        setMessages((m) => [...m, { role: "assistant", content: "✅ Appended this to your written ICP guidance (kept your prose intact). Review it on the ICP / Non-ICP tab.", learned: ["icp"] }]);
        return;
      }
      const a = r.added || {}, parts = [];
      if (a.categories?.length) parts.push(`${a.categories.length} fit type(s)`);
      if (a.rejects?.length) parts.push(`${a.rejects.length} reject rule(s)`);
      if (a.steps?.length) parts.push(`${a.steps.length} step(s)`);
      if (a.default) parts.push(`default → ${a.default}`);
      if (parts.length) {
        toast(`ICP updated: ${parts.join(", ")}`);
        setMessages((m) => [...m, { role: "assistant", content: `✅ Updated the ICP (added these, kept the rest): ${parts.join(", ")}. Review on the ICP / Non-ICP tab.`, learned: ["icp"] }]);
      } else { toast("No new ICP signals found in this chat", "bad"); }
    } catch (e) { toast(e.message, "bad"); } finally { setBusy(false); }
  };

  const suggestions = [
    "What's our angle for a manufacturing CFO?",
    "Draft a cold email for a real-estate CEO using a relevant case study.",
    "Summarize our strongest proof points.",
  ];

  return (
    <div className="brain-page">
      <PageHeader title="Ask the brain" desc="Teach company knowledge → update the brain · describe a variable → build that format · describe fit criteria → update ICP."
        actions={<div style={{ display: "flex", gap: 8, flexWrap: "wrap", justifyContent: "flex-end" }}>
          <button className="btn ghost" disabled={busy || !messages.length} onClick={saveAsRule}
            style={{ display: "flex", alignItems: "center", gap: 6 }} title="Turn cross-variable / global instructions into global Rules (obeyed on every email)"><Sparkles size={15} /> Save as rule</button>
          <button className="btn ghost" disabled={busy || !messages.length} onClick={updateIcp}
            style={{ display: "flex", alignItems: "center", gap: 6 }} title="Add the fit / reject signals you described to the ICP (keeps the rest)"><Sparkles size={15} /> Update ICP</button>
          <button className="btn secondary" disabled={busy || !messages.length} onClick={buildFormats}
            style={{ display: "flex", alignItems: "center", gap: 6 }} title="Update the variables you described (keeps the rest)"><Sparkles size={15} /> Build formats</button>
          <button className="btn" disabled={busy || !messages.length} onClick={saveToBrain}
            style={{ display: "flex", alignItems: "center", gap: 6 }} title="Save company knowledge (case studies, services, metrics)"><Sparkles size={15} /> Save to brain</button>
        </div>} />
      <div className="brain-chat">
        <div className="brain-scroll">
          <div className="brain-col">
            {messages.length === 0 && (
              <div style={{ margin: "auto", textAlign: "center", maxWidth: 460 }}>
                <Sparkles size={26} style={{ color: "var(--primary)" }} />
                <div style={{ fontWeight: 600, marginTop: 8 }}>Ask anything about this client — or teach it something new.</div>
                <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 4, marginBottom: 12 }}>
                  It answers from the Client Brain. To <b>train it</b>, paste material (case studies, services, metrics)
                  and click <b>Save to brain</b>. New facts are added, corrections update saved fields, and extra
                  details enrich the matching case study or problem. The section buttons build only that section.</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {suggestions.map((s) => (
                    <button key={s} className="btn ghost sm" style={{ textAlign: "left" }} onClick={() => setInput(s)}>{s}</button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} style={{ alignSelf: m.role === "user" ? "flex-end" : "flex-start", maxWidth: "78%" }}>
                <div style={{
                  padding: "10px 13px", borderRadius: 12, fontSize: 13.5, lineHeight: 1.5, whiteSpace: "pre-wrap",
                  background: m.role === "user" ? "var(--primary)" : "var(--card-2)", color: m.role === "user" ? "#fff" : "var(--text)",
                }}>{m.content}</div>
                {m.learned?.length ? (
                  <div style={{ fontSize: 11, color: "var(--ok-text)", marginTop: 3 }}>✓ brain updated: {m.learned.join(", ")}</div>
                ) : null}
              </div>
            ))}
            {busy && <div style={{ alignSelf: "flex-start", fontSize: 12.5, color: "var(--muted)" }}>Thinking…</div>}
            <div ref={endRef} />
          </div>
        </div>
        <div className="brain-composer">
          <div>
            <Area size="sm" value={input} onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
              placeholder="Ask about the client, draft outreach, or paste a new case study to save…"
              style={{ flex: 1, padding: "10px 12px", borderRadius: 8, border: "1px solid var(--border)",
                fontSize: 13.5, lineHeight: 1.5, fontFamily: "inherit" }} />
            <button className="btn" disabled={busy || !input.trim()} onClick={send}
              style={{ display: "flex", alignItems: "center", gap: 6 }}><Send size={15} /> Send</button>
          </div>
        </div>
      </div>
    </div>
  );
}
