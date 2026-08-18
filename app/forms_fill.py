"""One fill pipeline for the onboarding form, reachable by two credentials.

A client meets this form twice. First from a link in an email, days before they
have an account — that is the token. Later from their own dashboard, once the
account exists — that is the session. Both arrive here.

Keeping load / save / submit / upload in one module is what makes "pick up where
you left off" true rather than aspirational: each credential only has to resolve
a :class:`FormInvite`, and everything after that is identical. The working
response hangs off the invite, never off the session, so a form started from the
emailed link and finished after logging in is one response — not two that
disagree.

Nothing in here reads the session, the workspace's documents, its prospects or
its sequences. The only rows it touches are the invite, the pinned form version,
and the response being filled. That is what lets the same page render safely on
the one unauthenticated route in the product.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from fastapi import HTTPException, UploadFile
from pydantic import BaseModel, Field

from . import config
from .models.forms import (FormAnswer, FormInvite, FormResponse, FormUpload,
                           FormVersion)

MAX_UPLOAD = 10 * 1024 * 1024
UPLOAD_EXTENSIONS = {".pdf", ".doc", ".docx", ".png", ".jpg"}

# The four things we always already know. They are shown once, as a compact block
# at the top of the page, and never as blank questions in the body — we are
# emailing this to the address in question, so asking for it reads as though we
# have not done our homework.
CONTACT_SOURCES = {
    "invite.contact_name": "name", "invite.contact_email": "email",
    "invite.company_name": "company", "invite.website_url": "website",
}

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class FillPayload(BaseModel):
    answers: dict[str, object] = Field(default_factory=dict)
    details: dict[str, object] = Field(default_factory=dict)
    edited_question_ids: list[int] = Field(default_factory=list)


class InvalidLink(Exception):
    """Raised where a caller must answer with its own neutral message."""


def fingerprint(value: str) -> str:
    return hmac.new(config.JWT_SECRET.encode(), value.encode(), hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# Schema, answers, contact details
# ---------------------------------------------------------------------------
def pinned_schema(db, invite: FormInvite) -> dict:
    """The version the invite was sent against — never the live draft.

    Editing a form after invites have gone out must not reshape a response that
    is already in flight, so the render reads the frozen snapshot.
    """
    row = (db.query(FormVersion)
           .filter(FormVersion.form_id == invite.form_id,
                   FormVersion.version == invite.form_version).first())
    if row is None:
        raise InvalidLink()
    return json.loads(json.dumps(row.schema or {}))


def latest_response(db, invite: FormInvite) -> FormResponse | None:
    return (db.query(FormResponse).filter(FormResponse.invite_id == invite.id)
            .order_by(FormResponse.response_version.desc(), FormResponse.id.desc()).first())


def answer_map(db, response: FormResponse | None) -> dict[int, FormAnswer]:
    if response is None:
        return {}
    return {a.question_id: a for a in db.query(FormAnswer)
            .filter(FormAnswer.response_id == response.id).all()}


def contact_details(invite: FormInvite, response: FormResponse | None) -> dict:
    known = invite.known_context or {}
    base = {
        "name": known.get("invite.contact_name") or invite.recipient_name or "",
        "email": known.get("invite.contact_email") or invite.recipient_email,
        "company": known.get("invite.company_name") or "",
        "website": known.get("invite.website_url") or "",
    }
    return {**base, **(response.contact_details or {} if response else {})}


def _renderable_schema(schema: dict, invite: FormInvite) -> dict:
    """Strip what the filler must not see, attach what we already know.

    `maps_to` is where an answer lands in our systems. It is our routing, not
    their business, and it never crosses the wire to a form filler.
    """
    known = invite.known_context or {}
    for question in schema.get("questions") or []:
        source = question.get("prefill_source")
        question.pop("maps_to", None)
        if source:
            question["prefill_value"] = known.get(source)
            # Anything we pre-filled is a check, not a question — and stays
            # fully editable.
            question["display_mode"] = question.get("display_mode") or "confirm"
        question["contact_detail"] = source in CONTACT_SOURCES
    return schema


def load(db, invite: FormInvite) -> dict:
    """Everything the page needs, and nothing else in the workspace."""
    schema = _renderable_schema(pinned_schema(db, invite), invite)
    response = latest_response(db, invite)
    answers = answer_map(db, response)
    if invite.opened_at is None:
        invite.opened_at = datetime.utcnow()
    if invite.status == "sent":
        invite.status = "opened"
    db.commit()
    known = invite.known_context or {}
    return {
        "form": schema,
        # Their own company name, which they already know — enough for the page
        # to feel like their space without reading a single workspace row.
        "space_name": known.get("invite.company_name") or invite.recipient_name or "",
        "details": contact_details(invite, response),
        "answers": {str(qid): answer.value for qid, answer in answers.items()},
        "edited_question_ids": [qid for qid, answer in answers.items() if answer.was_edited],
        "status": response.status if response else invite.status,
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def _choice_values(options: dict) -> list:
    values = []
    for choice in options.get("choices") or []:
        values.append(choice.get("value") if isinstance(choice, dict) else choice)
    return values


def _validate_value(db, invite: FormInvite, question: dict, value):
    qtype = question.get("type")
    options = question.get("options") or {}
    if value in (None, ""):
        return None if value is None else ""
    if qtype in ("short_text", "long_text", "email", "url", "date"):
        value = str(value).strip()
        cap = 20000 if qtype == "long_text" else 2000
        if len(value) > cap:
            raise HTTPException(422, f"{question.get('label', 'Answer')} is too long")
        if qtype == "email" and not _EMAIL_RE.match(value):
            raise HTTPException(422, f"Enter a valid email for {question.get('label', 'this field')}")
        if qtype == "url":
            parsed = urlparse(value)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise HTTPException(422, f"Enter a full URL for {question.get('label', 'this field')}")
        if qtype == "date" and not re.match(r"^\d{4}-\d{2}-\d{2}$", value):
            raise HTTPException(422, f"Enter a valid date for {question.get('label', 'this field')}")
        return value
    if qtype == "number":
        try:
            number = float(value)
        except Exception:
            raise HTTPException(422, f"Enter a number for {question.get('label', 'this field')}")
        if options.get("min") is not None and number < float(options["min"]):
            raise HTTPException(422, f"{question.get('label', 'Value')} is below the minimum")
        if options.get("max") is not None and number > float(options["max"]):
            raise HTTPException(422, f"{question.get('label', 'Value')} is above the maximum")
        return number
    if qtype == "yes_no":
        if value not in (True, False):
            raise HTTPException(422, f"Choose yes or no for {question.get('label', 'this field')}")
        return value
    if qtype in ("single_choice", "dropdown"):
        allowed = _choice_values(options)
        if value not in allowed:
            raise HTTPException(422, f"Choose a valid option for {question.get('label', 'this field')}")
        return value
    if qtype == "multi_choice":
        if not isinstance(value, list):
            raise HTTPException(422, f"Choose valid options for {question.get('label', 'this field')}")
        allowed = _choice_values(options)
        if any(v not in allowed for v in value):
            raise HTTPException(422, f"Choose valid options for {question.get('label', 'this field')}")
        return list(dict.fromkeys(value))
    if qtype == "file_upload":
        if not isinstance(value, dict) or not value.get("upload_id"):
            raise HTTPException(422, f"Upload a file for {question.get('label', 'this field')}")
        upload = db.get(FormUpload, int(value["upload_id"]))
        if upload is None or upload.invite_id != invite.id or upload.question_id != question.get("id"):
            raise HTTPException(422, "That upload is not valid for this question")
        return {"upload_id": upload.id, "name": upload.original_name, "size": upload.size,
                "extension": upload.extension}
    raise HTTPException(422, "Unknown question type")


def _clean_details(raw: dict, current: dict) -> dict:
    out = dict(current)
    for key in ("name", "email", "company", "website"):
        if key not in raw:
            continue
        value = str(raw[key] or "").strip()[:1000]
        if key == "email" and value and not _EMAIL_RE.match(value):
            raise HTTPException(422, "Enter a valid email address")
        if key == "website" and value:
            parsed = urlparse(value)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise HTTPException(422, "Enter a full website URL")
        out[key] = value
    return out


# ---------------------------------------------------------------------------
# The working response
# ---------------------------------------------------------------------------
def _new_response(db, invite: FormInvite, previous: FormResponse | None) -> FormResponse:
    row = FormResponse(
        form_id=invite.form_id, form_version=invite.form_version, invite_id=invite.id,
        workspace_id=invite.workspace_id,
        response_version=(previous.response_version + 1) if previous else 1,
        supersedes_id=previous.id if previous else None, status="partial",
        contact_details=dict(previous.contact_details or {}) if previous else {},
    )
    db.add(row)
    db.flush()
    if previous:
        for answer in answer_map(db, previous).values():
            db.add(FormAnswer(response_id=row.id, question_id=answer.question_id,
                              value=answer.value, source="client_supplied",
                              prefill_value=answer.prefill_value,
                              was_edited=answer.was_edited))
        db.flush()
    return row


def working_response(db, invite: FormInvite) -> FormResponse:
    """The response this invite is currently filling.

    Keyed on the invite alone, which is the whole trick behind continuity: the
    token and the session resolve to the same invite, so they resolve to the
    same half-finished response. A submitted response is never reopened — it is
    an immutable record of what they said that day — so a later edit starts a
    superseding version instead.
    """
    latest = latest_response(db, invite)
    if latest is None:
        return _new_response(db, invite, None)
    if latest.status == "submitted":
        return _new_response(db, invite, latest)
    return latest


def _write_payload(db, invite: FormInvite, response: FormResponse, schema: dict,
                   body: FillPayload, *, submitting: bool) -> None:
    questions = {int(q["id"]): q for q in schema.get("questions") or []}
    if len(body.answers) > len(questions) + 20:
        raise HTTPException(422, "Too many answers")
    details_before = contact_details(invite, response)
    details = _clean_details(body.details, details_before)
    response.contact_details = details
    edited = {int(qid) for qid in body.edited_question_ids if int(qid) in questions}

    incoming = {}
    for raw_id, value in body.answers.items():
        try:
            qid = int(raw_id)
        except Exception:
            continue
        question = questions.get(qid)
        if question is None:
            continue
        incoming[qid] = value

    for qid, question in questions.items():
        detail_key = CONTACT_SOURCES.get(question.get("prefill_source"))
        if detail_key:
            incoming[qid] = details.get(detail_key, "")
            if details.get(detail_key) != details_before.get(detail_key):
                edited.add(qid)
        elif submitting and qid not in incoming and question.get("prefill_source"):
            # Never submitted blank just because they clicked past it: what we
            # showed them is what they confirmed.
            incoming[qid] = (invite.known_context or {}).get(question["prefill_source"])

    existing = answer_map(db, response)
    for qid, raw_value in incoming.items():
        question = questions[qid]
        value = _validate_value(db, invite, question, raw_value)
        answer = existing.get(qid)
        if answer is None:
            answer = FormAnswer(response_id=response.id, question_id=qid,
                                source="client_supplied")
            db.add(answer)
        answer.value = value
        # Self-reported, always. An answer on this form is what the client told
        # us, never verified evidence, and nothing downstream may promote it.
        answer.source = "client_supplied"
        answer.prefill_value = ((invite.known_context or {}).get(question.get("prefill_source"))
                                if question.get("prefill_source") else None)
        answer.was_edited = qid in edited
    db.flush()

    if submitting:
        all_answers = answer_map(db, response)
        missing = [q.get("label") or "Required question" for qid, q in questions.items()
                   if q.get("required") and
                   (qid not in all_answers or all_answers[qid].value in (None, "", []))]
        if missing:
            raise HTTPException(422, "Please complete: " + ", ".join(missing[:8]))


def save(db, invite: FormInvite, body: FillPayload) -> dict:
    schema = pinned_schema(db, invite)
    response = working_response(db, invite)
    _write_payload(db, invite, response, schema, body, submitting=False)
    response.status = "partial"
    response.updated_at = datetime.utcnow()
    invite.status = "partial"
    db.commit()
    return {"ok": True, "saved": True, "response_version": response.response_version}


def submit(db, invite: FormInvite, body: FillPayload, *, ip: str = "") -> dict:
    from .routers.forms import apply_response_mappings

    schema = pinned_schema(db, invite)
    response = working_response(db, invite)
    _write_payload(db, invite, response, schema, body, submitting=True)
    now = datetime.utcnow()
    response.status = "submitted"
    response.submitted_at = now
    response.updated_at = now
    response.ip_hash = fingerprint(ip) if ip else ""
    invite.status = "submitted"
    invite.submitted_at = now
    # A missing or unimplemented target is a logged skip, never a failed
    # submission — the client has done their part either way.
    mapping = apply_response_mappings(db, response)
    db.commit()
    return {"ok": True, "submitted": True, "response_version": response.response_version,
            "mapping": mapping}


# ---------------------------------------------------------------------------
# Uploads
# ---------------------------------------------------------------------------
def upload_root() -> Path:
    configured = os.getenv("FORM_UPLOAD_DIR", "").strip()
    if configured:
        root = Path(configured).resolve()
    else:
        root = (Path(__file__).resolve().parents[1] / "var" / "form_uploads").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


async def store_upload(db, invite: FormInvite, question_id: int, file: UploadFile) -> dict:
    """Write one file under a name we generated.

    The client-supplied filename is kept only as a label to show back to them.
    What lands on disk is a random key plus a checked extension, so nothing a
    filename can carry — a path, a traversal, a double extension — reaches the
    filesystem.
    """
    schema = pinned_schema(db, invite)
    question = next((q for q in schema.get("questions") or []
                     if int(q.get("id", 0)) == question_id), None)
    if question is None or question.get("type") != "file_upload":
        raise HTTPException(422, "This question does not accept files")
    original = Path(file.filename or "upload").name[:255]
    extension = Path(original).suffix.lower()
    if extension not in UPLOAD_EXTENSIONS:
        raise HTTPException(422, "Allowed file types: PDF, DOC, DOCX, PNG, JPG")
    accepted = {str(x).lower().lstrip(".") for x in
                ((question.get("options") or {}).get("accepted_file_types") or [])}
    if accepted and extension.lstrip(".") not in accepted:
        raise HTTPException(422, "This file type is not accepted for this question")

    destination = upload_root() / (secrets.token_hex(24) + extension)
    total = 0
    try:
        with destination.open("xb") as output:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD:
                    raise HTTPException(413, "Files must be 10MB or smaller")
                output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    if total == 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(422, "The uploaded file is empty")

    row = FormUpload(invite_id=invite.id, workspace_id=invite.workspace_id,
                     question_id=question_id, storage_key=destination.name,
                     original_name=original, extension=extension,
                     content_type=(file.content_type or "")[:120], size=total)
    db.add(row)
    db.commit()
    return {"upload_id": row.id, "name": row.original_name, "size": row.size,
            "extension": row.extension}
