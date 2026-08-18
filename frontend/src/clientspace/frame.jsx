// The Client Space frame: the two things an operator needs on a client-facing
// screen and a client must never see.
//
// 1. A persistent marker. Quiet, one line, always there: we are looking at this
//    as RevCadence, and this many internal-only items are hidden from the client.
//    It is not a warning — it is the answer to "wait, can they see this?", which
//    otherwise gets answered by guessing.
//
// 2. Preview as client. Not a nicety: before anyone hits Share they need to see
//    what is about to become visible. The toggle sets a request header, so the
//    server answers every call with the client's field of view — the same filter
//    the client hits, not a UI imitation of it that can drift out of agreement
//    with it. Writes are refused while it is on, so the preview cannot be acted
//    through by accident.
import { createContext, useContext, useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { Eye, EyeOff } from "lucide-react";
import { isClientPreview, setClientPreview } from "../api";
import { useAuth } from "../auth";
import { useApi } from "../components";

// Screens that take the whole viewport, marker and padding included.
//
// The marker earns its room by answering "can the client see this?". On the
// whiteboard the answer is fixed and known: the board is always shared, there is
// nothing on it to hide and nothing to preview, so the bar would repeat a
// constant while taking the room a canvas is the entire point of.
const FULL_BLEED = [/\/whiteboards$/];

// `asClient` is what screens should branch on: it is true for a real client AND
// for an operator with the preview on. Branching on the role alone is how a
// preview ends up showing client-filtered data under operator wording, which is
// worse than no preview — it looks checked when it has not been.
const ClientViewCtx = createContext({ previewing: false, setPreviewing: () => {}, isClient: true, asClient: true });
export const useClientView = () => useContext(ClientViewCtx);

const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

function Marker({ previewing, setPreviewing, workspaceId }) {
  // One request per visit to the module, not per screen — the frame outlives the
  // routes inside it. The count is deliberately read as ourselves even while
  // previewing, because "what is hidden" is the operator's question.
  const { data } = useApi("/api/client-space/overview", { workspace_id: workspaceId }, [previewing]);
  const hidden = data?.hidden_from_client?.total ?? null;
  return (
    <div className={`cs-marker ${previewing ? "previewing" : ""}`}>
      <span className="cs-marker-dot" />
      <span className="cs-marker-text">
        <b>{previewing ? "Previewing as the client" : "Viewing as RevCadence"}</b>
        <em>
          {hidden === null ? "Client-facing screen."
            : hidden === 0 ? "Client-facing screen — nothing is hidden from the client."
            : `Client-facing screen — ${plural(hidden, "internal-only item")} hidden from the client.`}
        </em>
      </span>
      <button className="cs-marker-toggle" onClick={() => setPreviewing(!previewing)}
        aria-pressed={previewing}>
        {previewing ? <EyeOff size={14} /> : <Eye size={14} />}
        {previewing ? "Exit preview" : "Preview as client"}
      </button>
    </div>
  );
}

// `children` is remounted whenever the preview flips (see the key below), so
// every screen refetches through the header instead of showing stale rows.
export default function ClientSpaceFrame({ children }) {
  const { me, wsParam } = useAuth();
  const { pathname } = useLocation();
  const isClient = me?.role === "client";
  const [previewing, setPreviewingRaw] = useState(false);
  // The module-level flag is set in the handler, before React re-renders, so a
  // child remounting in the next commit already fetches with the header on.
  const setPreviewing = (on) => { setClientPreview(on && !isClient); setPreviewingRaw(on); };
  useEffect(() => () => setClientPreview(false), []);   // leaving the module ends the preview
  useEffect(() => { if (isClient && isClientPreview()) setClientPreview(false); }, [isClient]);

  const full = FULL_BLEED.some((pattern) => pattern.test(pathname));
  const body = <div className={`cs-body${full ? " cs-body-full" : ""}`}
    key={previewing ? "as-client" : "as-us"}>{children}</div>;

  if (isClient) {
    return (
      <ClientViewCtx.Provider value={{ previewing: false, setPreviewing: () => {}, isClient: true, asClient: true }}>
        {body}
      </ClientViewCtx.Provider>
    );
  }
  return (
    <ClientViewCtx.Provider value={{ previewing, setPreviewing, isClient: false, asClient: previewing }}>
      {!full && <Marker previewing={previewing} setPreviewing={setPreviewing} workspaceId={wsParam} />}
      {body}
    </ClientViewCtx.Provider>
  );
}
