"""List-based enrichment API (port of the enrichment dashboard endpoints).
Views + full-list counts are server-side so 50k+ lists stay browsable and the
chips are always accurate. 'Select all in view' semantics: actions accept a
view name and apply to the entire filtered set, not just a page."""
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import func

from ..auth import AuthContext, get_ctx
from ..models.enrich import TERMINAL_STATUSES, EnrichConfig, EnrichLead, EnrichList
from ..models.jobs import Job

router = APIRouter(prefix="/api/enrich-lists", tags=["enrichment-lists"])

VIEWS = ("all", "processed", "verified", "enriched", "nonicp", "no_website",
         "invalid", "unsafe", "notrun", "title_rejected",
         "esp_microsoft", "esp_google", "esp_other", "esp_unknown")


def _view_filter(q, view: str):
    L = EnrichLead
    if view == "processed":
        return q.filter(L.status.in_(TERMINAL_STATUSES))
    if view == "verified":
        return q.filter(L.email_status.in_(["safe", "valid", "catch_all", "unknown"]))
    if view == "enriched":
        return q.filter(L.status == "done")
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
        if l.status in ("done", "skipped", "error"):
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
    rules: str | None = None
    skip_title_gate: bool | None = None
    skip_icp: bool | None = None
    only_safe: bool | None = None
    reoon_api_key: str | None = None
    reading_level: str | None = None
    writer_model: str | None = None
    research_depth: str | None = None


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
            "reading_level": cfg.reading_level or "",
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
    ctx.db.commit()
    return {"ok": True}


class BuildProfileIn(BaseModel):
    website: str = ""       # crawl this to gather material
    material: str = ""      # pasted case studies / docs / positioning
    merge: bool = True       # merge into the existing profile vs replace


# The Client Brain schema — one rich, structured knowledge base the AI writer uses.
CLIENT_BRAIN_KEYS = ["client_name", "one_liner", "service_brief", "main_offer", "what_we_are_pitching",
                     "target_outcome", "icp_summary", "industries", "services", "positioning",
                     "methodology", "results_metrics", "proof_points", "testimonials",
                     "target_titles", "tone", "case_studies", "problem_library", "objections"]
_BRAIN_LIST_KEYS = {"industries", "services", "positioning", "methodology", "results_metrics",
                    "proof_points", "testimonials", "target_titles", "case_studies",
                    "problem_library", "objections"}
# identity field per dict-list, so re-crawls dedupe by the REAL entity (not exact text)
_BRAIN_DICT_KEY = {
    "case_studies": lambda x: str(x.get("client", "")).strip().lower(),
    "problem_library": lambda x: str(x.get("industry", "")).strip().lower(),
    "objections": lambda x: str(x.get("objection", ""))[:60].strip().lower(),
    "testimonials": lambda x: (str(x.get("who", "")).strip().lower() + "|" + str(x.get("quote", ""))[:40].lower()),
}


