"""Public, no-auth client pages: the per-client Growth Blueprint served at
`/p/{slug}` on any domain, and — when a `blueprint.` host is used — at the bare
`blueprint.<domain>/{slug}`. Only PUBLISHED blueprints render; view opens are
counted (throttled). Internal fields never appear here."""
from datetime import datetime, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ..db import SessionLocal
from ..models.documents import Document

router = APIRouter(tags=["public"])

_404 = HTMLResponse(
    "<!doctype html><meta charset='utf-8'><title>Not found</title>"
    "<div style=\"font-family:-apple-system,Segoe UI,Arial;max-width:520px;margin:18vh auto;"
    "text-align:center;color:#333\"><h1 style='font-size:1.4rem'>This page isn't available</h1>"
    "<p style='color:#777'>The link may be unpublished or incorrect.</p></div>", status_code=404)


def _render_blueprint(slug: str) -> HTMLResponse:
    db = SessionLocal()
    try:
        d = (db.query(Document)
             .filter(Document.slug == slug, Document.kind == "blueprint",
                     Document.published == True)  # noqa: E712
             .first())
        if not d or not d.html:
            return _404
        now = datetime.utcnow()
        # count a view at most once / 6h per document (open analytics)
        if d.last_viewed_at is None or (now - d.last_viewed_at) > timedelta(hours=6):
            d.view_count = (d.view_count or 0) + 1
            d.last_viewed_at = now
            if d.first_viewed_at is None:
                d.first_viewed_at = now
            if d.status == "published":
                d.status = "viewed"
            db.commit()
        return HTMLResponse(d.html)
    finally:
        db.close()


@router.get("/p/{slug}", include_in_schema=False)
def public_blueprint(slug: str):
    return _render_blueprint(slug)
