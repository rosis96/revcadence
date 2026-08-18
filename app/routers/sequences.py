"""Shared operator/client workspace for plain-text email sequences.

There is deliberately no generation endpoint here.  A sequence references the
workspace's existing enrichment variables, previews them against stored leads,
and applies the same deterministic copy gates before rotation can use a variant.
"""
import hashlib
import json
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func

from ..auth import AuthContext, get_ctx
from ..library import store as library
from ..models.audit import AuditLog
from ..models.enrich import EnrichConfig, EnrichLead, EnrichList
from ..models.sequences import (SEQUENCE_STATUSES, VARIANT_LABELS, EmailAngle,
                                EmailSequence, EmailSequenceApproval,
                                EmailSequenceStep, EmailSequenceTemplate,
                                EmailSequenceVariant)

router = APIRouter(prefix="/api/sequences", tags=["email-sequences"])

TOKEN_RE = re.compile(r"{{\s*([A-Za-z0-9_ -]+?)\s*}}")
HTML_RE = re.compile(r"<\s*/?\s*[a-z][^>]*>", re.I)
CORE_PLACEHOLDERS = {
    "first_name": "First name", "last_name": "Last name", "title": "Job title",
    "company": "Company", "website": "Website", "email": "Email",
}

SYSTEM_TEMPLATES = [
    {
        "key": "founder-four", "name": "Founder-led outreach",
        "description": "A direct opener, concise bump, fresh proof angle, and respectful close.",
        "steps": [
            {"name": "Opener", "purpose": "opener", "wait_days": 0,
             "subject": "{{subject_line}}",
             "body": "Hi {{first_name}},\n\n{{personalized_first_line}}\n\nWorth a conversation?"},
            {"name": "Bump", "purpose": "bump", "wait_days": 2,
             "subject": "Re: {{subject_line}}",
             "body": "Hi {{first_name}},\n\nBringing this back to the top of your inbox. Is this relevant for {{company}}?"},
            {"name": "New angle", "purpose": "new_angle", "wait_days": 4,
             "subject": "A different thought",
             "body": "Hi {{first_name}},\n\n{{product_complimentary_1}}\n\nHappy to share the short version if useful."},
            {"name": "Breakup", "purpose": "breakup", "wait_days": 5,
             "subject": "Close the loop?",
             "body": "Hi {{first_name}},\n\nI will close the loop for now. If this becomes timely later, just reply here."},
        ],
    },
    {
        "key": "proof-first", "name": "Proof-first",
        "description": "Lead with specific proof, then add context without repeating the opener.",
        "steps": [
            {"name": "Proof opener", "purpose": "opener", "wait_days": 0,
             "subject": "{{subject_line}}", "body": "Hi {{first_name}},\n\n{{personalized_first_line}}\n\nOpen to seeing the relevant proof?"},
            {"name": "Short bump", "purpose": "bump", "wait_days": 3,
             "subject": "Re: {{subject_line}}", "body": "Hi {{first_name}},\n\nShould I send the example I mentioned?"},
            {"name": "Second observation", "purpose": "new_angle", "wait_days": 4,
             "subject": "One more observation", "body": "Hi {{first_name}},\n\n{{product_complimentary_2}}"},
            {"name": "Close", "purpose": "breakup", "wait_days": 6,
             "subject": "Leave it here?", "body": "Hi {{first_name}},\n\nNo problem if this is not a priority. I will leave it here."},
        ],
    },
    {
        "key": "question-led", "name": "Question-led",
        "description": "A light sequence built around specific, answerable observations.",
        "steps": [
            {"name": "Question", "purpose": "opener", "wait_days": 0,
             "subject": "{{subject_line}}", "body": "Hi {{first_name}},\n\n{{product_complimentary_1}}"},
            {"name": "Bump", "purpose": "bump", "wait_days": 2,
             "subject": "Re: {{subject_line}}", "body": "Hi {{first_name}},\n\nCurious whether I found the right person for this."},
            {"name": "Fresh angle", "purpose": "new_angle", "wait_days": 5,
             "subject": "Another angle", "body": "Hi {{first_name}},\n\n{{personalized_first_line}}\n\nWould a short example help?"},
            {"name": "Breakup", "purpose": "breakup", "wait_days": 5,
             "subject": "Close this out", "body": "Hi {{first_name}},\n\nI will stop here. Reply anytime if the timing changes."},
        ],
    },
]


# ---------------------------------------------------------------- access + output
def _sequence_q(ctx: AuthContext):
    return (ctx.db.query(EmailSequence)
            .filter(EmailSequence.org_id == ctx.org_id,
                    EmailSequence.workspace_id.in_(ctx.allowed_workspace_ids())))


def _sequence(ctx: AuthContext, sequence_id: int, *, include_archived: bool = False) -> EmailSequence:
    q = _sequence_q(ctx).filter(EmailSequence.id == sequence_id)
    if not include_archived:
        q = q.filter(EmailSequence.status != "archived")
    row = q.first()
    if row is None:
        raise HTTPException(404, "Sequence not found")
    return row


def _step(ctx: AuthContext, step_id: int) -> tuple[EmailSequenceStep, EmailSequence]:
    row = ctx.db.get(EmailSequenceStep, step_id)
    if row is None:
        raise HTTPException(404, "Step not found")
    try:
        seq = _sequence(ctx, row.sequence_id)
    except HTTPException:
        raise HTTPException(404, "Step not found")
    return row, seq


def _variant(ctx: AuthContext, variant_id: int) -> tuple[EmailSequenceVariant, EmailSequenceStep, EmailSequence]:
    row = ctx.db.get(EmailSequenceVariant, variant_id)
    if row is None:
        raise HTTPException(404, "Variant not found")
    try:
        step, seq = _step(ctx, row.step_id)
    except HTTPException:
        raise HTTPException(404, "Variant not found")
    return row, step, seq


def _team_only(ctx: AuthContext) -> None:
    if ctx.role == "client":
        raise HTTPException(403, "RevCadence team access required")


def _client_only(ctx: AuthContext) -> None:
    if ctx.role != "client":
        raise HTTPException(403, "Client approval access required")


