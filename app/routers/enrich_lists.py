"""List-based enrichment API (port of the enrichment dashboard endpoints).
Views + full-list counts are server-side so 50k+ lists stay browsable and the
chips are always accurate. 'Select all in view' semantics: actions accept a
view name and apply to the entire filtered set, not just a page."""
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func

from ..auth import AuthContext, get_ctx
from ..enrichment.brain import (
    CLIENT_BRAIN_KEYS,
    _BRAIN_LIST_KEYS,
    accumulate_brain as _accumulate_brain,
    merge_brain_list as _merge_brain_list,
)
from ..models.audit import AuditLog
from ..models.enrich import (
    TERMINAL_STATUSES,
    EnrichConfig,
    EnrichLead,
    EnrichList,
    WorkspaceTrainingRevision,
)
from ..models.identity import Workspace
from ..models.jobs import Job

router = APIRouter(prefix="/api/enrich-lists", tags=["enrichment-lists"])

VIEWS = ("all", "processed", "verified", "enriched", "insufficient", "needs_review",
         "generation_failed", "nonicp", "no_website", "invalid", "unsafe", "notrun", "title_rejected",
         "esp_microsoft", "esp_google", "esp_other", "esp_unknown")


def _view_filter(q, view: str):
    L = EnrichLead
    if view == "processed":
        return q.filter(L.status.in_(TERMINAL_STATUSES))
    if view == "verified":
        return q.filter(L.email_status.in_(["safe", "valid", "catch_all", "unknown"]))
    if view == "enriched":
        return q.filter(L.status == "done")
    if view == "insufficient":
        return q.filter(L.status == "insufficient")
    if view == "needs_review":
        return q.filter(L.status == "needs_review")
    if view == "generation_failed":
        return q.filter(L.status == "generation_failed")
    if view == "nonicp":
        return q.filter(L.icp_decision == "Non-ICP")
    if view == "no_website":
        return q.filter((L.website == "") | (L.website.is_(None)))
    if view == "invalid":
        return q.filter(L.status == "invalid")
    if view == "unsafe":
        return q.filter(L.status == "unsafe")
    if view == "notrun":
        return q.filter(L.status.notin_(TERMINAL_STATUSES))
    if view == "title_rejected":
        return q.filter(L.title_status == "rejected")
    # ESP (mailbox provider, MX-based) — segment for provider-aware sending.
    if view == "esp_microsoft":
        return q.filter(L.esp == "Microsoft")
    if view == "esp_google":
        return q.filter(L.esp == "Google")
    if view == "esp_other":
        return q.filter(L.esp == "Other")
    if view == "esp_unknown":
        return q.filter((L.esp == "") | (L.esp.is_(None)) | (L.esp == "Unknown"))
    return q


def _esp_filter(q, esp):
    """Multi-select provider facet: keep leads whose ESP is ANY of the chosen
    providers (Microsoft/Google/Other/Unknown). ANDs with the funnel view.
    Accepts a list or a comma-separated string; empty = no ESP filter."""
    from sqlalchemy import or_
    if isinstance(esp, str):
        esp = [e.strip() for e in esp.split(",") if e.strip()]
    if not esp:
        return q
    L = EnrichLead
    conds = []
    for e in esp:
        if e == "Microsoft":
            conds.append(L.esp == "Microsoft")
        elif e == "Google":
            conds.append(L.esp == "Google")
        elif e == "Other":
            conds.append(L.esp == "Other")
        elif e == "Unknown":
            conds.append((L.esp == "") | (L.esp.is_(None)) | (L.esp == "Unknown"))
    return q.filter(or_(*conds)) if conds else q


def _get_list(ctx, list_id) -> EnrichList:
    lst = ctx.db.get(EnrichList, list_id)
    if lst is None:
        raise HTTPException(404, "List not found")
    ctx.require_workspace(lst.workspace_id)
    return lst


# ---------------------------------------------------------------- lists
class ListIn(BaseModel):
    workspace_id: int
    name: str


@router.get("")
def lists(workspace_id: int | None = None, ctx: AuthContext = Depends(get_ctx)):
    ws_ids = ctx.workspace_ids_for_query(workspace_id)
    rows = (ctx.db.query(EnrichList, func.count(EnrichLead.id))
            .outerjoin(EnrichLead, EnrichLead.list_id == EnrichList.id)
            .filter(EnrichList.workspace_id.in_(ws_ids))
            .group_by(EnrichList.id).order_by(EnrichList.id.desc()).all())
    return [{"id": l.id, "workspace_id": l.workspace_id, "name": l.name, "leads": n,
             "created_at": l.created_at.isoformat()} for l, n in rows]


@router.post("")
def create_list(body: ListIn, ctx: AuthContext = Depends(get_ctx)):
    ctx.require_workspace(body.workspace_id)
    lst = EnrichList(workspace_id=body.workspace_id, name=body.name.strip() or "Untitled list")
    ctx.db.add(lst)
    ctx.db.commit()
    return {"id": lst.id}


@router.delete("/{list_id}")
def delete_list(list_id: int, ctx: AuthContext = Depends(get_ctx)):
    lst = _get_list(ctx, list_id)
    ctx.db.query(EnrichLead).filter(EnrichLead.list_id == lst.id).delete()
    ctx.db.delete(lst)
    ctx.db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- import
class ImportRowsIn(BaseModel):
    rows: list[dict]   # mapped client-side: first_name,last_name,title,company,website,email


@router.post("/{list_id}/import")
def import_rows(list_id: int, body: ImportRowsIn, ctx: AuthContext = Depends(get_ctx)):
    lst = _get_list(ctx, list_id)
    if len(body.rows) > 100_000:
        raise HTTPException(422, "Too many rows")
    n = 0
    for r in body.rows:
        email = str(r.get("email", "")).lower().strip()
        ctx.db.add(EnrichLead(
            workspace_id=lst.workspace_id, list_id=lst.id,
            first_name=str(r.get("first_name", "")).strip(), last_name=str(r.get("last_name", "")).strip(),
            title=str(r.get("title", "")).strip(), company=str(r.get("company", "")).strip(),
            website=str(r.get("website", "")).strip(), email=email, data=r))
        n += 1
    ctx.db.commit()
    return {"imported": n}


# ---------------------------------------------------------------- grid: leads + chips
@router.get("/{list_id}/leads")
def list_leads(list_id: int, view: str = "all", page: int = 1, page_size: int = 50,
               q: str = "", esp: str = "", ctx: AuthContext = Depends(get_ctx)):
    lst = _get_list(ctx, list_id)
    base = ctx.db.query(EnrichLead).filter(EnrichLead.list_id == lst.id)
    if q:
        like = f"%{q}%"
        base = base.filter((EnrichLead.email.ilike(like)) | (EnrichLead.company.ilike(like))
                           | (EnrichLead.first_name.ilike(like)) | (EnrichLead.last_name.ilike(like)))
    filtered = _esp_filter(_view_filter(base, view), esp)
    total = filtered.count()
    page_size = min(max(page_size, 10), 200)
    rows = (filtered.order_by(EnrichLead.id)
            .offset((max(page, 1) - 1) * page_size).limit(page_size).all())
    # live full-list chips (never just the visible page)
    chips = {v: _view_filter(base, v).count() for v in VIEWS}
    return {
        "list": {"id": lst.id, "name": lst.name, "workspace_id": lst.workspace_id},
        "total_in_view": total, "page": page, "page_size": page_size, "chips": chips,
        "leads": [{
            "id": l.id, "name": f"{l.first_name} {l.last_name}".strip(), "title": l.title,
            "company": l.company, "website": l.website, "email": l.email,
            "free_status": l.free_status, "email_status": l.email_status,
            "verify_source": l.verify_source, "title_status": l.title_status,
            "icp_decision": l.icp_decision, "icp_score": l.icp_score, "icp_reason": l.icp_reason,
            "industry": l.industry, "esp": l.esp, "status": l.status, "competitors": l.competitors or [],
            "vars": {k: v for k, v in (l.result or {}).items() if not k.startswith("_")},
            "research": (l.result or {}).get("_research"),
            "research_error": (l.result or {}).get("_error"),
            "generation_error": (l.result or {}).get("_generation_error"),
            "generation": (l.result or {}).get("_generation") or {},
            "insufficient": bool((l.result or {}).get("_insufficient")),
            "evidence": ((l.result or {}).get("_facts") or {}).get("evidence") or [],
            "assignments": (l.result or {}).get("_assignments") or {},
            "quality_failures": (l.result or {}).get("_quality_failures") or {},
            "imported": {k: v for k, v in (l.data or {}).items()
                         if not k.startswith("_") and k.lower() not in STD_ALIASES},
        } for l in rows],
    }


# ---------------------------------------------------------------- run / stop
class RunIn(BaseModel):
    steps: str = "pipeline"       # 'verify' or 'pipeline' (Verify → Enrich)
    lead_ids: list[int] = []      # empty = whole view
    view: str = "notrun"          # used when lead_ids empty ('select all N in view')
    esp: list[str] = []           # optional provider facet (ANDs with view)
    limit: int = 0                # test-first-N safety cap (0 = no cap)
    enrichments: list[str] = []   # output variables to write (empty = all configured)
    workers: int = 1              # concurrent leads to process at once (1–25)


