"""Job worker loop. Run as a second Railway service with the same DATABASE_URL:
    python -m app.workers.runner
Claims one due job at a time (SELECT ... FOR UPDATE SKIP LOCKED on Postgres),
runs its handler, retries failures up to max_attempts."""
import os
import socket
import time
import traceback
from datetime import datetime, timedelta

from sqlalchemy import text

from .. import config
from ..db import SessionLocal, engine, init_db
from ..models.jobs import Heartbeat, Job
from .registry import HANDLERS


def beat(db):
    """Upsert the worker heartbeat row — /healthz reads this."""
    info = {"db": engine.dialect.name, "handlers": sorted(HANDLERS),
            "pid": os.getpid(), "host": socket.gethostname()}
    hb = db.get(Heartbeat, "worker")
    if hb is None:
        hb = Heartbeat(name="worker")
        db.add(hb)
    hb.at = datetime.utcnow()
    hb.info = info
    db.commit()


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
        if job.status != "cancelled":   # handlers may honor a mid-run Stop
            job.status = "done"
        job.result = result
        job.error = ""
    except Exception:
        db.rollback()  # discard any partial writes from the failed handler
        err = traceback.format_exc()[-2000:]
        job.error = err
        job.status = "pending" if job.attempts < job.max_attempts else "failed"
        if job.status == "pending":
            # exponential-ish backoff: 30s, 60s, 120s...
            job.run_at = datetime.utcnow() + timedelta(seconds=30 * (2 ** (job.attempts - 1)))
    finally:
        job.finished_at = datetime.utcnow()
        db.commit()


_MAILBOX_POLL_SECONDS = int(os.getenv("MAILBOX_POLL_SECONDS", "120"))
_FOLLOWUP_TICK_SECONDS = int(os.getenv("FOLLOWUP_TICK_SECONDS", "300"))


def run_followups(db):
    """Fire any autonomous follow-ups that are due (opt-in, capped, reply-cancelled)."""
    from ..mailbox import service
    try:
        r = service.run_due_followups(db)
        if r.get("sent"):
            print(f"[worker] autopilot follow-ups sent: {r['sent']} (skipped {r.get('skipped', 0)})")
    except Exception as e:  # noqa: BLE001
        print(f"[worker] follow-up runner error: {e}")


def poll_mailboxes(db):
    """Every connected mailbox: fetch new replies and land them into the right Deal
    Conversation (which cancels that deal's scheduled follow-ups). Best-effort."""
    from ..mailbox import service
    from ..models.onboarding import MailboxConnection
    boxes = (db.query(MailboxConnection)
             .filter(MailboxConnection.active == True, MailboxConnection.status == "connected")  # noqa: E712
             .all())
    for b in boxes:
        try:
            service.poll_and_sync(db, b.workspace_id)
        except Exception as e:  # noqa: BLE001
            print(f"[worker] mailbox poll error ws={b.workspace_id}: {e}")


_DIGEST_HOUR_UTC = int(os.getenv("DIGEST_HOUR_UTC", "13"))   # ~morning US


def send_daily_digests(db):
    """Once a day: post each opted-in workspace its executive briefing to Slack."""
    from ..digest import build_digest, digest_text, send_slack_digest
    from ..models.identity import Workspace
    for w in db.query(Workspace).all():
        s = w.settings or {}
        if not (s.get("digest_enabled") and s.get("slack_webhook")):
            continue
        try:
            d = build_digest(db, w.id, hours=24)
            text = digest_text(s.get("digest_client_name") or w.name, d, os.getenv("PUBLIC_BASE_URL", ""))
            send_slack_digest(s["slack_webhook"], text)
        except Exception as e:  # noqa: BLE001
            print(f"[worker] digest error ws={w.id}: {e}")


def main():
    init_db()
    print(f"[worker] started · db={engine.dialect.name} · handlers={sorted(HANDLERS)}")
    if engine.dialect.name == "sqlite":
        print("[worker] *** WARNING: running on SQLITE — on Railway this means "
              "DATABASE_URL is NOT set on this service, and the worker is polling "
              "a private throwaway DB instead of the shared Postgres. Jobs queued "
              "by the web service will NEVER be seen. Fix the service variables. ***")
    last_mailbox_poll = 0.0
    last_followup_tick = 0.0
    last_digest_date = None
    while True:
        db = SessionLocal()
        try:
            beat(db)
            if time.time() - last_mailbox_poll >= _MAILBOX_POLL_SECONDS:
                poll_mailboxes(db)
                last_mailbox_poll = time.time()
            if time.time() - last_followup_tick >= _FOLLOWUP_TICK_SECONDS:
                run_followups(db)
                last_followup_tick = time.time()
            _now = datetime.utcnow()
            if _now.hour >= _DIGEST_HOUR_UTC and last_digest_date != _now.date():
                send_daily_digests(db)
                last_digest_date = _now.date()
            job = _claim(db)
            if job:
                print(f"[worker] running job {job.id} kind={job.kind} attempt={job.attempts}")
                run_one(db, job)
                print(f"[worker] job {job.id} → {job.status}")
                continue  # look for the next job immediately
        except Exception as e:
            print(f"[worker] loop error (continuing): {e}")
        finally:
            db.close()
        time.sleep(config.WORKER_POLL_SECONDS)


if __name__ == "__main__":
    main()
