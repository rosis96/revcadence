// Reply Management → Processing: a live window into the reply pipeline. Every
// inbound reply becomes a `process_reply` job that is HELD for the reply-delay
// (e.g. 260s) and then run. This page polls every 3s so you can watch a reply
// arrive, count down, run, and land — and diagnose "I replied but nothing
// showed up yet" (webhook not arriving vs. still delayed vs. unrouted vs. error).
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { Empty, ErrorBox, Metric, Spinner, StatusBadge } from "../components";

const TONE = { pending: "amber", running: "blue", done: "green", failed: "red", cancelled: "gray" };

export default function ReplyProcessing() {
  const { wsParam } = useAuth();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const timer = useRef(null);

  const load = () => {
    api("/api/reply/processing", { params: { workspace_id: wsParam } })
      .then((d) => { setData(d); setError(""); })
      .catch((e) => setError(e.message));
  };

  useEffect(() => {
    load();
    timer.current = setInterval(load, 3000);   // live refresh
    return () => clearInterval(timer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wsParam]);

  if (error && !data) return <ErrorBox msg={error} retry={load} />;
  if (!data) return <Spinner />;

  const s = data.summary;
  const fmtWhen = (iso) => (iso ? new Date(iso + "Z").toLocaleTimeString() : "");

  return (
    <>
      <div className="toolbar" style={{ marginBottom: 6 }}>
        <h1 style={{ fontSize: 18 }}>Processing</h1>
        <span style={{ color: "var(--muted)", fontSize: 12.5 }}>live · refreshes every 3s</span>
        <div className="spacer" />
        <StatusBadge tone={data.worker_alive ? "green" : "red"}>
          {data.worker_alive ? "Worker online" : "Worker offline"}
        </StatusBadge>
      </div>

      {!data.worker_alive && (
        <div className="error-box" style={{ marginBottom: 12 }}>
          The background worker is offline — scheduled replies won't run until it's back. Check the worker
          service on Railway (it should report to /healthz).
        </div>
      )}

      <div className="metrics" style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: 10, marginBottom: 16 }}>
        <Metric label="Replies (24h)" value={s.last_24h} />
        <Metric label="Scheduled" value={s.scheduled} sub="waiting out the delay" />
        <Metric label="Due now" value={s.due_now} />
        <Metric label="Running" value={s.running} />
        <Metric label="Done (24h)" value={s.done_24h} />
        <Metric label="Failed" value={s.failed} />
      </div>

      {s.last_24h === 0 && (
        <div className="card" style={{ padding: 16, marginBottom: 16, borderColor: "var(--amber, #f0b429)" }}>
          <b>No inbound replies have reached the system in the last 24h.</b>
          <div style={{ color: "var(--muted)", fontSize: 13, marginTop: 6, lineHeight: 1.5 }}>
            If you replied to a campaign and expected it here, the webhook isn't reaching us. Check that your
            sending platform's reply webhook points at
            {" "}<code>/api/reply/webhooks/instantly?workspace_name=&lt;your reply-space name&gt;</code>
            {" "}(or the Bison URL), and that the reply-space name matches Setup exactly. Note: <b>Test Thread</b>
            {" "}is a dry run — it never creates anything here.
          </div>
        </div>
      )}

      {data.jobs.length === 0 ? (
        <Empty icon="◔" title="Nothing in the queue" hint="Inbound replies will appear here the moment they arrive." />
      ) : (
        <table className="tbl">
          <thead><tr>
            <th>Reply</th><th>Routed to</th><th>Status</th><th>When</th><th>Detail</th>
          </tr></thead>
          <tbody>
            {data.jobs.map((j) => {
              const res = j.result || {};
              const detail = j.error
                ? j.error
                : res.unrouted ? "Unrouted — no matching reply-space"
                : res.skipped ? `Skipped: ${res.skipped}`
                : res.guard ? `Guard: ${res.guard}`
                : res.action ? `Decision: ${res.action}${res.intent ? ` · ${res.intent}` : ""}`
                : j.note || "";
              return (
                <tr key={j.id}>
                  <td>
                    <b>{j.email || "(no email in payload)"}</b>
                    <div style={{ color: "var(--muted)", fontSize: 12 }}>{j.platform} · {j.flow}</div>
                  </td>
                  <td>{j.routed_to === "Unrouted"
                    ? <StatusBadge tone="red">Unrouted</StatusBadge>
                    : j.routed_to}</td>
                  <td>
                    <StatusBadge tone={TONE[j.status] || "gray"}>{j.status}</StatusBadge>
                    {j.status === "pending" && j.seconds_until_run > 0 &&
                      <div style={{ color: "var(--muted)", fontSize: 12, marginTop: 2 }}>
                        runs in {j.seconds_until_run}s
                      </div>}
                  </td>
                  <td style={{ color: "var(--muted)", fontSize: 12.5 }}>
                    {j.finished_at ? fmtWhen(j.finished_at) : fmtWhen(j.created_at)}
                  </td>
                  <td style={{ fontSize: 12.5, color: j.error ? "var(--red-tx, #c0392b)" : "var(--muted)", maxWidth: 380 }}>
                    {detail}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </>
  );
}
