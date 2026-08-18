"""Authenticated form-builder API and response mapping service."""
import json
import logging
import os
import re
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func

from ..auth import AuthContext, require_master
from ..models.audit import AuditLog
from ..models.forms import (DISPLAY_MODES, FORM_STATUSES, MAP_TARGETS, PREFILL_SOURCES,
                            QUESTION_TYPES, Form, FormAnswer, FormInvite, FormQuestion,
                            FormResponse, FormSection, FormVersion)
from ..models.identity import Workspace
from ..models.jobs import Job

router = APIRouter(prefix="/api/forms", tags=["forms"])
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Access, snapshots, and serialization
# ---------------------------------------------------------------------------
def _form_query(ctx: AuthContext):
    """Forms are org-level. The client is chosen when an invite is sent."""
    return ctx.db.query(Form).filter(Form.org_id == ctx.org_id)


def _form(ctx: AuthContext, form_id: int, *, archived: bool = False) -> Form:
    q = _form_query(ctx).filter(Form.id == form_id)
    if not archived:
        q = q.filter(Form.status != "archived")
    row = q.first()
    if row is None:
        raise HTTPException(404, "Form not found")
    return row


def _section(ctx: AuthContext, section_id: int) -> tuple[FormSection, Form]:
    row = ctx.db.get(FormSection, section_id)
    if row is None:
        raise HTTPException(404, "Section not found")
    return row, _form(ctx, row.form_id)


def _question(ctx: AuthContext, question_id: int) -> tuple[FormQuestion, Form]:
    row = ctx.db.get(FormQuestion, question_id)
    if row is None:
        raise HTTPException(404, "Question not found")
    return row, _form(ctx, row.form_id)


def _question_out(q: FormQuestion) -> dict:
    return {
        "id": q.id, "form_id": q.form_id, "section_id": q.section_id,
        "position": q.position or 0, "type": q.type, "label": q.label or "",
        "help_text": q.help_text or "", "required": bool(q.required),
        "options": q.options or {}, "maps_to": q.maps_to,
        "prefill_source": q.prefill_source, "display_mode": q.display_mode or "ask",
    }


def _section_out(s: FormSection) -> dict:
    return {"id": s.id, "form_id": s.form_id, "position": s.position or 0,
            "title": s.title or "", "description": s.description or ""}


def _form_out(f: Form, *, counts: dict | None = None) -> dict:
    out = {
        "id": f.id, "org_id": f.org_id,
        "name": f.name, "description": f.description or "",
        "duplicated_from_id": f.duplicated_from_id,
        "version": f.version or 1, "status": f.status,
        "created_by": f.created_by,
        "created_at": f.created_at.isoformat() if f.created_at else None,
        "updated_at": f.updated_at.isoformat() if f.updated_at else None,
    }
    if counts:
        out.update(counts)
    return out


def _schema_payload(db, f: Form) -> dict:
    sections = (db.query(FormSection).filter(FormSection.form_id == f.id)
                .order_by(FormSection.position, FormSection.id).all())
    questions = (db.query(FormQuestion).filter(FormQuestion.form_id == f.id)
                 .order_by(FormQuestion.position, FormQuestion.id).all())
    return {
        "title": f.name, "description": f.description or "", "version": f.version or 1,
        "sections": [{"id": s.id, "position": s.position or 0, "title": s.title or "",
                      "description": s.description or ""} for s in sections],
        "questions": [{k: v for k, v in _question_out(q).items() if k != "form_id"}
                      for q in questions],
    }


def _ensure_version(db, f: Form, user_id: int | None = None) -> FormVersion:
    row = (db.query(FormVersion)
           .filter(FormVersion.form_id == f.id, FormVersion.version == f.version).first())
    if row is None:
        row = FormVersion(form_id=f.id, version=f.version,
                          schema=_schema_payload(db, f), created_by=user_id)
        db.add(row)
        db.flush()
    return row


def _begin_edit(ctx: AuthContext, f: Form) -> None:
    """The first edit after publish opens a new draft revision."""
    if f.status == "published":
        _ensure_version(ctx.db, f, ctx.user.id)
        f.version = (f.version or 1) + 1
        f.status = "draft"
    f.updated_at = datetime.utcnow()