@router.get("/{list_id}/active-job")
def active_job(list_id: int, ctx: AuthContext = Depends(get_ctx)):
    """The list's currently pending/running job, if any — so the grid reconnects
    to a run in progress after a page reload (Stop button + live progress
    persist instead of vanishing)."""
    lst = _get_list(ctx, list_id)
    from ..models.jobs import Job
    jobs = (ctx.db.query(Job)
            .filter(Job.kind.in_(["run_enrich_list", "find_competitors"]),
                    Job.status.in_(["pending", "running"]),
                    Job.workspace_id == lst.workspace_id)
            .order_by(Job.id.desc()).all())
    for j in jobs:
        if int((j.payload or {}).get("list_id", 0)) == lst.id:
            return {"job_id": j.id, "kind": j.kind, "status": j.status,
                    "progress": j.progress, "progress_note": j.progress_note}
    return {"job_id": None}


class DeleteLeadsIn(BaseModel):
    lead_ids: list[int] = []
    view: str = "all"
    esp: list[str] = []


@router.post("/{list_id}/delete-leads")
def delete_leads(list_id: int, body: DeleteLeadsIn, ctx: AuthContext = Depends(get_ctx)):
    """Delete selected leads (or a whole view). Legacy DELETE /lists/{id}/leads."""
    lst = _get_list(ctx, list_id)
    base = ctx.db.query(EnrichLead).filter(EnrichLead.list_id == lst.id)
    q = base.filter(EnrichLead.id.in_([int(i) for i in body.lead_ids])) if body.lead_ids \
        else _esp_filter(_view_filter(base, body.view), body.esp)
    n = q.count()
    q.delete(synchronize_session=False)
    ctx.db.commit()
    return {"deleted": n}


class DedupeIn(BaseModel):
    other_list_id: int
    target: str = "this"    # 'this' = delete dupes from the current list; 'other' = from the other list
    dry_run: bool = True     # preview count only


@router.post("/{list_id}/dedupe")
def dedupe(list_id: int, body: DedupeIn, ctx: AuthContext = Depends(get_ctx)):
    """Cross-list dedupe by EMAIL. A lead is a duplicate when its email also
    appears in the other list. Deletes the duplicates from the chosen target
    (default: this list — keep the other list as the reference/master). Emails
    are recovered from the raw uploaded row when the standard field is empty."""
    from ..enrichment.pipeline import email_from_row
    lst = _get_list(ctx, list_id)
    other = _get_list(ctx, body.other_list_id)
    if other.id == lst.id:
        raise HTTPException(422, "Pick a different list to compare against")
    keep, target = (other, lst) if body.target == "this" else (lst, other)

    def emails_of(l):
        m = {}
        for lid, email, data in (ctx.db.query(EnrichLead.id, EnrichLead.email, EnrichLead.data)
                                 .filter(EnrichLead.list_id == l.id).all()):
            e = (email or "").strip().lower() or email_from_row(data or {})
            if e:
                m.setdefault(e, []).append(lid)
        return m

    keep_emails = set(emails_of(keep).keys())
    target_map = emails_of(target)
    dup_ids = [lid for e, ids in target_map.items() if e in keep_emails for lid in ids]
    result = {"target_list": target.name, "keep_list": keep.name,
              "matches": len(dup_ids),
              "target_total": sum(len(v) for v in target_map.values())}
    if body.dry_run:
        return result
    if dup_ids:
        (ctx.db.query(EnrichLead).filter(EnrichLead.id.in_(dup_ids))
         .delete(synchronize_session=False))
        ctx.db.commit()
    result["deleted"] = len(dup_ids)
    return result


@router.get("/reoon/balance")
def reoon_balance(workspace_id: int | None = None, ctx: AuthContext = Depends(get_ctx)):
    """Reoon credit balance chip. Uses the workspace's saved key, else env.
    demo=True means NO key at all → emails are not being verified."""
    import os
    import requests
    key = os.getenv("REOON_API_KEY", "")
    if workspace_id:
        from ..crypto import decrypt
        from ..enrichment.pipeline import _config
        cfg = _config(ctx.db, workspace_id)
        if cfg.reoon_api_key_enc:
            key = decrypt(cfg.reoon_api_key_enc) or key
    if not key:
        return {"demo": True, "credits": None}
    try:
        r = requests.get("https://emailverifier.reoon.com/api/v1/account-info",
                         params={"key": key}, timeout=15)
        j = r.json() if r.status_code == 200 else {}
        return {"demo": False, "credits": j.get("credits_remaining") or j.get("credits"),
                "raw": j}
    except Exception as e:
        return {"demo": False, "error": str(e)[:200]}


@router.post("/{list_id}/run")
def run(list_id: int, body: RunIn, ctx: AuthContext = Depends(get_ctx)):
    lst = _get_list(ctx, list_id)
    lead_ids = body.lead_ids
    if not lead_ids:
        base = ctx.db.query(EnrichLead.id).filter(EnrichLead.list_id == lst.id)
        lead_ids = [r[0] for r in _esp_filter(_view_filter(base, body.view), body.esp).all()]
    if not lead_ids:
        raise HTTPException(422, "Nothing to run in this selection")
    workers = max(1, min(int(body.workers or 1), 25))
    j = Job(kind="run_enrich_list", workspace_id=lst.workspace_id,
            payload={"list_id": lst.id, "lead_ids": lead_ids, "steps": body.steps,
                     "limit": body.limit, "enrichments": body.enrichments, "workers": workers})
    ctx.db.add(j)
    ctx.db.commit()
    return {"job_id": j.id, "selected": len(lead_ids), "capped_at": body.limit or None, "workers": workers}


# ---------------------------------------------------------------- grammar fix
class GrammarFixIn(BaseModel):
    lead_ids: list[int] = []
    view: str = "enriched"   # used when lead_ids empty (select-all-in-view)
    esp: list[str] = []
    variable: str | None = None   # None = fix every variable; else just this one


@router.post("/{list_id}/fix-grammar")
def fix_grammar_ep(list_id: int, body: GrammarFixIn, ctx: AuthContext = Depends(get_ctx)):
    """Bulk grammar/punctuation cleanup over generated variables — all of them, or a
    single variable. Runs as a background job; preserves every fact (no re-crawl)."""
    lst = _get_list(ctx, list_id)
    lead_ids = body.lead_ids
    if not lead_ids:
        base = ctx.db.query(EnrichLead.id).filter(EnrichLead.list_id == lst.id)
        lead_ids = [r[0] for r in _esp_filter(_view_filter(base, body.view), body.esp).all()]
    if not lead_ids:
        raise HTTPException(422, "No enriched leads in this selection to correct.")
    j = Job(kind="fix_grammar_list", workspace_id=lst.workspace_id,
            payload={"list_id": lst.id, "lead_ids": lead_ids, "variable": body.variable})
    ctx.db.add(j)
    ctx.db.commit()
    return {"job_id": j.id, "selected": len(lead_ids), "variable": body.variable or "all"}


# ---------------------------------------------------------------- competitor finder
class CompetitorsIn(BaseModel):
    lead_ids: list[int] = []
    view: str = "enriched"   # used when lead_ids empty (select-all-in-view semantics)
    esp: list[str] = []


@router.post("/{list_id}/find-competitors")
def find_competitors_ep(list_id: int, body: CompetitorsIn, ctx: AuthContext = Depends(get_ctx)):
    """Model-knowledge competitor finder (no web search — cheap by design).
    Runs as a background job; skips leads that already have competitors."""
    lst = _get_list(ctx, list_id)
    lead_ids = body.lead_ids
    if not lead_ids:
        base = ctx.db.query(EnrichLead.id).filter(EnrichLead.list_id == lst.id)
        lead_ids = [r[0] for r in _esp_filter(_view_filter(base, body.view), body.esp).all()]
    if not lead_ids:
        raise HTTPException(422, "Nothing selected")
    j = Job(kind="find_competitors", workspace_id=lst.workspace_id,
            payload={"list_id": lst.id, "lead_ids": lead_ids})
    ctx.db.add(j)
    ctx.db.commit()
    return {"job_id": j.id, "selected": len(lead_ids)}


# ---------------------------------------------------------------- DNS / email diagnostics
@router.get("/diag/dns")
def diag_dns(ctx: AuthContext = Depends(get_ctx)):
    """Proves whether the free MX layer is live on this host. dns_working is
    True ONLY if a real domain resolves True AND a nonsense domain resolves
    False — otherwise the layer is failing open and rejecting nothing."""
    from ..enrichment.verify_free import _doh_mx, mx_diagnostics
    good = {d: _doh_mx(d) for d in ("gmail.com", "outlook.com")}
    dead = {d: _doh_mx(d) for d in ("no-such-domain-zzqx-1928374.com",)}
    working = any(v is True for v in good.values()) and all(v is False for v in dead.values())
    return {"dns_working": working,
            "results": {**good, **dead},
            # per-tier probe: shows EXACTLY which resolution path works on this host
            "probe": mx_diagnostics("gmail.com"),
            "verdict": ("MX layer live — dead domains are being rejected" if working
                        else "MX layer NOT conclusive — free verifier is failing open; "
                             "only Reoon is filtering")}


@router.get("/diag/email")
def diag_email(e: str, ctx: AuthContext = Depends(get_ctx)):
    from ..enrichment.verify_free import check
    return {"email": e, **check(e)}


