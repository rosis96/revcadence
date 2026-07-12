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
         "invalid", "unsafe", "notrun", "title_rejected")


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
    return q


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
               q: str = "", ctx: AuthContext = Depends(get_ctx)):
    lst = _get_list(ctx, list_id)
    base = ctx.db.query(EnrichLead).filter(EnrichLead.list_id == lst.id)
    if q:
        like = f"%{q}%"
        base = base.filter((EnrichLead.email.ilike(like)) | (EnrichLead.company.ilike(like))
                           | (EnrichLead.first_name.ilike(like)) | (EnrichLead.last_name.ilike(like)))
    filtered = _view_filter(base, view)
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
            "industry": l.industry, "status": l.status, "competitors": l.competitors or [],
            "vars": {k: v for k, v in (l.result or {}).items() if not k.startswith("_")},
        } for l in rows],
    }


# ---------------------------------------------------------------- run / stop
class RunIn(BaseModel):
    steps: str = "pipeline"       # 'verify' or 'pipeline' (Verify → Enrich)
    lead_ids: list[int] = []      # empty = whole view
    view: str = "notrun"          # used when lead_ids empty ('select all N in view')
    limit: int = 0                # test-first-N safety cap (0 = no cap)


@router.post("/{list_id}/run")
def run(list_id: int, body: RunIn, ctx: AuthContext = Depends(get_ctx)):
    lst = _get_list(ctx, list_id)
    lead_ids = body.lead_ids
    if not lead_ids:
        base = ctx.db.query(EnrichLead.id).filter(EnrichLead.list_id == lst.id)
        lead_ids = [r[0] for r in _view_filter(base, body.view).all()]
    if not lead_ids:
        raise HTTPException(422, "Nothing to run in this selection")
    j = Job(kind="run_enrich_list", workspace_id=lst.workspace_id,
            payload={"list_id": lst.id, "lead_ids": lead_ids, "steps": body.steps,
                     "limit": body.limit})
    ctx.db.add(j)
    ctx.db.commit()
    return {"job_id": j.id, "selected": len(lead_ids), "capped_at": body.limit or None}


# ---------------------------------------------------------------- competitor finder
class CompetitorsIn(BaseModel):
    lead_ids: list[int] = []
    view: str = "enriched"   # used when lead_ids empty (select-all-in-view semantics)


@router.post("/{list_id}/find-competitors")
def find_competitors_ep(list_id: int, body: CompetitorsIn, ctx: AuthContext = Depends(get_ctx)):
    """Model-knowledge competitor finder (no web search — cheap by design).
    Runs as a background job; skips leads that already have competitors."""
    lst = _get_list(ctx, list_id)
    lead_ids = body.lead_ids
    if not lead_ids:
        base = ctx.db.query(EnrichLead.id).filter(EnrichLead.list_id == lst.id)
        lead_ids = [r[0] for r in _view_filter(base, body.view).all()]
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
    from ..enrichment.verify_free import _doh_mx
    good = {d: _doh_mx(d) for d in ("gmail.com", "outlook.com")}
    dead = {d: _doh_mx(d) for d in ("no-such-domain-zzqx-1928374.com",)}
    working = any(v is True for v in good.values()) and all(v is False for v in dead.values())
    return {"dns_working": working,
            "results": {**good, **dead},
            "verdict": ("MX layer live — dead domains are being rejected" if working
                        else "MX layer NOT conclusive — free verifier is failing open; "
                             "only Reoon is filtering")}


@router.get("/diag/email")
def diag_email(e: str, ctx: AuthContext = Depends(get_ctx)):
    from ..enrichment.verify_free import check
    return {"email": e, **check(e)}


# ---------------------------------------------------------------- clear actions (mirror pair)
@router.post("/{list_id}/clear-results")
def clear_results(list_id: int, view: str = "all", ctx: AuthContext = Depends(get_ctx)):
    """Wipes enrichment, keeps verification."""
    lst = _get_list(ctx, list_id)
    base = ctx.db.query(EnrichLead).filter(EnrichLead.list_id == lst.id)
    n = 0
    for l in _view_filter(base, view).all():
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
def clear_verification(list_id: int, view: str = "all", ctx: AuthContext = Depends(get_ctx)):
    """Wipes free + Reoon verification (so leads re-verify), keeps enrichment;
    resets invalid/unsafe so the funnel re-runs them."""
    lst = _get_list(ctx, list_id)
    base = ctx.db.query(EnrichLead).filter(EnrichLead.list_id == lst.id)
    n = 0
    for l in _view_filter(base, view).all():
        l.free_status = ""
        l.email_status = ""
        l.verify_source = ""
        if l.status in ("invalid", "unsafe"):
            l.status = ""
        n += 1
    ctx.db.commit()
    return {"cleared": n}


# ---------------------------------------------------------------- export
@router.get("/{list_id}/export")
def export(list_id: int, view: str = "enriched", ctx: AuthContext = Depends(get_ctx)):
    import csv
    import io

    from fastapi.responses import PlainTextResponse

    lst = _get_list(ctx, list_id)
    base = ctx.db.query(EnrichLead).filter(EnrichLead.list_id == lst.id)
    rows = _view_filter(base, view).order_by(EnrichLead.id).all()
    var_names = []
    for l in rows:
        for k in (l.result or {}):
            if not k.startswith("_") and k not in var_names:
                var_names.append(k)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["first_name", "last_name", "title", "company", "website", "email",
                "system_check", "reoon", "icp", "icp_score", "industry", "status",
                "Top Competitors"] + var_names)
    for l in rows:
        comps = "; ".join(f"{c.get('name')} ({c.get('why')})" for c in (l.competitors or []) if c.get("name"))
        w.writerow([l.first_name, l.last_name, l.title, l.company, l.website, l.email,
                    l.free_status, l.email_status, l.icp_decision, l.icp_score or "",
                    l.industry, l.status, comps] + [(l.result or {}).get(v, "") for v in var_names])
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
    only_safe: bool | None = None


@router.get("/config/{workspace_id}")
def get_config(workspace_id: int, ctx: AuthContext = Depends(get_ctx)):
    ctx.require_workspace(workspace_id)
    from ..enrichment.pipeline import _config
    cfg = _config(ctx.db, workspace_id)
    ctx.db.commit()
    return {"profile": cfg.profile or {}, "icp_definition": cfg.icp_definition or "",
            "formats": cfg.formats or [], "rules": cfg.rules or "",
            "skip_title_gate": bool(cfg.skip_title_gate), "only_safe": bool(cfg.only_safe)}


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
    if body.only_safe is not None:
        cfg.only_safe = 1 if body.only_safe else 0
    ctx.db.commit()
    return {"ok": True}