def _audit(ctx: AuthContext, f: Form, action: str, object_type: str,
           object_id: int, data: dict | None = None,
           workspace_id: int | None = None) -> None:
    ctx.db.add(AuditLog(org_id=f.org_id, workspace_id=workspace_id,
                        user_id=ctx.user.id, action=action, object_type=object_type,
                        object_id=object_id, data=data or {}))


def _copy_structure(db, source: Form, target: Form) -> None:
    sections = (db.query(FormSection).filter(FormSection.form_id == source.id)
                .order_by(FormSection.position, FormSection.id).all())
    section_ids = {}
    for old in sections:
        new = FormSection(form_id=target.id, position=old.position,
                          title=old.title, description=old.description)
        db.add(new)
        db.flush()
        section_ids[old.id] = new.id
    questions = (db.query(FormQuestion).filter(FormQuestion.form_id == source.id)
                 .order_by(FormQuestion.position, FormQuestion.id).all())
    for old in questions:
        db.add(FormQuestion(
            form_id=target.id, section_id=section_ids.get(old.section_id), position=old.position,
            type=old.type, label=old.label, help_text=old.help_text,
            required=old.required, options=dict(old.options or {}), maps_to=old.maps_to,
            prefill_source=old.prefill_source, display_mode=old.display_mode,
        ))


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------
class FormIn(BaseModel):
    name: str


class FormPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None


class SectionIn(BaseModel):
    position: int | None = None
    title: str = "Section"
    description: str = ""


class SectionPatch(BaseModel):
    position: int | None = None
    title: str | None = None
    description: str | None = None


class QuestionIn(BaseModel):
    type: str
    label: str = "Untitled question"
    section_id: int | None = None
    position: int | None = None
    help_text: str = ""
    required: bool = False
    options: dict = Field(default_factory=dict)
    maps_to: str | None = None
    prefill_source: str | None = None
    display_mode: str | None = None


class QuestionPatch(BaseModel):
    type: str | None = None
    label: str | None = None
    section_id: int | None = None
    position: int | None = None
    help_text: str | None = None
    required: bool | None = None
    options: dict | None = None
    maps_to: str | None = None
    prefill_source: str | None = None
    display_mode: str | None = None


class ReorderIn(BaseModel):
    ordered_ids: list[int]


class InviteIn(BaseModel):
    workspace_id: int
    email: str
    name: str = ""


def _validate_question_values(data: dict) -> None:
    qtype = data.get("type")
    if qtype is not None and qtype not in QUESTION_TYPES:
        raise HTTPException(422, f"type must be one of {QUESTION_TYPES}")
    maps_to = data.get("maps_to")
    if maps_to not in (None, "") and maps_to not in MAP_TARGETS:
        raise HTTPException(422, "Unknown mapping target")
    source = data.get("prefill_source")
    if source not in (None, "") and source not in PREFILL_SOURCES:
        raise HTTPException(422, "Unknown pre-fill source")
    mode = data.get("display_mode")
    if mode not in (None, "") and mode not in DISPLAY_MODES:
        raise HTTPException(422, "Unknown display mode")


# ---------------------------------------------------------------------------
# Forms, templates, sections, questions
# ---------------------------------------------------------------------------
@router.get("")
def list_forms(ctx: AuthContext = Depends(require_master)):
    q = _form_query(ctx).filter(Form.status != "archived")
    rows = q.order_by(Form.updated_at.desc(), Form.id.desc()).all()
    fids = [f.id for f in rows]
    qcounts = dict(ctx.db.query(FormQuestion.form_id, func.count(FormQuestion.id))
                   .filter(FormQuestion.form_id.in_(fids)).group_by(FormQuestion.form_id).all()) if fids else {}
    icounts = dict(ctx.db.query(FormInvite.form_id, func.count(FormInvite.id))
                   .filter(FormInvite.form_id.in_(fids)).group_by(FormInvite.form_id).all()) if fids else {}
    return [_form_out(f, counts={"question_count": qcounts.get(f.id, 0),
                                 "invite_count": icounts.get(f.id, 0)}) for f in rows]


@router.post("")
def create_form(body: FormIn, ctx: AuthContext = Depends(require_master)):
    """Always blank. To reuse an existing form, duplicate it."""
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Name is required")
    f = Form(org_id=ctx.org_id, name=name, description="", version=1,
             status="draft", created_by=ctx.user.id)
    ctx.db.add(f)
    ctx.db.flush()
    _audit(ctx, f, "create_form", "form", f.id)
    ctx.db.commit()
    return _form_out(f)


