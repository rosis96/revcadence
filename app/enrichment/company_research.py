"""Company Research API client — the primary website crawler when configured.

Config lives in AppSetting (Settings -> Integrations) so an external provider can
be plugged in without a deploy. Returns a dict shaped exactly like
``crawler.crawl_site`` so it is a drop-in at the single call site in pipeline.py;
returns ``None`` when the provider is disabled/unconfigured or the request fails,
so the caller falls back to the in-house crawler.
"""
from __future__ import annotations

import time

import requests

from ..crypto import decrypt
from ..db import SessionLocal

_CACHE = {"at": 0.0, "cfg": None}
_CFG_TTL = 60.0  # re-read settings at most once a minute


def _config() -> dict:
    now = time.time()
    if _CACHE["cfg"] is not None and now - _CACHE["at"] < _CFG_TTL:
        return _CACHE["cfg"]
    cfg = {"enabled": False, "base_url": "", "api_key": ""}
    try:
        from ..models.settings import AppSetting
        db = SessionLocal()
        try:
            rows = {s.key: s for s in db.query(AppSetting).filter(AppSetting.key.like("research.%")).all()}
        finally:
            db.close()
        base = (rows["research.base_url"].value if rows.get("research.base_url") else "").strip().rstrip("/")
        enabled = (rows["research.enabled"].value if rows.get("research.enabled") else "0") == "1"
        key_row = rows.get("research.api_key")
        key = decrypt(key_row.value) if (key_row and key_row.value) else ""
        cfg = {"enabled": bool(enabled and base and key), "base_url": base, "api_key": key}
    except Exception:
        cfg = {"enabled": False, "base_url": "", "api_key": ""}
    _CACHE["cfg"] = cfg
    _CACHE["at"] = now
    return cfg


def is_enabled() -> bool:
    return _config()["enabled"]


def _to_crawl_shape(website: str, data: dict) -> dict:
    """Map the API response onto the crawl_site contract the pipeline expects."""
    pages = data.get("pages") or []
    records, parts = [], []
    for p in pages:
        url = p.get("url") or ""
        # The API names the page body "content" for every output_format —
        # output_format changes the ENCODING of that string (text / markdown /
        # html), never the key. Reading "markdown"/"text" here made every page
        # come back empty, which made every response look like a failed crawl,
        # which silently fell the whole pipeline back to the in-house crawler.
        text = p.get("content") or p.get("markdown") or p.get("text") or ""
        if not text:
            continue
        records.append({"url": url, "text": text})
        parts.append(f"# SOURCE: {url}\n{text}")
    text = "\n\n".join(parts)
    site = data.get("site") or {}
    # site.signals only. Falling back to `organization` here used to hand the
    # caller a completely different shape under the same key, which any
    # signal consumer would silently read as "no signals".
    signals = site.get("signals") or {}
    status = data.get("status")
    return {
        "url": site.get("final_url") or site.get("requested_url") or website,
        "text": text,
        "page_records": records,
        "image_candidates": [],
        "diagnostics": {"source": "company_research_api", "status": status},
        "signals": signals,
        "error": None if (status != "failed" and text) else (data.get("status_reason") or "research failed"),
    }


def research_site(website: str, deep: bool = False, timeout: float = 45.0) -> dict | None:
    if not website:
        return None
    cfg = _config()
    if not cfg["enabled"]:
        return None
    try:
        r = requests.post(
            f"{cfg['base_url']}/v1/research",
            headers={"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"},
            json={
                "url": website,
                "output_format": "markdown",
                "include_signals": True,
                "research_depth": "deep" if deep else "standard",
            },
            timeout=timeout,
        )
        if r.status_code != 200:
            return None
        return _to_crawl_shape(website, r.json())
    except Exception:
        return None
