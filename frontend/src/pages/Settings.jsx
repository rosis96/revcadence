import { useAuth } from "../auth";
import { Badge, useApi } from "../components";

export default function Settings() {
  const { me } = useAuth();
  const { data: health } = useApi("/healthz");
  return (
    <div style={{ maxWidth: 560 }}>
      <div className="card" style={{ padding: 18 }}>
        <h2 style={{ fontSize: 15, marginBottom: 12 }}>Account</h2>
        <div className="kv" style={{ margin: 0 }}>
          <div className="k">Name</div><div>{me.user.name || "—"}</div>
          <div className="k">Email</div><div>{me.user.email}</div>
          <div className="k">Role</div><div><Badge tone="indigo">{me.role}</Badge></div>
          <div className="k">Workspaces</div><div>{me.workspaces.map((w) => w.name).join(", ") || "—"}</div>
        </div>
      </div>
      <div className="card" style={{ padding: 18, marginTop: 14 }}>
        <h2 style={{ fontSize: 15, marginBottom: 12 }}>System</h2>
        <div className="kv" style={{ margin: 0 }}>
          <div className="k">API</div><div>{health?.ok ? <Badge tone="green">healthy</Badge> : <Badge tone="red">down</Badge>}</div>
          <div className="k">Database</div><div>{health?.db || "—"} · {health?.tables ?? "?"} tables</div>
          <div className="k">Migration</div><div style={{ fontFamily: "monospace", fontSize: 12 }}>{health?.migration || "—"}</div>
          <div className="k">Worker</div>
          <div>{health?.worker?.alive ? <Badge tone="green">online</Badge> : <Badge tone="red">offline</Badge>}
            <span style={{ color: "var(--muted)", fontSize: 12, marginLeft: 8 }}>
              {health?.worker?.last_beat ? `last beat ${new Date(health.worker.last_beat + "Z").toLocaleTimeString()}` : ""}
            </span>
          </div>
          <div className="k">Version</div><div>{health?.version || "—"}</div>
        </div>
      </div>
    </div>
  );
}