@router.get("/{form_id}")
def get_form(form_id: int, ctx: AuthContext = Depends(require_master)):
    f = _form(ctx, form_id)
    sections = (ctx.db.query(FormSection).filter(FormSection.form_id == f.id)
                .order_by(FormSection.position, FormSection.id).all())
    questions = (ctx.db.query(FormQuestion).filter(FormQuestion.form_id == f.id)
                 .order_by(FormQuestion.position, FormQuestion.id).all())
    return {**_form_out(f), "sections": [_section_out(s) for s in sections],
            "questions": [_question_out(q) for q in questions],
            "question_types": list(QUESTION_TYPES), "map_targets": list(MAP_TARGETS),
            "prefill_sources": list(PREFILL_SOURCES), "display_modes": list(DISPLAY_MODES)}


@router.patch("/{form_id}")
def patch_form(form_id: int, body: FormPatch,
               ctx: AuthContext = Depends(require_master)):
    f = _form(ctx, form_id)
    data = body.model_dump(exclude_unset=True)
    if "status" in data and data["status"] not in FORM_STATUSES:
        raise HTTPException(422, "Unknown form status")
    if data.get("status") == "published":
        raise HTTPException(422, "Use the publish endpoint")
    if any(k in data for k in ("name", "description")) or (
            data.get("status") == "draft" and f.status == "published"):
        _begin_edit(ctx, f)
    if "name" in data:
        if not (data["name"] or "").strip():
            raise HTTPException(422, "Name is required")
        f.name = data["name"].strip()
    if "description" in data:
        f.description = data["description"] or ""
    if "status" in data:
        f.status = data["status"]
    _audit(ctx, f, "update_form", "form", f.id, data)
    ctx.db.commit()
    return _form_out(f)


@router.delete("/{form_id}")
def archive_form(form_id: int, ctx: AuthContext = Depends(require_master)):
    f = _form(ctx, form_id)
    f.status = "archived"
    f.updated_at = datetime.utcnow()
    _audit(ctx, f, "archive_form", "form", f.id)
    ctx.db.commit()
    return {"ok": True, "status": "archived"}


@router.post("/{form_id}/duplicate")
def duplicate_form(form_id: int, ctx: AuthContext = Depends(require_master)):
    """This is the reuse mechanism, and the only one.

    The copy is a plain independent draft from the moment it exists — no link
    back that could push a later edit into a form somebody has already sent.
    """
    source = _form(ctx, form_id)
    target = Form(org_id=source.org_id, name=f"{source.name} copy",
                  description=source.description, duplicated_from_id=source.id,
                  version=1, status="draft", created_by=ctx.user.id)
    ctx.db.add(target)
    ctx.db.flush()
    _copy_structure(ctx.db, source, target)
    _audit(ctx, target, "duplicate_form", "form", target.id, {"source_id": source.id})
    ctx.db.commit()
    return _form_out(target)


@router.post("/{form_id}/publish")
def publish_form(form_id: int, ctx: AuthContext = Depends(require_master)):
    f = _form(ctx, form_id)
    count = ctx.db.query(FormQuestion).filter(FormQuestion.form_id == f.id).count()
    if count == 0:
        raise HTTPException(422, "Add at least one question before publishing")
    f.status = "published"
    f.updated_at = datetime.utcnow()
    version = _ensure_version(ctx.db, f, ctx.user.id)
    _audit(ctx, f, "publish_form", "form", f.id, {"version": f.version})
    ctx.db.commit()
    return {**_form_out(f), "version_snapshot_id": version.id}


@router.post("/{form_id}/sections")
def create_section(form_id: int, body: SectionIn,
                   ctx: AuthContext = Depends(require_master)):
    f = _form(ctx, form_id)
    _begin_edit(ctx, f)
    position = body.position
    if position is None:
        position = (ctx.db.query(func.max(FormSection.position))
                    .filter(FormSection.form_id == f.id).scalar() or 0) + 1
    row = FormSection(form_id=f.id, position=max(0, position),
                      title=(body.title or "Section").strip(), description=body.description or "")
    ctx.db.add(row)
    ctx.db.flush()
    _audit(ctx, f, "create_form_section", "form_section", row.id)
    ctx.db.commit()
    return _section_out(row)


