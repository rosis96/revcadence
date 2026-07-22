"""List-based enrichment API (port of the enrichment dashboard endpoints).
Views + full-list counts are server-side so 50k+ lists stay browsable and the
chips are always accurate. 'Select all in view' semantics: actions accept a
view name and apply to the entire filtered set, not just a page."""
from fastapi import APIRouter, Depends, HTTPException
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


@router.get("/config/{workspace_id}")
def get_config(workspace_id: int, ctx: AuthContext = Depends(get_ctx)):
    ctx.require_workspace(workspace_id)
    import os

    from ..enrichment.pipeline import _config
    cfg = _config(ctx.db, workspace_id)
    ctx.db.commit()
    return {"profile": cfg.profile or {}, "icp_definition": cfg.icp_definition or "",
            "formats": cfg.formats or [], "rules": cfg.rules or "",
            "skip_title_gate": bool(cfg.skip_title_gate), "skip_icp": bool(cfg.skip_icp),
            "only_safe": bool(cfg.only_safe),
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
    ctx.db.commit()
    return {"ok": True}
