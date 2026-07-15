// Blueprint editor: paste a Fathom transcript to (re)generate the client page,
// edit the title/slug, publish, and copy the public per-client link
// (blueprint.<domain>/{slug}). Internal notes stay here; the client page never shows them.
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { Badge, ErrorBox, Spinner, useApi } from "../components";

export default function BlueprintDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const { data, error, loading, reload } = useApi(`/api/documents/${id}`);
  const [d, setD] = useState(null);
  const [transcript, setTranscript] = useState("");
  const [busy, setBusy] = useState("");
  const [copied, setCopied] = useState(false);

  useEffect(() => { if (data) setD(data); }, [data]);
  if (loading || !d) return <Spinner />;
  if (error) return <ErrorBox msg={error} retry={reload} />;

  // Public URL — prefer a blueprint.<domain> host if we're on engine.<domain>.
  const host = window.location.host;
  const bpHost = host.startsWith("engine.") ? host.replace(/^engine\./, "blueprint.") : "";
  const publicUrl = bpHost ? `https://${bpHost}/${d.slug}` : `${window.location.origin}/p/${d.slug}`;

  const patch = async (body, key) => {
    setBusy(key);
    try { setD(await api(`/api/documents/${id}`, { method: "PUT", body })); }
    catch (e) { alert(e.message); }
    setBusy("");
  };
  const regenerate = async () => {
    if (!transcript.trim()) { alert("Paste the call transcript first."); return; }
    setBusy("gen");
    try { setD(await api("/api/blueprints/from-transcript", { method: "POST", body: { doc_id: Number(id), transcript } })); setTranscript(""); }
    catch (e) { alert(e.message); }
    setBusy("");
  };
  const copy = () => { navigator.clipboard?.writeText(publicUrl); setCopied(true); setTimeout(() => setCopied(false), 1500); };
  const remove = async () => {
    if (!confirm("Delete this blueprint? This cannot be undone.")) return;
    try { await api(`/api/documents/${id}`, { method: "DELETE" }); nav("/blueprints"); }
    catch (e) { alert(e.message); }
  };

  const notes = d.fields?.notes_for_ascendly || "";

  return (
    <div style={{ maxWidth: 1100 }}>
      <div className="toolbar">
        <input value={d.title} onChange={(e) => setD({ ...d, title: e.target.value })}
               onBlur={() => patch({ title: d.title }, "title")}
               style={{ fontSize: 16, fontWeight: 600, border: "none", background: "transparent", minWidth: 360 }} />
        <Badge>{d.kind}</Badge>
        <Badge tone={d.published ? "green" : "amber"}>{d.published ? "published" : d.status}</Badge>
        <div className="spacer" />
        <button className="btn danger sm" onClick={remove}>Delete</button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "360px 1fr", gap: 16 }}>
        <div>
          <div className="card" style={{ padding: 14, marginBottom: 12 }}>
            <label style={{ fontSize: 12.5, fontWeight: 600 }}>Build from Fathom transcript</label>
            <p style={{ fontSize: 12, color: "var(--muted)", margin: "3px 0 6px" }}>
              Paste the call transcript (or Fathom chat/summary). Every section is generated from what was said;
              pricing is used only if it came up on the call.</p>
            <textarea rows={8} style={{ width: "100%", fontFamily: "monospace", fontSize: 12 }}
                      value={transcript} onChange={(e) => setTranscript(e.target.value)}
                      placeholder="Paste the Fathom transcript here…" />
            <button className="btn" style={{ marginTop: 8, width: "100%" }} disabled={busy === "gen"} onClick={regenerate}>
              {busy === "gen" ? "Generating…" : "⚡ Generate blueprint"}</button>
            <div style={{ fontSize: 11.5, color: "var(--muted)", marginTop: 6 }}>
              Generator: {d.fields?.generator || "—"}</div>
          </div>

          <div className="card" style={{ padding: 14, marginBottom: 12 }}>
            <label style={{ fontSize: 12.5, fontWeight: 600 }}>Public link</label>
            <div className="field" style={{ margin: "6px 0 0" }}>
              <label>URL slug</label>
              <input value={d.slug} onChange={(e) => setD({ ...d, slug: e.target.value })}
                     onBlur={() => patch({ slug: d.slug }, "slug")} style={{ width: "100%", fontFamily: "monospace", fontSize: 12.5 }} />
            </div>
            <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8 }}>
              <input readOnly value={publicUrl} onFocus={(e) => e.target.select()}
                     style={{ flex: 1, fontFamily: "monospace", fontSize: 11.5, padding: "6px 8px" }} />
              <button className="btn ghost sm" onClick={copy}>{copied ? "Copied ✓" : "Copy"}</button>
            </div>
            <label style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 10, fontSize: 13 }}>
              <input type="checkbox" checked={!!d.published} disabled={busy === "pub"}
                     onChange={(e) => patch({ published: e.target.checked }, "pub")} />
              Published (live on the public link)
            </label>
            {d.published && (
              <a href={publicUrl} target="_blank" rel="noreferrer" className="btn ghost sm" style={{ marginTop: 8, display: "inline-block" }}>Open public page →</a>
            )}
            <div style={{ fontSize: 11.5, color: "var(--muted)", marginTop: 8 }}>
              Views: {d.view_count || 0}{d.last_viewed_at ? ` · last ${new Date(d.last_viewed_at + "Z").toLocaleString()}` : ""}
            </div>
          </div>

          {notes && (
            <div className="card" style={{ padding: 14, borderColor: "var(--amber, #f0b429)" }}>
              <label style={{ fontSize: 12.5, fontWeight: 600 }}>Internal notes (never shown to client)</label>
              <p style={{ fontSize: 12.5, color: "var(--muted)", margin: "6px 0 0", whiteSpace: "pre-wrap" }}>{notes}</p>
            </div>
          )}
        </div>

        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <iframe title="blueprint" style={{ width: "100%", height: "78vh", border: "none" }}
                  srcDoc={d.html || "<p style='font-family:sans-serif;padding:20px'>No content yet — paste a transcript and Generate.</p>"} />
        </div>
      </div>
    </div>
  );
}
