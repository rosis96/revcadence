"""Calendly scheduling — port of the legacy reply-manager Calendly logic.

Proposes meeting times that are (a) actually open on the client's calendar,
(b) in the PROSPECT's timezone, (c) within business hours, and (d) NEVER the
same slot pitched to two prospects (proposed_slots reservation).

Read-only on Calendly (needs event_types:read + availability:read; never
:write — the prospect books themselves via the link). Every failure path
degrades gracefully to "" so the reply is generated exactly as before.
"""
from datetime import datetime, timedelta, timezone

import requests

from ..crypto import decrypt

API = "https://api.calendly.com"

# US state → IANA timezone (most-populous zone per state). Fallback: Eastern.
_US_TZ = {
    "CA": "America/Los_Angeles", "WA": "America/Los_Angeles", "OR": "America/Los_Angeles",
    "NV": "America/Los_Angeles", "AZ": "America/Phoenix", "CO": "America/Denver",
    "UT": "America/Denver", "NM": "America/Denver", "MT": "America/Denver",
    "TX": "America/Chicago", "IL": "America/Chicago", "MN": "America/Chicago",
    "MO": "America/Chicago", "WI": "America/Chicago", "LA": "America/Chicago",
    "TN": "America/Chicago", "OK": "America/Chicago", "IA": "America/Chicago",
    "NY": "America/New_York", "NJ": "America/New_York", "MA": "America/New_York",
    "PA": "America/New_York", "FL": "America/New_York", "GA": "America/New_York",
    "NC": "America/New_York", "VA": "America/New_York", "OH": "America/New_York",
    "MI": "America/New_York", "CT": "America/New_York", "MD": "America/New_York",
}
_COUNTRY_TZ = {
    "united kingdom": "Europe/London", "uk": "Europe/London", "england": "Europe/London",
    "ireland": "Europe/Dublin", "germany": "Europe/Berlin", "france": "Europe/Paris",
    "spain": "Europe/Madrid", "netherlands": "Europe/Amsterdam", "india": "Asia/Kolkata",
    "australia": "Australia/Sydney", "singapore": "Asia/Singapore", "canada": "America/Toronto",
    "uae": "Asia/Dubai", "united arab emirates": "Asia/Dubai",
}


def timezone_from_location(location: str, default="America/New_York") -> str:
    loc = (location or "").strip()
    if not loc:
        return default
    low = loc.lower()
    for country, tz in _COUNTRY_TZ.items():
        if country in low:
            return tz
    # look for a 2-letter US state token
    for token in loc.replace(",", " ").split():
        t = token.strip().upper()
        if t in _US_TZ:
            return _US_TZ[t]
    return default


def _headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _list_event_types(token: str) -> tuple[list, dict]:
    """All event types the token can see, with diagnostics. Event types can be
    owned by the USER or by the ORGANIZATION; a token created by one member may
    only surface org-owned ones under the organization filter — so we try user
    first, then organization, then include inactive as a last resort."""
    meta = {"user_name": "", "user_link": "", "counts": {}}
    me = requests.get(f"{API}/users/me", headers=_headers(token), timeout=20)
    if me.status_code != 200:
        meta["error"] = f"users/me returned {me.status_code}"
        meta["status"] = me.status_code
        return [], meta
    res = me.json().get("resource", {})
    user_uri = res.get("uri")
    org_uri = res.get("current_organization")
    meta["user_name"] = res.get("name", "")
    meta["user_link"] = res.get("scheduling_url", "")

    def fetch(params):
        try:
            r = requests.get(f"{API}/event_types", headers=_headers(token), params=params, timeout=20)
            return r.json().get("collection", []) if r.status_code == 200 else []
        except Exception:
            return []

    types = fetch({"user": user_uri, "active": "true"})
    meta["counts"]["user_active"] = len(types)
    if not types and org_uri:
        types = fetch({"organization": org_uri, "active": "true"})
        meta["counts"]["org_active"] = len(types)
    if not types:                      # last resort — include inactive
        types = fetch({"user": user_uri}) or (fetch({"organization": org_uri}) if org_uri else [])
        meta["counts"]["any"] = len(types)
    return types, meta


def resolve_event_type(token: str, scheduling_url: str = "") -> dict:
    """→ {uri, scheduling_url, slug} or {} on failure."""
    try:
        types, _ = _list_event_types(token)
        if not types:
            return {}
        # prefer active event types once we've fallen back to include inactive
        pool = [t for t in types if t.get("active", True)] or types
        slug = (scheduling_url or "").rstrip("/").split("/")[-1].lower()
        for t in pool:
            if slug and slug in (t.get("scheduling_url", "").lower()):
                return {"uri": t["uri"], "scheduling_url": t["scheduling_url"], "slug": slug}
        t = pool[0]
        return {"uri": t["uri"], "scheduling_url": t["scheduling_url"], "slug": t.get("slug", "")}
    except Exception:
        return {}