@router.patch("/sections/{section_id}")
def patch_section(section_id: int, body: SectionPatch,
                  ctx: AuthContext = Depends(require_master)):
    row, f = _section(ctx, section_id)
    _begin_edit(ctx, f)
    for key, value in body.model_dump(exclude_unset=True).items():
        if key == "position":
            if value is not None:
                row.position = max(0, value)
        else:
            setattr(row, key, value or "")
    _audit(ctx, f, "update_form_section", "form_section", row.id)
    ctx.db.commit()
    return _section_out(row)


@router.delete("/sections/{section_id}")
def delete_section(section_id: int, ctx: AuthContext = Depends(require_master)):
    row, f = _section(ctx, section_id)
    _begin_edit(ctx, f)
    (ctx.db.query(FormQuestion).filter(FormQuestion.section_id == row.id)
     .update({FormQuestion.section_id: None}, synchronize_session=False))
    ctx.db.delete(row)
    _audit(ctx, f, "delete_form_section", "form_section", section_id)
    ctx.db.commit()
    return {"ok": True}


@router.post("/{form_id}/questions")
def create_question(form_id: int, body: QuestionIn,
                    ctx: AuthContext = Depends(require_master)):
    f = _form(ctx, form_id)
    data = body.model_dump()
    _validate_question_values(data)
    if body.section_id is not None:
        sec = ctx.db.get(FormSection, body.section_id)
        if sec is None or sec.form_id != f.id:
            raise HTTPException(422, "Section does not belong to this form")
    _begin_edit(ctx, f)
    position = body.position
    if position is None:
        position = (ctx.db.query(func.max(FormQuestion.position))
                    .filter(FormQuestion.form_id == f.id).scalar() or 0) + 1
    mode = body.display_mode or ("confirm" if body.prefill_source else "ask")
    row = FormQuestion(
        form_id=f.id, section_id=body.section_id, position=max(0, position), type=body.type,
        label=(body.label or "Untitled question").strip(), help_text=body.help_text or "",
        required=body.required, options=body.options or {}, maps_to=body.maps_to or None,
        prefill_source=body.prefill_source or None, display_mode=mode,
    )
    ctx.db.add(row)
    ctx.db.flush()
    _audit(ctx, f, "create_form_question", "form_question", row.id, {"type": row.type})
    ctx.db.commit()
    return _question_out(row)


@router.patch("/questions/{question_id}")
def patch_question(question_id: int, body: QuestionPatch,
                   ctx: AuthContext = Depends(require_master)):
    row, f = _question(ctx, question_id)
    data = body.model_dump(exclude_unset=True)
    _validate_question_values(data)
    if "section_id" in data and data["section_id"] is not None:
        sec = ctx.db.get(FormSection, data["section_id"])
        if sec is None or sec.form_id != f.id:
            raise HTTPException(422, "Section does not belong to this form")
    _begin_edit(ctx, f)
    if "prefill_source" in data and data["prefill_source"] and "display_mode" not in data:
        data["display_mode"] = "confirm"
    for key, value in data.items():
        if key in ("maps_to", "prefill_source") and value == "":
            value = None
        setattr(row, key, value)
    _audit(ctx, f, "update_form_question", "form_question", row.id, data)
    ctx.db.commit()
    return _question_out(row)


@router.delete("/questions/{question_id}")
def delete_question(question_id: int, ctx: AuthContext = Depends(require_master)):
    row, f = _question(ctx, question_id)
    _begin_edit(ctx, f)
    ctx.db.delete(row)
    _audit(ctx, f, "delete_form_question", "form_question", question_id)
    ctx.db.commit()
    return {"ok": True}


@router.post("/{form_id}/questions/reorder")
def reorder_questions(form_id: int, body: ReorderIn,
                      ctx: AuthContext = Depends(require_master)):
    f = _form(ctx, form_id)
    rows = ctx.db.query(FormQuestion).filter(FormQuestion.form_id == f.id).all()
    current = {q.id: q for q in rows}
    if len(body.ordered_ids) != len(set(body.ordered_ids)) or set(body.ordered_ids) != set(current):
        raise HTTPException(422, "ordered_ids must contain every question exactly once")
    _begin_edit(ctx, f)
    for position, qid in enumerate(body.ordered_ids, 1):
        current[qid].position = position
    _audit(ctx, f, "reorder_form_questions", "form", f.id,
           {"ordered_ids": body.ordered_ids})
    ctx.db.commit()
    return {"ok": True, "ordered_ids": body.ordered_ids}