@router.get("/{list_id}/diag-esp")
def diag_esp(list_id: int, ctx: AuthContext = Depends(get_ctx)):
    """Per-list ESP reality check: how many leads actually have an email, and for
    a few real leads — does their domain resolve and classify? Pinpoints whether
    'all Unknown' is a no-email problem vs a resolution/persistence problem."""
    from ..enrichment.pipeline import email_from_row
    from ..enrichment.verify_free import _doh_mx, esp_for
    lst = _get_list(ctx, list_id)
    q = ctx.db.query(EnrichLead).filter(EnrichLead.list_id == lst.id)
    total = q.count()
    std_email = q.filter(EnrichLead.email != "", EnrichLead.email.isnot(None)).count()
    samples = []
    recoverable = 0
    for l in q.order_by(EnrichLead.id).limit(8).all():
        eml = (l.email or "").strip() or email_from_row(l.data or {})
        if eml:
            recoverable += 1
        dom = eml.split("@", 1)[1].lower() if "@" in eml else ""
        res = _doh_mx(dom) if dom else None
        samples.append({"email": eml or "(none)", "std_field": bool(l.email),
                        "domain": dom, "resolved": res,
                        "esp_live": (esp_for(dom) or "Unknown") if dom else "no email",
                        "esp_stored": l.esp or ""})
    return {"list": lst.name, "total": total, "email_in_standard_field": std_email,
            "note": ("emails are in the uploaded row but NOT the standard field — "
                     "the run now self-heals this" if std_email == 0 else "ok"),
            "sample_recoverable": f"{recoverable}/8", "samples": samples}


# ---------------------------------------------------------------- clear actions (mirror pair)
@router.post("/{list_id}/clear-results")
def clear_results(list_id: int, view: str = "all", esp: str = "", ctx: AuthContext = Depends(get_ctx)):
    """Wipes enrichment, keeps verification."""
    lst = _get_list(ctx, list_id)
    base = ctx.db.query(EnrichLead).filter(EnrichLead.list_id == lst.id)
    n = 0
    for l in _esp_filter(_view_filter(base, view), esp).all():
        l.result = {}
        l.icp_decision = ""
        l.icp_score = None
        l.icp_reason = ""
        l.title_status = ""
        # Keep verification-only terminal states (invalid/unsafe), but reopen
        # every status produced by research, ICP or generation.
        if l.status in ("done", "skipped", "error", "insufficient",
                        "generation_failed", "needs_review"):
            l.status = ""
        n += 1
    ctx.db.commit()
    return {"cleared": n}


@router.post("/{list_id}/clear-verification")
def clear_verification(list_id: int, view: str = "all", esp: str = "", ctx: AuthContext = Depends(get_ctx)):
    """Wipes free + Reoon verification (so leads re-verify), keeps enrichment.
    Resets the funnel status for EVERY already-processed lead (done/skipped/
    invalid/unsafe/error) back to unprocessed — otherwise the resume guard
    (`status in TERMINAL_STATUSES → return`) would skip them and re-verification
    silently does nothing. Verification is the FIRST gate, so clearing it must
    re-open the whole funnel."""
    lst = _get_list(ctx, list_id)
    base = ctx.db.query(EnrichLead).filter(EnrichLead.list_id == lst.id)
    n = 0
    for l in _esp_filter(_view_filter(base, view), esp).all():
        l.free_status = ""
        l.email_status = ""
        l.verify_source = ""
        if l.status in TERMINAL_STATUSES:   # done/skipped/invalid/unsafe/error → re-flow
            l.status = ""
        n += 1
    ctx.db.commit()
    return {"cleared": n}


# ---------------------------------------------------------------- database (all leads in workspace)
@router.get("/database/{workspace_id}")
def database_view(workspace_id: int, view: str = "all", q: str = "", page: int = 1,
                  ctx: AuthContext = Depends(get_ctx)):
    """The legacy Database section: every lead across all lists in a workspace,
    filterable, with the list name attached — filter here, then act per list."""
    ctx.require_workspace(workspace_id)
    base = ctx.db.query(EnrichLead).filter(EnrichLead.workspace_id == workspace_id)
    if q:
        like = f"%{q}%"
        base = base.filter((EnrichLead.email.ilike(like)) | (EnrichLead.company.ilike(like)))
    filtered = _view_filter(base, view)
    total = filtered.count()
    rows = filtered.order_by(EnrichLead.id.desc()).offset((max(page, 1) - 1) * 50).limit(50).all()
    lists = {l.id: l.name for l in ctx.db.query(EnrichList)
             .filter(EnrichList.workspace_id == workspace_id).all()}
    chips = {v: _view_filter(base, v).count() for v in VIEWS}
    return {"total_in_view": total, "chips": chips, "page": page,
            "leads": [{"id": l.id, "list_id": l.list_id, "list_name": lists.get(l.list_id, ""),
                       "name": f"{l.first_name} {l.last_name}".strip(), "company": l.company,
                       "email": l.email, "status": l.status, "icp_decision": l.icp_decision,
                       "esp": l.esp, "industry": l.industry} for l in rows]}


# ---------------------------------------------------------------- split by industry (legacy tool)
@router.post("/{list_id}/split-by-industry")
def split_by_industry(list_id: int, ctx: AuthContext = Depends(get_ctx)):
    """Creates '<List> — <Industry>' lists and MOVES classified leads into them."""
    lst = _get_list(ctx, list_id)
    rows = (ctx.db.query(EnrichLead)
            .filter(EnrichLead.list_id == lst.id, EnrichLead.industry != "").all())
    if not rows:
        raise HTTPException(422, "No leads with an industry classification yet — run enrichment first")
    targets: dict = {}
    for l in rows:
        ind = l.industry.strip()
        if ind not in targets:
            name = f"{lst.name} — {ind}"
            t = ctx.db.query(EnrichList).filter(EnrichList.workspace_id == lst.workspace_id,
                                                EnrichList.name == name).first()
            if t is None:
                t = EnrichList(workspace_id=lst.workspace_id, name=name)
                ctx.db.add(t)
                ctx.db.flush()
            targets[ind] = t
        l.list_id = targets[ind].id
    ctx.db.commit()
    return {"moved": len(rows), "lists_created": sorted(targets.keys())}


# ---------------------------------------------------------------- export
# Original-CSV headers that map to our standard model columns — excluded from
# the "extra uploaded columns" so we don't duplicate first_name/company/etc.
STD_ALIASES = {
    "first_name", "firstname", "first name", "first", "last_name", "lastname", "last name", "last",
    "email", "email address", "e-mail", "title", "job title", "position", "role",
    "company", "company_name", "company name", "organization", "website", "company website",
    "domain", "url", "company_website", "html_override",
}


@router.get("/{list_id}/export")
def export(list_id: int, view: str = "enriched", esp: str = "", ctx: AuthContext = Depends(get_ctx)):
    """Export = every ORIGINAL uploaded column (preserved on import) + our
    enrichment outputs. Nothing the client uploaded is dropped."""
    import csv
    import io

    from fastapi.responses import PlainTextResponse

    from ..enrichment.pipeline import sanitize_text as _s

    lst = _get_list(ctx, list_id)
    base = ctx.db.query(EnrichLead).filter(EnrichLead.list_id == lst.id)
    rows = _esp_filter(_view_filter(base, view), esp).order_by(EnrichLead.id).all()

    # original uploaded columns (first-seen order), minus standard + internal keys
    orig_cols = []
    for l in rows:
        for k in (l.data or {}):
            if k.startswith("_") or k.lower() in STD_ALIASES:
                continue
            if k not in orig_cols:
                orig_cols.append(k)
    # enrichment result variables (our generated copy)
    var_names = []
    for l in rows:
        for k in (l.result or {}):
            if not k.startswith("_") and k not in var_names:
                var_names.append(k)
    # if a result var name collides with an uploaded column, suffix it
    def vh(v):
        return f"{v} (enriched)" if v in orig_cols else v

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["first_name", "last_name", "title", "company", "website", "email"]
               + orig_cols + [vh(v) for v in var_names]
               + ["system_check", "reoon", "esp", "icp", "icp_score", "industry", "enrich_status", "Top Competitors"])
    for l in rows:
        d = l.data or {}
        res = l.result or {}
        comps = "; ".join(f"{c.get('name')} ({c.get('why')})" for c in (l.competitors or []) if c.get("name"))
        # sanitize every cell — strips invisible/control chars so Instantly, Excel,
        # and CRMs accept the file ("characters that cannot be stored" error).
        w.writerow([_s(x) for x in
                    ([l.first_name, l.last_name, l.title, l.company, l.website, l.email]
                     + [d.get(c, "") for c in orig_cols]
                     + [res.get(v, "") for v in var_names]
                     + [l.free_status, l.email_status, l.esp, l.icp_decision, l.icp_score or "",
                        l.industry, l.status, comps])])
    return PlainTextResponse(buf.getvalue(), media_type="text/csv",
                             headers={"Content-Disposition":
                                      f"attachment; filename={lst.name.replace(' ', '_')}-{view}.csv"})


# ---------------------------------------------------------------- workspace config
class ConfigIn(BaseModel):
    profile: dict | None = None
    icp_definition: str | None = None
    formats: list | None = None
    variables: list | None = None   # alias: old variable-set JSON calls the array "variables"
    rules: str | None = None
    skip_title_gate: bool | None = None
    skip_icp: bool | None = None
    only_safe: bool | None = None
    reoon_api_key: str | None = None
    reading_level: str | None = None
    writer_model: str | None = None
    research_depth: str | None = None
    require_research_gate: bool | None = None