def _audit(ctx: AuthContext, seq: EmailSequence, action: str, object_type: str,
           object_id: int, data: dict | None = None) -> None:
    ctx.db.add(AuditLog(org_id=seq.org_id, workspace_id=seq.workspace_id,
                        user_id=ctx.user.id, action=action, object_type=object_type,
                        object_id=object_id, data=data or {}))


def _touch(ctx: AuthContext, seq: EmailSequence) -> None:
    """An approved/reviewed tree is never mutated under its pinned version."""
    if seq.status in ("approved", "in_review"):
        seq.version = (seq.version or 1) + 1
        seq.status = "draft"
    seq.updated_at = datetime.utcnow()


def _formats(db, workspace_id: int) -> list[dict]:
    from ..enrichment.defaults import effective_formats
    cfg = db.query(EnrichConfig).filter(EnrichConfig.workspace_id == workspace_id).first()
    return effective_formats(cfg.formats if cfg else [])


def _proof_choices(db, workspace_id: int) -> list[dict]:
    """What an angle may point at, with its provenance attached.

    Now read from the Library rather than assembled from the brain profile, so a
    choice carries `source` / `named_claim_allowed` and keeps a stable key when
    its wording is edited. Proof still sitting in the profile is included with
    its original hash key, so angles written before the Library keep resolving.
    """
    return library.proof_choices(db, workspace_id)


def _variant_out(v: EmailSequenceVariant) -> dict:
    sent = int(v.sent_count or 0)
    return {
        "id": v.id, "step_id": v.step_id, "label": v.label,
        "subject": v.subject or "", "body": v.body or "", "change_note": v.change_note or "",
        "enabled": bool(v.enabled), "promoted": bool(v.promoted),
        "quality": v.quality or {}, "revision": v.revision or 1,
        "archived": bool(v.archived_at),
        "performance": {
            "sent": sent, "replies": int(v.reply_count or 0),
            "positive": int(v.positive_count or 0), "meetings": int(v.meeting_count or 0),
            "reply_rate": round(100 * int(v.reply_count or 0) / sent, 1) if sent else 0,
            "positive_rate": round(100 * int(v.positive_count or 0) / sent, 1) if sent else 0,
        },
    }


def _step_out(db, step: EmailSequenceStep, *, archived: bool = False) -> dict:
    q = db.query(EmailSequenceVariant).filter(EmailSequenceVariant.step_id == step.id)
    # Archived variants remain visible forever with their statistics.  The
    # rotation and approval queries below explicitly exclude them.
    variants = q.order_by(EmailSequenceVariant.label).all()
    return {
        "id": step.id, "sequence_id": step.sequence_id, "position": step.position,
        "name": step.name, "purpose": step.purpose, "wait_days": step.wait_days,
        "archived": bool(step.archived_at), "variants": [_variant_out(v) for v in variants],
    }


def _snapshot(db, seq: EmailSequence) -> dict:
    angle = db.get(EmailAngle, seq.angle_id)
    steps = (db.query(EmailSequenceStep)
             .filter(EmailSequenceStep.sequence_id == seq.id, EmailSequenceStep.archived_at.is_(None))
             .order_by(EmailSequenceStep.position, EmailSequenceStep.id).all())
    return {
        "sequence": {"id": seq.id, "name": seq.name, "description": seq.description or "",
                     "version": seq.version},
        "angle": {"name": angle.name, "hypothesis": angle.hypothesis or "",
                  "proof_key": angle.proof_key or "", "proof_label": angle.proof_label or ""},
        "steps": [_step_out(db, s) for s in steps],
    }


def _sequence_out(db, seq: EmailSequence, *, full: bool = False) -> dict:
    angle = db.get(EmailAngle, seq.angle_id)
    steps = (db.query(EmailSequenceStep)
             .filter(EmailSequenceStep.sequence_id == seq.id, EmailSequenceStep.archived_at.is_(None))
             .order_by(EmailSequenceStep.position, EmailSequenceStep.id).all())
    out = {
        "id": seq.id, "workspace_id": seq.workspace_id, "name": seq.name,
        "description": seq.description or "", "status": seq.status, "version": seq.version,
        "current_list_id": seq.current_list_id, "template_source_id": seq.template_source_id,
        "angle": {"id": angle.id, "name": angle.name, "hypothesis": angle.hypothesis or "",
                  "proof_key": angle.proof_key or "", "proof_label": angle.proof_label or ""},
        "step_count": len(steps),
        "enabled_variants": sum(1 for s in steps for v in
                                db.query(EmailSequenceVariant).filter(
                                    EmailSequenceVariant.step_id == s.id,
                                    EmailSequenceVariant.enabled.is_(True),
                                    EmailSequenceVariant.archived_at.is_(None)).all()),
        "created_at": seq.created_at.isoformat() if seq.created_at else None,
        "updated_at": seq.updated_at.isoformat() if seq.updated_at else None,
    }
    if full:
        out["steps"] = [_step_out(db, s) for s in steps]
        approvals = (db.query(EmailSequenceApproval)
                     .filter(EmailSequenceApproval.sequence_id == seq.id)
                     .order_by(EmailSequenceApproval.id.desc()).all())
        out["approvals"] = [{
            "id": a.id, "version": a.sequence_version, "status": a.status,
            "note": a.note or "", "requested_at": a.requested_at.isoformat() if a.requested_at else None,
            "decided_at": a.decided_at.isoformat() if a.decided_at else None,
        } for a in approvals]
    return out


