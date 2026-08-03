// Reply Management → Test Thread: paste a thread, run the exact engine, review
// the decision + drafted reply + follow-ups. Zero side effects (nothing sent).
import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { Badge, ErrorBox, Spinner, useApi } from "../components";

export default function ReplyTest() {
  const { wsParam, me } = useAuth();
  const { data: spaces } = useApi("/api/reply/workspaces", { workspace_id: wsParam });
  const [rwsId, setRwsId] = useState("");
  const [thread, setThread] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => { if (spaces?.length && !rwsId) setRwsId(String(spaces[0].id)); }, [spaces]);

  const run = async () => {
    setBusy(true); setError(""); setResult(null);
    try {
      setResult(await api("/api/reply/test-thread", { method: "POST",
        body: { reply_workspace_id: Number(rwsId), thread } }));
    } catch (e) { setError(e.message); }
    setBusy(false);
  };

  if (!me.is_master) return <ErrorBox msg="Master access required." />;

  return (
    <div style={{ maxWidth: 1000 }}>
      <p style={{ color: "var(--muted)", fontSize: 13, marginBottom: 14 }}>
        Paste an example email thread and generate the reply + follow-ups exactly as the system
        would for a real lead. <b>Nothing is sent, saved, or pushed</b> to Bison / Instantly.</p>

      <div className="field"><label>Reply space (uses its client profile, reply format, rules, AI provider)</label>
        <select value={rwsId} onChange={(e) => setRwsId(e.target.value)} style={{ width: "100%" }}>
          {(spaces || []).map((s) => <option key={s.id} value={s.id}>{s.name} ({s.platform}/{s.mode})</option>)}
        </select></div>
      <div className="field"><label>Email thread (paste the conversation — the prospect's latest reply matters most)</label>
        <textarea rows={10} style={{ width: "100%" }} value={thread} onChange={(e) => setThread(e.target.value)} placeholder="Paste the full thread here…" /></div>
      <button className="btn" disabled={busy || !thread.trim() || !rwsId} onClick={run}>{busy ? "Generating…" : "Generate reply"}</button>

      {error && <div style={{ marginTop: 14 }}><ErrorBox msg={error} /></div>}
      {busy && <Spinner />}
      {result && (
        <div className="section">
          <div className="card" style={{ padding: 16 }}>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 12 }}>
              <Badge tone="indigo">intent: {result.intent || "—"}</Badge>
              <Badge>confidence: {result.confidence || "—"}</Badge>
              <Badge tone={result.decision === "stop" ? "red" : result.decision === "send" ? "green" : "amber"}>decision: {result.decision}</Badge>
              {result.would_auto_send ? <Badge tone="green">would auto-send</Badge> : <Badge tone="amber">would go to review</Badge>}
              {!result.model_ran && <Badge tone="red">⚠ model didn't run (fallback)</Badge>}
            </div>
            {!result.model_ran && result.error && (
              <div className="error-box" style={{ fontSize: 12.5, marginBottom: 12 }}>
                <b>Why the model didn't run:</b> {result.error}
              </div>
            )}
            <h3 style={{ fontSize: 13, marginBottom: 6 }}>Drafted reply</h3>
            <div className="card" style={{ padding: 12, whiteSpace: "pre-wrap", fontSize: 13, background: "#fafbfc" }}>{result.reply || "—"}</div>
            {result.followups?.length > 0 && (
              <>
                <h3 style={{ fontSize: 13, margin: "14px 0 6px" }}>Follow-ups ({result.followups.length})</h3>
                {result.followups.map((f, i) => <div key={i} className="card" style={{ padding: 10, marginBottom: 6, fontSize: 12.5, whiteSpace: "pre-wrap" }}><b>FUP{i + 1}</b><br />{f}</div>)}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