# ---------------------------------------------------------------------------
# Invites and response reads
# ---------------------------------------------------------------------------
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _known_context(db, workspace_id: int, email: str, name: str) -> dict:
    from ..models.client_profile import ClientProfile
    from ..models.crm import Company, Contact
    from ..models.enrich import EnrichConfig

    ws = db.get(Workspace, workspace_id)
    contact = (db.query(Contact).filter(Contact.workspace_id == workspace_id,
                                        Contact.email.ilike(email)).first())
    profile = None
    company = None
    if contact:
        company = db.get(Company, contact.company_id) if contact.company_id else None
        profile = db.query(ClientProfile).filter(ClientProfile.contact_id == contact.id).first()
    if profile is None:
        profile = (db.query(ClientProfile)
                   .filter(ClientProfile.workspace_id == workspace_id,
                           ClientProfile.is_active_client == True)  # noqa: E712
                   .order_by(ClientProfile.updated_at.desc()).first())
    if company is None and profile:
        company = db.get(Company, profile.company_id)
    cfg = db.query(EnrichConfig).filter(EnrichConfig.workspace_id == workspace_id).first()
    brain = cfg.profile or {} if cfg else {}
    contact_name = name.strip()
    if not contact_name and contact:
        contact_name = f"{contact.first_name or ''} {contact.last_name or ''}".strip()
    company_name = company.name if company else (brain.get("client_name") or (ws.name if ws else ""))
    website = (company.website or company.domain) if company else (brain.get("website") or "")
    return {
        "invite.contact_name": contact_name,
        "invite.contact_email": email,
        "invite.company_name": company_name,
        "invite.website_url": website,
        "crawl.positioning": brain.get("positioning") or brain.get("one_liner") or "",
        "crawl.offers": brain.get("offers") or brain.get("services") or brain.get("main_offer") or "",
        "crawl.case_studies": brain.get("case_studies") or [],
    }


def _base_url(request: Request) -> str:
    return (os.getenv("PUBLIC_BASE_URL", "").strip() or str(request.base_url)).rstrip("/")


@router.post("/{form_id}/invites")
def create_invite(form_id: int, body: InviteIn, request: Request,
                  ctx: AuthContext = Depends(require_master)):
    f = _form(ctx, form_id)
    if f.status != "published":
        raise HTTPException(422, "Publish the form before sending it")
    ctx.require_workspace(body.workspace_id)
    email = body.email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise HTTPException(422, "Enter a valid email address")
    _ensure_version(ctx.db, f, ctx.user.id)
    invite = FormInvite(
        form_id=f.id, form_version=f.version, workspace_id=body.workspace_id,
        recipient_email=email, recipient_name=body.name.strip(),
        known_context=_known_context(ctx.db, body.workspace_id, email, body.name),
        token=secrets.token_urlsafe(32), status="sent",
        expires_at=datetime.utcnow() + timedelta(days=30), reminder_count=0,
    )
    ctx.db.add(invite)
    ctx.db.flush()
    ctx.db.add(Job(kind="send_form_invite", workspace_id=body.workspace_id,
                   payload={"invite_id": invite.id, "base_url": _base_url(request)}))
    _audit(ctx, f, "send_form_invite", "form_invite", invite.id,
           {"recipient": email, "form_version": f.version},
           workspace_id=body.workspace_id)
    ctx.db.commit()
    return {"id": invite.id, "status": invite.status,
            "expires_at": invite.expires_at.isoformat()}


def _invite(ctx: AuthContext, invite_id: int) -> tuple[FormInvite, Form]:
    """The form is org-level, so reachability is decided by the invite's
    workspace — which is the client whose answers these are."""
    row = ctx.db.get(FormInvite, invite_id)
    if row is None:
        raise HTTPException(404, "Invite not found")
    f = _form(ctx, row.form_id)
    if row.workspace_id not in ctx.allowed_workspace_ids():
        raise HTTPException(404, "Invite not found")
    return row, f


@router.post("/invites/{invite_id}/resend")
def resend_invite(invite_id: int, request: Request,
                  ctx: AuthContext = Depends(require_master)):
    invite, f = _invite(ctx, invite_id)
    if invite.expires_at and invite.expires_at <= datetime.utcnow():
        invite.status = "expired"
        ctx.db.commit()
        raise HTTPException(409, "This invite has expired")
    invite.reminder_count = (invite.reminder_count or 0) + 1
    ctx.db.add(Job(kind="send_form_invite", workspace_id=invite.workspace_id,
                   payload={"invite_id": invite.id, "base_url": _base_url(request)}))
    _audit(ctx, f, "resend_form_invite", "form_invite", invite.id,
           {"reminder_count": invite.reminder_count})
    ctx.db.commit()
    return {"ok": True, "reminder_count": invite.reminder_count}


