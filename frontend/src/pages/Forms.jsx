// SYSTEM · Forms. The org-level builder index.
//
// There is no template library, deliberately. Duplicate does the same job for a
// fraction of the machinery: build the onboarding form once for the first
// client, copy it and tweak it for the next. A template system would add a
// second kind of form and a standing question — "the template changed, do the
// forms that came from it?" — that nobody wants to answer.
import { useState } from "react";
import { AnimatePresence } from "framer-motion";
import { Copy, FilePlus2 } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { api, localDate } from "../api";
import { Badge, Button, Empty, Input, Modal, PageHeader, SkeletonRows, useApi, useToast } from "../components";

export default function Forms() {
  const nav = useNavigate();
  const toast = useToast();
  const { data, loading, error, reload } = useApi("/api/forms");
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const forms = data || [];

  const create = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try {
      const made = await api("/api/forms", { method: "POST", body: { name: name.trim() } });
      setCreating(false); setName(""); reload(); nav(`/forms/${made.id}/edit`);
    } catch (e) { toast(e.message, "bad"); }
    setBusy(false);
  };

  const duplicate = async (event, item) => {
    event.stopPropagation();
    try {
      const made = await api(`/api/forms/${item.id}/duplicate`, { method: "POST" });
      reload(); nav(`/forms/${made.id}/edit`);
    } catch (e) { toast(e.message, "bad"); }
  };

  return (
    <div className="forms-page">
      <PageHeader actions={<Button icon={FilePlus2} onClick={() => setCreating(true)}>New form</Button>} />
      <div className="forms-page-heading">
        <div>
          <span className="forms-kicker">Client onboarding</span>
          <h1>Forms</h1>
          <p>Build a form once, send it to a client, and read what comes back.
            Duplicate one to start the next.</p>
        </div>
      </div>

      {error && <div className="error-box">{error}</div>}

      <section className="forms-list-section">
        {loading ? (
          <div className="surface"><table className="dt"><tbody><SkeletonRows cols={5} rows={6} /></tbody></table></div>
        ) : forms.length === 0 ? (
          <Empty icon="▤" title="No forms yet"
            hint="Create a blank form and add your questions. Once it fits, duplicate it for the next client." />
        ) : (
          <div className="surface forms-table-surface">
            <table className="dt">
              <thead><tr><th>Name</th><th>Status</th><th>Version</th><th>Questions</th><th>Sent</th><th>Updated</th><th /></tr></thead>
              <tbody>{forms.map((item) => (
                <tr key={item.id} className="click" onClick={() => nav(`/forms/${item.id}/edit`)}>
                  <td><b>{item.name}</b><div className="forms-row-sub">{item.description || "No description"}</div></td>
                  <td><Badge tone={item.status === "published" ? "green" : "amber"}>{item.status}</Badge></td>
                  <td>v{item.version}</td>
                  <td>{item.question_count}</td>
                  <td>{item.invite_count || 0}</td>
                  <td>{localDate(item.updated_at)}</td>
                  <td><button className="rowact" title="Duplicate" onClick={(event) => duplicate(event, item)}><Copy size={15} /></button></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </section>

      <AnimatePresence>
      {creating && (
        <Modal key="create" title="Create a form" onClose={() => setCreating(false)}>
          <div className="field">
            <label>Name</label>
            <Input autoFocus value={name} onChange={(e) => setName(e.target.value)}
              placeholder="Client onboarding" onKeyDown={(e) => e.key === "Enter" && create()} />
          </div>
          <div className="actions">
            <Button variant="ghost" onClick={() => setCreating(false)}>Cancel</Button>
            <Button loading={busy} disabled={!name.trim()} onClick={create}>Create form</Button>
          </div>
        </Modal>
      )}
      </AnimatePresence>
    </div>
  );
}
