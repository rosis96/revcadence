"""Library API — the client's raw materials, and the provenance rules on them.

Three things about this router are deliberate.

**The client writes here.** Most of the workspace is us showing them something.
The Library is the one place they hand us facts, so `get_ctx` is enough and
`require_master` would defeat the point. What a client cannot do is set
`source`: their additions are `client_supplied` because that is what they are,
and letting the form choose would turn the field into a formality.

**Verification is ours.** `POST .../verify` refuses a client token and demands a
link. A verification nobody else can re-check is a memory.

**Reads are one request.** The Library page has three tabs, usage counts, an
inbox and an add surface. Splitting that across six endpoints would make the tab
switch a loading state for data we already had.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import AuthContext, get_ctx
from ..library import store
from ..models.audit import AuditLog
from ..models.enrich import EnrichList
from ..models.identity import User, Workspace
from ..models.library import (SOURCES, VERDICTS, LibraryCaseStudy, LibraryExclusion,
                              LibraryIcpTest, LibrarySegment)
from ..models.reply import ReplyBlock
from .client_space import _one_workspace, _require_workspace

router = APIRouter(prefix="/api/library", tags=["library"])


# ---------------------------------------------------------------- gates
def _writable(ctx: AuthContext) -> AuthContext:
    """Previewing as the client is read-only, exactly as it is everywhere else in
    the module — otherwise the preview is a costume an operator can still act
    through, and the record lands with the wrong provenance."""
    if ctx.preview_as_client:
        raise HTTPException(403, "Exit the client preview to change the Library")
    return ctx


def _source_for(ctx: AuthContext, requested: str | None, *, default: str = "operator") -> str:
    """A client's contribution is `client_supplied`, full stop.

    Not a UI restriction — the value never leaves this function's control, so a
    hand-rolled request cannot promote its own evidence.
    """
    if ctx.role == "client":
        return "client_supplied"
    return store.clean_source(requested, default=default)


def _ours(ctx: AuthContext) -> AuthContext:
    if ctx.sees_as_client:
        raise HTTPException(403, "Verifying evidence is RevCadence's job, not the client's")
    return ctx


def _guard(fn, *args, **kwargs):
    """Turn a store rejection into a 422 the form can render."""
    try:
        return fn(*args, **kwargs)
    except store.LibraryError as exc:
        raise HTTPException(422, str(exc)) from exc


def _audit(ctx: AuthContext, workspace_id: int, action: str, kind: str, object_id: int,
           data: dict | None = None) -> None:
    ctx.db.add(AuditLog(org_id=ctx.org_id, workspace_id=workspace_id, user_id=ctx.user.id,
                        action=action, object_type=f"library_{kind}", object_id=object_id,
                        data=data or {}))


def _row(ctx: AuthContext, model, row_id: int):
    """404, never 403, on a bare record id: a client probing ids must not learn
    which of them exist in somebody else's workspace."""
    row = ctx.db.get(model, row_id)
    if row is None or row.workspace_id not in ctx.allowed_workspace_ids():
        raise HTTPException(404, "Library record not found")
    return row


def _client_owned(ctx: AuthContext, row) -> None:
    """A client may withdraw what they contributed. They may not remove our
    verified evidence, or an ICP test whose verdict is a record of what happened.
    """
    if ctx.role == "client" and getattr(row, "source", "") != "client_supplied":
        raise HTTPException(403, "Only RevCadence can remove this record")


# ---------------------------------------------------------------- read
def _verifier_names(ctx: AuthContext, rows: list) -> dict:
    ids = {getattr(r, "verified_by", None) for r in rows if getattr(r, "verified_by", None)}
    if not ids:
        return {}
    return {u.id: (u.name or u.email or "")
            for u in ctx.db.query(User).filter(User.id.in_(ids)).all()}