def _version_schema(db, form_id: int, version: int) -> dict:
    row = (db.query(FormVersion)
           .filter(FormVersion.form_id == form_id, FormVersion.version == version).first())
    return dict(row.schema or {}) if row else {}


def _answers_for(db, response_id: int) -> dict[int, FormAnswer]:
    return {a.question_id: a for a in db.query(FormAnswer)
            .filter(FormAnswer.response_id == response_id).all()}


def _completion(schema: dict, answers: dict[int, FormAnswer]) -> int:
    questions = schema.get("questions") or []
    if not questions:
        return 100
    filled = sum(1 for q in questions
                 if q.get("id") in answers and answers[q["id"]].value not in (None, "", []))
    return int(round(100 * filled / len(questions)))


@router.get("/{form_id}/responses")
def list_responses(form_id: int, ctx: AuthContext = Depends(require_master)):
    f = _form(ctx, form_id)
    invites = (ctx.db.query(FormInvite)
               .filter(FormInvite.form_id == f.id,
                       FormInvite.workspace_id.in_(ctx.allowed_workspace_ids()))
               .order_by(FormInvite.id.desc()).all())
    out = []
    for invite in invites:
        response = (ctx.db.query(FormResponse).filter(FormResponse.invite_id == invite.id)
                    .order_by(FormResponse.response_version.desc(), FormResponse.id.desc()).first())
        schema = _version_schema(ctx.db, f.id, invite.form_version)
        answers = _answers_for(ctx.db, response.id) if response else {}
        out.append({
            "invite_id": invite.id, "response_id": response.id if response else None,
            "recipient_email": invite.recipient_email, "recipient_name": invite.recipient_name,
            "status": response.status if response else invite.status,
            "sent_at": invite.sent_at.isoformat() if invite.sent_at else None,
            "opened_at": invite.opened_at.isoformat() if invite.opened_at else None,
            "submitted_at": response.submitted_at.isoformat() if response and response.submitted_at else None,
            "completion": _completion(schema, answers),
            "response_version": response.response_version if response else None,
        })
    return out


def _response(ctx: AuthContext, response_id: int) -> tuple[FormResponse, Form]:
    row = ctx.db.get(FormResponse, response_id)
    if row is None:
        raise HTTPException(404, "Response not found")
    f = _form(ctx, row.form_id)
    if row.workspace_id not in ctx.allowed_workspace_ids():
        raise HTTPException(404, "Response not found")
    return row, f


@router.get("/responses/{response_id}")
def response_detail(response_id: int, ctx: AuthContext = Depends(require_master)):
    response, f = _response(ctx, response_id)
    invite = ctx.db.get(FormInvite, response.invite_id)
    schema = _version_schema(ctx.db, response.form_id, response.form_version)
    questions = {q["id"]: q for q in schema.get("questions") or []}
    answers = _answers_for(ctx.db, response.id)
    rows = []
    for qid, q in questions.items():
        answer = answers.get(qid)
        engagement = None
        if q.get("prefill_source") and answer:
            engagement = "edited" if answer.was_edited else "confirmed"
        rows.append({
            "question_id": qid, "label": q.get("label", ""), "type": q.get("type"),
            "value": answer.value if answer else None,
            "source": answer.source if answer else "client_supplied",
            "engagement": engagement, "maps_to": q.get("maps_to"),
        })
    return {
        "id": response.id, "form_version": response.form_version,
        "response_version": response.response_version, "status": response.status,
        "recipient_email": invite.recipient_email if invite else "",
        "recipient_name": invite.recipient_name if invite else "",
        "contact_details": response.contact_details or {}, "answers": rows,
        "submitted_at": response.submitted_at.isoformat() if response.submitted_at else None,
    }


# ---------------------------------------------------------------------------
# Mapping service (also called by the public submit router)
# ---------------------------------------------------------------------------
def _items(value) -> list:
    if value in (None, "", [], {}):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str) and ("," in value or "\n" in value):
        return [x.strip() for x in re.split(r"[,\n]", value) if x.strip()]
    return [value]