class FormatExampleIn(BaseModel):
    text: str


class FormatFeedbackIn(BaseModel):
    text: str
    verdict: str
    reason: str = ""


class TrainingPackageIn(BaseModel):
    package: dict
    expected_revision: str = ""
    note: str = ""


class TrainingEvaluationRunIn(BaseModel):
    confirm_spend: bool = False
    case_names: list[str] = Field(default_factory=list)


def _training_admin(workspace_id: int, ctx: AuthContext):
    ctx.require_workspace(workspace_id)
    if not ctx.is_master:
        raise HTTPException(403, "Workspace training imports and rollback require owner/admin access.")
    workspace = ctx.db.get(Workspace, workspace_id)
    if workspace is None or workspace.org_id != ctx.org_id:
        raise HTTPException(404, "Workspace not found.")
    return workspace


def _save_training_revision(ctx: AuthContext, workspace_id: int, snapshot: dict,
                            *, action: str, note: str) -> WorkspaceTrainingRevision:
    """Save the pre-change state and bound retained history to 25 snapshots."""
    from ..enrichment.training import revision_hash

    latest = (
        ctx.db.query(func.max(WorkspaceTrainingRevision.version))
        .filter(WorkspaceTrainingRevision.workspace_id == workspace_id)
        .scalar()
    ) or 0
    row = WorkspaceTrainingRevision(
        workspace_id=workspace_id,
        version=latest + 1,
        action=action[:30],
        note=(note or "")[:500],
        revision_hash=revision_hash(snapshot),
        snapshot=snapshot,
        created_by=ctx.user.id,
    )
    ctx.db.add(row)
    ctx.db.flush()
    old = (
        ctx.db.query(WorkspaceTrainingRevision)
        .filter(WorkspaceTrainingRevision.workspace_id == workspace_id)
        .order_by(WorkspaceTrainingRevision.version.desc())
        .offset(25)
        .all()
    )
    for item in old:
        ctx.db.delete(item)
    return row


@router.post("/config/{workspace_id}/formats/{format_name}/examples")
def add_format_example(workspace_id: int, format_name: str, body: FormatExampleIn,
                       ctx: AuthContext = Depends(get_ctx)):
    """Approve generated copy as a future style/structure example for one variable."""
    ctx.require_workspace(workspace_id)
    from ..enrichment.pipeline import _config

    text = " ".join((body.text or "").split()).strip()
    if len(text) < 8:
        raise HTTPException(422, "The approved example is empty or too short.")
    if len(text) > 4000:
        raise HTTPException(422, "The approved example is too long.")
    cfg = _config(ctx.db, workspace_id)
    formats = [dict(f) for f in (cfg.formats or []) if isinstance(f, dict)]
    found = False
    for fmt in formats:
        if str(fmt.get("name") or "") != format_name:
            continue
        found = True
        examples = [str(x).strip() for x in (fmt.get("examples") or []) if str(x).strip()]
        normalized = {" ".join(x.casefold().split()) for x in examples}
        if " ".join(text.casefold().split()) not in normalized:
            examples.append(text)
        fmt["examples"] = examples[-20:]  # durable memory; writer retrieves only the latest two
        break
    if not found:
        raise HTTPException(404, "That format variable no longer exists.")
    cfg.formats = formats
    ctx.db.commit()
    return {"ok": True, "format": format_name,
            "example_count": len(next(f["examples"] for f in formats if f.get("name") == format_name))}


@router.post("/config/{workspace_id}/formats/{format_name}/feedback")
def add_format_feedback(workspace_id: int, format_name: str, body: FormatFeedbackIn,
                        ctx: AuthContext = Depends(get_ctx)):
    """Remember both good outputs and rejected anti-examples with a reason."""
    ctx.require_workspace(workspace_id)
    from ..enrichment.pipeline import _config

    text = " ".join((body.text or "").split()).strip()
    verdict = (body.verdict or "").strip().lower()
    reason = " ".join((body.reason or "").split()).strip()
    if verdict not in ("approved", "rejected"):
        raise HTTPException(422, "verdict must be approved or rejected.")
    if len(text) < 8 or len(text) > 4000:
        raise HTTPException(422, "Feedback text must be between 8 and 4,000 characters.")
    if len(reason) > 1000:
        raise HTTPException(422, "Feedback reason is too long.")
    if verdict == "rejected" and len(reason) < 3:
        raise HTTPException(422, "Explain briefly why this output should not be repeated.")

    cfg = _config(ctx.db, workspace_id)
    formats = [dict(f) for f in (cfg.formats or []) if isinstance(f, dict)]
    target = next((f for f in formats if str(f.get("name") or "") == format_name), None)
    if target is None:
        raise HTTPException(404, "That format variable no longer exists.")
    normalized = " ".join(text.casefold().split())
    if verdict == "approved":
        examples = [str(x).strip() for x in (target.get("examples") or []) if str(x).strip()]
        if normalized not in {" ".join(x.casefold().split()) for x in examples}:
            examples.append(text)
        target["examples"] = examples[-20:]
        count = len(target["examples"])
    else:
        rejected = [
            dict(x) for x in (target.get("rejected_examples") or [])
            if isinstance(x, dict) and str(x.get("text") or "").strip()
        ]
        rejected = [
            x for x in rejected
            if " ".join(str(x.get("text") or "").casefold().split()) != normalized
        ]
        from datetime import datetime
        rejected.append({
            "text": text,
            "reason": reason,
            "created_at": datetime.utcnow().isoformat(),
        })
        target["rejected_examples"] = rejected[-50:]
        count = len(target["rejected_examples"])
    cfg.formats = formats
    ctx.db.add(AuditLog(
        org_id=ctx.org_id, workspace_id=workspace_id, user_id=ctx.user.id,
        action=f"training.feedback.{verdict}", object_type="enrichment_format",
        data={"format": format_name, "reason": reason[:240]},
    ))
    ctx.db.commit()
    return {"ok": True, "format": format_name, "verdict": verdict, "count": count}


@router.get("/config/{workspace_id}/training/export")
def export_training_package(workspace_id: int, ctx: AuthContext = Depends(get_ctx)):
    """Export only sanitized writing/training configuration—never operational data."""
    workspace = _training_admin(workspace_id, ctx)
    from ..enrichment.pipeline import _config
    from ..enrichment.training import export_bundle

    cfg = _config(ctx.db, workspace_id)
    ctx.db.commit()
    return export_bundle(ctx.db, cfg, workspace.name)


@router.post("/config/{workspace_id}/training/preview")
def preview_training_package(workspace_id: int, body: TrainingPackageIn,
                             ctx: AuthContext = Depends(get_ctx)):
    workspace = _training_admin(workspace_id, ctx)
    from ..enrichment.pipeline import _config
    from ..enrichment.training import (
        normalize_bundle,
        revision_hash,
        state_diff,
        workspace_state,
    )

    cfg = _config(ctx.db, workspace_id)
    ctx.db.commit()
    current = workspace_state(ctx.db, cfg)
    proposed = normalize_bundle(body.package, current)
    return {
        "workspace": {"id": workspace.id, "name": workspace.name},
        "current_revision": revision_hash(current),
        "proposed_revision": revision_hash(proposed),
        "changes": state_diff(current, proposed),
        "normalized_package": {
            "schema": "revcadence.workspace-training",
            "schema_version": 1,
            **proposed,
        },
    }


@router.post("/config/{workspace_id}/training/apply")
def apply_training_package(workspace_id: int, body: TrainingPackageIn,
                           ctx: AuthContext = Depends(get_ctx)):
    workspace = _training_admin(workspace_id, ctx)
    from ..enrichment.pipeline import _config
    from ..enrichment.training import (
        apply_config_state,
        normalize_bundle,
        replace_evaluations,
        revision_hash,
        state_diff,
        workspace_state,
    )

    cfg = _config(ctx.db, workspace_id)
    ctx.db.commit()
    current = workspace_state(ctx.db, cfg)
    current_hash = revision_hash(current)
    if not body.expected_revision:
        raise HTTPException(409, "Preview the package first and send its current_revision.")
    if body.expected_revision != current_hash:
        raise HTTPException(409, "Workspace training changed after preview. Preview again before applying.")
    proposed = normalize_bundle(body.package, current)
    changes = state_diff(current, proposed)
    if not changes:
        return {"ok": True, "changed": False, "revision": current_hash, "changes": []}

    saved = _save_training_revision(
        ctx, workspace_id, current, action="before_apply", note=body.note or "Training package apply",
    )
    apply_config_state(cfg, proposed)
    replace_evaluations(ctx.db, workspace_id, proposed["evaluation_cases"])
    ctx.db.add(AuditLog(
        org_id=ctx.org_id, workspace_id=workspace_id, user_id=ctx.user.id,
        action="training.package.apply", object_type="workspace",
        object_id=workspace_id,
        data={
            "previous_revision": current_hash,
            "new_revision": revision_hash(proposed),
            "rollback_revision_id": saved.id,
            "sections": [item["section"] for item in changes],
        },
    ))
    ctx.db.commit()
    return {
        "ok": True,
        "changed": True,
        "revision": revision_hash(proposed),
        "rollback_revision_id": saved.id,
        "changes": changes,
    }


