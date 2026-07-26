"""Pure Client Brain schema and merge semantics.

Kept free of web/database imports so the update rules are easy to test and reuse.
"""
import json
import re


CLIENT_BRAIN_KEYS = [
    "client_name", "one_liner", "service_brief", "main_offer", "what_we_are_pitching",
    "target_outcome", "icp_summary", "industries", "services", "positioning",
    "methodology", "results_metrics", "proof_points", "testimonials",
    "target_titles", "tone", "case_studies", "problem_library", "objections",
]
_BRAIN_LIST_KEYS = {
    "industries", "services", "positioning", "methodology", "results_metrics",
    "proof_points", "testimonials", "target_titles", "case_studies",
    "problem_library", "objections",
}
_BRAIN_DICT_KEY = {
    "case_studies": lambda x: str(x.get("client", "")).strip().casefold(),
    "problem_library": lambda x: str(x.get("industry", "")).strip().casefold(),
    "objections": lambda x: str(x.get("objection", ""))[:60].strip().casefold(),
    "testimonials": lambda x: (
        str(x.get("who", "")).strip().casefold()
        + "|"
        + str(x.get("quote", ""))[:40].casefold()
    ),
}


def _items(value):
    if value in (None, "", [], {}):
        return []
    return list(value) if isinstance(value, list) else [value]


def _present(value):
    return value not in (None, "", [], {})


def _norm(value):
    if isinstance(value, str):
        return re.sub(r"[\W_]+", " ", value.casefold()).strip()
    return json.dumps(value, sort_keys=True, ensure_ascii=False).casefold()


def _merge_value(old, fresh):
    """Merge nested knowledge while treating new scalar facts as authoritative."""
    if not _present(fresh):
        return old
    if isinstance(old, dict) and isinstance(fresh, dict):
        result = dict(old)
        for field, value in fresh.items():
            if _present(value):
                result[field] = _merge_value(result.get(field), value)
        return result
    if isinstance(fresh, list):
        combined, seen = [], set()
        for item in _items(old) + fresh:
            key = _norm(item)
            if key and key not in seen:
                seen.add(key)
                combined.append(item)
        return combined
    return fresh


def merge_brain_list(key, existing, new):
    """Accumulate a Brain list, enriching matching structured entities."""
    items = _items(existing) + _items(new)
    if key in _BRAIN_DICT_KEY:
        identity = _BRAIN_DICT_KEY[key]
        by, keyless, keyless_seen = {}, [], set()
        for item in items:
            if not isinstance(item, dict):
                continue
            entity_key = identity(item)
            if not entity_key:
                fingerprint = _norm(item)
                if fingerprint not in keyless_seen:
                    keyless_seen.add(fingerprint)
                    keyless.append(item)
            elif entity_key in by:
                by[entity_key] = _merge_value(by[entity_key], item)
            else:
                by[entity_key] = item
        return list(by.values()) + keyless

    seen, output = set(), []
    for item in items:
        normalized = _norm(item)
        if normalized and normalized not in seen:
            seen.add(normalized)
            output.append(item)
    return output


def accumulate_brain(existing: dict, new: dict, scalar_strategy: str = "replace") -> dict:
    """Merge knowledge without erasing fields omitted from the new material.

    ``replace`` lets explicit operator corrections win even when shorter.
    ``richer`` makes automated refreshes conservative for scalar descriptions.
    """
    merged = {**(existing or {})}
    for key, value in (new or {}).items():
        if key not in CLIENT_BRAIN_KEYS or not _present(value):
            continue
        if key in _BRAIN_LIST_KEYS:
            merged[key] = merge_brain_list(key, merged.get(key), value)
        elif isinstance(value, str) and value.strip():
            fresh = value.strip()
            old = str(merged.get(key) or "").strip()
            if scalar_strategy == "replace" or not old or len(fresh) > len(old):
                merged[key] = fresh
    return merged
