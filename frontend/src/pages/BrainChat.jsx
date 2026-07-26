// Ask the brain — a ChatGPT-style panel grounded in the workspace's Client Brain.
// Answers from the brain, and LEARNS new facts you tell it (saved + deduped).
import { useEffect, useRef, useState } from "react";
import { Send, Sparkles } from "lucide-react";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorBox, PageHeader, useToast } from "../components";

export default function BrainChat() {
  const { wsParam, me } = useAuth();
  const wsId = wsParam || (!me?.is_master ? me?.workspaces?.[0]?.id : null);
  const toast = useToast();
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef(null);
  const taRef = useRef(null);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages, busy]);
  // auto-grow the input with its content (up to a max), then scroll — like Claude/ChatGPT
  useEffect(() => {
    const el = taRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 320)}px`;
  }, [input]);

  if (!wsId) return <ErrorBox msg="Pick a specific workspace (top-left) — the brain is per client workspace." />;

  const send = async () => {
    const text = input.trim();
    if (!text || busy) return;
    const next = [...messages, { role: "user", content: text }];
    setMessages(next); setInput(""); setBusy(true);
    try {
      const r = await api(`/api/enrich-lists/config/${wsId}/brain-chat`, { method: "POST", body: { messages: next } });
      setMessages((m) => [...m, { role: "assistant", content: r.reply, learned: r.learned }]);
      if (r.learned?.length) toast(`Added to the brain: ${r.learned.join(", ")}`);
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
        toast(`Saved to brain: ${r.saved.join(", ")}`);
        setMessages((m) => [...m, { role: "assistant", content: `✅ Saved to the brain: ${r.saved.join(", ")}. It now has ${r.counts.case_studies} case studies, ${r.counts.services} services, ${r.counts.metrics} metrics.`, learned: r.saved }]);
      } else {
        toast("Nothing new to save from this conversation", "bad");
      }
    } catch (e) { toast(e.message, "bad"); } finally { setBusy(false); }
  };

  const buildFormats = async () => {
    if (busy) return;
    const instructions = messages.filter((m) => m.role === "user").map((m) => m.content).join("\n\n").trim();
    if (!instructions) { toast("Explain your formats in the chat first", "bad"); return; }
    if (!confirm("Apply this conversation to your formats? It updates the variables you described (e.g. value proposition) and keeps the rest. Review/edit on the Formats tab afterward.")) return;
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

  const suggestions = [
    "What's our angle for a manufacturing CFO?",
    "Draft a cold email for a real-estate CEO using a relevant case study.",
    "Summarize our strongest proof points.",
  ];

  return (
    <>
      <PageHeader title="Ask the brain" desc="Chat with this client's knowledge base. Save what you paste, or build formats from it."
        actions={<div style={{ display: "flex", gap: 8 }}>
          <button className="btn secondary" disabled={busy || !messages.length} onClick={buildFormats}
            style={{ display: "flex", alignItems: "center", gap: 6 }}><Sparkles size={15} /> Build formats</button>
          <button className="btn" disabled={busy || !messages.length} onClick={saveToBrain}
            style={{ display: "flex", alignItems: "center", gap: 6 }}><Sparkles size={15} /> Save to brain</button>
        </div>} />
      <div className="card" style={{ padding: 0, display: "flex", flexDirection: "column", height: "70vh", overflow: "hidden" }}>
        <div style={{ flex: 1, overflowY: "auto", padding: 18, display: "flex", flexDirection: "column", gap: 12 }}>
          {messages.length === 0 && (
            <div style={{ margin: "auto", textAlign: "center", maxWidth: 460 }}>
              <Sparkles size={26} style={{ color: "var(--primary)" }} />
              <div style={{ fontWeight: 600, marginTop: 8 }}>Ask anything about this client — or teach it something new.</div>
              <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 4, marginBottom: 12 }}>
                It answers from the Client Brain. To <b>train it</b>, paste material (case studies, services, metrics)
                and click <b>Save to brain</b> — everything gets extracted and stored permanently.</div>
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
                background: m.role === "user" ? "var(--primary)" : "#f2f5f9", color: m.role === "user" ? "#fff" : "#20303f",
              }}>{m.content}</div>
              {m.learned?.length ? (
                <div style={{ fontSize: 11, color: "#15803d", marginTop: 3 }}>✓ saved to brain: {m.learned.join(", ")}</div>
              ) : null}
            </div>
          ))}
          {busy && <div style={{ alignSelf: "flex-start", fontSize: 12.5, color: "var(--muted)" }}>Thinking…</div>}
          <div ref={endRef} />
        </div>
        <div style={{ borderTop: "1px solid #e6edf5", padding: 12, display: "flex", gap: 8, alignItems: "flex-end" }}>
          <textarea ref={taRef} rows={1} value={input} onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
            placeholder="Ask about the client, draft outreach, or paste a new case study to save…"
            style={{ flex: 1, resize: "none", padding: "10px 12px", borderRadius: 8, border: "1px solid #d9e2ec",
              fontSize: 13.5, lineHeight: 1.5, minHeight: 44, maxHeight: 320, overflowY: "auto", fontFamily: "inherit" }} />
          <button className="btn" disabled={busy || !input.trim()} onClick={send}
            style={{ display: "flex", alignItems: "center", gap: 6 }}><Send size={15} /> Send</button>
        </div>
      </div>
    </>
  );
}