# ---------------------------------------------------------------- copy quality
def _copy_hash(v: EmailSequenceVariant) -> str:
    raw = json.dumps([v.subject or "", v.body or "", v.change_note or ""], ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


_CLAIM_NOISE = re.compile(r"[^a-z0-9]+")
# Suffixes a writer drops in copy: "Harlow Group Ltd" is named the moment
# "Harlow Group" appears, so the check must not depend on the legal form.
_CLAIM_SUFFIXES = ("ltd", "limited", "llc", "inc", "plc", "gmbh", "bv", "pty",
                   "co", "corp", "group", "holdings", "studio", "studios")


def _norm_claim(text: str) -> str:
    return f" {_CLAIM_NOISE.sub(' ', str(text or '').lower()).strip()} "


def _named_client(proof: dict) -> str:
    """The token sequence that counts as naming this proof's client, or "".

    Padded with spaces on both sides and matched against padded copy, so the test
    is whole-word: "Kaya" must not fire on "kayak", and a two-letter client name
    is skipped entirely rather than matching half the alphabet.
    """
    raw = str(proof.get("client_name") or proof.get("label") or "").split("—")[0]
    words = _norm_claim(raw).split()
    while words and words[-1] in _CLAIM_SUFFIXES:
        words.pop()
    name = " ".join(words)
    return f" {name} " if len(name) >= 3 else ""


def _quality(db, seq: EmailSequence, variant: EmailSequenceVariant) -> dict:
    from ..enrichment.pipeline import _BANNED_PHRASES
    issues = []
    copy = f"{variant.subject or ''}\n{variant.body or ''}"
    if not (variant.subject or "").strip():
        issues.append({"code": "missing_subject", "message": "Add a subject line."})
    if not (variant.body or "").strip():
        issues.append({"code": "missing_body", "message": "Add the email body."})
    if HTML_RE.search(copy):
        issues.append({"code": "html", "message": "Sequences are plain text; remove HTML markup."})
    if "—" in copy:
        issues.append({"code": "em_dash", "message": "Remove the em dash to meet the workspace copy rules."})
    low = copy.casefold()
    for phrase in _BANNED_PHRASES:
        if phrase in low:
            issues.append({"code": "banned_phrase", "message": f"Remove banned phrase: “{phrase}”."})
    if variant.label != "A" and not (variant.change_note or "").strip():
        issues.append({"code": "change_note", "message": f"Variant {variant.label} needs a one-line change note."})

    formats = _formats(db, seq.workspace_id)
    allowed = {str(f.get("name") or "").strip(): f for f in formats if f.get("name")}
    allowed.update({key: {"name": key, "label": label, "core": True}
                    for key, label in CORE_PLACEHOLDERS.items()})
    tokens = [re.sub(r"[ -]+", "_", t.strip().lower()) for t in TOKEN_RE.findall(copy)]
    unknown = sorted({t for t in tokens if t not in allowed})
    if unknown:
        issues.append({"code": "unknown_placeholder",
                       "message": "Unknown shared placeholder(s): " + ", ".join(unknown) + ".",
                       "link": "/enrichment/formats"})

    angle = db.get(EmailAngle, seq.angle_id)
    proofs = {p["key"]: p for p in _proof_choices(db, seq.workspace_id)}
    proof = proofs.get(angle.proof_key or "")
    evidence = {}
    if not proof:
        issues.append({"code": "missing_proof",
                       "message": "This angle needs a current case study or proof record before it can send.",
                       "link": "/w/library"})
    else:
        evidence = {"proof_key": proof["key"], "proof_label": proof["label"],
                    "source": proof.get("source", "operator"),
                    "verified": bool(proof.get("verified")),
                    "named_claim_allowed": bool(proof.get("named_claim_allowed"))}
        literal_numbers = set(re.findall(r"(?<![A-Za-z_])\d+(?:[.,]\d+)?%?", TOKEN_RE.sub("", copy)))
        grounding = f"{proof.get('label', '')} {proof.get('detail', '')}"
        unsupported = sorted(number for number in literal_numbers if number not in grounding)
        if unsupported:
            issues.append({"code": "unsupported_number",
                           "message": "Numbers must be supported by the selected proof: " + ", ".join(unsupported) + "."})
        # Evidence first: a client-supplied or operator-noted fact is usable as
        # background, but naming the client turns it into a claim the recipient
        # could check and we could not. Blocked here rather than in the form,
        # because enabling a variant runs this and refuses on any issue.
        if not proof.get("named_claim_allowed"):
            named = _named_client(proof)
            if named and named in _norm_claim(copy):
                issues.append({
                    "code": "unverified_named_claim",
                    "message": (f"“{proof.get('client_name') or proof['label']}” is "
                                f"{proof.get('source_label', proof.get('source', 'unverified'))} "
                                "evidence, so it cannot be named in an email. Use it as "
                                "background, or verify it in the Library."),
                    "link": "/w/library"})
    return {"passed": not issues, "issues": issues, "checked_at": datetime.utcnow().isoformat(),
            "copy_hash": _copy_hash(variant), "placeholder_count": len(tokens),
            "evidence": evidence}


# ---------------------------------------------------------------- request bodies
class SequenceCreate(BaseModel):
    workspace_id: int
    name: str = "New email sequence"
    template_key: str = "founder-four"
    angle_name: str = "Primary angle"
    hypothesis: str = ""
    proof_key: str = ""


class SequencePatch(BaseModel):
    name: str | None = None
    description: str | None = None
    current_list_id: int | None = None
    angle_name: str | None = None
    hypothesis: str | None = None
    proof_key: str | None = None


class StepCreate(BaseModel):
    name: str = "New step"
    purpose: str = "follow_up"
    wait_days: int = Field(default=2, ge=0, le=365)
    position: int | None = None


class StepPatch(BaseModel):
    name: str | None = None
    purpose: str | None = None
    wait_days: int | None = Field(default=None, ge=0, le=365)
    position: int | None = Field(default=None, ge=0)


class ReorderIn(BaseModel):
    ordered_ids: list[int]


class VariantCreate(BaseModel):
    from_variant_id: int | None = None
    subject: str = ""
    body: str = ""
    change_note: str = ""


class VariantPatch(BaseModel):
    subject: str | None = None
    body: str | None = None
    change_note: str | None = None
    enabled: bool | None = None


class NoteIn(BaseModel):
    note: str = ""


class PerformanceIn(BaseModel):
    sent: int = Field(default=0, ge=0)
    replies: int = Field(default=0, ge=0)
    positive: int = Field(default=0, ge=0)
    meetings: int = Field(default=0, ge=0)


class TemplateIn(BaseModel):
    name: str | None = None


class FormatPatch(BaseModel):
    guidance: str | None = None
    template: str | None = None


class ProofIn(BaseModel):
    workspace_id: int
    name: str
    outcome: str
    engagement: str = ""
    segment: str = ""
    year: int | None = Field(default=None, ge=1900, le=2200)
    source_url: str = ""


# ---------------------------------------------------------------- sequences + context
@router.get("")
def list_sequences(workspace_id: int | None = None, ctx: AuthContext = Depends(get_ctx)):
    ws_ids = ctx.workspace_ids_for_query(workspace_id)
    rows = (_sequence_q(ctx).filter(EmailSequence.workspace_id.in_(ws_ids),
                                    EmailSequence.status != "archived")
            .order_by(EmailSequence.updated_at.desc(), EmailSequence.id.desc()).all())
    return [_sequence_out(ctx.db, row) for row in rows]


@router.get("/context")
def context(workspace_id: int, ctx: AuthContext = Depends(get_ctx)):
    ctx.require_workspace(workspace_id)
    formats = _formats(ctx.db, workspace_id)
    custom = (ctx.db.query(EmailSequenceTemplate)
              .filter(EmailSequenceTemplate.org_id == ctx.org_id,
                      EmailSequenceTemplate.archived_at.is_(None))
              .order_by(EmailSequenceTemplate.id.desc()).all())
    lists = (ctx.db.query(EnrichList).filter(EnrichList.workspace_id == workspace_id)
             .order_by(EnrichList.id.desc()).all())
    return {
        "role": ctx.role,
        "can_request_approval": ctx.role != "client",
        "can_approve": ctx.role == "client",
        "templates": [{"key": f"system:{t['key']}", "name": t["name"],
                       "description": t["description"], "system": True} for t in SYSTEM_TEMPLATES] +
                     [{"key": f"saved:{t.id}", "name": t.name,
                       "description": t.description or "", "system": False} for t in custom],
        "formats": [{"name": f.get("name"), "label": f.get("label") or f.get("name"),
                     "guidance": f.get("guidance") or f.get("purpose") or "",
                     "template": f.get("template") or "", "enabled": f.get("enabled", True)}
                    for f in formats],
        "core_placeholders": [{"name": k, "label": v} for k, v in CORE_PLACEHOLDERS.items()],
        "proof": _proof_choices(ctx.db, workspace_id),
        "lists": [{"id": row.id, "name": row.name} for row in lists],
    }


def _template_structure(ctx: AuthContext, key: str) -> tuple[list[dict], int | None]:
    raw = key.removeprefix("system:")
    system = next((t for t in SYSTEM_TEMPLATES if t["key"] == raw), None)
    if system:
        return list(system["steps"]), None
    if key.startswith("saved:"):
        try:
            template_id = int(key.split(":", 1)[1])
        except ValueError:
            raise HTTPException(422, "Invalid template")
        row = (ctx.db.query(EmailSequenceTemplate)
               .filter(EmailSequenceTemplate.id == template_id,
                       EmailSequenceTemplate.org_id == ctx.org_id,
                       EmailSequenceTemplate.archived_at.is_(None)).first())
        if row:
            return list((row.structure or {}).get("steps") or []), row.id
    raise HTTPException(422, "Unknown sequence template")


@router.post("")
def create_sequence(body: SequenceCreate, ctx: AuthContext = Depends(get_ctx)):
    _team_only(ctx)
    ctx.require_workspace(body.workspace_id)
    steps, source_id = _template_structure(ctx, body.template_key)
    proof = next((p for p in _proof_choices(ctx.db, body.workspace_id) if p["key"] == body.proof_key), None)
    angle = EmailAngle(org_id=ctx.org_id, workspace_id=body.workspace_id,
                       name=body.angle_name.strip() or "Primary angle",
                       hypothesis=body.hypothesis.strip(), proof_key=body.proof_key if proof else "",
                       proof_label=proof["label"] if proof else "", created_by=ctx.user.id)
    ctx.db.add(angle); ctx.db.flush()
    seq = EmailSequence(org_id=ctx.org_id, workspace_id=body.workspace_id, angle_id=angle.id,
                        name=body.name.strip() or "New email sequence", template_source_id=source_id,
                        created_by=ctx.user.id)
    ctx.db.add(seq); ctx.db.flush()
    for position, spec in enumerate(steps):
        step = EmailSequenceStep(sequence_id=seq.id, position=position,
                                 name=str(spec.get("name") or f"Email {position + 1}"),
                                 purpose=str(spec.get("purpose") or "follow_up"),
                                 wait_days=max(0, min(int(spec.get("wait_days") or 0), 365)))
        ctx.db.add(step); ctx.db.flush()
        variants = spec.get("variants") if isinstance(spec.get("variants"), list) else None
        if not variants:
            variants = [{"label": "A", "subject": spec.get("subject") or "",
                         "body": spec.get("body") or "", "change_note": ""}]
        for variant in variants[:7]:
            label = str(variant.get("label") or "A").upper()
            if label not in VARIANT_LABELS:
                continue
            ctx.db.add(EmailSequenceVariant(
                step_id=step.id, label=label, subject=str(variant.get("subject") or ""),
                body=str(variant.get("body") or ""),
                change_note=str(variant.get("change_note") or ""), enabled=False))
    _audit(ctx, seq, "create_email_sequence", "email_sequence", seq.id,
           {"template": body.template_key, "steps": len(steps)})
    ctx.db.commit()
    return _sequence_out(ctx.db, seq, full=True)


@router.get("/{sequence_id}")
def get_sequence(sequence_id: int, ctx: AuthContext = Depends(get_ctx)):
    return _sequence_out(ctx.db, _sequence(ctx, sequence_id), full=True)


@router.patch("/{sequence_id}")
def patch_sequence(sequence_id: int, body: SequencePatch, ctx: AuthContext = Depends(get_ctx)):
    _team_only(ctx)
    seq = _sequence(ctx, sequence_id)
    data = body.model_dump(exclude_unset=True)
    if "current_list_id" in data and data["current_list_id"] is not None:
        lst = ctx.db.get(EnrichList, data["current_list_id"])
        if not lst or lst.workspace_id != seq.workspace_id:
            raise HTTPException(422, "List must belong to this workspace")
    _touch(ctx, seq)
    angle = ctx.db.get(EmailAngle, seq.angle_id)
    for key in ("name", "description", "current_list_id"):
        if key in data:
            setattr(seq, key, data[key].strip() if isinstance(data[key], str) else data[key])
    if "angle_name" in data:
        angle.name = data["angle_name"].strip() or "Primary angle"
    if "hypothesis" in data:
        angle.hypothesis = data["hypothesis"].strip()
    if "proof_key" in data:
        proof = next((p for p in _proof_choices(ctx.db, seq.workspace_id) if p["key"] == data["proof_key"]), None)
        angle.proof_key = data["proof_key"] if proof else ""
        angle.proof_label = proof["label"] if proof else ""
    _audit(ctx, seq, "update_email_sequence", "email_sequence", seq.id, {"fields": list(data)})
    ctx.db.commit()
    return _sequence_out(ctx.db, seq, full=True)


@router.delete("/{sequence_id}")
def archive_sequence(sequence_id: int, ctx: AuthContext = Depends(get_ctx)):
    _team_only(ctx)
    seq = _sequence(ctx, sequence_id)
    seq.status = "archived"; seq.updated_at = datetime.utcnow()
    _audit(ctx, seq, "archive_email_sequence", "email_sequence", seq.id)
    ctx.db.commit()
    return {"ok": True}


def _copy_tree(db, source: EmailSequence, target: EmailSequence) -> None:
    steps = (db.query(EmailSequenceStep).filter(EmailSequenceStep.sequence_id == source.id,
                                               EmailSequenceStep.archived_at.is_(None))
             .order_by(EmailSequenceStep.position, EmailSequenceStep.id).all())
    for old_step in steps:
        step = EmailSequenceStep(sequence_id=target.id, position=old_step.position,
                                 name=old_step.name, purpose=old_step.purpose, wait_days=old_step.wait_days)
        db.add(step); db.flush()
        variants = (db.query(EmailSequenceVariant)
                    .filter(EmailSequenceVariant.step_id == old_step.id,
                            EmailSequenceVariant.archived_at.is_(None))
                    .order_by(EmailSequenceVariant.label).all())
        for old in variants:
            db.add(EmailSequenceVariant(step_id=step.id, label=old.label, subject=old.subject,
                                        body=old.body, change_note=old.change_note,
                                        enabled=False, quality={}))


@router.post("/{sequence_id}/duplicate")
def duplicate_sequence(sequence_id: int, ctx: AuthContext = Depends(get_ctx)):
    _team_only(ctx)
    source = _sequence(ctx, sequence_id)
    old_angle = ctx.db.get(EmailAngle, source.angle_id)
    angle = EmailAngle(org_id=source.org_id, workspace_id=source.workspace_id,
                       name=old_angle.name, hypothesis=old_angle.hypothesis,
                       proof_key=old_angle.proof_key, proof_label=old_angle.proof_label,
                       created_by=ctx.user.id)
    ctx.db.add(angle); ctx.db.flush()
    target = EmailSequence(org_id=source.org_id, workspace_id=source.workspace_id, angle_id=angle.id,
                           name=f"{source.name} copy", description=source.description,
                           current_list_id=source.current_list_id, created_by=ctx.user.id)
    ctx.db.add(target); ctx.db.flush(); _copy_tree(ctx.db, source, target)
    _audit(ctx, target, "duplicate_email_sequence", "email_sequence", target.id, {"source_id": source.id})
    ctx.db.commit()
    return _sequence_out(ctx.db, target, full=True)


@router.post("/{sequence_id}/save-as-template")
def save_template(sequence_id: int, body: TemplateIn, ctx: AuthContext = Depends(get_ctx)):
    _team_only(ctx)
    seq = _sequence(ctx, sequence_id)
    snap = _snapshot(ctx.db, seq)
    structure = {"angle": {"name": snap["angle"]["name"], "hypothesis": snap["angle"]["hypothesis"]},
                 "steps": [{"name": s["name"], "purpose": s["purpose"], "wait_days": s["wait_days"],
                            "variants": [{"label": v["label"], "subject": v["subject"], "body": v["body"],
                                          "change_note": v["change_note"]} for v in s["variants"] if not v["archived"]]}
                           for s in snap["steps"]]}
    row = EmailSequenceTemplate(org_id=ctx.org_id, name=(body.name or seq.name).strip(),
                                description=seq.description or "", structure=structure,
                                created_by=ctx.user.id)
    ctx.db.add(row); ctx.db.flush()
    _audit(ctx, seq, "save_email_sequence_template", "email_sequence_template", row.id)
    ctx.db.commit()
    return {"id": row.id, "key": f"saved:{row.id}", "name": row.name}


# ---------------------------------------------------------------- steps + variants
@router.post("/{sequence_id}/steps")
def create_step(sequence_id: int, body: StepCreate, ctx: AuthContext = Depends(get_ctx)):
    _team_only(ctx)
    seq = _sequence(ctx, sequence_id); _touch(ctx, seq)
    position = body.position
    if position is None:
        maximum = (ctx.db.query(func.max(EmailSequenceStep.position))
                   .filter(EmailSequenceStep.sequence_id == seq.id).scalar())
        position = 0 if maximum is None else maximum + 1
    row = EmailSequenceStep(sequence_id=seq.id, position=position, name=body.name.strip() or "New step",
                            purpose=body.purpose.strip() or "follow_up", wait_days=body.wait_days)
    ctx.db.add(row); ctx.db.flush()
    ctx.db.add(EmailSequenceVariant(step_id=row.id, label="A"))
    _audit(ctx, seq, "create_email_sequence_step", "email_sequence_step", row.id)
    ctx.db.commit()
    return _step_out(ctx.db, row)


@router.patch("/steps/{step_id}")
def patch_step(step_id: int, body: StepPatch, ctx: AuthContext = Depends(get_ctx)):
    _team_only(ctx)
    row, seq = _step(ctx, step_id); _touch(ctx, seq)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(row, key, value.strip() if isinstance(value, str) else value)
    _audit(ctx, seq, "update_email_sequence_step", "email_sequence_step", row.id)
    ctx.db.commit()
    return _step_out(ctx.db, row)


@router.delete("/steps/{step_id}")
def archive_step(step_id: int, ctx: AuthContext = Depends(get_ctx)):
    _team_only(ctx)
    row, seq = _step(ctx, step_id); _touch(ctx, seq)
    row.archived_at = datetime.utcnow()
    for variant in ctx.db.query(EmailSequenceVariant).filter(EmailSequenceVariant.step_id == row.id).all():
        variant.enabled = False
    _audit(ctx, seq, "archive_email_sequence_step", "email_sequence_step", row.id)
    ctx.db.commit()
    return {"ok": True}


@router.post("/{sequence_id}/steps/reorder")
def reorder_steps(sequence_id: int, body: ReorderIn, ctx: AuthContext = Depends(get_ctx)):
    _team_only(ctx)
    seq = _sequence(ctx, sequence_id)
    rows = (ctx.db.query(EmailSequenceStep)
            .filter(EmailSequenceStep.sequence_id == seq.id, EmailSequenceStep.archived_at.is_(None)).all())
    if set(body.ordered_ids) != {r.id for r in rows} or len(body.ordered_ids) != len(rows):
        raise HTTPException(422, "ordered_ids must contain each active step exactly once")
    _touch(ctx, seq)
    by_id = {r.id: r for r in rows}
    for position, row_id in enumerate(body.ordered_ids):
        by_id[row_id].position = position
    _audit(ctx, seq, "reorder_email_sequence_steps", "email_sequence", seq.id)
    ctx.db.commit()
    return {"ok": True}


@router.post("/steps/{step_id}/variants")
def create_variant(step_id: int, body: VariantCreate, ctx: AuthContext = Depends(get_ctx)):
    _team_only(ctx)
    step, seq = _step(ctx, step_id); _touch(ctx, seq)
    existing = {v.label for v in ctx.db.query(EmailSequenceVariant).filter(
        EmailSequenceVariant.step_id == step.id).all()}
    label = next((letter for letter in VARIANT_LABELS if letter not in existing), None)
    if not label:
        raise HTTPException(422, "A step supports variants A through G")
    if label != "A" and not body.change_note.strip():
        raise HTTPException(422, f"Variant {label} needs a one-line change note")
    subject, copy_body = body.subject, body.body
    if body.from_variant_id is not None:
        source = ctx.db.get(EmailSequenceVariant, body.from_variant_id)
        if not source or source.step_id != step.id:
            raise HTTPException(422, "Source variant must belong to this step")
        subject, copy_body = source.subject or "", source.body or ""
    row = EmailSequenceVariant(step_id=step.id, label=label, subject=subject,
                               body=copy_body, change_note=body.change_note.strip(), enabled=False)
    ctx.db.add(row); ctx.db.flush()
    _audit(ctx, seq, "create_email_sequence_variant", "email_sequence_variant", row.id, {"label": label})
    ctx.db.commit()
    return _variant_out(row)


@router.patch("/variants/{variant_id}")
def patch_variant(variant_id: int, body: VariantPatch, ctx: AuthContext = Depends(get_ctx)):
    _team_only(ctx)
    row, _step_row, seq = _variant(ctx, variant_id)
    if row.archived_at:
        raise HTTPException(409, "Archived variants are read-only")
    data = body.model_dump(exclude_unset=True)
    _touch(ctx, seq)
    copy_changed = any(key in data and data[key] != getattr(row, key) for key in ("subject", "body", "change_note"))
    for key in ("subject", "body", "change_note"):
        if key in data:
            setattr(row, key, data[key])
    if copy_changed:
        row.revision = (row.revision or 1) + 1
        row.quality = {"passed": False, "stale": True, "issues": []}
        row.enabled = False
    if data.get("enabled") is True:
        quality = _quality(ctx.db, seq, row)
        row.quality = quality
        if not quality["passed"]:
            ctx.db.flush()
            raise HTTPException(422, {"message": "This variant must pass quality checks before enabling.",
                                      "quality": quality})
        row.enabled = True
    elif data.get("enabled") is False:
        row.enabled = False
    _audit(ctx, seq, "update_email_sequence_variant", "email_sequence_variant", row.id,
           {"fields": list(data), "enabled": bool(row.enabled)})
    ctx.db.commit()
    return _variant_out(row)


@router.post("/variants/{variant_id}/quality")
def check_quality(variant_id: int, ctx: AuthContext = Depends(get_ctx)):
    _team_only(ctx)
    row, _step_row, seq = _variant(ctx, variant_id)
    row.quality = _quality(ctx.db, seq, row)
    _audit(ctx, seq, "check_email_variant_quality", "email_sequence_variant", row.id,
           {"passed": row.quality["passed"]})
    ctx.db.commit()
    return row.quality


@router.post("/variants/{variant_id}/archive")
def archive_variant(variant_id: int, ctx: AuthContext = Depends(get_ctx)):
    _team_only(ctx)
    row, _step_row, seq = _variant(ctx, variant_id); _touch(ctx, seq)
    row.archived_at = datetime.utcnow(); row.enabled = False; row.promoted = False
    _audit(ctx, seq, "archive_email_sequence_variant", "email_sequence_variant", row.id)
    ctx.db.commit()
    return {"ok": True}


@router.post("/variants/{variant_id}/promote")
def promote_variant(variant_id: int, ctx: AuthContext = Depends(get_ctx)):
    _team_only(ctx)
    row, step, seq = _variant(ctx, variant_id); _touch(ctx, seq)
    if row.archived_at:
        raise HTTPException(409, "Archived variants cannot be promoted")
    for sibling in ctx.db.query(EmailSequenceVariant).filter(EmailSequenceVariant.step_id == step.id).all():
        sibling.promoted = sibling.id == row.id
    _audit(ctx, seq, "promote_email_sequence_variant", "email_sequence_variant", row.id)
    ctx.db.commit()
    return _variant_out(row)


@router.post("/variants/{variant_id}/performance")
def update_performance(variant_id: int, body: PerformanceIn, ctx: AuthContext = Depends(get_ctx)):
    _team_only(ctx)
    row, _step_row, seq = _variant(ctx, variant_id)
    row.sent_count = body.sent; row.reply_count = body.replies
    row.positive_count = body.positive; row.meeting_count = body.meetings
    _audit(ctx, seq, "update_email_variant_performance", "email_sequence_variant", row.id,
           body.model_dump())
    ctx.db.commit()
    return _variant_out(row)


@router.post("/steps/{step_id}/next-variant")
def next_variant(step_id: int, ctx: AuthContext = Depends(get_ctx)):
    """Rotation boundary used by senders: only current, enabled variants are returned."""
    _team_only(ctx)
    step, _seq = _step(ctx, step_id)
    rows = (ctx.db.query(EmailSequenceVariant)
            .filter(EmailSequenceVariant.step_id == step.id,
                    EmailSequenceVariant.enabled.is_(True),
                    EmailSequenceVariant.archived_at.is_(None))
            .order_by(EmailSequenceVariant.promoted.desc(), EmailSequenceVariant.label).all())
    if not rows:
        raise HTTPException(409, "No enabled variant is available for this step")
    row = rows[(step.rotation_cursor or 0) % len(rows)]
    step.rotation_cursor = (step.rotation_cursor or 0) + 1
    ctx.db.commit()
    return _variant_out(row)


# ---------------------------------------------------------------- approval
def _approval_gate(db, seq: EmailSequence) -> list[dict]:
    issues = []
    steps = (db.query(EmailSequenceStep).filter(EmailSequenceStep.sequence_id == seq.id,
                                               EmailSequenceStep.archived_at.is_(None))
             .order_by(EmailSequenceStep.position).all())
    if not steps:
        return [{"code": "no_steps", "message": "Add at least one email."}]
    for step in steps:
        variants = (db.query(EmailSequenceVariant)
                    .filter(EmailSequenceVariant.step_id == step.id,
                            EmailSequenceVariant.enabled.is_(True),
                            EmailSequenceVariant.archived_at.is_(None)).all())
        if not variants:
            issues.append({"code": "step_disabled", "message": f"{step.name} has no enabled variant."})
        for variant in variants:
            quality = _quality(db, seq, variant)
            variant.quality = quality
            if not quality["passed"]:
                issues.append({"code": "quality", "message": f"{step.name}, variant {variant.label} needs attention.",
                               "variant_id": variant.id, "quality": quality})
    return issues


@router.post("/{sequence_id}/submit-approval")
def submit_approval(sequence_id: int, body: NoteIn, ctx: AuthContext = Depends(get_ctx)):
    _team_only(ctx)
    seq = _sequence(ctx, sequence_id)
    issues = _approval_gate(ctx.db, seq)
    if issues:
        ctx.db.flush()
        raise HTTPException(422, {"message": "Resolve the sequence checks before sending for approval.",
                                  "issues": issues})
    ctx.db.query(EmailSequenceApproval).filter(
        EmailSequenceApproval.sequence_id == seq.id,
        EmailSequenceApproval.status == "pending").update({"status": "superseded"})
    row = EmailSequenceApproval(sequence_id=seq.id, sequence_version=seq.version,
                                status="pending", snapshot=_snapshot(ctx.db, seq),
                                note=body.note.strip(), requested_by=ctx.user.id)
    ctx.db.add(row); seq.status = "in_review"; seq.updated_at = datetime.utcnow()
    _audit(ctx, seq, "submit_email_sequence_for_approval", "email_sequence_approval", seq.id,
           {"version": seq.version})
    ctx.db.commit()
    return _sequence_out(ctx.db, seq, full=True)


def _pending_approval(db, seq: EmailSequence) -> EmailSequenceApproval:
    row = (db.query(EmailSequenceApproval)
           .filter(EmailSequenceApproval.sequence_id == seq.id,
                   EmailSequenceApproval.status == "pending",
                   EmailSequenceApproval.sequence_version == seq.version)
           .order_by(EmailSequenceApproval.id.desc()).first())
    if not row or seq.status != "in_review":
        raise HTTPException(409, "This sequence is not awaiting approval")
    return row


@router.post("/{sequence_id}/approve")
def approve(sequence_id: int, body: NoteIn, ctx: AuthContext = Depends(get_ctx)):
    _client_only(ctx)
    seq = _sequence(ctx, sequence_id); row = _pending_approval(ctx.db, seq)
    row.status = "approved"; row.note = body.note.strip() or row.note
    row.decided_by = ctx.user.id; row.decided_at = datetime.utcnow()
    seq.status = "approved"; seq.updated_at = datetime.utcnow()
    _audit(ctx, seq, "approve_email_sequence", "email_sequence_approval", row.id,
           {"version": seq.version})
    ctx.db.commit()
    return _sequence_out(ctx.db, seq, full=True)


@router.post("/{sequence_id}/request-changes")
def request_changes(sequence_id: int, body: NoteIn, ctx: AuthContext = Depends(get_ctx)):
    _client_only(ctx)
    if not body.note.strip():
        raise HTTPException(422, "Tell the team what should change")
    seq = _sequence(ctx, sequence_id); row = _pending_approval(ctx.db, seq)
    row.status = "changes_requested"; row.note = body.note.strip()
    row.decided_by = ctx.user.id; row.decided_at = datetime.utcnow()
    seq.status = "changes_requested"; seq.updated_at = datetime.utcnow()
    _audit(ctx, seq, "request_email_sequence_changes", "email_sequence_approval", row.id)
    ctx.db.commit()
    return _sequence_out(ctx.db, seq, full=True)


# ---------------------------------------------------------------- real-prospect preview + shared format editing
def _value_for(token: str, lead: EnrichLead) -> str:
    direct = {"first_name": lead.first_name, "last_name": lead.last_name, "title": lead.title,
              "company": lead.company, "website": lead.website, "email": lead.email}
    if token in direct:
        return str(direct[token] or "")
    result = dict(lead.result or {})
    data = dict(lead.data or {})
    return str(result.get(token) or data.get(token) or "")


def _render(text: str, lead: EnrichLead, format_names: set[str]) -> tuple[str, list[dict], list[str]]:
    parts, missing, cursor = [], [], 0
    for match in TOKEN_RE.finditer(text or ""):
        if match.start() > cursor:
            parts.append({"kind": "literal", "text": text[cursor:match.start()]})
        token = re.sub(r"[ -]+", "_", match.group(1).strip().lower())
        value = _value_for(token, lead)
        if not value:
            missing.append(token)
            value = f"{{{{{token}}}}}"
        parts.append({"kind": "generated" if token in format_names else "prospect",
                      "text": value, "token": token, "missing": token in missing})
        cursor = match.end()
    if cursor < len(text or ""):
        parts.append({"kind": "literal", "text": text[cursor:]})
    return "".join(p["text"] for p in parts), parts, missing


@router.get("/{sequence_id}/preview")
def preview(sequence_id: int, list_id: int | None = Query(default=None),
            variant_id: int | None = Query(default=None), ctx: AuthContext = Depends(get_ctx)):
    seq = _sequence(ctx, sequence_id)
    target_list = list_id or seq.current_list_id
    if not target_list:
        raise HTTPException(422, "Choose the current prospect list first")
    lst = ctx.db.get(EnrichList, target_list)
    if not lst or lst.workspace_id != seq.workspace_id:
        raise HTTPException(404, "Prospect list not found")
    if variant_id:
        variant, step, owner = _variant(ctx, variant_id)
        if owner.id != seq.id:
            raise HTTPException(404, "Variant not found")
    else:
        step = (ctx.db.query(EmailSequenceStep)
                .filter(EmailSequenceStep.sequence_id == seq.id, EmailSequenceStep.archived_at.is_(None))
                .order_by(EmailSequenceStep.position).first())
        variant = (ctx.db.query(EmailSequenceVariant)
                   .filter(EmailSequenceVariant.step_id == step.id,
                           EmailSequenceVariant.archived_at.is_(None))
                   .order_by(EmailSequenceVariant.label).first()) if step else None
    if not variant:
        raise HTTPException(422, "This sequence has no variant to preview")
    leads = (ctx.db.query(EnrichLead)
             .filter(EnrichLead.workspace_id == seq.workspace_id, EnrichLead.list_id == lst.id)
             .order_by(EnrichLead.id).limit(10).all())
    names = {str(f.get("name")) for f in _formats(ctx.db, seq.workspace_id) if f.get("name")}
    rows = []
    for lead in leads:
        subject, subject_parts, sm = _render(variant.subject or "", lead, names)
        body, body_parts, bm = _render(variant.body or "", lead, names)
        rows.append({"lead_id": lead.id, "prospect": f"{lead.first_name} {lead.last_name}".strip() or lead.email,
                     "company": lead.company or "", "subject": subject, "body": body,
                     "subject_parts": subject_parts, "body_parts": body_parts,
                     "missing": sorted(set(sm + bm))})
    return {"list": {"id": lst.id, "name": lst.name}, "step": step.name,
            "variant": variant.label, "prospects": rows, "count": len(rows)}


@router.patch("/formats/{workspace_id}/{format_name}")
def patch_shared_format(workspace_id: int, format_name: str, body: FormatPatch,
                        ctx: AuthContext = Depends(get_ctx)):
    _team_only(ctx)
    ctx.require_workspace(workspace_id)
    cfg = ctx.db.query(EnrichConfig).filter(EnrichConfig.workspace_id == workspace_id).first()
    if not cfg:
        cfg = EnrichConfig(workspace_id=workspace_id, profile={}, formats=[])
        ctx.db.add(cfg); ctx.db.flush()
    formats = [dict(f) for f in _formats(ctx.db, workspace_id)]
    target = next((f for f in formats if str(f.get("name")) == format_name), None)
    if not target:
        raise HTTPException(404, "Shared format not found")
    data = body.model_dump(exclude_unset=True)
    for key, value in data.items():
        target[key] = value
    cfg.formats = formats
    ctx.db.add(AuditLog(org_id=ctx.org_id, workspace_id=workspace_id, user_id=ctx.user.id,
                        action="update_shared_email_format", object_type="enrich_config",
                        object_id=cfg.id, data={"format": format_name, "fields": list(data)}))
    ctx.db.commit()
    return {"ok": True, "format": target}


@router.post("/proof")
def add_proof(body: ProofIn, ctx: AuthContext = Depends(get_ctx)):
    """Add proof from inside the sequence editor, without leaving it.

    Writes a Library record, not a brain-profile entry: the record gets a
    mandatory `source`, a stable id an angle can point at, and a usage count.
    A client's addition is `client_supplied` — that is decided here, from the
    token, so the request body cannot promote its own evidence.

    Deliberately NOT `_team_only`, unlike every other write on this router:
    supplying your own case study is evidence FOR the copy, not an edit OF it,
    and the client's proof library links here.
    """
    ctx.require_workspace(body.workspace_id)
    if ctx.preview_as_client:
        raise HTTPException(403, "Exit the client preview to change the Library")
    try:
        row = library.add_case_study(
            ctx.db, body.workspace_id, client_name=body.name, outcome=body.outcome,
            source="client_supplied" if ctx.role == "client" else "operator",
            engagement=body.engagement, segment=body.segment, year=body.year,
            source_url=body.source_url, user_id=ctx.user.id)
    except library.LibraryError as exc:
        raise HTTPException(422, str(exc)) from exc
    ctx.db.add(AuditLog(org_id=ctx.org_id, workspace_id=body.workspace_id, user_id=ctx.user.id,
                        action="add_client_proof", object_type="library_case_study",
                        object_id=row.id, data={"name": row.client_name, "source": row.source}))
    ctx.db.commit()
    return {"ok": True, "proof": library.proof_for_key(ctx.db, body.workspace_id,
                                                       library.proof_key_for(row))}
