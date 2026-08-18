"""Read the LIVE outbound ladder back out of Instantly / Bison.

Why this exists: the client-facing sequence screen must show what the prospect
will actually receive, and we are not the ones sending. Anything rendered from
our own tables is a claim; anything rendered from here is the truth. If an
operator adds a fifth step directly in Instantly, this is what notices.

Read-only by construction. Nothing in this module writes to a platform, which is
the whole point of it, and the reason it can be pointed at a client's own account
without asking them to trust us with more than a read.

--------------------------------------------------------------------------------
CORRECTING THE FIELD MAPPING
--------------------------------------------------------------------------------
Vendor response shapes are not pinned down in this codebase yet, so every read
goes through `_pick()` against a candidate list in `FIELDS` below. That makes a
wrong guess a one-line edit in ONE dict instead of a hunt through parsing code.

When a real payload is available:
  1. Call `fetch(...)` - the vendor JSON comes back under "raw" and is persisted
     on CampaignSnapshot.raw.
  2. Compare it against `FIELDS` and correct the candidate lists.
  3. Nothing else in this module, the router, or the UI needs to change.

Until then the normalizer degrades honestly: a field it cannot find comes back
empty/zero rather than raising, and `normalize()` reports what it could not map
in `_unmapped`, so a half-working mapping is visible instead of silent.
"""
import re

import requests

INSTANTLY_BASE = "https://api.instantly.ai/api/v2"
TIMEOUT = 30
VARIANT_LABELS = "ABCDEFG"


# ---------------------------------------------------------------- field candidates
# normalized name -> key names to try, in order of preference. Dotted paths are
# nested. Correct these against a real payload; nothing else moves.
FIELDS = {
    "campaign_id":     ["id", "campaign_id", "uuid"],
    "campaign_name":   ["name", "campaign_name", "title"],
    "campaign_status": ["status", "state", "campaign_status"],
    # the container holding the ladder
    "sequences":       ["sequences", "sequence", "campaign_schedule.sequences"],
    "steps":           ["steps", "sequence_steps", "emails"],
    # per step
    "step_delay":      ["delay", "wait_days", "days", "delay_days", "waitDays"],
    "step_type":       ["type", "step_type"],
    "variants":        ["variants", "versions", "bodies"],
    # per variant
    "subject":         ["subject", "subject_line", "title"],
    "body":            ["body", "content", "html", "email_body", "text"],
    "variant_label":   ["label", "variant", "name"],
    "variant_on":      ["enabled", "active", "is_active"],
    # analytics (campaign or step level)
    "sent":            ["sent", "emails_sent", "sent_count", "total_sent"],
    "replies":         ["replies", "reply_count", "total_replies", "replied"],
    "opportunities":   ["opportunities", "leads_interested", "interested", "positive"],
}

# Platforms disagree on both spelling and numbering (Instantly has historically
# used integer status codes), so map both onto one vocabulary.
STATUS_MAP = {
    "0": "draft", "1": "live", "2": "paused", "3": "completed", "4": "paused",
    "active": "live", "running": "live", "started": "live", "live": "live",
    "paused": "paused", "pause": "paused", "stopped": "paused",
    "draft": "draft", "new": "draft",
    "completed": "completed", "complete": "completed", "finished": "completed",
}


# ---------------------------------------------------------------- tolerant readers
def _pick(obj, field: str, default=None):
    """Read `field` from `obj` by trying every candidate key in FIELDS[field].
    Supports dotted paths. Returns `default` when nothing matches - never raises."""
    if not isinstance(obj, dict):
        return default
    for key in FIELDS.get(field, [field]):
        cur, ok = obj, True
        for part in key.split("."):
            if isinstance(cur, dict) and part in cur and cur[part] is not None:
                cur = cur[part]
            else:
                ok = False
                break
        if ok:
            return cur
    return default


def _int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _rate(part: int, whole: int) -> float:
    return round((part / whole) * 100, 1) if whole else 0.0