@router.get("/config/{workspace_id}/training/revisions")
def training_revisions(workspace_id: int, ctx: AuthContext = Depends(get_ctx)):
    _training_admin(workspace_id, ctx)
    rows = (
        ctx.db.query(WorkspaceTrainingRevision)
        .filter(WorkspaceTrainingRevision.workspace_id == workspace_id)
        .order_by(WorkspaceTrainingRevision.version.desc())
        .limit(25)
        .all()
    )
    return [{
        "id": row.id,
        "version": row.version,
        "action": row.action,
        "note": row.note or "",
        "revision": row.revision_hash,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "created_by": row.created_by,
    } for row in rows]


@router.post("/config/{workspace_id}/training/evaluate")
def run_training_evaluation(workspace_id: int, body: TrainingEvaluationRunIn,
                            ctx: AuthContext = Depends(get_ctx)):
    """Run up to five active golden cases through the live writer.

    This is deliberately explicit because it spends OpenAI tokens. It never
    changes leads or the workspace training configuration.
    """
    _training_admin(workspace_id, ctx)
    if not body.confirm_spend:
        raise HTTPException(422, "Set confirm_spend=true after confirming the live AI cost.")
    from ..enrichment.pipeline import _config, _write_copy
    from ..enrichment.training import score_evaluation_case
    from ..models.enrich import WorkspaceEvaluationCase

    query = (
        ctx.db.query(WorkspaceEvaluationCase)
        .filter(
            WorkspaceEvaluationCase.workspace_id == workspace_id,
            WorkspaceEvaluationCase.active == True,  # noqa: E712
        )
        .order_by(WorkspaceEvaluationCase.id)
    )
    names = [str(x).strip() for x in body.case_names if str(x).strip()]
    if len(names) > 5:
        raise HTTPException(422, "Run at most five evaluation cases at a time.")
    if names:
        query = query.filter(WorkspaceEvaluationCase.name.in_(names))
    cases = query.limit(5).all()
    if not cases:
        raise HTTPException(422, "No active golden evaluation cases were selected.")

    cfg = _config(ctx.db, workspace_id)
    ctx.db.commit()
    results = []
    for case in cases:
        transient = EnrichLead(
            workspace_id=workspace_id,
            list_id=0,
            company=case.company or case.name,
            website=case.website or "",
        )
        generated = _write_copy(transient, cfg, {"facts": case.facts or {}})
        scored = score_evaluation_case(
            case.expected_outputs or {},
            generated.get("vars") or {},
            generated.get("quality_failures") or {},
        )
        results.append({
            "id": case.id,
            "name": case.name,
            "company": case.company or "",
            **scored,
            "generation": generated.get("generation") or {},
            "writer_error": generated.get("error") or "",
        })
    passed = sum(1 for item in results if item["passed"])
    ctx.db.add(AuditLog(
        org_id=ctx.org_id, workspace_id=workspace_id, user_id=ctx.user.id,
        action="training.evaluation.run", object_type="workspace", object_id=workspace_id,
        data={"cases": len(results), "passed": passed,
              "average_score": round(sum(x["score"] for x in results) / len(results))},
    ))
    ctx.db.commit()
    return {
        "cases": len(results),
        "passed": passed,
        "average_score": round(sum(x["score"] for x in results) / len(results)),
        "results": results,
    }


@router.post("/config/{workspace_id}/training/rollback/{revision_id}")
def rollback_training_package(workspace_id: int, revision_id: int,
                              ctx: AuthContext = Depends(get_ctx)):
    workspace = _training_admin(workspace_id, ctx)
    from ..enrichment.pipeline import _config
    from ..enrichment.training import (
        apply_config_state,
        replace_evaluations,
        revision_hash,
        workspace_state,
    )

    target = (
        ctx.db.query(WorkspaceTrainingRevision)
        .filter(
            WorkspaceTrainingRevision.id == revision_id,
            WorkspaceTrainingRevision.workspace_id == workspace_id,
        )
        .first()
    )
    if target is None:
        raise HTTPException(404, "Training revision not found.")
    cfg = _config(ctx.db, workspace_id)
    ctx.db.commit()
    current = workspace_state(ctx.db, cfg)
    _save_training_revision(
        ctx, workspace_id, current, action="before_rollback",
        note=f"Before rollback to revision {target.version}",
    )
    restored = target.snapshot
    apply_config_state(cfg, restored)
    replace_evaluations(ctx.db, workspace_id, restored.get("evaluation_cases", []))
    ctx.db.add(AuditLog(
        org_id=ctx.org_id, workspace_id=workspace_id, user_id=ctx.user.id,
        action="training.package.rollback", object_type="workspace", object_id=workspace_id,
        data={"restored_revision_id": target.id, "restored_revision": revision_hash(restored)},
    ))
    ctx.db.commit()
    return {
        "ok": True,
        "workspace": workspace.name,
        "revision": revision_hash(restored),
        "restored_revision_id": target.id,
    }


@router.get("/config/{workspace_id}")
def get_config(workspace_id: int, ctx: AuthContext = Depends(get_ctx)):
    ctx.require_workspace(workspace_id)
    import os

    from ..enrichment import ai
    from ..enrichment.pipeline import _config
    cfg = _config(ctx.db, workspace_id)
    ctx.db.commit()
    return {"profile": cfg.profile or {}, "icp_definition": cfg.icp_definition or "",
            "formats": cfg.formats or [], "rules": cfg.rules or "",
            "skip_title_gate": bool(cfg.skip_title_gate), "skip_icp": bool(cfg.skip_icp),
            "only_safe": bool(cfg.only_safe),
            "require_research_gate": bool(getattr(cfg, "require_research_gate", 0)),
            "reading_level": cfg.reading_level or "b2 business",
            "writer_model": cfg.writer_model or "",
            "research_depth": cfg.research_depth or "standard",
            # which models are actually used (writer override else env default)
            "writer_model_effective": (cfg.writer_model or ai.writer_model()),
            "icp_model_effective": ai.extract_model(),
            "ai_enabled": ai.has_ai(),
            # never return the secret — only whether one is set, and from where
            "reoon_api_key_set": bool((cfg.reoon_api_key_enc or "") or os.getenv("REOON_API_KEY", "")),
            "reoon_key_source": ("workspace" if (cfg.reoon_api_key_enc or "")
                                 else ("env" if os.getenv("REOON_API_KEY", "") else "none"))}


@router.put("/config/{workspace_id}")
def put_config(workspace_id: int, body: ConfigIn, ctx: AuthContext = Depends(get_ctx)):
    ctx.require_workspace(workspace_id)
    from ..enrichment.pipeline import _config
    cfg = _config(ctx.db, workspace_id)
    if body.profile is not None:
        cfg.profile = body.profile
    if body.icp_definition is not None:
        cfg.icp_definition = body.icp_definition
    if body.formats is not None:
        cfg.formats = body.formats
    elif body.variables is not None:      # accept the old "variables" array name too
        cfg.formats = body.variables
    if body.rules is not None:
        cfg.rules = body.rules
    if body.skip_title_gate is not None:
        cfg.skip_title_gate = 1 if body.skip_title_gate else 0
    if body.skip_icp is not None:
        cfg.skip_icp = 1 if body.skip_icp else 0
    if body.only_safe is not None:
        cfg.only_safe = 1 if body.only_safe else 0
    if body.reoon_api_key is not None:
        from ..crypto import encrypt
        key = body.reoon_api_key.strip()
        cfg.reoon_api_key_enc = encrypt(key) if key else ""   # blank clears it
    if body.reading_level is not None:
        cfg.reading_level = body.reading_level.strip()
    if body.writer_model is not None:
        cfg.writer_model = body.writer_model.strip()
    if body.research_depth is not None:
        cfg.research_depth = body.research_depth if body.research_depth in ("standard", "deep") else "standard"
    if body.require_research_gate is not None:
        cfg.require_research_gate = 1 if body.require_research_gate else 0
    ctx.db.commit()
    return {"ok": True}


class BuildProfileIn(BaseModel):
    website: str = ""       # crawl this to gather material
    material: str = ""      # pasted case studies / docs / positioning
    merge: bool = True       # merge into the existing profile vs replace




def _extract_upload_text(raw: bytes, filename: str) -> str:
    """Read text from an uploaded ICP doc — PDF (pypdf) or plain text."""
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        try:
            import io

            from pypdf import PdfReader
            r = PdfReader(io.BytesIO(raw))
            return "\n".join((p.extract_text() or "") for p in r.pages)
        except Exception:
            return ""
    try:
        return raw.decode("utf-8", "ignore")
    except Exception:
        return ""


