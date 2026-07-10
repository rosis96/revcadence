"""Job worker loop. Run as a second Railway service with the same DATABASE_URL:
    python -m app.workers.runner
Claims one due job at a time (SELECT ... FOR UPDATE SKIP LOCKED on Postgres),
runs its handler, retries failures up to max_attempts."""
import time
import traceback
from datetime import datetime

from sqlalchemy import text

from .. import config
from ..db import SessionLocal, engine, init_db
from ..models.jobs import Job
from .registry import HANDLERS


def _claim(db):
    q = db.query(Job).filter(Job.status == "pending", Job.run_at <= datetime.utcnow()).order_by(Job.id)
    if engine.dialect.name == "postgresql":
        q = q.with_for_update(skip_locked=True)
    job = q.first()
    if job:
        job.status = "running"
        job.started_at = datetime.utcnow()
        job.attempts += 1
        db.commit()
    return job


def run_one(db, job) -> None:
    handler = HANDLERS.get(job.kind)
    try:
        if handler is None:
            raise RuntimeError(f"No handler registered for kind '{job.kind}'")
        result = handler(db, job) or {}
        job.status = "done"
        job.result = result
        job.error = ""
    except Exception:
        err = traceback.format_exc()[-2000:]
        job.error = err
        job.status = "pending" if job.attempts < job.max_attempts else "failed"
        if job.status == "pending":
            job.run_at = datetime.utcnow()  # simple immediate retry; add backoff later
    finally:
        job.finished_at = datetime.utcnow()
        db.commit()


def main():
    init_db()
    print(f"[worker] started · db={engine.dialect.name} · handlers={sorted(HANDLERS)}")
    while True:
        db = SessionLocal()
        try:
            job = _claim(db)
            if job:
                print(f"[worker] running job {job.id} kind={job.kind} attempt={job.attempts}")
                run_one(db, job)
                print(f"[worker] job {job.id} → {job.status}")
                continue  # look for the next job immediately
        finally:
            db.close()
        time.sleep(config.WORKER_POLL_SECONDS)


if __name__ == "__main__":
    main()