@router.get("")
def library(workspace_id: int | None = None, ctx: AuthContext = Depends(get_ctx)):
    resolved = _one_workspace(ctx, workspace_id)
    if resolved is None:
        return {"workspace": None, "counts": {}, "case_studies": [], "segments": [],
                "icp_tests": [], "exclusions": [], "objections": [], "unfiled": [],
                "lists": [], "can_edit": False}
    ws = ctx.db.get(Workspace, resolved)
    studies = store.case_studies(ctx.db, resolved)
    segment_rows = store.segments(ctx.db, resolved)
    test_rows = store.icp_tests(ctx.db, resolved)

    usage = store.usage_by_proof_key(ctx.db, resolved)
    in_list = store.in_list_counts(ctx.db, resolved, segment_rows)
    names = _verifier_names(ctx, [*studies, *segment_rows, *test_rows])
    lists = {row.id: row.name for row in ctx.db.query(EnrichList)
             .filter(EnrichList.workspace_id == resolved).order_by(EnrichList.id.desc()).all()}
    segment_names = {row.id: row.name for row in segment_rows}

    can_edit = not ctx.preview_as_client
    return {
        "workspace": {"id": resolved, "name": ws.name if ws else ""},
        "counts": store.counts(ctx.db, resolved),
        "case_studies": [
            store.case_study_out(row, usage=usage.get(store.proof_key_for(row)),
                                 verifier_names=names) for row in studies],
        "segments": [
            store.segment_out(row, in_list=in_list.get(row.id),
                              list_name=lists.get(row.enrich_list_id or 0, ""),
                              verifier_names=names) for row in segment_rows],
        "icp_tests": [
            store.icp_test_out(row, segment_name=segment_names.get(row.segment_id or 0, ""),
                               verifier_names=names) for row in test_rows],
        "exclusions": [store.exclusion_out(row) for row in store.exclusions(ctx.db, resolved)],
        "objections": store.objections(ctx.db, resolved),
        # The brain inbox. Clients never see it — it is our tidying, and showing
        # a client "9 unfiled items" reads as a mess they caused.
        "unfiled": [] if ctx.sees_as_client else store.unfiled(ctx.db, resolved),
        "lists": [{"id": key, "name": value} for key, value in lists.items()],
        "sources": list(SOURCES),
        "verdicts": list(VERDICTS),
        "can_edit": can_edit,
        "can_verify": can_edit and not ctx.sees_as_client,
        "is_client": ctx.role == "client",
    }


def _payload(ctx: AuthContext, workspace_id: int) -> dict:
    ctx.db.commit()
    return library(workspace_id=workspace_id, ctx=ctx)


# ---------------------------------------------------------------- case studies
class CaseStudyIn(BaseModel):
    workspace_id: int | None = None
    client_name: str
    outcome: str
    engagement: str = ""
    segment: str = ""
    year: int | None = Field(default=None, ge=1900, le=2200)
    note: str = ""
    source: str | None = None
    source_url: str = ""


class CaseStudyPatch(BaseModel):
    client_name: str | None = None
    outcome: str | None = None
    engagement: str | None = None
    segment: str | None = None
    year: int | None = Field(default=None, ge=1900, le=2200)
    note: str | None = None
    source_url: str | None = None


@router.post("/case-studies")
def create_case_study(body: CaseStudyIn, ctx: AuthContext = Depends(get_ctx)):
    _writable(ctx)
    workspace_id = _require_workspace(ctx, body.workspace_id)
    row = _guard(store.add_case_study, ctx.db, workspace_id,
                 client_name=body.client_name, outcome=body.outcome,
                 source=_source_for(ctx, body.source), engagement=body.engagement,
                 segment=body.segment, year=body.year, note=body.note,
                 source_url=body.source_url, user_id=ctx.user.id)
    _audit(ctx, workspace_id, "add_library_case_study", "case_study", row.id,
           {"client": row.client_name, "source": row.source})
    return _payload(ctx, workspace_id)


@router.patch("/case-studies/{row_id}")
def patch_case_study(row_id: int, body: CaseStudyPatch, ctx: AuthContext = Depends(get_ctx)):
    _writable(ctx)
    row = _row(ctx, LibraryCaseStudy, row_id)
    _client_owned(ctx, row)
    data = body.model_dump(exclude_unset=True)
    if "client_name" in data:
        name = str(data["client_name"] or "").strip()
        if not name:
            raise HTTPException(422, "A case study needs the client's name")
        row.client_name = name[:240]
    if "outcome" in data:
        outcome = str(data["outcome"] or "").strip()
        if not outcome:
            raise HTTPException(422, "A case study needs the result it produced")
        row.outcome = outcome[:4000]
    for field, limit in (("engagement", 240), ("segment", 160), ("note", 4000),
                         ("source_url", 2000)):
        if field in data:
            setattr(row, field, str(data[field] or "").strip()[:limit])
    if "year" in data:
        row.year = data["year"]
    # Editing a verified record's substance retires the verification: the words
    # somebody checked are no longer the words on file. It drops to `operator`
    # rather than to `client_supplied`, because we made the edit.
    if row.source == "verified" and {"client_name", "outcome"} & set(data):
        row.source = "operator"
        row.verified_at = None
        row.verified_by = None
    _audit(ctx, row.workspace_id, "update_library_case_study", "case_study", row.id,
           {"fields": sorted(data), "source": row.source})
    return _payload(ctx, row.workspace_id)


