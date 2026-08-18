"""The Client Library — the raw materials the writer is allowed to use.

A document is something you read and approve. A library record is something the
system *uses*, which is why these are rows and not paragraphs. A paragraph
cannot carry a source, a verification date, or a usage count, and an angle
cannot point at one and survive its own wording being edited.

`source` is the load-bearing column here. It is mandatory on every record, and
it is not decoration — it decides what the writer is allowed to do with the
fact:

- `verified`        we can check it: a public case-study page, our own sending
                   data, something with a URL. Usable as a **named** claim.
- `client_supplied` the client told us. Usable as background and as a reason to
                   write about a problem, **not** as a named claim, because
                   nobody outside the client can check it.
- `operator`       we wrote it down off a call or a deck. Same limit as above
                   until somebody verifies it.

That is `AGENT_BRIEF.md` §2 rule 4 stored as a data field rather than left as a
rule somebody has to remember. `app/routers/sequences.py::_quality` is where it
bites: copy that names the client of a non-verified case study fails QC, and a
variant that fails QC cannot be enabled.

**One store, not two.** Case studies used to live inside
`EnrichConfig.profile["case_studies"]` as free-form JSON, where `source` was an
optional string nobody enforced and a record's identity was a hash of its own
text — so editing a case study silently orphaned every angle pointing at it.
This table is now the source of truth. That profile key becomes an *inbox*: the
Library surfaces whatever is still sitting there as "unfiled" with an Import
action, and every new write — client add, whiteboard promotion, onboarding-form
mapping — lands here instead. See `app/library/store.py`.
"""
from datetime import datetime

from sqlalchemy import (Column, DateTime, ForeignKey, Integer, String, Text,
                        UniqueConstraint)

from ..db import Base

# Ordered weakest-to-strongest claim strength. The Library sorts by it, so the
# records that need attention surface above the ones that are already usable.
SOURCES = ("client_supplied", "operator", "verified")
SOURCE_LABELS = {
    "client_supplied": "client-supplied",
    "operator": "operator",
    "verified": "verified",
}
# The whole point of the vocabulary: only this set may be named in an email.
NAMED_CLAIM_SOURCES = ("verified",)

# ICP test verdicts. `testing` is the honest default — a hypothesis with no
# result yet is not a weak validation, it is an open question.
VERDICTS = ("testing", "validated", "killed")
VERDICT_LABELS = {"testing": "Testing", "validated": "Validated", "killed": "Killed"}

# What an exclusion is matched on. `domain` is the useful one — a client says
# "don't touch Acme" and means the company, not one mailbox.
EXCLUSION_KINDS = ("domain", "company", "email")


class LibraryCaseStudy(Base):
    """Proof. What makes an email specific instead of generic."""

    __tablename__ = "library_case_studies"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)

    # The client's name, kept in its own column rather than folded into a title,
    # because the named-claim check has to look for exactly this string in the
    # copy. "Kaya — full rebrand" would match "full" and "rebrand" too.
    client_name = Column(String(240), nullable=False)
    engagement = Column(String(240), default="")     # "full rebrand", "SaaS retainer"
    segment = Column(String(160), default="")        # "Consumer", "B2B SaaS"
    year = Column(Integer)
    # The result, in the client's own units. This is the text the number check
    # grounds against, so it must contain the figures the copy is allowed to use.
    outcome = Column(Text, nullable=False)
    note = Column(Text, default="")                  # context that is not the claim

    source = Column(String(20), nullable=False, index=True)
    source_url = Column(Text, default="")            # the public page, when there is one
    verified_at = Column(DateTime)
    verified_by = Column(Integer, ForeignKey("users.id"))

    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    archived_at = Column(DateTime)


class LibrarySegment(Base):
    """Who we are going after, and how many of them exist.

    `tam_estimate` is entered and therefore carries a `source` like everything
    else here — an unsourced market size is a number that sounds like research.
    The in-list count is NOT stored: it is counted from `enrich_list_id` on read,
    so it cannot drift away from the list it describes.
    """

    __tablename__ = "library_segments"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)

    name = Column(String(240), nullable=False)
    company_type = Column(String(240), default="")   # "Independent creative agencies"
    headcount = Column(String(80), default="")       # "10–50" — a range, kept as written
    geography = Column(String(240), default="")      # "UK & Ireland"
    tam_estimate = Column(Integer)
    tam_note = Column(Text, default="")              # how the figure was arrived at
    enrich_list_id = Column(Integer, ForeignKey("enrich_lists.id"), index=True)

    source = Column(String(20), nullable=False, index=True)
    source_url = Column(Text, default="")
    verified_at = Column(DateTime)
    verified_by = Column(Integer, ForeignKey("users.id"))

    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    archived_at = Column(DateTime)


class LibraryIcpTest(Base):
    """What we have learned. One hypothesis, its result, and a verdict.

    Killed tests are kept. A record of what did not work is the reason the next
    quarter does not retry it, and deleting it is how a team relearns the same
    lesson twice.
    """

    __tablename__ = "library_icp_tests"

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)

    hypothesis = Column(Text, nullable=False)
    verdict = Column(String(20), nullable=False, default="testing", index=True)
    result = Column(Text, default="")                # what actually happened
    sample_size = Column(Integer)                    # prospects the test ran across
    segment_id = Column(Integer, ForeignKey("library_segments.id"), index=True)
    started_at = Column(DateTime)
    decided_at = Column(DateTime)

    source = Column(String(20), nullable=False, index=True)
    source_url = Column(Text, default="")
    verified_at = Column(DateTime)
    verified_by = Column(Integer, ForeignKey("users.id"))

    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    archived_at = Column(DateTime)


class LibraryExclusion(Base):
    """An account we must not contact.

    Deliberately not `ReplyBlock`. That table answers "a reply from this address
    is auto-stopped" — inbound suppression, one mailbox at a time, set by an
    operator clearing their inbox. This one answers "never research or prospect
    this company", which is a different lifecycle, a different granularity, and
    client-owned. Conflating them means blocking one noisy sender quietly
    removes their entire employer from the target list.

    Checked in `app/enrichment/pipeline.py` **before** the first verify call, so
    an excluded account costs nothing rather than being researched and then
    filtered out afterwards.
    """

    __tablename__ = "library_exclusions"
    __table_args__ = (
        UniqueConstraint("workspace_id", "kind", "value", name="uq_library_exclusion_value"),
    )

    id = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False, index=True)

    kind = Column(String(20), nullable=False, default="domain")   # EXCLUSION_KINDS
    # Normalised on write: lower-cased, `https://`/`www.` stripped from domains.
    # Matching is exact against a normalised lead domain, never a substring —
    # "cast.com" must not exclude "podcast.com".
    value = Column(String(320), nullable=False, index=True)
    label = Column(String(240), default="")          # the name a human recognises
    reason = Column(String(500), default="")         # "existing customer", "live deal"

    source = Column(String(20), nullable=False, index=True)

    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    archived_at = Column(DateTime)