def get_calendly_slots(token: str, scheduling_url: str, prospect_tz: str,
                       count: int = 3, exclude_utc=None) -> list:
    """Real open times in the prospect's timezone, business-hours, one per day,
    excluding already-reserved UTC keys. Returns [{"utc","label"}]."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(prospect_tz)
    except Exception:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/New_York")
    exclude = set(exclude_utc or [])
    et = resolve_event_type(token, scheduling_url)
    if not et:
        return []
    # Calendly caps the window at 7 days; start 2 days out.
    start = datetime.now(timezone.utc) + timedelta(days=2)
    end = start + timedelta(days=6, hours=23)
    try:
        r = requests.get(f"{API}/event_type_available_times", headers=_headers(token),
                         params={"event_type": et["uri"],
                                 "start_time": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                 "end_time": end.strftime("%Y-%m-%dT%H:%M:%SZ")}, timeout=25)
        times = r.json().get("collection", [])
    except Exception:
        return []

    def pick(window):
        out, used_days = [], set()
        for slot in times:
            iso = slot.get("start_time")
            if not iso or iso in exclude:
                continue
            try:
                dt_utc = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            except Exception:
                continue
            local = dt_utc.astimezone(tz)
            if local.weekday() >= 5:            # weekdays only
                continue
            if not (window[0] <= local.hour < window[1]):
                continue
            day = local.date()
            if day in used_days:                # one per distinct day
                continue
            used_days.add(day)
            out.append({"utc": iso,
                        "label": local.strftime("%A, %b %d at %-I:%M %p %Z")})
            if len(out) >= count:
                break
        return out

    slots = pick((10, 14))                       # prefer 10 AM–2 PM local
    if len(slots) < count:
        slots = pick((9, 17)) or slots           # relax to 9–5 if sparse
    return slots[:count]


def build_scheduling_context(db, rws, location: str, prospect_key: str = "",
                             mode: str = "reply") -> str:
    """Reserve real open times for this prospect and return a prompt block telling
    the AI to propose ONLY those. Follow-up mode asks for more, distinct times.
    Returns "" (graceful) when there's no token / no slots / any error."""
    token = decrypt(rws.calendly_token_enc)
    if not token or not rws.calendly_scheduling_url:
        return ""
    from ..models.reply import ProposedSlot
    # prune past reservations + collect still-reserved UTC keys for this workspace
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    db.query(ProposedSlot).filter(ProposedSlot.workspace_id == rws.workspace_id,
                                  ProposedSlot.slot_utc < now_iso).delete(synchronize_session=False)
    reserved = {r[0] for r in db.query(ProposedSlot.slot_utc)
                .filter(ProposedSlot.workspace_id == rws.workspace_id).all()}
    tz = timezone_from_location(location)
    count = 6 if mode == "followup" else 3
    slots = get_calendly_slots(token, rws.calendly_scheduling_url, tz, count=count, exclude_utc=reserved)
    if not slots:  # everything reserved → fall back to the open pool (slight overlap beats nothing)
        slots = get_calendly_slots(token, rws.calendly_scheduling_url, tz, count=count)
    if not slots:
        return ""
    for s in slots:
        db.add(ProposedSlot(workspace_id=rws.workspace_id, reply_workspace=rws.name,
                            prospect=prospect_key or "", slot_utc=s["utc"], label=s["label"]))
    db.flush()
    lines = "\n".join(f"- {s['label']}" for s in slots)
    extra = (" Use a DIFFERENT real time in each follow-up." if mode == "followup" else "")
    return (f"Propose ONLY these real open times (prospect timezone {tz}), and include the "
            f"booking link {rws.calendly_scheduling_url}.{extra}\n{lines}")


def probe(rws) -> dict:
    """Diagnostic: does the token work, what event type, how many raw slots.
    Powers the 'Check Calendly availability' button."""
    token = decrypt(rws.calendly_token_enc)
    if not token:
        return {"ok": False, "error": "No Calendly token set on this reply space."}
    if not rws.calendly_scheduling_url:
        return {"ok": False, "error": "No Calendly scheduling link set."}
    types, meta = _list_event_types(token)
    if meta.get("error"):
        st = meta.get("status")
        if st == 403:
            msg = ("Calendly returned 403 on this token. A Personal Access Token has full access by "
                   "default, so a 403 almost always means the Calendly account's PLAN doesn't include "
                   "API access — Calendly's v2 API requires a paid plan (Standard or higher). Confirm "
                   "the account is on a paid plan, then create a fresh Personal Access Token at "
                   "calendly.com/integrations/api_webhooks and paste it here. (Calendly is optional — "
                   "without it, replies simply invite the prospect to book via your scheduling link.)")
        elif st == 401:
            msg = ("Calendly returned 401 — the token is invalid or expired. Create a fresh Personal "
                   "Access Token at calendly.com/integrations/api_webhooks and paste it here (no "
                   "'Bearer ' prefix, no extra spaces). Calendly is optional — without it, replies "
                   "invite the prospect to book via your scheduling link.")
        else:
            msg = (f"Calendly rejected the token ({meta['error']}). Create a fresh Personal Access Token "
                   "at calendly.com/integrations/api_webhooks and paste it here. Calendly is optional — "
                   "without it, replies invite the prospect to book via your scheduling link.")
        return {"ok": False, "error": msg}
    if not types:
        who = meta.get("user_name") or "this token"
        link = meta.get("user_link")
        hint = (f" The token belongs to {who}"
                + (f" whose own booking link is {link}." if link else ".")
                + " Make sure the scheduling link above is an ACTIVE event type owned by that same account,"
                  " or create the token from the account that owns the link.")
        return {"ok": False, "error": "Token works, but Calendly returned no event types for it." + hint}
    et = resolve_event_type(token, rws.calendly_scheduling_url)
    if not et:
        return {"ok": False, "error": "Token works but no active event type matched the scheduling link (check the link)."}
    slots = get_calendly_slots(token, rws.calendly_scheduling_url, "America/New_York", count=3)
    return {"ok": True, "event_type_slug": et.get("slug"), "token_user": meta.get("user_name"),
            "event_types_found": len(types),
            "sample_slots": [s["label"] for s in slots],
            "note": "Reads only — the system never books; the prospect books via the link."}