def _merge_list(existing, fresh) -> list:
    out, seen = [], set()
    for item in _items(existing) + _items(fresh):
        key = json.dumps(item, sort_keys=True, ensure_ascii=False).casefold()
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _map_audit(db, f: Form, response: FormResponse, target: str, *, skipped: str = "",
               data: dict | None = None) -> bool:
    payload = {"target": target, "response_id": response.id,
               "source": "client_supplied", **(data or {})}
    if skipped:
        payload["warning"] = skipped
    db.add(AuditLog(org_id=f.org_id, workspace_id=response.workspace_id, user_id=None,
                    action="form_mapping_skipped" if skipped else "form_mapping_applied",
                    object_type="form_response", object_id=response.id, data=payload))
    if skipped:
        log.warning("form mapping skipped response=%s target=%s: %s",
                    response.id, target, skipped)
    return not bool(skipped)


def _client_records(db, response: FormResponse, invite: FormInvite):
    from ..models.client_profile import ClientProfile
    from ..models.crm import Company, Contact

    details = response.contact_details or {}
    email = str(details.get("email") or invite.recipient_email or "").strip()
    contact = (db.query(Contact).filter(Contact.workspace_id == response.workspace_id,
                                        Contact.email.ilike(email)).first()) if email else None
    profile = None
    if contact:
        profile = db.query(ClientProfile).filter(ClientProfile.contact_id == contact.id).first()
    if profile is None:
        profile = (db.query(ClientProfile)
                   .filter(ClientProfile.workspace_id == response.workspace_id,
                           ClientProfile.is_active_client == True)  # noqa: E712
                   .order_by(ClientProfile.updated_at.desc()).first())
    if contact is None and profile and profile.contact_id:
        contact = db.get(Contact, profile.contact_id)
    company = db.get(Company, profile.company_id) if profile else None
    if company is None and contact and contact.company_id:
        company = db.get(Company, contact.company_id)
    return contact, company