class VerifyIn(BaseModel):
    source_url: str = ""


@router.delete("/case-studies/{row_id}")
def archive_case_study(row_id: int, ctx: AuthContext = Depends(get_ctx)):
    _writable(ctx)
    row = _row(ctx, LibraryCaseStudy, row_id)
    _client_owned(ctx, row)
    used = store.usage_by_proof_key(ctx.db, row.workspace_id).get(store.proof_key_for(row))
    if used and used["angles"]:
        # Removing the proof under a live angle would break QC on copy that is
        # already approved. Name what is using it instead of failing vaguely.
        raise HTTPException(409, "This case study is in use by "
                                 f"{', '.join(used['angle_names'][:3])}. "
                                 "Point those angles at other proof first.")
    row.archived_at = datetime.utcnow()
    _audit(ctx, row.workspace_id, "archive_library_case_study", "case_study", row.id, {})
    return _payload(ctx, row.workspace_id)


# ---------------------------------------------------------------- segments
class SegmentIn(BaseModel):
    workspace_id: int | None = None
    name: str
    company_type: str = ""
    headcount: str = ""
    geography: str = ""
    tam_estimate: int | None = Field(default=None, ge=0)
    tam_note: str = ""
    enrich_list_id: int | None = None
    source: str | None = None
    source_url: str = ""


class SegmentPatch(BaseModel):
    name: str | None = None
    company_type: str | None = None
    headcount: str | None = None
    geography: str | None = None
    tam_estimate: int | None = Field(default=None, ge=0)
    tam_note: str | None = None
    enrich_list_id: int | None = None
    source_url: str | None = None


def _check_list(ctx: AuthContext, workspace_id: int, list_id: int | None) -> int | None:
    if list_id is None:
        return None
    row = ctx.db.get(EnrichList, list_id)
    if row is None or row.workspace_id != workspace_id:
        raise HTTPException(422, "That prospect list belongs to another workspace")
    return row.id


@router.post("/segments")
def create_segment(body: SegmentIn, ctx: AuthContext = Depends(get_ctx)):
    _writable(ctx)
    workspace_id = _require_workspace(ctx, body.workspace_id)
    row = _guard(store.add_segment, ctx.db, workspace_id, name=body.name,
                 source=_source_for(ctx, body.source), company_type=body.company_type,
                 headcount=body.headcount, geography=body.geography,
                 tam_estimate=body.tam_estimate, tam_note=body.tam_note,
                 enrich_list_id=_check_list(ctx, workspace_id, body.enrich_list_id),
                 source_url=body.source_url, user_id=ctx.user.id)
    _audit(ctx, workspace_id, "add_library_segment", "segment", row.id,
           {"name": row.name, "source": row.source})
    return _payload(ctx, workspace_id)


@router.patch("/segments/{row_id}")
def patch_segment(row_id: int, body: SegmentPatch, ctx: AuthContext = Depends(get_ctx)):
    _writable(ctx)
    row = _row(ctx, LibrarySegment, row_id)
    _client_owned(ctx, row)
    data = body.model_dump(exclude_unset=True)
    if "name" in data:
        name = str(data["name"] or "").strip()
        if not name:
            raise HTTPException(422, "A segment needs a name")
        row.name = name[:240]
    for field, limit in (("company_type", 240), ("headcount", 80), ("geography", 240),
                         ("tam_note", 2000), ("source_url", 2000)):
        if field in data:
            setattr(row, field, str(data[field] or "").strip()[:limit])
    if "tam_estimate" in data:
        row.tam_estimate = data["tam_estimate"]
    if "enrich_list_id" in data:
        row.enrich_list_id = _check_list(ctx, row.workspace_id, data["enrich_list_id"])
    if row.source == "verified" and {"name", "tam_estimate"} & set(data):
        row.source = "operator"
        row.verified_at = None
        row.verified_by = None
    _audit(ctx, row.workspace_id, "update_library_segment", "segment", row.id,
           {"fields": sorted(data)})
    return _payload(ctx, row.workspace_id)


