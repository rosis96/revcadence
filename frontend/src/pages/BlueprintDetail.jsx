import { useParams } from "react-router-dom";
import { Badge, ErrorBox, Spinner, useApi } from "../components";

export default function BlueprintDetail() {
  const { id } = useParams();
  const { data: d, error, loading, reload } = useApi(`/api/documents/${id}`);
  if (loading) return <Spinner />;
  if (error) return <ErrorBox msg={error} retry={reload} />;
  return (
    <>
      <div className="toolbar">
        <h1 style={{ fontSize: 18 }}>{d.title}</h1>
        <Badge>{d.kind}</Badge>
        <Badge tone={d.status === "draft" ? "amber" : "green"}>{d.status}</Badge>
        <div className="spacer" />
        <span style={{ color: "var(--muted)", fontSize: 12.5 }}>
          generator: {d.fields?.generator || "—"} · slug: {d.slug}
        </span>
      </div>
      <iframe className="preview" title="blueprint" srcDoc={d.html || "<p style='font-family:sans-serif;padding:20px'>No HTML content.</p>"} />
    </>
  );
}