@router.post("/config/{workspace_id}/build-icp")
async def build_icp(workspace_id: int,
                    file: UploadFile = File(None), text: str = Form(""), website: str = Form(""),
                    ctx: AuthContext = Depends(get_ctx)):
    """Build the ICP definition from a PDF / pasted text / a website, so nobody has
    to hand-write JSON. Returns structured ICP JSON to review and save."""
    ctx.require_workspace(workspace_id)
    import json as _json

    from ..enrichment import ai
    from ..enrichment.crawler import crawl_site
    from ..enrichment.pipeline import _config
    if not ai.has_ai():
        raise HTTPException(422, "No OpenAI key set — connect AI before building the ICP.")
    material = (text or "").strip()
    if file is not None:
        raw = await file.read()
        material = (material + "\n\n" + _extract_upload_text(raw, file.filename)).strip()
    if website:
        crawl = crawl_site(website, max_pages=10, max_chars=24000)
        if crawl.get("text"):
            material = (material + "\n\n" + crawl["text"]).strip()
    # use the TRAINED BRAIN too — so after training in chat you can just hit Build.
    cfg = _config(ctx.db, workspace_id)
    brain = cfg.profile or {}
    # ICP decisions benefit from the whole relevant commercial picture, not only
    # the old small subset. In particular, objections and proof often contain the
    # clearest fit/reject signals.
    icp_brain_keys = (
        "client_name", "one_liner", "service_brief", "main_offer", "what_we_are_pitching",
        "target_outcome", "icp_summary", "industries", "services", "positioning",
        "methodology", "results_metrics", "proof_points", "target_titles",
        "problem_library", "case_studies", "objections",
    )
    brain_ctx = _json.dumps({k: brain.get(k) for k in icp_brain_keys if brain.get(k)})
    if not material.strip() and brain_ctx in ("", "{}"):
        raise HTTPException(422, "Nothing to learn from — train the brain (Ask the Brain), upload a PDF, paste text, or give a website.")
    full = ((f"TRAINED CLIENT BRAIN:\n{brain_ctx}\n\n" if brain_ctx not in ("", "{}") else "")
            + (f"ADDITIONAL MATERIAL:\n{material}" if material else ""))[:26000]

    system = (
        "You write a STRICT ICP (ideal customer profile) definition for a B2B outbound engine, from the "
        "material provided (the trained CLIENT BRAIN and any additional material). Ground ONLY in what is "
        "provided — never invent. Return JSON with EXACTLY these keys:\n"
        'procedure (list of str — the ordered steps to decide if a company is a fit), '
        'icp_categories (list of str — the specific company types that ARE a fit), '
        'hard_non_icp (list of str — signals that AUTO-REJECT a company), '
        'default (str — one of "ICP", "Non-ICP", "Needs Review" — what to return when unsure). '
        "Be concrete and specific to this business.")
    try:
        out = ai._call_openai(system, full, model=ai.extract_model())
    except Exception as e:
        raise HTTPException(502, f"AI extraction failed: {str(e)[:200]}")
    if not isinstance(out, dict):
        raise HTTPException(502, "AI returned an unexpected format — try again or paste cleaner material.")
    icp = {k: out.get(k, [] if k in ("procedure", "icp_categories", "hard_non_icp") else "")
           for k in ("procedure", "icp_categories", "hard_non_icp", "default")}
    return {"icp_json": _json.dumps(icp, indent=2), "icp": icp,
            "counts": {"categories": len(icp["icp_categories"] or []),
                       "rejects": len(icp["hard_non_icp"] or []), "steps": len(icp["procedure"] or [])}}


class BrainChatMsg(BaseModel):
    role: str
    content: str


class BrainChatIn(BaseModel):
    messages: list[BrainChatMsg] = []


@router.post("/config/{workspace_id}/brain-chat")
def brain_chat(workspace_id: int, body: BrainChatIn, ctx: AuthContext = Depends(get_ctx)):
    """The workspace's own ChatGPT: grounded in the Client Brain. Answers questions
    and drafts outreach from the brain, and when you TEACH it new facts about the
    client (a case study, service, metric...) it captures them into the brain
    (accumulated, deduped) so the knowledge grows through conversation."""
    ctx.require_workspace(workspace_id)
    import json as _json
    import os

    import requests

    from ..enrichment import ai
    from ..enrichment.pipeline import _config
    if not ai.has_ai():
        raise HTTPException(422, "No OpenAI key set — connect AI to use the brain chat.")
    if not body.messages:
        raise HTTPException(422, "No message")
    cfg = _config(ctx.db, workspace_id)
    brain = cfg.profile or {}

    # If the user shared any website URL, SCRAPE it (we have a crawler) so the brain
    # can actually read it — no more "I can't browse websites".
    import re as _re
    scraped = ""
    recent = " ".join((m.content or "") for m in body.messages[-4:] if m.role == "user")
    urls = []
    for u in _re.findall(r"https?://[^\s<>\"')\]]+", recent):
        u = u.rstrip(".,);]")
        if u not in urls:
            urls.append(u)
    if urls:
        from ..enrichment.crawler import crawl_site
        for u in urls[:2]:
            try:
                cr = crawl_site(u, max_pages=6, max_chars=10000, render=True)
                if cr.get("text"):
                    scraped += f"\n\n--- WEBSITE: {u} ---\n{cr['text'][:10000]}"
            except Exception:
                pass

    system = (
        "You are the private assistant for this client's workspace — an expert on the company described "
        "in CLIENT BRAIN below. Help the user: answer questions, draft cold emails / follow-ups, and give "
        "advice, using the brain plus what the user tells you. Never invent facts about the CLIENT (the "
        "company in the brain). You CAN read any website the user shares — its scraped content is provided "
        "under SCRAPED WEBSITES; use that real content to write about a prospect/company.\n"
        "If the user TEACHES you new information about the client (a case study, a service, a metric, "
        "positioning, a problem they solve, a testimonial, an objection), capture it in 'learned' so it is "
        "saved to the brain. If they ADD detail to an existing case study/problem/testimonial, return the "
        "same identifying client/industry/person plus the new or corrected fields; storage will merge the "
        "fields. For a scalar field, return the complete UPDATED current value: combine supported saved and "
        "new detail when the user adds information, or return the corrected value when they replace a fact "
        "(even if it is shorter). Only include keys the user actually added to or corrected; do not repeat "
        "unchanged brain fields.\n"
        "Return JSON: {\"reply\": <your message to the user>, \"learned\": {<any of: service_brief (str), "
        "main_offer (str), one_liner (str), target_outcome (str), icp_summary (str), industries (list), "
        "services (list), positioning (list), methodology (list), results_metrics (list), proof_points "
        "(list), target_titles (list), case_studies (list of {client,industry,problem,solution,outcome,"
        "metrics}), problem_library (list of {industry,pains,our_angle}), testimonials (list of "
        "{quote,who}), objections (list of {objection,response})> or {} if nothing new}}.\n"
        "CLIENT BRAIN:\n" + _json.dumps(brain)[:14000]
        + (("\n\nSCRAPED WEBSITES (real page content the user shared — use this):\n" + scraped[:16000]) if scraped else ""))

    msgs = [{"role": "system", "content": system}]
    for m in body.messages[-14:]:
        msgs.append({"role": "assistant" if m.role == "assistant" else "user", "content": (m.content or "")[:6000]})
    try:
        chat_model = (cfg.writer_model or ai.writer_model()).lower()
        chat_payload = {
            "model": chat_model,
            "response_format": {"type": "json_object"},
            "messages": msgs,
        }
        if chat_model.startswith("gpt-5"):
            chat_payload["reasoning_effort"] = "low"
        else:
            chat_payload["temperature"] = 0.4
        r = requests.post(ai.OPENAI_URL,
            headers={"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}", "Content-Type": "application/json"},
            json=chat_payload, timeout=60)
        r.raise_for_status()
        out = _json.loads(r.json()["choices"][0]["message"]["content"])
    except Exception as e:
        raise HTTPException(502, f"Chat failed: {str(e)[:200]}")
    reply = str(out.get("reply", "")).strip() or "…"
    learned = out.get("learned") if isinstance(out.get("learned"), dict) else {}

    updated = []
    if learned:
        before = cfg.profile or {}
        accepted = {k: v for k, v in learned.items()
                    if k in CLIENT_BRAIN_KEYS and v not in (None, "", [], {})}
        merged = _accumulate_brain(before, accepted, scalar_strategy="replace")
        updated = [k for k in accepted if merged.get(k) != before.get(k)]
        if updated:
            cfg.profile = merged        # reassign so the JSON column change is detected
            ctx.db.commit()
    return {"reply": reply, "learned": updated}


class BuildFormatsIn(BaseModel):
    instructions: str = ""    # the operator's rules / how variables should be written / pasted formats
    current: list | None = None   # the operator's live formats to REVISE in place (None → use saved)
    merge: bool = True            # True → edit the variables discussed, keep the rest; False → clean rebuild


