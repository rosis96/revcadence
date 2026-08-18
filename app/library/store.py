"""Library reads, writes, and the two things that make the records worth having:
provenance and usage.

Deliberately free of FastAPI so the enrichment pipeline can ask
`exclusion_reason()` before it spends anything, and so the merge/normalise rules
are testable without a request.

Three ideas run through this module.

**Stable identity.** An angle points at a case study by `lib:<id>`. The old
scheme hashed the record's own text, so editing a case study orphaned every
angle that referenced it and QC started reporting "missing proof" for copy
nobody had touched. Ids do not move when wording does.

**One store, with a visible inbox.** `EnrichConfig.profile["case_studies"]` is
still written by the crawler and the brain chat, so it cannot simply be ignored.
`unfiled()` surfaces whatever is sitting there and `import_unfiled()` moves it
into real rows. Everything else — client adds, whiteboard promotions, form
mappings — writes rows directly.

**Usage is counted, never stored.** "Used in 2 angles · 312 emails" is derived
from the angles and variants that exist right now. A stored counter would be
wrong the first time somebody archived a sequence.
"""
import hashlib
import json
import re
from datetime import datetime

from sqlalchemy import func

from ..models.enrich import EnrichConfig, EnrichLead
from ..models.library import (EXCLUSION_KINDS, NAMED_CLAIM_SOURCES, SOURCE_LABELS, SOURCES,
                              VERDICT_LABELS, VERDICTS, LibraryCaseStudy, LibraryExclusion,
                              LibraryIcpTest, LibrarySegment)
from ..models.sequences import (EmailAngle, EmailSequence, EmailSequenceStep,
                                EmailSequenceVariant)

# The brain keys that hold proof. Read for the inbox, never written to by the
# Library itself.
PROFILE_PROOF_KEYS = ("case_studies", "proof_points", "results_metrics", "testimonials")

MODELS = {
    "case_study": LibraryCaseStudy,
    "segment": LibrarySegment,
    "icp_test": LibraryIcpTest,
    "exclusion": LibraryExclusion,
}

_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*://", re.I)


# ---------------------------------------------------------------- vocabulary
class LibraryError(ValueError):
    """A record was rejected. Carries a message the client can read."""


def clean_source(value, *, default: str | None = None) -> str:
    """`source` is mandatory. A record without one is a fact whose provenance we
    have already lost, so this raises rather than guessing a default."""
    raw = str(value or "").strip().lower()
    if not raw:
        if default:
            return default
        raise LibraryError("Every library record needs a source")
    if raw not in SOURCES:
        raise LibraryError(f"source must be one of {', '.join(SOURCES)}")
    return raw


def clean_verdict(value, *, default: str = "testing") -> str:
    raw = str(value or "").strip().lower() or default
    if raw not in VERDICTS:
        raise LibraryError(f"verdict must be one of {', '.join(VERDICTS)}")
    return raw


def named_claim_allowed(source: str) -> bool:
    return source in NAMED_CLAIM_SOURCES


def domain_of(value: str) -> str:
    """The registrable host in a URL, an email, or a bare domain — lower-cased,
    scheme and `www.` removed, path and port dropped. Returns "" when there is
    nothing domain-shaped in the input, which callers must treat as "no match"
    rather than as a wildcard."""
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    if "@" in raw:
        raw = raw.rsplit("@", 1)[1]
    raw = _SCHEME.sub("", raw)
    raw = raw.split("/", 1)[0].split("?", 1)[0].split(":", 1)[0]
    raw = raw.removeprefix("www.").strip(".")
    return raw if "." in raw and " " not in raw else ""