def _merge_brain_list(k, existing, new):
    import json as _j
    items = list(existing or []) + list(new or [])
    if k in _BRAIN_DICT_KEY:
        keyf = _BRAIN_DICT_KEY[k]
        by, keyless = {}, []
        for x in items:
            if not isinstance(x, dict):
                continue
            key = keyf(x)
            if not key:
                keyless.append(x)
            elif key not in by or len(_j.dumps(x)) > len(_j.dumps(by[key])):
                by[key] = x          # keep the richer (more detailed) version
        return list(by.values()) + keyless
    seen, out = set(), []             # plain string list — dedupe case-insensitively
    for x in items:
        key = " ".join(str(x if isinstance(x, str) else _j.dumps(x, sort_keys=True)).lower().split())
        if key and key not in seen:
            seen.add(key)
            out.append(x)
    return out


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
    brain_ctx = _json.dumps({k: brain.get(k) for k in
                             ("client_name", "main_offer", "icp_summary", "industries", "services",
                              "target_titles", "problem_library", "case_studies") if brain.get(k)})
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

    system = (
        "You are the private assistant for this client's workspace — an expert on the company described "
        "in CLIENT BRAIN below. Help the user: answer questions, draft cold emails / follow-ups, and give "
        "advice, using ONLY the brain plus what the user tells you. Never invent facts about the client.\n"
        "If the user TEACHES you new information about the client (a case study, a service, a metric, "
        "positioning, a problem they solve, a testimonial, an objection), capture it in 'learned' so it is "
        "saved to the brain. Only include keys the user actually provided.\n"
        "Return JSON: {\"reply\": <your message to the user>, \"learned\": {<any of: service_brief (str), "
        "main_offer (str), one_liner (str), target_outcome (str), icp_summary (str), industries (list), "
        "services (list), positioning (list), methodology (list), results_metrics (list), proof_points "
        "(list), target_titles (list), case_studies (list of {client,industry,problem,solution,outcome,"
        "metrics}), problem_library (list of {industry,pains,our_angle}), testimonials (list of "
        "{quote,who}), objections (list of {objection,response})> or {} if nothing new}}.\n"
        "CLIENT BRAIN:\n" + _json.dumps(brain)[:14000])

    msgs = [{"role": "system", "content": system}]
    for m in body.messages[-14:]:
        msgs.append({"role": "assistant" if m.role == "assistant" else "user", "content": (m.content or "")[:6000]})
    try:
        r = requests.post(ai.OPENAI_URL,
            headers={"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}", "Content-Type": "application/json"},
            json={"model": (cfg.writer_model or ai.writer_model()).lower(), "temperature": 0.4,
                  "response_format": {"type": "json_object"}, "messages": msgs}, timeout=60)
        r.raise_for_status()
        out = _json.loads(r.json()["choices"][0]["message"]["content"])
    except Exception as e:
        raise HTTPException(502, f"Chat failed: {str(e)[:200]}")
    reply = str(out.get("reply", "")).strip() or "…"
    learned = out.get("learned") if isinstance(out.get("learned"), dict) else {}

    updated = []
    if learned:
        merged = {**(cfg.profile or {})}
        for k, v in learned.items():
            if k in _BRAIN_LIST_KEYS and v:
                merged[k] = _merge_brain_list(k, merged.get(k), v)
                updated.append(k)
            elif isinstance(v, str) and v.strip() and k in CLIENT_BRAIN_KEYS:
                old = str(merged.get(k) or "")
                if len(v.strip()) > len(old.strip()):
                    merged[k] = v
                    updated.append(k)
        if updated:
            cfg.profile = merged        # reassign so the JSON column change is detected
            ctx.db.commit()
    return {"reply": reply, "learned": updated}


class BuildFormatsIn(BaseModel):
    instructions: str = ""    # the operator's rules / how variables should be written / pasted formats


@router.post("/config/{workspace_id}/build-formats")
def build_formats(workspace_id: int, body: BuildFormatsIn, ctx: AuthContext = Depends(get_ctx)):
    """The AI designs the OUTPUT VARIABLES (formats) the cold-email writer will
    produce — grounded in the Client Brain + the operator's rules. This replaces
    hand-writing format JSON: describe how you want it written, and it builds the
    variable definitions (guidance, template, word ranges, rules, examples)."""
    ctx.require_workspace(workspace_id)
    import json as _json
    import re as _re

    from ..enrichment import ai
    from ..enrichment.pipeline import _config
    if not ai.has_ai():
        raise HTTPException(422, "No OpenAI key set — connect AI before building formats.")
    cfg = _config(ctx.db, workspace_id)
    brain = cfg.profile or {}

    system = (
        "You design the OUTPUT VARIABLES ('formats') that an AI cold-email writer will produce for THIS "
        "client, in a lead-generation workflow. Use the CLIENT BRAIN (their offer, services, case studies, "
        "per-industry problems, proof) and the OPERATOR INSTRUCTIONS to design excellent variables. "
        "Return JSON {\"formats\": [ ... ]}. Each format = {\"label\": str (human name), \"name\": snake_case "
        "slug, \"guidance\": str (exactly how to write this variable, grounded in the client's real offer/"
        "problems/proof — specific, not generic), \"template\": str (optional; use {{placeholders}} for "
        "fill-in parts, else \"\"), \"min_words\": int, \"max_words\": int, \"rules\": [str] (concrete do/"
        "don'ts), \"examples\": [str] (1-2 strong sample outputs grounded in the brain), \"enabled\": true}. "
        "Design the classic set unless the operator says otherwise: Personalized First Line, Value "
        "Proposition, Product Complimentary, Reference, and Pitch — but adapt to the operator's instructions. "
        "Ground guidance and examples ONLY in the CLIENT BRAIN + instructions; never invent client facts.")
    user = ("OPERATOR INSTRUCTIONS / RULES / SAMPLE FORMATS:\n" + (body.instructions or "(none — use best practice)")
            + "\n\nCLIENT BRAIN:\n" + _json.dumps(brain)[:14000])
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
    return {"formats": clean, "count": len(clean)}