@router.post("/config/{workspace_id}/build-formats")
def build_formats(workspace_id: int, body: BuildFormatsIn, ctx: AuthContext = Depends(get_ctx)):
    """The AI designs OR REVISES the OUTPUT VARIABLES (formats) the cold-email
    writer produces — grounded in the Client Brain + the operator's rules. When
    formats already exist and merge=True, it EDITS IN PLACE: it revises only the
    variables the operator is talking about and keeps every other variable exactly
    as it was (nothing hand-tuned is lost)."""
    ctx.require_workspace(workspace_id)
    import json as _json
    import re as _re

    from ..enrichment import ai
    from ..enrichment.pipeline import _config
    if not ai.has_ai():
        raise HTTPException(422, "No OpenAI key set — connect AI before building formats.")
    cfg = _config(ctx.db, workspace_id)
    brain = cfg.profile or {}
    # Baseline to revise: the live formats the UI sent, else what's saved.
    existing = body.current if body.current is not None else (cfg.formats or [])
    existing = [f for f in (existing or []) if isinstance(f, dict)]
    editing = bool(body.merge and existing)

    system = (
        "You design OR REVISE the OUTPUT VARIABLES ('formats') an AI cold-email writer will produce for THIS "
        "client, using the CLIENT BRAIN and the OPERATOR INSTRUCTIONS. Follow these rules of CARE:\n"
        "1) BE FAITHFUL to what the operator actually described. Build/revise the variables THEY explain or "
        "ask for. If they give no specific variables and none exist yet, propose the standard set "
        "(Personalized First Line, Value Proposition, Product Complimentary, Reference, Pitch) — but never "
        "force a variable they didn't want.\n"
        "2) MATCH DEPTH per variable to how much the operator explained it. Where they gave detailed "
        "structure, rules, or examples, reflect that fully. Where they said little, keep THAT variable "
        "light — short guidance, NO invented rigid template, NO fabricated rules or examples. Do NOT impose "
        "one uniform format on every variable, and do NOT invent rules, templates, word limits, or examples "
        "the operator didn't provide or clearly imply. Set min_words/max_words ONLY if a length was "
        "specified, else null. Prefer 0-2 REAL examples grounded in the brain over made-up ones.\n"
        + ("3) YOU ARE EDITING EXISTING FORMATS (given under CURRENT FORMATS). Return ONLY the variables the "
           "operator's instructions actually address — revise those, reusing their exact 'name' slug so they "
           "map onto the current ones. Do NOT return the untouched variables; they are kept automatically. "
           "Do NOT rename or renumber. If the operator describes a brand-new variable, include it with a new "
           "slug.\n" if editing else "")
        + "Return JSON {\"formats\": [ {\"label\": str, \"name\": snake_case slug, \"guidance\": str (how to "
        "write it, grounded in the client's real offer/problems/proof), \"template\": str (optional; "
        "{{placeholders}} or \"\"), \"min_words\": int|null, \"max_words\": int|null, \"rules\": [str], "
        "\"examples\": [str], \"enabled\": true} ] }. Ground everything ONLY in the CLIENT BRAIN + operator "
        "instructions; never invent client facts.")
    user = ("OPERATOR INSTRUCTIONS / RULES / SAMPLE FORMATS:\n" + (body.instructions or "(none — use best practice)")
            + (("\n\nCURRENT FORMATS (revise only the ones the instructions address; keep names):\n"
                + _json.dumps([{k: f.get(k) for k in ("label", "name", "guidance", "template", "min_words",
                                                       "max_words", "rules", "examples")} for f in existing])[:8000])
               if editing else "")
            + "\n\nCLIENT BRAIN:\n" + _json.dumps(brain)[:12000])
    try:
        out = ai._call_openai(system, user, model=ai.extract_model())
    except Exception as e:
        raise HTTPException(502, f"AI format design failed: {str(e)[:200]}")
    formats = out.get("formats") if isinstance(out, dict) else None
    if not isinstance(formats, list) or not formats:
        raise HTTPException(502, "AI didn't return formats — try again with clearer instructions.")

    def _slug(s, i):
        s = _re.sub(r"[^a-z0-9]+", "_", str(s or "").lower()).strip("_")
        return s or f"variable_{i + 1}"
    clean = []
    for i, f in enumerate(formats):
        if not isinstance(f, dict):
            continue
        clean.append({
            "label": str(f.get("label") or f"Variable {i + 1}"),
            "name": _slug(f.get("name") or f.get("label"), i),
            "guidance": str(f.get("guidance") or ""),
            "template": str(f.get("template") or ""),
            "min_words": int(f.get("min_words") or 0) or None,
            "max_words": int(f.get("max_words") or 0) or None,
            "rules": [str(r) for r in (f.get("rules") or []) if r],
            "examples": [str(e) for e in (f.get("examples") or []) if e],
            "enabled": f.get("enabled", True) is not False,
        })

    if not editing:
        return {"formats": clean, "count": len(clean), "updated": [f["name"] for f in clean], "merged": False}

    # ---- merge in place: overlay revised variables onto the existing set by slug,
    # preserving order, untouched variables, and per-variable extras (placeholders,
    # fallback). Only substantive (non-empty) fields overwrite an existing variable.
    def _nonempty(d):
        return {k: v for k, v in d.items() if v not in (None, "", [], {})}
    order = [f.get("name") for f in existing]
    merged = {f.get("name"): dict(f) for f in existing}
    updated = []
    for f in clean:
        n = f["name"]
        if n in merged:
            merged[n] = {**merged[n], **_nonempty(f)}
        else:
            merged[n] = f
            order.append(n)
        updated.append(n)
    final = [merged[n] for n in order if n in merged]
    return {"formats": final, "count": len(final), "updated": updated, "merged": True}


class AppendRulesIn(BaseModel):
    text: str = ""
    messages: list[dict] | None = None


@router.post("/config/{workspace_id}/append-rules")
def append_global_rules(workspace_id: int, body: AppendRulesIn, ctx: AuthContext = Depends(get_ctx)):
    """Turn cross-variable / global instructions from the chat into GLOBAL RULES
    (cfg.rules) — the plain-English lines the writer obeys on EVERY email (e.g.
    'never repeat the same personalization across variables'). Appends new rules,
    deduped; never touches the per-variable formats."""
    ctx.require_workspace(workspace_id)
    from ..enrichment import ai
    from ..enrichment.pipeline import _config
    cfg = _config(ctx.db, workspace_id)

    src = (body.text or "").strip()
    if not src and body.messages:
        src = "\n\n".join((m.get("content") or "") for m in body.messages if m.get("role") == "user").strip()
    if not src:
        raise HTTPException(422, "Nothing to turn into a rule.")

    existing_lines = [ln.strip() for ln in (cfg.rules or "").splitlines() if ln.strip()]
    existing_lower = {ln.lower() for ln in existing_lines}

    new_rules = []
    if ai.has_ai():
        system = (
            "Extract GLOBAL writing rules from the operator's message — short imperative do/don't lines that "
            "apply ACROSS every variable and every email (tone, things never to repeat, formatting bans, "
            "length caps, banned words). Do NOT include instructions that define ONE variable's format/"
            "structure — those are not global rules. Rewrite each as a concise, standalone directive. "
            "Return JSON {\"rules\": [str, ...]} (deduplicated); {\"rules\": []} if there are none.")
        try:
            out = ai._call_openai(system, src[:6000], model=ai.extract_model())
            cand = out.get("rules") if isinstance(out, dict) else None
            if isinstance(cand, list):
                new_rules = [str(r).strip() for r in cand if str(r).strip()]
        except Exception:
            new_rules = []
    if not new_rules:   # fallback: keep the operator's own lines verbatim
        new_rules = [ln.strip(" -•\t") for ln in src.splitlines() if ln.strip()]

    added = []
    for r in new_rules:
        if r.lower() not in existing_lower:
            existing_lines.append(r)
            existing_lower.add(r.lower())
            added.append(r)
    cfg.rules = "\n".join(existing_lines)
    ctx.db.commit()
    return {"added": added, "count": len(added), "rules": cfg.rules}


class UpdateIcpIn(BaseModel):
    text: str = ""
    messages: list[dict] | None = None


@router.post("/config/{workspace_id}/update-icp")
def update_icp_from_chat(workspace_id: int, body: UpdateIcpIn, ctx: AuthContext = Depends(get_ctx)):
    """ACCUMULATE ICP signals described in the chat into the existing ICP
    definition (cfg.icp_definition): add the fit types / auto-reject rules / steps
    the operator states, keep everything already there, deduped. Never replaces."""
    ctx.require_workspace(workspace_id)
    import json as _json

    from ..enrichment import ai
    from ..enrichment.pipeline import _config
    if not ai.has_ai():
        raise HTTPException(422, "No OpenAI key set — connect AI before updating the ICP.")
    cfg = _config(ctx.db, workspace_id)

    src = (body.text or "").strip()
    if not src and body.messages:
        src = "\n\n".join((m.get("content") or "") for m in body.messages if m.get("role") == "user").strip()
    if not src:
        raise HTTPException(422, "Nothing to add to the ICP.")

    # If the saved ICP is free-form PROSE (not our structured JSON), never restructure
    # it into JSON — that would discard the operator's written guidance. Append the new
    # instruction to the prose verbatim instead.
    existing = (cfg.icp_definition or "").strip()
    is_structured = False
    if existing:
        try:
            is_structured = isinstance(_json.loads(existing), dict)
        except Exception:
            is_structured = False
    if existing and not is_structured:
        cfg.icp_definition = existing + "\n" + src
        ctx.db.commit()
        return {"icp": None, "appended_prose": True,
                "added": {"note": "Appended to your written ICP guidance."}}

    try:
        cur = _json.loads(cfg.icp_definition) if cfg.icp_definition else {}
        if not isinstance(cur, dict):
            cur = {}
    except Exception:
        cur = {}
    cats = [str(x).strip() for x in (cur.get("icp_categories") or []) if str(x).strip()]
    rejects = [str(x).strip() for x in (cur.get("hard_non_icp") or []) if str(x).strip()]
    proc = [str(x).strip() for x in (cur.get("procedure") or []) if str(x).strip()]
    default = cur.get("default") or "Needs Review"

    system = (
        "From the operator's message, extract NEW ICP (ideal customer profile) signals to ADD to an existing "
        "definition. Return JSON with keys: icp_categories (list of company types that ARE a fit), "
        "hard_non_icp (list of signals that AUTO-REJECT a company), procedure (list of new decision steps), "
        "default (one of 'ICP','Non-ICP','Needs Review', or '' if not specified). Include ONLY what the "
        "operator actually stated or clearly implied; never invent. Empty lists are fine.")
    try:
        out = ai._call_openai(system, src[:6000], model=ai.extract_model())
    except Exception as e:
        raise HTTPException(502, f"AI ICP update failed: {str(e)[:200]}")
    out = out if isinstance(out, dict) else {}

    def _merge(existing, new):
        low = {e.lower() for e in existing}
        added = []
        for x in (new or []):
            x = str(x).strip()
            if x and x.lower() not in low:
                existing.append(x)
                low.add(x.lower())
                added.append(x)
        return added
    added_cats = _merge(cats, out.get("icp_categories"))
    added_rej = _merge(rejects, out.get("hard_non_icp"))
    added_proc = _merge(proc, out.get("procedure"))
    nd = str(out.get("default") or "").strip()
    if nd in ("ICP", "Non-ICP", "Needs Review"):
        default = nd

    icp = {"procedure": proc, "icp_categories": cats, "hard_non_icp": rejects, "default": default}
    cfg.icp_definition = _json.dumps(icp, indent=2)
    ctx.db.commit()
    return {"icp": icp,
            "added": {"categories": added_cats, "rejects": added_rej, "steps": added_proc,
                      "default": nd if nd in ("ICP", "Non-ICP", "Needs Review") else None},
            "counts": {"categories": len(cats), "rejects": len(rejects), "steps": len(proc)}}