def _status(value) -> str:
    return STATUS_MAP.get(str(value if value is not None else "").strip().lower(), "draft")


_TAG_RE = re.compile(r"<\s*/?\s*[a-z][^>]*>", re.I)
_BR_RE = re.compile(r"<\s*br\s*/?\s*>|</\s*p\s*>", re.I)


def to_text(value) -> str:
    """Platform bodies arrive as HTML. The client screen renders plain text with
    the placeholder tokens intact, so strip tags but keep {{tokens}} and breaks."""
    import html as _html
    if not value:
        return ""
    out = _BR_RE.sub("\n", str(value))
    out = _TAG_RE.sub("", out)
    out = _html.unescape(out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


# ---------------------------------------------------------------- normalizer
def normalize(raw: dict, platform: str) -> dict:
    """Vendor campaign JSON -> the one shape the API and UI speak.

    {external_id, name, status, platform,
     steps: [{position, wait_days, day_offset,
              variants: [{label, subject, body, enabled, sent, replies, reply_rate}]}],
     stats: {sent, replies, reply_rate, opportunities},
     _unmapped: [...]}
    """
    raw = raw if isinstance(raw, dict) else {}
    unmapped = []

    # Some responses wrap the campaign one level down.
    body = raw
    for wrapper in ("data", "campaign", "result"):
        if isinstance(body.get(wrapper), dict):
            body = body[wrapper]
            break

    # The ladder may be a list of sequences (each with steps) or steps directly.
    steps_raw = []
    seqs = _pick(body, "sequences")
    if isinstance(seqs, list):
        for seq in seqs:
            found = _pick(seq, "steps") if isinstance(seq, dict) else None
            if isinstance(found, list):
                steps_raw.extend(found)
    if not steps_raw:
        found = _pick(body, "steps")
        if isinstance(found, list):
            steps_raw = found
    if not steps_raw:
        unmapped.append("steps")

    steps, day_offset = [], 0
    for index, step in enumerate(steps_raw):
        if not isinstance(step, dict):
            continue
        # Step 1 always sends on day 0 regardless of what the platform stores as
        # its delay - a leading delay is a campaign start offset, not a wait.
        wait = 0 if index == 0 else max(0, _int(_pick(step, "step_delay"), 0))
        day_offset += wait

        variants_raw = _pick(step, "variants")
        if not isinstance(variants_raw, list) or not variants_raw:
            variants_raw = [step]          # single-variant step: the step IS the email

        variants = []
        for vi, var in enumerate(variants_raw):
            if not isinstance(var, dict):
                continue
            sent = _int(_pick(var, "sent"))
            replies = _int(_pick(var, "replies"))
            enabled = _pick(var, "variant_on")
            label = str(_pick(var, "variant_label") or "").strip()
            variants.append({
                "label": (label[:1].upper() if label[:1].isalpha()
                          else VARIANT_LABELS[vi % len(VARIANT_LABELS)]),
                "subject": to_text(_pick(var, "subject", "")),
                "body": to_text(_pick(var, "body", "")),
                "enabled": True if enabled is None else bool(enabled),
                "sent": sent,
                "replies": replies,
                "reply_rate": _rate(replies, sent),
            })

        steps.append({
            "position": index + 1,
            "wait_days": wait,
            "day_offset": day_offset,
            "variants": variants,
        })

    sent = _int(_pick(body, "sent"))
    replies = _int(_pick(body, "replies"))
    # Fall back to summing the steps when the campaign object carries no totals.
    if not sent:
        sent = sum(v["sent"] for s in steps for v in s["variants"])
    if not replies:
        replies = sum(v["replies"] for s in steps for v in s["variants"])

    name = _pick(body, "campaign_name", "")
    if not name:
        unmapped.append("campaign_name")

    return {
        "external_id": str(_pick(body, "campaign_id", "") or ""),
        "name": str(name or "Untitled campaign"),
        "status": _status(_pick(body, "campaign_status")),
        "platform": platform,
        "steps": steps,
        "stats": {
            "sent": sent,
            "replies": replies,
            "reply_rate": _rate(replies, sent),
            "opportunities": _int(_pick(body, "opportunities")),
        },
        "_unmapped": unmapped,
    }


# ---------------------------------------------------------------- platform fetch
def _get(url: str, headers: dict, params: dict = None) -> tuple:
    """(json, error). Never raises - a third-party outage must degrade the page's
    freshness and nothing else."""
    try:
        r = requests.get(url, headers=headers, params=params or {}, timeout=TIMEOUT)
        if r.status_code >= 400:
            return None, f"HTTP {r.status_code}: {(r.text or '')[:200]}"
        return r.json(), ""
    except Exception as e:  # noqa: BLE001
        return None, str(e)[:200]


def _as_list(payload) -> list:
    """Vendor list endpoints wrap their items differently ({items}, {data}, [...])."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("items", "data", "campaigns", "results"):
            if isinstance(payload.get(key), list):
                return payload[key]
    return []


def list_campaigns(platform: str, api_key: str, base_url: str = "") -> tuple:
    """(campaigns, error) - id + name only, enough to choose what to snapshot."""
    if not api_key:
        return [], "no API key on this reply space"
    headers = {"Authorization": f"Bearer {api_key}"}
    if platform == "bison":
        if not base_url:
            return [], "no Bison base URL on this reply space"
        data, err = _get(f"{base_url.rstrip('/')}/api/campaigns", headers)
    else:
        data, err = _get(f"{INSTANTLY_BASE}/campaigns", headers, {"limit": 100})
    if err:
        return [], err
    out = []
    for row in _as_list(data):
        if not isinstance(row, dict):
            continue
        cid = str(_pick(row, "campaign_id", "") or "")
        if cid:
            out.append({"external_id": cid,
                        "name": str(_pick(row, "campaign_name", "") or "Untitled campaign"),
                        "status": _status(_pick(row, "campaign_status"))})
    return out, ""


def fetch(platform: str, api_key: str, campaign_id: str, base_url: str = "") -> dict:
    """One campaign, normalized. Returns {ok, campaign, raw, error}.

    Analytics live on a separate endpoint on both platforms, so they are fetched
    alongside and merged in. A campaign with no stats still renders: the ladder is
    the point of the screen and the numbers are decoration.
    """
    if not api_key:
        return {"ok": False, "error": "no API key on this reply space", "raw": {}}
    if not campaign_id:
        return {"ok": False, "error": "no campaign id", "raw": {}}
    headers = {"Authorization": f"Bearer {api_key}"}

    if platform == "bison":
        if not base_url:
            return {"ok": False, "error": "no Bison base URL on this reply space", "raw": {}}
        root = base_url.rstrip("/")
        raw, err = _get(f"{root}/api/campaigns/{campaign_id}", headers)
        stats, _ = _get(f"{root}/api/campaigns/{campaign_id}/stats", headers)
    else:
        raw, err = _get(f"{INSTANTLY_BASE}/campaigns/{campaign_id}", headers)
        stats, _ = _get(f"{INSTANTLY_BASE}/campaigns/analytics", headers,
                        {"campaign_id": campaign_id})

    if err:
        return {"ok": False, "error": err, "raw": {}}
    if not isinstance(raw, dict):
        return {"ok": False, "error": "campaign response was not an object", "raw": {}}

    merged = dict(raw)
    # Analytics endpoints return either the object or a one-item list for the
    # campaign asked about; both mean the same thing here.
    block = stats
    if isinstance(block, list):
        block = block[0] if block else None
    if isinstance(block, dict):
        for key in ("sent", "replies", "opportunities"):
            for candidate in FIELDS[key]:
                if candidate in block:
                    merged.setdefault(candidate, block[candidate])
                    break

    campaign = normalize(merged, platform)
    if not campaign["external_id"]:
        campaign["external_id"] = str(campaign_id)
    return {"ok": True, "campaign": campaign, "raw": raw, "error": ""}


# ================================================================ persistence
# Everything above is pure and testable without a database. Below is the thin
# layer that stores what was fetched, so the client screen never blocks on a
# third-party call and a platform outage costs freshness, not availability.
def _campaign_ids(rws) -> list:
    """Which campaigns this reply space mirrors.

    Preference order:
      1. `mirror_campaign_ids` on the space - an explicit operator choice.
      2. `reply_followup_campaign_id` - the one id the space already stores.
      3. Everything the API lists, capped, so a space with neither set still
         shows something rather than an empty screen.
    """
    explicit = [str(c).strip() for c in (getattr(rws, "mirror_campaign_ids", None) or []) if str(c).strip()]
    if explicit:
        return explicit
    single = str(getattr(rws, "reply_followup_campaign_id", "") or "").strip()
    return [single] if single else []


def snapshot_workspace(db, rws, *, limit: int = 25) -> dict:
    """Refresh every mirrored campaign for one reply space. Returns a summary.

    Failures are recorded on the row rather than raised: a snapshot that is stale
    and says so is more useful to a client than a page that will not load.
    """
    from datetime import datetime

    from ..crypto import decrypt
    from ..models.campaigns import CampaignSnapshot

    api_key = decrypt(rws.api_key_enc) if rws.api_key_enc else ""
    platform = rws.platform or "instantly"
    base_url = rws.base_url or ""
    if not api_key:
        return {"ok": False, "error": "no API key on this reply space", "refreshed": 0}

    ids = _campaign_ids(rws)
    listed_names = {}
    if not ids:
        listed, err = list_campaigns(platform, api_key, base_url)
        if err and not listed:
            return {"ok": False, "error": err, "refreshed": 0}
        ids = [c["external_id"] for c in listed][:limit]
        listed_names = {c["external_id"]: c["name"] for c in listed}

    refreshed, failed = 0, []
    for cid in ids[:limit]:
        row = (db.query(CampaignSnapshot)
               .filter(CampaignSnapshot.reply_workspace_id == rws.id,
                       CampaignSnapshot.external_id == str(cid)).first())
        if row is None:
            row = CampaignSnapshot(workspace_id=rws.workspace_id, reply_workspace_id=rws.id,
                                   external_id=str(cid), platform=platform)
            db.add(row)
        res = fetch(platform, api_key, str(cid), base_url)
        row.fetched_at = datetime.utcnow()
        row.platform = platform
        if res.get("ok"):
            campaign = res["campaign"]
            row.payload = campaign
            row.raw = res.get("raw") or {}
            row.name = campaign["name"] if campaign["name"] != "Untitled campaign" else (
                listed_names.get(str(cid)) or campaign["name"])
            row.status = campaign["status"]
            row.fetch_status = "ok"
            row.fetch_error = ""
            refreshed += 1
        else:
            row.fetch_status = "error"
            row.fetch_error = str(res.get("error", ""))[:500]
            failed.append(str(cid))
    db.commit()
    return {"ok": True, "refreshed": refreshed, "failed": failed, "total": len(ids)}


def snapshots_for(db, rws) -> list:
    """Stored snapshots for one reply space, newest-fetched first."""
    from ..models.campaigns import CampaignSnapshot
    rows = (db.query(CampaignSnapshot)
            .filter(CampaignSnapshot.reply_workspace_id == rws.id)
            .order_by(CampaignSnapshot.fetched_at.desc().nullslast()).all())
    return [{
        "id": r.id,
        "external_id": r.external_id,
        "name": r.name or "Untitled campaign",
        "status": r.status or "draft",
        "platform": r.platform or "",
        "steps": (r.payload or {}).get("steps", []),
        "stats": (r.payload or {}).get("stats", {}),
        "unmapped": (r.payload or {}).get("_unmapped", []),
        "fetch_status": r.fetch_status or "ok",
        "fetch_error": r.fetch_error or "",
        "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None,
    } for r in rows]
