"""Job queue API: enqueue, inspect, cancel. Handlers register in app/workers."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import AuthContext, get_ctx
from ..models.jobs import Job
from ..workers.registry import HANDLERS

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class JobIn(BaseModel):
    kind: str
    workspace_id: int | None = None
    payload: dict = {}
    run_at: datetime | None = None


@router.post("")
def enqueue(body: JobIn, ctx: AuthContext = Depends(get_ctx)):
    if body.kind not in HANDLERS:
        raise HTTPException(422, f"Unknown job kind. Registered: {sorted(HANDLERS)}")
    if body.workspace_id is not None:
        ctx.require_workspace(body.workspace_id)
    j = Job(kind=body.kind, workspace_id=body.workspace_id, payload=body.payload,
            run_at=body.run_at or datetime.utcnow())
    ctx.db.add(j)
    ctx.db.commit()
    return {"id": j.id, "status": j.status}


@router.get("")
def list_jobs(status: str = "", ctx: AuthContext = Depends(get_ctx)):
    q = ctx.db.query(Job)
    if not ctx.is_master:
        q = q.filter(Job.workspace_id.in_(ctx.allowed_workspace_ids()))
    if status:
        q = q.filter(Job.status == status)
    rows = q.order_by(Job.id.desc()).limit(100).all()
    return [{"id": j.id, "kind": j.kind, "status": j.status, "run_at": j.run_at.isoformat() if j.run_at else None,
             "attempts": j.attempts, "error": j.error} for j in rows]


@router.post("/{job_id}/cancel")
def cancel(job_id: int, ctx: AuthContext = Depends(get_ctx)):
    j = ctx.db.query(Job).filter(Job.id == job_id).first()
    if not j:
        raise HTTPException(404, "Job not found")
    if j.workspace_id is not None:
        ctx.require_workspace(j.workspace_id)
    elif not ctx.is_master:
        raise HTTPException(403, "Only masters can cancel org-level jobs")
    if j.status in ("pending", "running"):
        j.status = "cancelled"
        ctx.db.commit()
    return {"id": j.id, "status": j.status}
