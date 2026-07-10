"""Pipeline-kind registry (the pattern from the Intelligence Workspace schema):
new capabilities are registered handlers, never architecture changes.

A handler is `def handler(db, job) -> dict` — the returned dict is stored in
job.result. Raise to fail the job (it retries up to max_attempts)."""

HANDLERS: dict = {}


def register(kind: str):
    def deco(fn):
        HANDLERS[kind] = fn
        return fn
    return deco


# ---------------------------------------------------------------- built-ins
@register("noop")
def noop(db, job):
    """Health-check job used by tests and the deploy checklist."""
    return {"ok": True, "echo": job.payload}


@register("import_legacy_leads")
def import_legacy_leads(db, job):
    """Wraps scripts/import_legacy.py so a migration can be run as a queued job
    from the API. payload: {"legacy_db_url": "...", "dry_run": true}"""
    from scripts.import_legacy import run_import
    return run_import(job.payload.get("legacy_db_url", ""), dry_run=bool(job.payload.get("dry_run", True)))

# Future handlers land here, one decorator each:
#   @register("enrich_contact")     — run.py pipeline against a Contact
#   @register("same_day_nudge")     — handoff doc §12
#   @register("proposal_follow_up") — unopened-proposal reminder
