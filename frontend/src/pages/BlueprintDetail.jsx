// Blueprint editor (DESIGN_SYSTEM.md step 6). Notion feel: big quiet title,
// auto-save with a live indicator, large distraction-free preview, version
// history, comments, publish toggle, share. Shared components only.
import { useEffect, useMemo, useState } from "react";
import { AnimatePresence } from "framer-motion";
import { useNavigate, useParams } from "react-router-dom";
import { ExternalLink, Eye, Link2, Sparkles, Trash2, Upload } from "lucide-react";
import { api } from "../api";
import { useAppPath } from "../clientspace/appPath";
import {
  Area, Badge, Breadcrumbs, Button, CommentsPanel, ConfirmDialog, ErrorBox, RowCard,
  SaveIndicator, Spinner, StatusPill, Tabs, VersionList, useApi, useAutoSave, useToast,
} from "../components";

export default function BlueprintDetail() {
  const appTo = useAppPath();
  const { id } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const { data, error, loading, reload } = useApi(`/api/documents/${id}`);
  const { data: versions, reload: reloadVers } = useApi(`/api/documents/${id}/versions`);
  const [d, setD] = useState(null);
  const [transcript, setTranscript] = useState("");
  const [busy, setBusy] = useState("");
  const [confirmDel, setConfirmDel] = useState(false);
  const [sideTab, setSideTab] = useState("build");

  useEffect(() => { if (data) setD(data); }, [data]);

  const uploaded = d?.fields?.generator === "uploaded";
  const editable = !!d;

  // auto-save title + slug + (uploaded) html — Notion-style, no Save buttons
  const [saveState] = useAutoSave(
    d ? { title: d.title, slug: d.slug, html: uploaded ? d.html : undefined } : null,
    async (v) => {
      if (!v) return;
      const body = { title: v.title, slug: v.slug };
      if (uploaded && v.html !== undefined) body.html = v.html;
      const r = await api(`/api/documents/${id}`, { method: "PUT", body });
      setD((cur) => ({ ...r, html: cur?.html ?? r.html }));
      reloadVers();
    },
    { enabled: editable },
  );

  const publicUrl = useMemo(() => {
    if (!d?.slug) return "";
    const host = window.location.host;
    const bpHost = host.startsWith("engine.") ? host.replace(/^engine\./, "blueprint.") : "";
    return bpHost ? `https://${bpHost}/${d.slug}` : `${window.location.origin}/p/${d.slug}`;
  }, [d?.slug]);

  if (loading || !d) return <Spinner />;
  if (error) return <ErrorBox msg={error} retry={reload} />;

  const patch = async (body, key) => {
    setBusy(key);
    try { setD(await api(`/api/documents/${id}`, { method: "PUT", body })); }
    catch (e) { toast(e.message, "bad"); }
    setBusy("");
  };
  const regenerate = async () => {
    if (!transcript.trim()) { toast("Paste the call transcript first.", "bad"); return; }
    setBusy("gen");
    try {
      setD(await api("/api/blueprints/from-transcript", { method: "POST", body: { doc_id: Number(id), transcript } }));
      setTranscript(""); reloadVers(); toast("Blueprint generated");
    } catch (e) { toast(e.message, "bad"); }
    setBusy("");
  };
  const onFile = (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    const r = new FileReader();
    r.onload = async () => {
      setBusy("gen");
      try {
        setD(await api("/api/blueprints/upload", { method: "POST", body: { doc_id: Number(id), html: String(r.result || "") } }));
        reloadVers(); toast(`Replaced with ${f.name}`);
      } catch (err) { toast(err.message, "bad"); }
      setBusy("");
    };
    r.readAsText(f);
  };
  const share = () => { navigator.clipboard?.writeText(publicUrl); toast("Public link copied"); };
  const restore = async (_v, idx) => {
    const real = (versions || [])[idx]?.index;
    setBusy("restore");
    try { setD(await api(`/api/documents/${id}/versions/${real}/restore`, { method: "POST" })); reloadVers(); toast("Version restored"); }
    catch (e) { toast(e.message, "bad"); }
    setBusy("");
  };
  const addComment = (text) => {
    const comments = [...(d.fields?.comments || []), { id: Date.now(), text, author: "You", at: new Date().toISOString() }];
    patch({ fields: { comments } }, "cmt");
  };

  const notes = d.fields?.notes_for_ascendly || "";

  return (
    <>
      <Breadcrumbs items={[{ label: "Blueprints", href: appTo("/blueprints") }, { label: d.title || "Blueprint" }]} />
      <div className="page-head">
        <div style={{ flex: 1, minWidth: 0 }}>
          <input className="doc-title" value={d.title} placeholder="Untitled blueprint"
            onChange={(e) => setD({ ...d, title: e.target.value })} />
          <p style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <StatusPill tone={d.published ? "green" : "gray"}>{d.published ? "published" : d.status}</StatusPill>
            <Badge>{d.kind}</Badge>
            <SaveIndicator state={saveState} />
            <span style={{ color: "var(--muted2)", fontSize: 12 }}>
              {d.view_count || 0} views{d.last_viewed_at ? ` · last ${new Date(d.last_viewed_at + "Z").toLocaleString()}` : ""}
            </span>
          </p>
        </div>
        <div className="acts">
          <Button variant="secondary" icon={Link2} onClick={share}>Share</Button>
          <Button variant="secondary" icon={ExternalLink} disabled={!d.published}
            onClick={() => window.open(publicUrl, "_blank")}>Preview</Button>
          <Button variant={d.published ? "secondary" : "primary"} icon={Eye} loading={busy === "pub"}
            onClick={() => patch({ published: !d.published }, "pub")}>
            {d.published ? "Unpublish" : "Publish"}</Button>
          <Button variant="danger" icon={Trash2} onClick={() => setConfirmDel(true)}>Delete</Button>
        </div>
      </div>

      <div className="doc-split">
        {/* the document itself — large, distraction-free */}
        <div className="doc-preview" style={{ minHeight: "70vh" }}>
          <div className="dp-head">
            <span>Client page</span>
            <span style={{ fontFamily: "monospace", textTransform: "none", letterSpacing: 0 }}>
              /{d.slug}
            </span>
          </div>
          <iframe title="blueprint" style={{ width: "100%", height: "70vh", border: "none", display: "block" }}
            srcDoc={d.html || "<p style='font-family:sans-serif;padding:24px;color:#6b7280'>No content yet. Paste a transcript on the right and Generate.</p>"} />
        </div>

        <div className="doc-side">
          <div className="card" style={{ padding: 14 }}>
            <Tabs value={sideTab} onChange={setSideTab} tabs={[
              { key: "build", label: "Build" },
              { key: "versions", label: "Versions", count: (versions || []).length },
              { key: "comments", label: "Comments", count: (d.fields?.comments || []).length },
            ]} />
            <div style={{ paddingTop: 14 }}>
              {sideTab === "build" && (
                <div style={{ display: "grid", gap: 12 }}>
                  {uploaded ? (
                    <>
                      <p style={{ fontSize: 12.5, color: "var(--muted)" }}>
                        This blueprint uses uploaded HTML. Edit it below (auto-saves) or replace the file;
                        the slug and public link stay the same.</p>
                      <label className="ui-btn secondary sm" style={{ justifyContent: "center", cursor: "pointer" }}>
                        <Upload size={14} /> Replace HTML file
                        <input type="file" accept=".html,.htm,text/html" style={{ display: "none" }} onChange={onFile} />
                      </label>
                      <Area size="lg" style={{ fontFamily: "monospace", fontSize: 11.5 }}
                        value={d.html || ""} onChange={(e) => setD({ ...d, html: e.target.value })} />
                    </>
                  ) : (
                    <>
                      <p style={{ fontSize: 12.5, color: "var(--muted)" }}>
                        Paste the call transcript. Every section is generated from what was said;
                        pricing appears only if it came up on the call.</p>
                      <Area size="lg" style={{ fontFamily: "monospace", fontSize: 11.5 }}
                        value={transcript} onChange={(e) => setTranscript(e.target.value)}
                        placeholder="Paste the Fathom transcript here…" />
                      <Button icon={Sparkles} loading={busy === "gen"} onClick={regenerate}>Generate blueprint</Button>
                      <span style={{ fontSize: 11.5, color: "var(--muted2)" }}>Generator: {d.fields?.generator || "—"}</span>
                    </>
                  )}
                  <div className="field" style={{ margin: 0 }}>
                    <label>URL slug</label>
                    <input value={d.slug} style={{ fontFamily: "monospace", fontSize: 12 }}
                      onChange={(e) => setD({ ...d, slug: e.target.value })} />
                  </div>
                </div>
              )}
              {sideTab === "versions" && (
                <VersionList
                  versions={[{ label: "Current", at: d.updated_at, current: true },
                    ...(versions || []).map((v) => ({ label: v.title || "Version", at: v.at }))]}
                  onRestore={(v, i) => i > 0 && restore(v, i - 1)} />
              )}
              {sideTab === "comments" && (
                <CommentsPanel comments={d.fields?.comments || []} onAdd={addComment} />
              )}
            </div>
          </div>

          {notes && (
            <RowCard title="Internal notes" empty="">
              <p style={{ fontSize: 12.5, color: "var(--muted)", padding: "0 10px 8px", whiteSpace: "pre-wrap" }}>{notes}</p>
            </RowCard>
          )}
        </div>
      </div>

      <AnimatePresence>
      {confirmDel && (
        <ConfirmDialog key="del" danger title="Delete this blueprint?" message="The public page goes offline immediately. This cannot be undone."
          confirmLabel="Delete"
          onConfirm={async () => {
            try { await api(`/api/documents/${id}`, { method: "DELETE" }); nav(appTo("/blueprints")); }
            catch (e) { toast(e.message, "bad"); }
          }}
          onClose={() => setConfirmDel(false)} />
      )}
      </AnimatePresence>
    </>
  );
}