def _apply_one(db, f: Form, response: FormResponse, invite: FormInvite,
               target: str, value) -> bool:
    from ..models.enrich import EnrichConfig
    from ..models.reply import ReplyBlock

    ws = db.get(Workspace, response.workspace_id)
    contact, company = _client_records(db, response, invite)
    if target == "workspace.name":
        if not ws:
            return _map_audit(db, f, response, target, skipped="workspace is missing")
        old = ws.name
        ws.name = str(value).strip() or ws.name
        return _map_audit(db, f, response, target, data={"old": old, "new": ws.name})

    if target == "client.website_url":
        if not company:
            return _map_audit(db, f, response, target, skipped="no unambiguous client company")
        old = company.website
        company.website = str(value).strip()
        db.add(Job(kind="enrich_company", workspace_id=response.workspace_id,
                   payload={"company_id": company.id}))
        return _map_audit(db, f, response, target,
                          data={"company_id": company.id, "old": old, "new": company.website,
                                "crawl_queued": True})

    if target in ("client.contact_name", "client.contact_email", "client.role"):
        if not contact:
            return _map_audit(db, f, response, target, skipped="no unambiguous client contact")
        if target == "client.contact_name":
            parts = str(value).strip().split(None, 1)
            contact.first_name = parts[0] if parts else ""
            contact.last_name = parts[1] if len(parts) > 1 else ""
        elif target == "client.contact_email":
            contact.email = str(value).strip().lower()
        else:
            contact.title = str(value).strip()
        return _map_audit(db, f, response, target, data={"contact_id": contact.id})

    if target == "client.timezone":
        if not ws:
            return _map_audit(db, f, response, target, skipped="workspace is missing")
        ws.settings = {**(ws.settings or {}), "timezone": value}
        return _map_audit(db, f, response, target)

    if target == "library.case_study":
        # Straight into the Library, tagged `client_supplied` — which is exactly
        # what an answer on an onboarding form is. It stays usable as background
        # and cannot become a named claim until somebody verifies it.
        from ..library import store as _library
        made = skipped = 0
        for item in _items(value):
            if isinstance(item, dict):
                name = str(item.get("client") or item.get("name") or "").strip()
                outcome = str(item.get("outcome") or item.get("result") or "").strip()
            else:
                # One free-text answer: the client's own sentence is the result,
                # and its first clause is the best name available.
                name = str(item).strip().split(".")[0][:200]
                outcome = str(item).strip()
            try:
                _library.add_case_study(db, response.workspace_id, client_name=name,
                                        outcome=outcome, source="client_supplied",
                                        note="From the onboarding form.")
                made += 1
            except _library.LibraryError:
                skipped += 1
        return _map_audit(db, f, response, target,
                          data={"created": made, "skipped": skipped})

    if target in ("brain.offers", "brain.positioning"):
        cfg = db.query(EnrichConfig).filter(EnrichConfig.workspace_id == response.workspace_id).first()
        if cfg is None:
            return _map_audit(db, f, response, target, skipped="EnrichConfig is missing")
        profile = dict(cfg.profile or {})
        key = {"brain.offers": "offers", "brain.positioning": "positioning"}[target]
        profile[key] = _merge_list(profile.get(key), value)
        cfg.profile = profile
        return _map_audit(db, f, response, target)

    if target.startswith("icp."):
        cfg = db.query(EnrichConfig).filter(EnrichConfig.workspace_id == response.workspace_id).first()
        if cfg is None:
            return _map_audit(db, f, response, target, skipped="EnrichConfig is missing")
        key = target.split(".", 1)[1]
        raw = (cfg.icp_definition or "").strip()
        try:
            current = json.loads(raw) if raw else {}
        except Exception:
            current = None
        if isinstance(current, dict):
            current[key] = _merge_list(current.get(key), value)
            cfg.icp_definition = json.dumps(current, ensure_ascii=False, indent=2)
        else:
            line = f"Client-supplied {key.replace('_', ' ')}: " + ", ".join(map(str, _items(value)))
            existing_lines = [x.strip().casefold() for x in raw.splitlines()]
            if line.strip().casefold() not in existing_lines:
                cfg.icp_definition = (raw + "\n\n" + line).strip()
        return _map_audit(db, f, response, target)

    if target == "library.do_not_contact":
        # Clients answer this with a mix of addresses, domains and company names,
        # so all three land as Library exclusions and the pipeline skips them
        # before it spends anything. Addresses are mirrored into `ReplyBlock` so
        # inbound suppression agrees with outbound exclusion.
        from ..library import store as _library
        made = 0
        for raw in _items(value):
            # A `long_text` answer arrives as one blob and `_items` splits it on
            # commas and newlines, which leaves quotes and bullets on the pieces.
            entry = _library.strip_noise(raw)
            if not entry:
                continue
            if _EMAIL_RE.match(entry.lower()):
                kind = "email"
            elif _library.domain_of(entry):
                kind = "domain"
            else:
                kind = "company"
            try:
                row = _library.add_exclusion(
                    db, response.workspace_id, value=entry, kind=kind,
                    source="client_supplied",
                    reason="client supplied through onboarding form")
            except _library.LibraryError:
                continue
            made += 1
            if row.kind == "email":
                exists = (db.query(ReplyBlock)
                          .filter(ReplyBlock.workspace_id == response.workspace_id,
                                  ReplyBlock.email.ilike(row.value)).first())
                if not exists:
                    db.add(ReplyBlock(workspace_id=response.workspace_id, email=row.value,
                                      reason="client supplied through onboarding form"))
        return _map_audit(db, f, response, target, data={"created": made})

    return _map_audit(db, f, response, target, skipped="mapping target is not implemented")


def apply_response_mappings(db, response: FormResponse) -> dict:
    f = db.get(Form, response.form_id)
    invite = db.get(FormInvite, response.invite_id)
    if not f or not invite:
        return {"applied": 0, "skipped": 0}
    schema = _version_schema(db, response.form_id, response.form_version)
    questions = {q["id"]: q for q in schema.get("questions") or []}
    answers = _answers_for(db, response.id)
    applied = skipped = 0
    for qid, answer in answers.items():
        target = (questions.get(qid) or {}).get("maps_to")
        if not target or answer.value in (None, "", []):
            continue
        if _apply_one(db, f, response, invite, target, answer.value):
            applied += 1
        else:
            skipped += 1
    return {"applied": applied, "skipped": skipped}


@router.post("/responses/{response_id}/apply-mappings")
def rerun_mappings(response_id: int, ctx: AuthContext = Depends(require_master)):
    response, f = _response(ctx, response_id)
    result = apply_response_mappings(ctx.db, response)
    _audit(ctx, f, "rerun_form_mappings", "form_response", response.id, result)
    ctx.db.commit()
    return {"ok": True, **result}