def _accumulate_brain(existing: dict, new: dict) -> dict:
    """Merge extracted knowledge INTO the brain: lists dedupe by real entity,
    scalars keep the fuller version. Never wipes prior data."""
    merged = {**(existing or {})}
    for k, v in (new or {}).items():
        if k in _BRAIN_LIST_KEYS:
            merged[k] = _merge_brain_list(k, merged.get(k), v)
        elif isinstance(v, str) and v.strip():
            old = str(merged.get(k) or "")
            merged[k] = v if len(v.strip()) > len(old.strip()) else old
    return merged


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

    system = (
        "You extract a COMPREHENSIVE knowledge base about a B2B company from the material the operator "
        "shares, to save into the company's brain. Be exhaustive — capture every case study, metric, "
        "service, proof and problem, preserving real detail and numbers. Ground ONLY in the material; "
        "never invent; leave a field empty/[] if unsupported. Return JSON with these keys: "
        "service_brief (str), main_offer (str), one_liner (str), target_outcome (str), icp_summary (str), "
        "industries (list), services (list), positioning (list), methodology (list), results_metrics "
        "(list), proof_points (list), target_titles (list), tone (str), case_studies (list of "
        "{client,industry,problem,solution,outcome,metrics}), problem_library (list of "
        "{industry,pains,our_angle}), testimonials (list of {quote,who}), objections (list of "
        "{objection,response}). Include only keys the material supports.")
    try:
        out = ai._call_openai(system, "MATERIAL:\n" + material[:40000], model=ai.extract_model())
    except Exception as e:
        raise HTTPException(502, f"AI extraction failed: {str(e)[:200]}")
    if not isinstance(out, dict):
        raise HTTPException(502, "AI returned an unexpected format — try again.")
    new = {k: v for k, v in out.items() if k in CLIENT_BRAIN_KEYS and v not in (None, "", [])}
    cfg = _config(ctx.db, workspace_id)
    before = cfg.profile or {}
    merged = _accumulate_brain(before, new)
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
    text = (body.material or "").strip()
    pages_crawled = js_rendered = 0
    if body.website:
        # crawl the WHOLE site (every same-domain page) to capture all case studies,
        # results and industries — and render JS-empty pages (SPA support).
        crawl = crawl_site(body.website, max_pages=40, max_chars=140000, follow_all=True, render=True)
        pages_crawled = len(crawl.get("pages") or [])
        js_rendered = crawl.get("js_rendered", 0)
        if crawl.get("text"):
            text = (crawl["text"] + "\n\n---PASTED---\n" + text)
    text = text[:120000]    # gpt-4o-mini has a large context — send a lot, don't over-summarize
    if not text.strip():
        raise HTTPException(422, "Provide a website URL or paste some material to learn from.")

    system = (
        "You are building a COMPREHENSIVE knowledge base about a B2B company from THEIR OWN material, "
        "so an AI can write outreach and follow-ups that sound like a true insider. Be EXHAUSTIVE — "
        "capture every case study, metric, service, proof point and problem you can find. DO NOT "
        "summarize into one-liners: preserve the real detail, numbers, client names, and outcomes as "
        "written. Ground EVERYTHING only in the material — never invent; leave a field empty/[] if the "
        "material doesn't support it. Return JSON with EXACTLY these keys:\n"
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
    user = "COMPANY MATERIAL (be exhaustive — extract everything):\n" + text
    try:
        out = ai._call_openai(system, user, model=ai.extract_model())
    except Exception as e:
        raise HTTPException(502, f"AI extraction failed: {str(e)[:200]}")
    if not isinstance(out, dict):
        raise HTTPException(502, "AI returned an unexpected format — try again or paste cleaner material.")
    profile = {k: out.get(k, [] if k in _BRAIN_LIST_KEYS else "") for k in CLIENT_BRAIN_KEYS}

    if body.merge:
        # ACCUMULATE — new data ADDS to what's there, never wipes it. Lists merge by
        # the real entity (client/industry) so re-crawls don't duplicate; scalars keep
        # the FULLER version so each crawl can enrich them.
        cfg = _config(ctx.db, workspace_id)
        merged = {**(cfg.profile or {})}
        for k, v in profile.items():
            if k in _BRAIN_LIST_KEYS:
                merged[k] = _merge_brain_list(k, merged.get(k), v)
            elif isinstance(v, str) and v.strip():
                old = str(merged.get(k) or "")
                merged[k] = v if len(v.strip()) > len(old.strip()) else old
        profile = merged
    return {"profile": profile,
            "counts": {"case_studies": len(profile.get("case_studies") or []),
                       "problems": len(profile.get("problem_library") or []),
                       "services": len(profile.get("services") or []),
                       "metrics": len(profile.get("results_metrics") or []),
                       "industries": len(profile.get("industries") or [])},
            "pages_crawled": pages_crawled, "js_rendered": js_rendered, "crawled": bool(body.website)}