class BrainLearnIn(BaseModel):
    messages: list[dict] = []
    text: str = ""


@router.post("/config/{workspace_id}/brain-learn")
def brain_learn(workspace_id: int, body: BrainLearnIn, ctx: AuthContext = Depends(get_ctx)):
    """Explicitly SAVE what you've shared into the brain: extract every case study,
    service, metric, problem and proof from the material/conversation and merge it
    (accumulated, deduped). Grounds only in what you provided — never invents."""
    ctx.require_workspace(workspace_id)
    import json as _json

    from ..enrichment import ai
    from ..enrichment.pipeline import _config
    if not ai.has_ai():
        raise HTTPException(422, "No OpenAI key set — connect AI to save to the brain.")
    material = (body.text or "").strip()
    if not material and body.messages:
        material = "\n\n".join(str(m.get("content") or "") for m in body.messages if m.get("role") == "user")
    material = material.strip()
    if not material:
        raise HTTPException(422, "Nothing to save — share some material first.")

    cfg = _config(ctx.db, workspace_id)
    before = cfg.profile or {}
    system = (
        "You extract a COMPREHENSIVE knowledge base about a B2B company from the material the operator "
        "shares, to save into the company's brain. Be exhaustive — capture every case study, metric, "
        "service, proof and problem, preserving real detail and numbers. Ground ONLY in the material; "
        "never invent; leave a field empty/[] if unsupported. Compare it with the EXISTING CLIENT BRAIN. "
        "For scalar fields, return the complete UPDATED value: combine supported existing and new detail "
        "when information is added. A later explicit operator correction is authoritative, even when the "
        "corrected value is shorter. For an existing case study, problem, testimonial, or "
        "objection, return its identifying field plus its new/corrected fields so storage can enrich it "
        "without losing facts not re-mentioned. Do not repeat unchanged facts. Return JSON with these keys: "
        "service_brief (str), main_offer (str), one_liner (str), target_outcome (str), icp_summary (str), "
        "industries (list), services (list), positioning (list), methodology (list), results_metrics "
        "(list), proof_points (list), target_titles (list), tone (str), case_studies (list of "
        "{client,industry,problem,solution,outcome,metrics}), problem_library (list of "
        "{industry,pains,our_angle}), testimonials (list of {quote,who}), objections (list of "
        "{objection,response}). Include only keys the material supports.")
    try:
        prompt = ("EXISTING CLIENT BRAIN:\n" + _json.dumps(before)[:16000]
                  + "\n\nNEW OPERATOR MATERIAL (authoritative when it corrects the brain):\n"
                  + material[:28000])
        out = ai._call_openai(system, prompt, model=ai.extract_model())
    except Exception as e:
        raise HTTPException(502, f"AI extraction failed: {str(e)[:200]}")
    if not isinstance(out, dict):
        raise HTTPException(502, "AI returned an unexpected format — try again.")
    new = {k: v for k, v in out.items() if k in CLIENT_BRAIN_KEYS and v not in (None, "", [])}
    merged = _accumulate_brain(before, new, scalar_strategy="replace")
    cfg.profile = merged
    ctx.db.commit()
    saved = [k for k in new if merged.get(k) != before.get(k)]
    return {"saved": saved,
            "counts": {"case_studies": len(merged.get("case_studies") or []),
                       "services": len(merged.get("services") or []),
                       "metrics": len(merged.get("results_metrics") or []),
                       "problems": len(merged.get("problem_library") or [])}}


@router.post("/config/{workspace_id}/build-profile")
def build_profile(workspace_id: int, body: BuildProfileIn, ctx: AuthContext = Depends(get_ctx)):
    """Train the workspace on ONE client: crawl their site + read any pasted
    material, and extract a structured Client Brain (offer, ICP, case studies, and
    a per-industry problem library) that grounds all AI writing. Grounds only in
    the material — never invents metrics or case studies."""
    ctx.require_workspace(workspace_id)
    import json as _json

    from ..enrichment import ai
    from ..enrichment.crawler import crawl_site
    from ..enrichment.pipeline import _config
    if not ai.has_ai():
        raise HTTPException(422, "No OpenAI key set — connect AI before building the profile.")
    cfg = _config(ctx.db, workspace_id)
    existing_brain = cfg.profile or {}
    pasted_material = (body.material or "").strip()
    text = pasted_material
    pages_crawled = js_rendered = 0
    if body.website:
        # crawl the WHOLE site (every same-domain page) to capture all case studies,
        # results and industries — and render JS-empty pages (SPA support).
        crawl = crawl_site(body.website, max_pages=40, max_chars=140000, follow_all=True, render=True)
        pages_crawled = len(crawl.get("pages") or [])
        js_rendered = crawl.get("js_rendered", 0)
        if crawl.get("text"):
            text = (crawl["text"] + "\n\n---PASTED---\n" + text)
    text = text[:120000]    # current extract models have ample context; preserve proof-rich material
    if not text.strip():
        raise HTTPException(422, "Provide a website URL or paste some material to learn from.")

    system = (
        "You are building a COMPREHENSIVE knowledge base about a B2B company from THEIR OWN material, "
        "so an AI can write outreach and follow-ups that sound like a true insider. Be EXHAUSTIVE — "
        "capture every case study, metric, service, proof point and problem you can find. DO NOT "
        "summarize into one-liners: preserve the real detail, numbers, client names, and outcomes as "
        "written. Ground EVERYTHING only in the material — never invent; leave a field empty/[] if the "
        "material doesn't support it. Reconcile the new material with the CURRENT SAVED CLIENT BRAIN: "
        "preserve supported existing facts, enrich matching structured records, and treat explicit pasted "
        "operator corrections as authoritative. Return JSON with EXACTLY these keys:\n"
        'client_name (str), one_liner (str), '
        'service_brief (str — a full paragraph: who the client is and everything they sell), '
        'main_offer (str — full, detailed), '
        'what_we_are_pitching (str), target_outcome (str), icp_summary (str), '
        'industries (list of str), '
        'services (list of str — every service/offering, specific), '
        'positioning (list of str — real differentiators, detailed), '
        'methodology (list of str — how they deliver / their process, step by step), '
        'results_metrics (list of str — every concrete metric/number/stat, verbatim), '
        'proof_points (list of str — awards, notable clients/logos, credentials), '
        'testimonials (list of {quote, who}), '
        'target_titles (list of str — the buyer roles they sell to), tone (str), '
        'case_studies (list of {client, industry, problem, solution, outcome, metrics (list of str), quote}) '
        "— capture the FULL story of each, not a summary; include every case study present, "
        'problem_library (list of {industry, pains: list of str, our_angle: str, proof: str} — the '
        'specific problems buyers in each industry face, how this company solves them, and the proof), '
        'objections (list of {objection, response}).')
    user = ("CURRENT SAVED CLIENT BRAIN:\n" + _json.dumps(existing_brain)[:18000]
            + "\n\nNEW COMPANY MATERIAL (be exhaustive — extract everything):\n" + text)
    try:
        out = ai._call_openai(system, user, model=ai.extract_model())
    except Exception as e:
        raise HTTPException(502, f"AI extraction failed: {str(e)[:200]}")
    if not isinstance(out, dict):
        raise HTTPException(502, "AI returned an unexpected format — try again or paste cleaner material.")
    profile = {k: out.get(k, [] if k in _BRAIN_LIST_KEYS else "") for k in CLIENT_BRAIN_KEYS}

    if body.merge:
        # Explicit pasted material can correct a saved scalar. Website-only
        # re-crawls stay conservative and only replace a scalar with a richer one.
        strategy = "replace" if pasted_material else "richer"
        profile = _accumulate_brain(existing_brain, profile, scalar_strategy=strategy)
    return {"profile": profile,
            "counts": {"case_studies": len(profile.get("case_studies") or []),
                       "problems": len(profile.get("problem_library") or []),
                       "services": len(profile.get("services") or []),
                       "metrics": len(profile.get("results_metrics") or []),
                       "industries": len(profile.get("industries") or [])},
            "pages_crawled": pages_crawled, "js_rendered": js_rendered, "crawled": bool(body.website)}
