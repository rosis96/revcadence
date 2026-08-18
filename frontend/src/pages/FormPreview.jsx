import { useMemo, useState } from "react";
import { ArrowLeft, MonitorSmartphone } from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";
import { Button, ErrorBox, Spinner, useApi } from "../components";
import FormFields from "../forms/FormFields";

export default function FormPreview() {
  const { id } = useParams();
  const nav = useNavigate();
  const { data, loading, error, reload } = useApi(`/api/forms/${id}`);
  const [answers, setAnswers] = useState({});
  const [details, setDetails] = useState({
    name: "Alex Morgan", email: "alex@client.com", company: "Client company", website: "https://client.com",
  });
  const schema = useMemo(() => data ? {
    title: data.name, description: data.description, version: data.version,
    sections: data.sections,
    questions: data.questions.map((question) => ({ ...question,
      prefill_value: question.prefill_source?.startsWith("crawl.") ? "Example information found on the client’s website" : undefined,
    })),
  } : null, [data]);
  if (error) return <ErrorBox msg={error} retry={reload} />;
  if (loading || !schema) return <Spinner />;
  return (
    <div className="forms-preview-page">
      <div className="forms-preview-toolbar"><Button variant="ghost" icon={ArrowLeft} onClick={() => nav(`/forms/${id}/edit`)}>Back to builder</Button>
        <span><MonitorSmartphone size={15} /> Client preview · version {data.version}</span></div>
      {/* Same containers the real page uses, so what an operator checks here is
          what the client gets rather than a lookalike that can drift. */}
      <div className="forms-public-wrap forms-preview-wrap">
        <main className="forms-public-card">
          <header className="forms-public-head"><h1>{schema.title}</h1>{schema.description && <p>{schema.description}</p>}</header>
          <FormFields schema={schema} answers={answers}
            setAnswer={(questionId, value) => setAnswers((current) => ({ ...current, [questionId]: value }))}
            details={details} setDetails={setDetails} disabled />
          <div className="forms-public-submit"><Button disabled>Submit</Button></div>
        </main>
      </div>
    </div>
  );
}
