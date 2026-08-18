"""The token boundary — the only unauthenticated path in the product.

Everything here treats its input as hostile. The token is the sole credential,
so it is long and cryptographically random, and the two ways it can fail —
never existed, or existed and expired — are answered identically. A distinct
"expired" message would tell someone probing tokens that they had found a real
one, which is exactly the signal worth denying.

Filling logic lives in :mod:`app.forms_fill`, shared with the signed-in route.
This module only resolves a token into an invite and rate-limits what happens
next. It loads the invite and the pinned form and nothing else — no documents,
no prospects, no sequences — which is what makes it safe for this page to render
inside the client dashboard shell.
"""
import time
from collections import defaultdict, deque
from datetime import datetime

from fastapi import (APIRouter, Depends, File, Form as FormField, HTTPException,
                     Request, UploadFile)

from .. import forms_fill
from ..db import get_db
from ..forms_fill import FillPayload, InvalidLink
from ..models.forms import FormInvite

router = APIRouter(prefix="/api/public/forms", tags=["public-forms"])

_INVALID_DETAIL = "This link is no longer valid."
_HITS: dict[str, deque] = defaultdict(deque)


def _invalid():
    raise HTTPException(404, _INVALID_DETAIL)


def _invite(db, token: str) -> FormInvite:
    if not isinstance(token, str) or len(token) < 32 or len(token) > 160:
        _invalid()
    row = db.query(FormInvite).filter(FormInvite.token == token).first()
    if row is None or not row.expires_at or row.expires_at <= datetime.utcnow():
        _invalid()
    return row


def _rate_bucket(key: str, limit: int, window: int) -> tuple[bool, int]:
    now = time.time()
    hits = _HITS[key]
    while hits and now - hits[0] >= window:
        hits.popleft()
    if len(hits) >= limit:
        return False, max(1, int(window - (now - hits[0])))
    hits.append(now)
    return True, 0


def _rate_guard(request: Request, token: str, action: str) -> None:
    """Per-token and per-IP, because either one alone is trivially sidestepped."""
    ip = request.client.host if request.client else "unknown"
    token_key = forms_fill.fingerprint(token)[:24]
    limits = {"save": (90, 60), "submit": (15, 300), "upload": (20, 300)}
    token_limit, window = limits[action]
    for key, limit in ((f"{action}:token:{token_key}", token_limit),
                       (f"{action}:ip:{ip}", token_limit * 3)):
        allowed, retry = _rate_bucket(key, limit, window)
        if not allowed:
            raise HTTPException(429, "Too many requests. Please wait and try again.",
                                headers={"Retry-After": str(retry)})


@router.get("/{token}")
def get_public_form(token: str, db=Depends(get_db)):
    invite = _invite(db, token)
    try:
        return forms_fill.load(db, invite)
    except InvalidLink:
        _invalid()


@router.post("/{token}/save")
def save_public_form(token: str, body: FillPayload, request: Request, db=Depends(get_db)):
    _rate_guard(request, token, "save")
    invite = _invite(db, token)
    try:
        return forms_fill.save(db, invite, body)
    except InvalidLink:
        _invalid()


@router.post("/{token}/submit")
def submit_public_form(token: str, body: FillPayload, request: Request, db=Depends(get_db)):
    _rate_guard(request, token, "submit")
    invite = _invite(db, token)
    try:
        return forms_fill.submit(db, invite, body,
                                 ip=request.client.host if request.client else "")
    except InvalidLink:
        _invalid()


@router.post("/{token}/upload")
async def upload_public_file(token: str, request: Request,
                             question_id: int = FormField(...),
                             file: UploadFile = File(...), db=Depends(get_db)):
    _rate_guard(request, token, "upload")
    invite = _invite(db, token)
    try:
        return await forms_fill.store_upload(db, invite, question_id, file)
    except InvalidLink:
        _invalid()
