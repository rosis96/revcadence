"""Pure scoring helpers for evidence planning and copy selection.

The expensive model should write, not decide which of 28 signals is valuable.
These deterministic helpers make that decision consistently and are intentionally
free of database/web imports so they can be regression-tested cheaply.
"""
from itertools import permutations
import re


_VAGUE_EVIDENCE = (
    "exceeded expectations", "customer satisfaction", "client satisfaction",
    "commitment to", "high quality", "innovative", "leading provider",
)
_COMMERCIAL_TERMS = (
    "approved", "patent", "first and only", "first-ever", "launch", "market",
    "fund", "crowdfund", "revenue", "sales", "grew", "growth", "increase",
    "reduced", "award", "winner", "validated", "adoption", "customers",
)
_ANCHOR_STOPWORDS = {
    "about", "above", "across", "after", "again", "also", "annual", "approach",
    "brand", "business", "campaign", "clarity", "client", "clients", "college",
    "company", "completed", "creating", "customer", "customers", "design",
    "developed", "developing", "exceeded", "expectations", "fund", "growth",
    "help", "helped", "helping", "identity", "increase", "increased", "industry",
    "leading", "methodology", "more", "organization", "program", "project",
    "result", "results", "revenue", "service", "services", "their", "through",
    "using", "with", "work", "your",
}


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def evidence_numbers(value: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.,]\d+)?%?", str(value or "")))


def evidence_terms(value: str) -> set[str]:
    return {
        token.casefold()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9'-]{3,}", str(value or ""))
        if token.casefold() not in _ANCHOR_STOPWORDS
    }


def enrich_signal(signal: dict) -> dict:
    """Add specificity/commercial-quality dimensions to a normalized signal."""
    out = dict(signal)
    claim = str(out.get("text") or "")
    quote = str(out.get("supporting_quote") or "")
    combined = f"{claim} {quote}".strip()
    low = combined.casefold()
    numbers = evidence_numbers(combined)
    commercial = sum(1 for term in _COMMERCIAL_TERMS if term in low)
    named = len(evidence_terms(claim))
    quote_detail = len(evidence_terms(quote) - evidence_terms(claim))
    vague = sum(1 for term in _VAGUE_EVIDENCE if term in low)

    # Base type score remains useful, but concrete specificity can now move a
    # measurable launch above a shallow testimonial with the same nominal type.
    quality = float(out.get("score") or 0)
    quality += min(len(numbers), 3) * 2.4
    quality += min(named, 4) * 0.55
    quality += min(commercial, 3) * 1.2
    quality += min(quote_detail, 8) * 0.18
    quality -= vague * 2.5
    out.update({
        "quality_score": round(quality, 3),
        "number_count": len(numbers),
        "commercial_score": commercial,
        "quote_detail_score": quote_detail,
        "vague_score": vague,
    })
    return out


def role_signal_score(role: str, signal: dict) -> float:
    """Score how well one signal performs one variable's particular job."""
    kind = signal.get("type", "")
    score = float(signal.get("quality_score", signal.get("score", 0)))
    numbers = int(signal.get("number_count") or 0)
    commercial = int(signal.get("commercial_score") or 0)
    detail = int(signal.get("quote_detail_score") or 0)

    if role == "first_line":
        score += {"result": 6, "case_study": 5, "project": 4, "service": 2,
                  "framework": 3, "award": 2, "client": -1, "industry": -3}.get(kind, 0)
        score += min(numbers, 2) * 2.5
    elif role == "value_proposition":
        score += {"result": 7, "case_study": 7, "client": 1, "project": 2,
                  "award": 1, "service": 0}.get(kind, 0)
        score += min(commercial, 3) * 1.5
    elif role == "product_compliment":
        score += {"project": 8, "service": 7, "framework": 4, "case_study": 3,
                  "award": 1, "client": -2, "industry": -4}.get(kind, 0)
        score += min(detail, 6) * 0.45
    return score


def plan_core_assignments(signals: list[dict], roles: list[str]) -> dict[str, dict]:
    """Globally choose distinct evidence for the core variables.

    A tiny exhaustive search (at most 16P3 combinations) avoids the old greedy
    failure where the value proposition consumed the best first-line proof.
    """
    core_roles = [r for r in ("first_line", "value_proposition", "product_compliment")
                  if r in roles]
    if not core_roles or not signals:
        return {}
    candidates = sorted(signals, key=lambda s: float(s.get("quality_score", 0)),
                        reverse=True)[:16]
    best_score, best = float("-inf"), {}
    for chosen in permutations(candidates, len(core_roles)):
        total = sum(role_signal_score(role, sig)
                    for role, sig in zip(core_roles, chosen))
        # A varied plan reads like research rather than five rewrites of one page.
        source_count = len({s.get("source_url") for s in chosen if s.get("source_url")})
        type_count = len({s.get("type") for s in chosen if s.get("type")})
        total += max(0, source_count - 1) * 0.6 + max(0, type_count - 1) * 0.35
        if total > best_score:
            best_score = total
            best = dict(zip(core_roles, chosen))
    return best


def anchor_matches(text: str, assignment: dict) -> set[str]:
    """Distinctive assigned-evidence anchors that survive into generated copy."""
    normalized = normalize(text)
    evidence = " ".join([
        str(assignment.get("evidence") or ""),
        str(assignment.get("supporting_quote") or ""),
    ])
    matches = {n for n in evidence_numbers(evidence) if n in text}
    matches.update(term for term in evidence_terms(evidence)
                   if normalize(term) in normalized)
    return matches


def supporting_detail_matches(text: str, assignment: dict) -> set[str]:
    """Details from the quote beyond the short claim/project identity."""
    quote_terms = evidence_terms(assignment.get("supporting_quote", ""))
    claim_terms = evidence_terms(assignment.get("evidence", ""))
    normalized = normalize(text)
    return {term for term in quote_terms - claim_terms if normalize(term) in normalized}


def local_candidate_score(text: str, role: str, assignment: dict, fmt: dict) -> float:
    """Rank model candidates locally; higher is better."""
    text = str(text or "").strip()
    if not text:
        return -10_000
    words = re.findall(r"\b[\w'-]+\b", text)
    score = 20.0
    score += len(anchor_matches(text, assignment)) * 3.0
    score += len(supporting_detail_matches(text, assignment)) * 4.0
    score += len(evidence_numbers(text)) * 2.5
    minimum, maximum = fmt.get("min_words"), fmt.get("max_words")
    if minimum and len(words) < int(minimum):
        score -= (int(minimum) - len(words)) * 3
    if maximum and len(words) > int(maximum):
        score -= (len(words) - int(maximum)) * 3
    if role == "product_compliment":
        score += 3 if "?" in text else -8
    if role == "first_line":
        score += 2 if len(re.findall(r"[.!?]", text)) <= 1 else -4
    if text.casefold().startswith("and"):
        score -= 5
    return score
