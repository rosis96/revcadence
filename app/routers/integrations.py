"""Settings -> Integrations: pluggable external providers.

First provider is the Company Research API (primary website crawler for
enrichment). Config is stored in AppSetting so it can be changed without a
deploy; the API key is encrypted at rest and never returned to the client.
"""
import requests
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import AuthContext, get_ctx
from ..crypto import decrypt, encrypt
from ..models.settings import AppSetting

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


def _set(db, key, value, secret=False):
    row = db.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, is_secret=1 if secret else 0)
        db.add(row)
    row.value = encrypt(value) if secret else value
    row.is_secret = 1 if secret else 0


@router.get("/research")
def get_research(ctx: AuthContext = Depends(get_ctx)):
    db = ctx.db
    base = db.get(AppSetting, "research.base_url")
    enabled = db.get(AppSetting, "research.enabled")
    key = db.get(AppSetting, "research.api_key")
    return {
        "base_url": base.value if base else "",
        "enabled": (enabled.value if enabled else "0") == "1",
        "key_set": bool(key and key.value),
    }


class ResearchIn(BaseModel):
    base_url: str | None = None
    enabled: bool | None = None
    api_key: str | None = None  # blank/omitted = keep existing secret


@router.put("/research")
def put_research(body: ResearchIn, ctx: AuthContext = Depends(get_ctx)):
    db = ctx.db
    if body.base_url is not None:
        _set(db, "research.base_url", body.base_url.strip().rstrip("/"))
    if body.enabled is not None:
        _set(db, "research.enabled", "1" if body.enabled else "0")
    if body.api_key:  # non-empty = replace
        _set(db, "research.api_key", body.api_key.strip(), secret=True)
    db.commit()
    return {"ok": True}


@router.post("/research/test")
def test_research(ctx: AuthContext = Depends(get_ctx)):
    db = ctx.db
    base = db.get(AppSetting, "research.base_url")
    key = db.get(AppSetting, "research.api_key")
    if not (base and base.value and key and key.value):
        raise HTTPException(400, "Set the base URL and API key first, then save.")
    try:
        r = requests.get(
            f"{base.value.rstrip('/')}/v1/health",
            headers={"Authorization": f"Bearer {decrypt(key.value)}"},
            timeout=15,
        )
        return {"ok": r.status_code == 200, "status_code": r.status_code, "body": (r.text or "")[:200]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:200]}