def _norm_company(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def strip_noise(value: str) -> str:
    """Trim the punctuation a pasted list leaves on its items.

    Clients answer "anyone we should never contact" by pasting from a spreadsheet
    or a chat message, so entries arrive as `"acme.com",` or `- acme.com` or
    `['acme.com'`. Keeping that punctuation produces an exclusion that matches
    nothing, which is the worst outcome available: it looks applied and is not.
    """
    return str(value or "").strip().strip("[](){}<>\"'`,;:•-*• \t").strip()


def clean_exclusion(kind, value) -> tuple[str, str]:
    """Normalise an exclusion to (kind, value) or raise.

    A client typing `https://Acme.com/about` and a client typing `acme.com` mean
    the same account, and an exclusion that only matches one of those spellings
    is an exclusion that quietly fails.
    """
    kind = str(kind or "").strip().lower() or "domain"
    if kind not in EXCLUSION_KINDS:
        raise LibraryError(f"kind must be one of {', '.join(EXCLUSION_KINDS)}")
    raw = strip_noise(value)
    if not raw:
        raise LibraryError("An exclusion needs a value")
    if kind == "email":
        raw = raw.lower()
        if "@" not in raw or "." not in raw.rsplit("@", 1)[1]:
            raise LibraryError("That does not look like an email address")
        return kind, raw[:320]
    if kind == "domain":
        host = domain_of(raw)
        if not host:
            raise LibraryError("Enter a company domain, like acme.com")
        return kind, host[:320]
    return kind, raw[:320]


# ---------------------------------------------------------------- usage
def _sum_sends(db, workspace_id: int) -> dict[int, int]:
    """Emails sent per angle. Archived variants keep their statistics — the
    counts are a record of what happened, and pruning them would make a
    successful angle look untested."""
    rows = (db.query(EmailSequence.angle_id, EmailSequenceVariant.sent_count)
            .join(EmailSequenceStep, EmailSequenceStep.sequence_id == EmailSequence.id)
            .join(EmailSequenceVariant, EmailSequenceVariant.step_id == EmailSequenceStep.id)
            .filter(EmailSequence.workspace_id == workspace_id).all())
    out: dict[int, int] = {}
    for angle_id, sent in rows:
        out[angle_id] = out.get(angle_id, 0) + int(sent or 0)
    return out


def usage_by_proof_key(db, workspace_id: int) -> dict[str, dict]:
    """`proof_key → {angles, emails, angle_names}`.

    This is what turns a paragraph into a record: the Library can say a case
    study is carrying 312 live emails, which is the difference between "we wrote
    this down" and "this is load-bearing".
    """
    angles = (db.query(EmailAngle.id, EmailAngle.proof_key, EmailAngle.name)
              .filter(EmailAngle.workspace_id == workspace_id).all())
    sends = _sum_sends(db, workspace_id)
    out: dict[str, dict] = {}
    for angle_id, proof_key, name in angles:
        key = (proof_key or "").strip()
        if not key:
            continue
        bucket = out.setdefault(key, {"angles": 0, "emails": 0, "angle_names": []})
        bucket["angles"] += 1
        bucket["emails"] += sends.get(angle_id, 0)
        bucket["angle_names"].append(name or "Untitled angle")
    return out


# ---------------------------------------------------------------- serialisers
def _iso(value):
    return value.isoformat() if value else None


def _provenance(row, *, verifier_names: dict | None = None) -> dict:
    names = verifier_names or {}
    return {
        "source": row.source,
        "source_label": SOURCE_LABELS.get(row.source, row.source),
        "source_url": getattr(row, "source_url", "") or "",
        "verified": row.source == "verified",
        "named_claim_allowed": named_claim_allowed(row.source),
        "verified_at": _iso(getattr(row, "verified_at", None)),
        "verified_by": names.get(getattr(row, "verified_by", None) or 0, ""),
    }


def case_study_title(row) -> str:
    engagement = (row.engagement or "").strip()
    return f"{row.client_name} — {engagement}" if engagement else row.client_name


def case_study_out(row: LibraryCaseStudy, *, usage: dict | None = None,
                   verifier_names: dict | None = None) -> dict:
    used = usage or {}
    return {
        "id": row.id,
        "proof_key": proof_key_for(row),
        "title": case_study_title(row),
        "client_name": row.client_name,
        "engagement": row.engagement or "",
        "segment": row.segment or "",
        "year": row.year,
        "outcome": row.outcome or "",
        "note": row.note or "",
        "usage": {"angles": used.get("angles", 0), "emails": used.get("emails", 0),
                  "angle_names": used.get("angle_names", [])},
        # Why a client-supplied record is still worth having, said in the card
        # rather than in a rule somebody has to look up.
        "limitation": ("" if row.source == "verified" else
                       "Usable as background. Not usable as a named claim until verified."),
        "updated_at": _iso(row.updated_at),
        **_provenance(row, verifier_names=verifier_names),
    }


def segment_out(row: LibrarySegment, *, in_list: int | None = None,
                list_name: str = "", verifier_names: dict | None = None) -> dict:
    tam = row.tam_estimate
    return {
        "id": row.id,
        "name": row.name,
        "company_type": row.company_type or "",
        "headcount": row.headcount or "",
        "geography": row.geography or "",
        "tam_estimate": tam,
        "tam_note": row.tam_note or "",
        "enrich_list_id": row.enrich_list_id,
        "list_name": list_name,
        # Counted from the linked list, so it cannot disagree with it. None means
        # "not in a list yet", which is a real state and not zero.
        "in_list": in_list,
        "coverage": (round(100 * in_list / tam, 1) if tam and in_list is not None and tam > 0
                     else None),
        "updated_at": _iso(row.updated_at),
        **_provenance(row, verifier_names=verifier_names),
    }


def icp_test_out(row: LibraryIcpTest, *, segment_name: str = "",
                 verifier_names: dict | None = None) -> dict:
    return {
        "id": row.id,
        "hypothesis": row.hypothesis or "",
        "verdict": row.verdict,
        "verdict_label": VERDICT_LABELS.get(row.verdict, row.verdict),
        "result": row.result or "",
        "sample_size": row.sample_size,
        "segment_id": row.segment_id,
        "segment_name": segment_name,
        "started_at": _iso(row.started_at),
        "decided_at": _iso(row.decided_at),
        "updated_at": _iso(row.updated_at),
        **_provenance(row, verifier_names=verifier_names),
    }


def exclusion_out(row: LibraryExclusion) -> dict:
    return {
        "id": row.id, "kind": row.kind, "value": row.value,
        "label": row.label or "", "reason": row.reason or "",
        "source": row.source, "source_label": SOURCE_LABELS.get(row.source, row.source),
        "created_at": _iso(row.created_at),
    }


# ---------------------------------------------------------------- queries
def _live(db, model, workspace_id: int):
    return (db.query(model)
            .filter(model.workspace_id == workspace_id, model.archived_at.is_(None)))


def case_studies(db, workspace_id: int) -> list[LibraryCaseStudy]:
    """Newest first, but records that need verification float to the top: the
    Library's job is to show the client the one thing worth doing next."""
    rows = _live(db, LibraryCaseStudy, workspace_id).all()
    return sorted(rows, key=lambda r: (r.source == "verified",
                                       -(r.year or 0), -(r.id or 0)))


def segments(db, workspace_id: int) -> list[LibrarySegment]:
    return _live(db, LibrarySegment, workspace_id).order_by(LibrarySegment.id.desc()).all()


def icp_tests(db, workspace_id: int) -> list[LibraryIcpTest]:
    """Open tests first — a `testing` row is a question waiting on an answer,
    and the decided ones are history."""
    rows = _live(db, LibraryIcpTest, workspace_id).all()
    rank = {"testing": 0, "validated": 1, "killed": 2}
    return sorted(rows, key=lambda r: (rank.get(r.verdict, 9), -(r.id or 0)))


def exclusions(db, workspace_id: int) -> list[LibraryExclusion]:
    return _live(db, LibraryExclusion, workspace_id).order_by(LibraryExclusion.id.desc()).all()


def in_list_counts(db, workspace_id: int, rows: list[LibrarySegment]) -> dict[int, int]:
    """How many researched prospects each segment's linked list actually holds.

    Counts leads the pipeline did not reject, so the figure answers "how many
    can we write to" rather than "how many rows were uploaded".
    """
    list_ids = {r.enrich_list_id for r in rows if r.enrich_list_id}
    if not list_ids:
        return {}
    counted = dict(
        db.query(EnrichLead.list_id, func.count(EnrichLead.id))
        .filter(EnrichLead.workspace_id == workspace_id,
                EnrichLead.list_id.in_(list_ids),
                EnrichLead.status.notin_(("invalid", "unsafe", "skipped")))
        .group_by(EnrichLead.list_id).all())
    return {r.id: counted.get(r.enrich_list_id, 0) for r in rows if r.enrich_list_id}


# ---------------------------------------------------------------- proof keys
def proof_key_for(row: LibraryCaseStudy) -> str:
    return f"lib:{row.id}"


def _legacy_key(kind: str, item) -> str:
    """The pre-Library key: a hash of the record's own JSON. Reproduced exactly
    so angles created before this table keep resolving to their proof instead of
    failing QC as "missing proof"."""
    raw = json.dumps(item, sort_keys=True, default=str)
    return f"{kind}:{hashlib.sha256(raw.encode()).hexdigest()[:20]}"


def _profile(db, workspace_id: int) -> tuple[EnrichConfig | None, dict]:
    cfg = db.query(EnrichConfig).filter(EnrichConfig.workspace_id == workspace_id).first()
    return cfg, (dict(cfg.profile or {}) if cfg is not None else {})


def _profile_entry(kind: str, item) -> dict | None:
    if not item:
        return None
    if isinstance(item, dict):
        label = str(item.get("name") or item.get("client") or item.get("title")
                    or item.get("outcome") or item.get("text") or "").strip()
        detail = str(item.get("outcome") or item.get("result") or item.get("text")
                     or item.get("quote") or "").strip()
        source = str(item.get("source") or "").strip().lower()
    else:
        label = detail = str(item).strip()
        source = ""
    if not label:
        label = detail[:160]
    if not label:
        return None
    # Legacy rows carried free-text sources ("whiteboard", "operator_supplied").
    # Anything we cannot map is `operator`: written down by us, not verified.
    mapped = {"client_supplied": "client_supplied", "verified": "verified"}.get(source, "operator")
    return {"key": _legacy_key(kind, item), "kind": kind, "label": label[:240],
            "detail": detail[:1000], "source": mapped, "raw": item}


def unfiled(db, workspace_id: int) -> list[dict]:
    """Proof still sitting in the brain profile rather than in the Library.

    Shown to the operator with an Import action instead of being silently
    absorbed on read: importing writes rows and stamps provenance, and doing
    that as a side effect of a GET would make a page load a data migration.

    Anything already filed drops out of this list, which is what lets the inbox
    visibly empty and makes importing twice a no-op. The profile itself is never
    edited — the crawler and the brain chat keep writing there, and destroying
    their output to tidy a counter would be the wrong trade.
    """
    _cfg, profile = _profile(db, workspace_id)
    filed = {(r.client_name.strip().casefold(), (r.outcome or "").strip().casefold())
             for r in case_studies(db, workspace_id)}
    out = []
    for kind in PROFILE_PROOF_KEYS:
        value = profile.get(kind) or []
        if not isinstance(value, list):
            value = [value]
        for item in value:
            entry = _profile_entry(kind, item)
            if entry is None:
                continue
            detail = entry["detail"] or entry["label"]
            if (entry["label"].strip().casefold(), detail.strip().casefold()) in filed:
                continue
            out.append(entry)
    return out


def proof_choices(db, workspace_id: int) -> list[dict]:
    """Everything an angle may point at: Library rows first, then whatever is
    still unfiled. Each choice carries its provenance, so the sequence editor can
    say "client-supplied — not usable as a named claim" at the moment somebody
    picks it rather than at QC time."""
    out = []
    for row in case_studies(db, workspace_id):
        out.append({
            "key": proof_key_for(row), "kind": "case_study",
            "label": case_study_title(row), "detail": row.outcome or "",
            "client_name": row.client_name,
            "source": row.source, "source_label": SOURCE_LABELS.get(row.source, row.source),
            "verified": row.source == "verified",
            "named_claim_allowed": named_claim_allowed(row.source),
            "library_id": row.id, "unfiled": False,
        })
    for entry in unfiled(db, workspace_id):
        out.append({
            "key": entry["key"], "kind": entry["kind"], "label": entry["label"],
            "detail": entry["detail"], "client_name": entry["label"],
            "source": entry["source"],
            "source_label": SOURCE_LABELS.get(entry["source"], entry["source"]),
            "verified": entry["source"] == "verified",
            "named_claim_allowed": named_claim_allowed(entry["source"]),
            "library_id": None, "unfiled": True,
        })
    return out


def proof_for_key(db, workspace_id: int, key: str) -> dict | None:
    key = (key or "").strip()
    if not key:
        return None
    return next((p for p in proof_choices(db, workspace_id) if p["key"] == key), None)


# ---------------------------------------------------------------- writes
def add_case_study(db, workspace_id: int, *, client_name: str, outcome: str, source: str,
                   engagement: str = "", segment: str = "", year=None, note: str = "",
                   source_url: str = "", user_id: int | None = None,
                   verified_by: int | None = None) -> LibraryCaseStudy:
    """The one way a case study enters the Library.

    Called by the client's add form, the whiteboard promotion, the onboarding
    form mapping and the import. A single entry point is what keeps `source`
    mandatory in practice rather than only in the column definition.
    """
    client_name = str(client_name or "").strip()
    outcome = str(outcome or "").strip()
    if not client_name:
        raise LibraryError("A case study needs the client's name")
    if not outcome:
        raise LibraryError("A case study needs the result it produced")
    source = clean_source(source)
    url = str(source_url or "").strip()
    if source == "verified" and not url:
        # "Verified" has to mean somebody can check it. Without a link this is a
        # claim we are choosing to trust, which is what `operator` is for.
        raise LibraryError("A verified case study needs a link somebody can check")

    duplicate = (_live(db, LibraryCaseStudy, workspace_id)
                 .filter(LibraryCaseStudy.client_name.ilike(client_name)).all())
    for row in duplicate:
        if (row.outcome or "").strip().casefold() == outcome.casefold():
            raise LibraryError(f"{client_name} is already in the Library with that result")

    try:
        year = int(year) if str(year or "").strip() else None
    except (TypeError, ValueError):
        year = None

    row = LibraryCaseStudy(
        workspace_id=workspace_id, client_name=client_name[:240],
        engagement=str(engagement or "").strip()[:240],
        segment=str(segment or "").strip()[:160], year=year,
        outcome=outcome[:4000], note=str(note or "").strip()[:4000],
        source=source, source_url=url[:2000],
        verified_at=datetime.utcnow() if source == "verified" else None,
        verified_by=(verified_by or user_id) if source == "verified" else None,
        created_by=user_id)
    db.add(row)
    db.flush()
    return row


def add_segment(db, workspace_id: int, *, name: str, source: str, company_type: str = "",
                headcount: str = "", geography: str = "", tam_estimate=None,
                tam_note: str = "", enrich_list_id=None, source_url: str = "",
                user_id: int | None = None) -> LibrarySegment:
    name = str(name or "").strip()
    if not name:
        raise LibraryError("A segment needs a name")
    source = clean_source(source)
    try:
        tam = int(tam_estimate) if str(tam_estimate or "").strip() else None
    except (TypeError, ValueError):
        tam = None
    if tam is not None and tam < 0:
        raise LibraryError("A market size cannot be negative")
    row = LibrarySegment(
        workspace_id=workspace_id, name=name[:240],
        company_type=str(company_type or "").strip()[:240],
        headcount=str(headcount or "").strip()[:80],
        geography=str(geography or "").strip()[:240],
        tam_estimate=tam, tam_note=str(tam_note or "").strip()[:2000],
        enrich_list_id=enrich_list_id, source=source,
        source_url=str(source_url or "").strip()[:2000],
        verified_at=datetime.utcnow() if source == "verified" else None,
        verified_by=user_id if source == "verified" else None,
        created_by=user_id)
    db.add(row)
    db.flush()
    return row


def add_icp_test(db, workspace_id: int, *, hypothesis: str, source: str, verdict: str = "testing",
                 result: str = "", sample_size=None, segment_id=None,
                 user_id: int | None = None) -> LibraryIcpTest:
    hypothesis = str(hypothesis or "").strip()
    if not hypothesis:
        raise LibraryError("A test needs a hypothesis")
    verdict = clean_verdict(verdict)
    if verdict != "testing" and not str(result or "").strip():
        raise LibraryError("A decided test needs its result written down")
    try:
        sample = int(sample_size) if str(sample_size or "").strip() else None
    except (TypeError, ValueError):
        sample = None
    now = datetime.utcnow()
    row = LibraryIcpTest(
        workspace_id=workspace_id, hypothesis=hypothesis[:4000], verdict=verdict,
        result=str(result or "").strip()[:4000], sample_size=sample, segment_id=segment_id,
        source=clean_source(source), started_at=now,
        decided_at=now if verdict != "testing" else None, created_by=user_id)
    db.add(row)
    db.flush()
    return row


def add_exclusion(db, workspace_id: int, *, value: str, source: str, kind: str = "domain",
                  label: str = "", reason: str = "",
                  user_id: int | None = None) -> LibraryExclusion:
    kind, value = clean_exclusion(kind, value)
    existing = (db.query(LibraryExclusion)
                .filter(LibraryExclusion.workspace_id == workspace_id,
                        LibraryExclusion.kind == kind,
                        LibraryExclusion.value == value).first())
    if existing is not None:
        # Re-adding is how somebody un-archives in practice, so treat it as that
        # rather than as a conflict they have to go and undo first.
        if existing.archived_at is not None:
            existing.archived_at = None
            db.flush()
            return existing
        raise LibraryError(f"{value} is already excluded")
    row = LibraryExclusion(
        workspace_id=workspace_id, kind=kind, value=value,
        label=str(label or "").strip()[:240], reason=str(reason or "").strip()[:500],
        source=clean_source(source), created_by=user_id)
    db.add(row)
    db.flush()
    return row


def verify(db, row, *, user_id: int, source_url: str = "") -> None:
    """Promote a record to `verified`. Requires a link, for the same reason
    `add_case_study` does: verification that cannot be re-checked by the next
    person is a memory, not a verification."""
    url = str(source_url or "").strip() or (getattr(row, "source_url", "") or "").strip()
    if not url:
        raise LibraryError("Verifying needs a link somebody else can check")
    row.source = "verified"
    row.source_url = url[:2000]
    row.verified_at = datetime.utcnow()
    row.verified_by = user_id
    db.flush()


def _repoint_angles(db, workspace_id: int, old_key: str, row: LibraryCaseStudy) -> int:
    """Move angles off a legacy hash key onto the imported row's stable id.

    Without this, importing would break the very thing the Library exists to
    protect: the angle would keep pointing at a key that no longer resolves, and
    QC would report "missing proof" on copy nobody had touched.
    """
    angles = (db.query(EmailAngle)
              .filter(EmailAngle.workspace_id == workspace_id,
                      EmailAngle.proof_key == old_key).all())
    for angle in angles:
        angle.proof_key = proof_key_for(row)
        angle.proof_label = case_study_title(row)
    return len(angles)


def import_unfiled(db, workspace_id: int, *, user_id: int | None = None) -> dict:
    """Move brain-profile proof into real Library rows.

    Idempotent: `unfiled()` already excludes anything filed, and an entry that
    collides with an existing row is repointed to it rather than duplicated. The
    profile is left as it is — the crawler owns that key, and emptying it here
    would make the next crawl look like it had invented new facts.
    """
    made = merged = relinked = 0
    for entry in unfiled(db, workspace_id):
        item = entry["raw"]
        engagement = segment = ""
        year = None
        if isinstance(item, dict):
            engagement = str(item.get("engagement") or item.get("problem") or "").strip()
            segment = str(item.get("industry") or item.get("segment") or "").strip()
            year = item.get("year")
        detail = entry["detail"] or entry["label"]
        try:
            row = add_case_study(db, workspace_id, client_name=entry["label"],
                                 outcome=detail, source=entry["source"],
                                 engagement=engagement, segment=segment, year=year,
                                 note="Imported from the client brain.", user_id=user_id)
            made += 1
        except LibraryError:
            row = next((r for r in case_studies(db, workspace_id)
                        if r.client_name.strip().casefold() == entry["label"].strip().casefold()),
                       None)
            if row is None:
                continue
            merged += 1
        relinked += _repoint_angles(db, workspace_id, entry["key"], row)
    return {"imported": made, "merged": merged, "angles_relinked": relinked}


# ---------------------------------------------------------------- writer packet
def writer_packet(db, workspace_id: int) -> dict:
    """The Library, split by what the writer is allowed to do with it.

    Two lists rather than one flag, because a model follows "these may be named,
    these may not" far more reliably than it follows a `source` field it has to
    interpret. `background_only` is included rather than withheld: a
    client-supplied fact is still a reason to write about a problem, and dropping
    it would lose real signal to enforce a rule that only concerns *naming*.

    Legacy `profile["case_studies"]` is not touched here. Client answers and
    client additions no longer land there — they land in this table — so what
    remains in the profile is our own crawler and operator notes, and moving it
    would change copy for live workspaces to enforce a rule about client-supplied
    facts that are not in it.
    """
    nameable, background = [], []
    for row in case_studies(db, workspace_id):
        item = {"client": row.client_name, "result": row.outcome or ""}
        if row.engagement:
            item["engagement"] = row.engagement
        if row.source == "verified":
            item["link"] = row.source_url or ""
            nameable.append(item)
        else:
            background.append({**item, "why_not_nameable": SOURCE_LABELS.get(row.source, row.source)})
    return {"nameable_proof": nameable[:6], "background_only": background[:6]}


# The line that carries the rule into the prompt. Kept next to the packet that
# feeds it so the two cannot drift apart.
WRITER_RULE = (
    "- EVIDENCE: `client_library.nameable_proof` is verified and may be named in copy "
    "(the client, the engagement, its numbers). `client_library.background_only` is NOT "
    "verified: use it to understand what matters to the reader, and NEVER name its client "
    "or quote its numbers as a claim. If the only proof for a line is background_only, "
    "write the line without the name or leave it empty.\n"
)


# ---------------------------------------------------------------- objections
def add_objection(db, workspace_id: int, *, objection: str, response: str = "",
                  source: str = "client_supplied") -> dict:
    """Objections stay in the brain, not in a table of their own.

    The writer already reads `profile["objections"]` and `brain.merge_brain_list`
    already knows how to accumulate them without wiping prior work. A Library
    table for objections would be a second copy of a fact the brain is already
    the store for — which is the exact thing rule 1 forbids. So this is a Library
    *surface* over the brain's store.
    """
    from ..enrichment.brain import merge_brain_list

    objection = str(objection or "").strip()
    if not objection:
        raise LibraryError("Write the objection as you hear it on calls")
    source = clean_source(source)
    cfg = db.query(EnrichConfig).filter(EnrichConfig.workspace_id == workspace_id).first()
    if cfg is None:
        cfg = EnrichConfig(workspace_id=workspace_id, profile={}, formats=[])
        db.add(cfg)
        db.flush()
    profile = dict(cfg.profile or {})
    item = {"objection": objection[:600], "response": str(response or "").strip()[:2000],
            "source": source}
    profile["objections"] = merge_brain_list("objections", profile.get("objections"), [item])
    cfg.profile = profile
    db.flush()
    return item


def objections(db, workspace_id: int) -> list[dict]:
    _cfg, profile = _profile(db, workspace_id)
    out = []
    for item in profile.get("objections") or []:
        if isinstance(item, dict):
            text = str(item.get("objection") or "").strip()
            answer = str(item.get("response") or "").strip()
            source = str(item.get("source") or "").strip().lower()
        else:
            text, answer, source = str(item).strip(), "", ""
        if not text:
            continue
        source = source if source in SOURCES else "operator"
        out.append({"objection": text, "response": answer, "source": source,
                    "source_label": SOURCE_LABELS.get(source, source)})
    return out


# ---------------------------------------------------------------- exclusions
def exclusion_reason(db, workspace_id: int, *, email: str = "", website: str = "",
                     company: str = "") -> str:
    """Why this lead must not be researched, or "".

    Called by the pipeline before the first verify, so an excluded account costs
    nothing. Matching is exact on a normalised domain and never a substring:
    "cast.com" must not take out "podcast.com".
    """
    rows = exclusions(db, workspace_id)
    if not rows:
        return ""
    addr = str(email or "").strip().lower()
    hosts = {h for h in (domain_of(email), domain_of(website)) if h}
    name = _norm_company(company)
    for row in rows:
        if row.kind == "email" and addr and row.value == addr:
            return row.reason or f"do-not-contact: {row.value}"
        if row.kind == "domain" and row.value in hosts:
            return row.reason or f"do-not-contact: {row.value}"
        if row.kind == "company" and name and _norm_company(row.value) == name:
            return row.reason or f"do-not-contact: {row.value}"
    return ""


# ---------------------------------------------------------------- counts
def counts(db, workspace_id: int) -> dict:
    """Tab counters and the one number that decides whether campaigns can run.

    `verified_case_studies` is the honest measure of how good the copy can get:
    three thin, repetitive angles versus six that can each name somebody.
    """
    studies = case_studies(db, workspace_id)
    return {
        "case_studies": len(studies),
        "verified_case_studies": sum(1 for r in studies if r.source == "verified"),
        "needs_verification": sum(1 for r in studies if r.source != "verified"),
        "segments": len(segments(db, workspace_id)),
        "icp_tests": len(icp_tests(db, workspace_id)),
        "exclusions": len(exclusions(db, workspace_id)),
        "objections": len(objections(db, workspace_id)),
        "unfiled": len(unfiled(db, workspace_id)),
    }
