"""Executive digest — the daily/weekly briefing that pulls a client back in every
morning with RevCadence tied directly to hot opportunities.

Pure builders (testable, no network) + a Slack sender. Numbers are scoped to one
workspace and a rolling window (default last 24h)."""
from datetime import datetime, timedelta

import requests

_HOT_BUCKETS = ("Wants a call/meeting", "Price-based interest", "Basic interest")


def build_digest(db, workspace_id: int, hours: int = 24) -> dict:
    """Compute the last-`hours` summary for a workspace: new positive replies,
    meetings booked, pipeline generated ($), and a few named highlights."""
    from .models.crm import Deal, Stage
    from .models.reply import ReplyLead
    since = datetime.utcnow() - timedelta(hours=hours)

    replies = (db.query(ReplyLead)
               .filter(ReplyLead.workspace_id == workspace_id, ReplyLead.created_at >= since).all())
    positive = [r for r in replies if (r.intent_bucket or "") in _HOT_BUCKETS]

    new_deals = (db.query(Deal)
                 .filter(Deal.workspace_id == workspace_id, Deal.created_at >= since).all())
    booked_ids = {s.id for s in db.query(Stage).filter(Stage.workspace_id == workspace_id).all()
                  if (s.name or "").strip().lower() in ("meeting booked", "booked")}
    booked = [d for d in new_deals if d.stage_id in booked_ids]
    pipeline_generated = round(sum(d.value or 0 for d in new_deals))

    return {
        "workspace_id": workspace_id,
        "hours": hours,
        "positive_replies": len(positive),
        "meetings_booked": len(booked),
        "new_opportunities": len(new_deals),
        "pipeline_generated": pipeline_generated,
        "has_activity": bool(positive or new_deals),
        "highlights": [{
            "name": r.name or r.company or r.email,
            "company": r.company or "",
            "intent": r.intent_bucket or r.intent or "",
        } for r in positive[:5]],
    }


def digest_text(client_name: str, d: dict, app_url: str = "") -> str:
    """Plain-text briefing (Slack / email body). Leads with the money."""
    who = (client_name or "there").strip()
    when = "yesterday" if d["hours"] <= 24 else f"the last {d['hours'] // 24} days"
    if not d["has_activity"]:
        return (f"Good morning {who}! No new replies from RevCadence {when} — the engine is still "
                f"working your list. We'll flag the moment a hot lead comes in.")
    reps = d["positive_replies"]
    parts = [f"Good morning {who}! RevCadence generated {reps} new positive "
             f"repl{'y' if reps == 1 else 'ies'} {when}"]
    if d["meetings_booked"]:
        parts.append(f" and {d['meetings_booked']} booked meeting{'' if d['meetings_booked'] == 1 else 's'}")
    if d["pipeline_generated"]:
        parts.append(f" — ${d['pipeline_generated']:,} in new pipeline")
    msg = "".join(parts) + "."
    if d["highlights"]:
        names = ", ".join(h["name"] for h in d["highlights"][:3] if h["name"])
        if names:
            msg += f" Hot right now: {names}."
    if app_url:
        msg += f" View them in RevCadence: {app_url}"
    return msg


def send_slack_digest(webhook_url: str, text: str) -> bool:
    """Post the briefing to a Slack Incoming Webhook. Returns True on success."""
    if not webhook_url:
        return False
    try:
        r = requests.post(webhook_url, json={"text": text}, timeout=10)
        return r.status_code < 300
    except Exception:
        return False