@router.delete("/segments/{row_id}")
def archive_segment(row_id: int, ctx: AuthContext = Depends(get_ctx)):
    _writable(ctx)
    row = _row(ctx, LibrarySegment, row_id)
    _client_owned(ctx, row)
    row.archived_at = datetime.utcnow()
    _audit(ctx, row.workspace_id, "archive_library_segment", "segment", row.id, {})
    return _payload(ctx, row.workspace_id)


# ---------------------------------------------------------------- ICP tests
class IcpTestIn(BaseModel):
    workspace_id: int | None = None
    hypothesis: str
    verdict: str = "testing"
    result: str = ""
    sample_size: int | None = Field(default=None, ge=0)
    segment_id: int | None = None
    source: str | None = None


class IcpTestPatch(BaseModel):
    hypothesis: str | None = None
    verdict: str | None = None
    result: str | None = None
    sample_size: int | None = Field(default=None, ge=0)
    segment_id: int | None = None


def _check_segment(ctx: AuthContext, workspace_id: int, segment_id: int | None) -> int | None:
    if segment_id is None:
        return None
    row = ctx.db.get(LibrarySegment, segment_id)
    if row is None or row.workspace_id != workspace_id:
        raise HTTPException(422, "That segment belongs to another workspace")
    return row.id


@router.post("/icp-tests")
def create_icp_test(body: IcpTestIn, ctx: AuthContext = Depends(get_ctx)):
    _writable(ctx)
    workspace_id = _require_workspace(ctx, body.workspace_id)
    row = _guard(store.add_icp_test, ctx.db, workspace_id, hypothesis=body.hypothesis,
                 source=_source_for(ctx, body.source), verdict=body.verdict,
                 result=body.result, sample_size=body.sample_size,
                 segment_id=_check_segment(ctx, workspace_id, body.segment_id),
                 user_id=ctx.user.id)
    _audit(ctx, workspace_id, "add_library_icp_test", "icp_test", row.id,
           {"verdict": row.verdict, "source": row.source})
    return _payload(ctx, workspace_id)


@router.patch("/icp-tests/{row_id}")
def patch_icp_test(row_id: int, body: IcpTestPatch, ctx: AuthContext = Depends(get_ctx)):
    _writable(ctx)
    row = _row(ctx, LibraryIcpTest, row_id)
    _client_owned(ctx, row)
    data = body.model_dump(exclude_unset=True)
    if "hypothesis" in data:
        text = str(data["hypothesis"] or "").strip()
        if not text:
            raise HTTPException(422, "A test needs a hypothesis")
        row.hypothesis = text[:4000]
    if "result" in data:
        row.result = str(data["result"] or "").strip()[:4000]
    if "sample_size" in data:
        row.sample_size = data["sample_size"]
    if "segment_id" in data:
        row.segment_id = _check_segment(ctx, row.workspace_id, data["segment_id"])
    if "verdict" in data:
        verdict = _guard(store.clean_verdict, data["verdict"])
        if verdict != "testing" and not (row.result or "").strip():
            raise HTTPException(422, "Write down what happened before deciding a test")
        # A verdict is a moment. Re-opening a decided test clears the date rather
        # than leaving a decision stamp on a question that is open again.
        row.decided_at = datetime.utcnow() if verdict != "testing" else None
        row.verdict = verdict
    _audit(ctx, row.workspace_id, "update_library_icp_test", "icp_test", row.id,
           {"fields": sorted(data), "verdict": row.verdict})
    return _payload(ctx, row.workspace_id)


@router.delete("/icp-tests/{row_id}")
def archive_icp_test(row_id: int, ctx: AuthContext = Depends(get_ctx)):
    _writable(ctx)
    row = _row(ctx, LibraryIcpTest, row_id)
    _client_owned(ctx, row)
    row.archived_at = datetime.utcnow()
    _audit(ctx, row.workspace_id, "archive_library_icp_test", "icp_test", row.id, {})
    return _payload(ctx, row.workspace_id)


# ---------------------------------------------------------------- exclusions
class ExclusionIn(BaseModel):
    workspace_id: int | None = None
    value: str
    kind: str = "domain"
    label: str = ""
    reason: str = ""


