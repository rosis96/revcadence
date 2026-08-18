// Client Space · Sharing & Access.
//
// Two questions, answered on one screen: who can open this workspace, and what
// of it the client can actually see. The page list is the honest version of the
// second question — every page with the visibility it currently has, rather than
// a count anyone has to trust.
//
// A client reads this too. They see their own people by name and our side as a
// number: an agency's staff roster is not theirs to hold, but "four people at
// RevCadence can see this" is exactly what an access screen owes them.
import { useLocation, useNavigate } from "react-router-dom";
import { Building2, Eye, EyeOff, ShieldCheck, Users } from "lucide-react";
import { localDate } from "../../api";
import { useAuth } from "../../auth";
import {
  EmptyState, ErrorBox, Row, RowCard, Skeleton, StatCard, StatusPill, useApi,
} from "../../components";
import { docsBase } from "../nav";
import { useClientView } from "../frame";

const ROLE_LABEL = { owner: "Owner", admin: "Admin", member: "Member", client: "Client" };

export default function Sharing() {
  const { me, wsParam } = useAuth();
  const nav = useNavigate();
  // `asClient` covers the preview too, so previewing this screen shows the
  // client's wording over the client's data rather than a mix of the two.
  const { asClient } = useClientView();
  const isClient = me?.role === "client";
  const base = docsBase(useLocation().pathname, isClient);
  const { data, error, loading, reload } = useApi("/api/client-space/sharing", { workspace_id: wsParam });

  if (error) return <ErrorBox msg={error} retry={reload} />;
  if (loading || !data) {
    return <div className="card" style={{ padding: 16 }}><Skeleton w="40%" /><Skeleton style={{ marginTop: 12 }} /></div>;
  }
  if (!data.workspace) {
    return (
      <EmptyState icon={Building2} title="Choose a client"
        hint="Access is granted per client workspace. Pick one in the switcher above." />
    );
  }

  const people = data.people || [];
  const pages = data.pages || [];
  const hidden = data.hidden_from_client;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Sharing & Access</h1>
          <p>{asClient
            ? "Who can open this workspace, and what is shared with you."
            : "Who can open this workspace, and exactly what the client can see in it."}</p>
        </div>
      </div>

      <div className="metrics">
        <StatCard label="People with access" value={people.length + (data.team_count || 0)}
          sub={data.team_count ? `${data.team_count} at RevCadence` : "in this workspace"} />
        <StatCard label="Shared documents" value={data.shared?.docs ?? 0} sub="pages the client can read" />
        <StatCard label="Shared whiteboards" value={data.shared?.whiteboards ?? 0} sub="canvases we map together" />
        <StatCard label={asClient ? "Email sequences" : "Internal-only"}
          value={asClient ? (data.shared?.sequences ?? 0) : (hidden?.total ?? 0)}
          sub={asClient ? "going out under your name" : "hidden from the client"} />
      </div>

      <div className="cc-grid">
        <RowCard title="People" count={people.length}
          empty="Nobody has been given access yet.">
          {people.map((p) => (
            <Row key={p.id} avatar={p.name || p.email} title={p.name || p.email}
              sub={p.last_login_at ? `last seen ${localDate(p.last_login_at)}` : "never signed in"}
              right={<StatusPill tone={p.role === "client" ? "blue" : "gray"}>
                {ROLE_LABEL[p.role] || p.role}
              </StatusPill>} />
          ))}
          {data.team_count > 0 && (
            <Row icon={Users} title="The RevCadence team"
              sub="operators who run this account" right={data.team_count} />
          )}
        </RowCard>

        <RowCard title={asClient ? "Shared with you" : "What the client sees"} count={pages.length}
          className="span2" viewAll={base}
          empty="No pages yet. Anything you create in Docs or Whiteboards appears here with its visibility.">
          {pages.map((p) => (
            <Row key={p.id} icon={p.visibility === "shared" ? Eye : EyeOff} title={p.title}
              sub={`${p.section}${p.kind === "folder" ? " · folder" : ""}${
                p.updated_at ? ` · updated ${localDate(p.updated_at)}` : ""}`}
              right={<StatusPill tone={p.visibility === "shared" ? "green" : "gray"}>
                {p.visibility === "shared" ? "Shared" : "Internal"}
              </StatusPill>}
              onClick={p.kind === "folder" ? undefined : () => nav(`${base}/${p.id}`)} />
          ))}
        </RowCard>
      </div>

      {!asClient && (
        <div className="cs-note">
          <ShieldCheck size={15} />
          <span>A page reaches the client only through the share action in Docs. Use
            <b> Preview as client</b> above to see any screen exactly as they will.</span>
        </div>
      )}
    </>
  );
}
