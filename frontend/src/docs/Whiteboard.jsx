// The workspace's whiteboard.
//
// One canvas per workspace, and the same canvas for the team and the client.
// So there is no index here, no create action, and nothing to name: opening the
// section *is* opening the board. The server brings it into being on the first
// visit and returns the same block to everyone after that.
//
// The board still lives on a page underneath, which is what keeps comments,
// version history and the audit trail working on it — but none of that surfaces
// as a choice. The screen is the canvas.
import { useEffect, useState } from "react";
import { Columns2 } from "lucide-react";
import { api } from "../api";
import { useAuth } from "../auth";
import { EmptyState, useToast } from "../components";
import WhiteboardBlock from "./WhiteboardBlock";

export default function Whiteboard() {
  const toast = useToast();
  const { wsParam } = useAuth();
  const [state, setState] = useState({ status: "loading" });

  useEffect(() => {
    let active = true;
    setState({ status: "loading" });
    api("/api/workspace/whiteboard", { params: { workspace_id: wsParam } })
      .then((data) => { if (active) setState({ status: "ready", block: data.board }); })
      .catch((error) => {
        if (!active) return;
        toast(error.message, "bad");
        setState({ status: "error", message: error.message });
      });
    return () => { active = false; };
  }, [wsParam, toast]);

  if (state.status === "loading") {
    return <div className="wb-page center"><div className="spinner" /></div>;
  }
  if (state.status === "error") {
    return (
      <div className="wb-page">
        <EmptyState icon={Columns2} title="This whiteboard could not be opened"
          hint={state.message || "Reload the page to try again."} />
      </div>
    );
  }
  return (
    <div className="wb-page">
      <WhiteboardBlock block={state.block} fill />
    </div>
  );
}