@router.post("/exclusions")
def create_exclusion(body: ExclusionIn, ctx: AuthContext = Depends(get_ctx)):
    """An account we must not contact. Applied before research, so it costs
    nothing — see `app/enrichment/pipeline.py`."""
    _writable(ctx)
    workspace_id = _require_workspace(ctx, body.workspace_id)
    row = _guard(store.add_exclusion, ctx.db, workspace_id, value=body.value,
                 source=_source_for(ctx, None, default="operator"), kind=body.kind,
                 label=body.label, reason=body.reason, user_id=ctx.user.id)
    # An excluded mailbox should also stop replying into the inbox. Mirrored, not
    # merged: `ReplyBlock` answers a different question and keeps its own rows.
    if row.kind == "email":
        exists = (ctx.db.query(ReplyBlock)
                  .filter(ReplyBlock.workspace_id == workspace_id,
                          ReplyBlock.email.ilike(row.value)).first())
        if exists is None:
            ctx.db.add(ReplyBlock(workspace_id=workspace_id, email=row.value,
                                  reason="library exclusion"))
    _audit(ctx, workspace_id, "add_library_exclusion", "exclusion", row.id,
           {"kind": row.kind, "value": row.value})
    return _payload(ctx, workspace_id)


@router.delete("/exclusions/{row_id}")
def archive_exclusion(row_id: int, ctx: AuthContext = Depends(get_ctx)):
    _writable(ctx)
    row = _row(ctx, LibraryExclusion, row_id)
    _client_owned(ctx, row)
    row.archived_at = datetime.utcnow()
    _audit(ctx, row.workspace_id, "archive_library_exclusion", "exclusion", row.id, {})
    return _payload(ctx, row.workspace_id)


# ---------------------------------------------------------------- objections
class ObjectionIn(BaseModel):
    workspace_id: int | None = None
    objection: str
    response: str = ""


@router.post("/objections")
def create_objection(body: ObjectionIn, ctx: AuthContext = Depends(get_ctx)):
    """Objections accumulate in the client brain, which already stores them and
    already knows how to merge without wiping prior work. This is a Library
    surface over that store, not a second copy of it."""
    _writable(ctx)
    workspace_id = _require_workspace(ctx, body.workspace_id)
    item = _guard(store.add_objection, ctx.db, workspace_id, objection=body.objection,
                  response=body.response,
                  source=_source_for(ctx, None, default="operator"))
    _audit(ctx, workspace_id, "add_library_objection", "objection", 0,
           {"objection": item["objection"][:120], "source": item["source"]})
    return _payload(ctx, workspace_id)


# ---------------------------------------------------------------- verification
@router.post("/{kind}/{row_id}/verify")
def verify_record(kind: str, row_id: int, body: VerifyIn, ctx: AuthContext = Depends(get_ctx)):
    """Promote a record to `verified` — the only state a named claim may come
    from. Needs a link, and refuses a client token: a client verifying their own
    evidence is the loop this field exists to break."""
    _writable(ctx)
    _ours(ctx)
    model = {"case-studies": LibraryCaseStudy, "segments": LibrarySegment,
             "icp-tests": LibraryIcpTest}.get(kind)
    if model is None:
        raise HTTPException(404, "Not a verifiable record type")
    row = _row(ctx, model, row_id)
    _guard(store.verify, ctx.db, row, user_id=ctx.user.id, source_url=body.source_url)
    _audit(ctx, row.workspace_id, "verify_library_record", kind.replace("-", "_"), row.id,
           {"source_url": row.source_url})
    return _payload(ctx, row.workspace_id)


# ---------------------------------------------------------------- brain inbox
class ImportIn(BaseModel):
    workspace_id: int | None = None


@router.post("/import-unfiled")
def import_unfiled(body: ImportIn, ctx: AuthContext = Depends(get_ctx)):
    """File the proof still sitting in the brain profile.

    Ours to run, not the client's: it is a tidying operation on our own data
    model and it repoints angles, which is not a client-facing action.
    """
    _writable(ctx)
    _ours(ctx)
    workspace_id = _require_workspace(ctx, body.workspace_id)
    result = store.import_unfiled(ctx.db, workspace_id, user_id=ctx.user.id)
    _audit(ctx, workspace_id, "import_library_unfiled", "case_study", 0, result)
    payload = _payload(ctx, workspace_id)
    payload["imported"] = result
    return payload
