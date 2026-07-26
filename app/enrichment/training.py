"""Safe, versioned training packages for RevCadence workspaces.

The bridge deliberately exposes only the inputs that shape enrichment output.
Operational data (leads, emails, mailboxes, keys and secrets) is never exported.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timezone

from fastapi import HTTPException

from ..models.enrich import WorkspaceEvaluationCase

SCHEMA_VERSION = 1
CONFIG_FIELDS = (
    "profile", "icp_definition", "formats", "rules", "skip_title_gate",
    "skip_icp", "only_safe", "reading_level", "writer_model", "research_depth",
)
FORBIDDEN_KEY_PARTS = (
    "api_key", "apikey", "password", "secret", "access_token", "refresh_token",
    "bearer_token", "reset_token", "credential",
    "mailbox", "reoon_api_key", "reoon_api_key_enc",
)
READING_LEVELS = {
    "", "b2 business", "plain professional", "5th grade", "6th grade",
    "7th grade", "8th grade", "10th grade",
}
MODEL_RE = re.compile(r"^[A-Za-z0-9._-]{0,60}$")

B2_WRITING_RULE = (
    "Write in clear, natural B2-level business English. Use simple vocabulary and direct "
    "sentence structures. Prefer specific facts over sophisticated wording. Avoid academic "
    "language, corporate jargon, vague flattery, exaggerated or poetic praise, and unnecessarily "
    "complex sentences. Personalized first lines and product compliments should use B1–B2 English. "
    "Value propositions, references, and pitches should use B2 English; use advanced industry terms "
    "only when the exact term comes from the prospect's website and is necessary for accuracy."
)


def _json_copy(value):
    """Return a JSON-safe detached copy and reject non-JSON payloads."""
    try:
        return json.loads(json.dumps(value, ensure_ascii=False))
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, f"Training data must be valid JSON: {exc}") from exc


def _forbidden_keys(value, path="") -> list[str]:
    found = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_l = str(key).casefold()
            child_path = f"{path}.{key}" if path else str(key)
            if any(part in key_l for part in FORBIDDEN_KEY_PARTS):
                found.append(child_path)
            found.extend(_forbidden_keys(child, child_path))
    elif isinstance(value, list):
        for i, child in enumerate(value):
            found.extend(_forbidden_keys(child, f"{path}[{i}]"))
    return found


def config_state(cfg) -> dict:
    return {
        "profile": _json_copy(cfg.profile or {}),
        "icp_definition": cfg.icp_definition or "",
        "formats": _json_copy(cfg.formats or []),
        "rules": cfg.rules or "",
        "skip_title_gate": bool(cfg.skip_title_gate),
        "skip_icp": bool(cfg.skip_icp),
        "only_safe": bool(cfg.only_safe),
        # Blank legacy values intentionally mean the new safe default.
        "reading_level": cfg.reading_level or "b2 business",
        "writer_model": cfg.writer_model or "",
        "research_depth": cfg.research_depth or "standard",
    }


def evaluation_state(db, workspace_id: int) -> list[dict]:
    rows = (
        db.query(WorkspaceEvaluationCase)
        .filter(WorkspaceEvaluationCase.workspace_id == workspace_id)
        .order_by(WorkspaceEvaluationCase.id)
        .all()
    )
    return [{
        "name": row.name,
        "company": row.company or "",
        "website": row.website or "",
        "facts": _json_copy(row.facts or {}),
        "expected_outputs": _json_copy(row.expected_outputs or {}),
        "notes": row.notes or "",
        "active": bool(row.active),
    } for row in rows]


def workspace_state(db, cfg) -> dict:
    return {
        "config": config_state(cfg),
        "evaluation_cases": evaluation_state(db, cfg.workspace_id),
    }


def revision_hash(state: dict) -> str:
    raw = json.dumps(state, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def export_bundle(db, cfg, workspace_name: str) -> dict:
    state = workspace_state(db, cfg)
    return {
        "schema": "revcadence.workspace-training",
        "schema_version": SCHEMA_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "workspace": {"id": cfg.workspace_id, "name": workspace_name},
        "revision": revision_hash(state),
        **state,
        "safety": {
            "contains_leads": False,
            "contains_credentials": False,
            "allowed_content": list(CONFIG_FIELDS) + ["evaluation_cases"],
        },
    }


def _validate_config(raw) -> dict:
    if not isinstance(raw, dict):
        raise HTTPException(422, "config must be a JSON object.")
    unknown = sorted(set(raw) - set(CONFIG_FIELDS))
    if unknown:
        raise HTTPException(422, f"Unsupported config fields: {', '.join(unknown)}")
    out = _json_copy(raw)
    if "profile" in out and not isinstance(out["profile"], dict):
        raise HTTPException(422, "config.profile must be an object.")
    if "formats" in out:
        if not isinstance(out["formats"], list) or len(out["formats"]) > 100:
            raise HTTPException(422, "config.formats must contain at most 100 variables.")
        if any(not isinstance(item, dict) for item in out["formats"]):
            raise HTTPException(422, "Every format must be an object.")
    for key in ("icp_definition", "rules", "reading_level", "writer_model", "research_depth"):
        if key in out and not isinstance(out[key], str):
            raise HTTPException(422, f"config.{key} must be text.")
    if len(out.get("rules", "")) > 50_000:
        raise HTTPException(422, "Global rules are too large (50,000 character limit).")
    if len(json.dumps(out.get("profile", {}), ensure_ascii=False)) > 300_000:
        raise HTTPException(422, "Client Brain is too large (300,000 character limit).")
    if len(json.dumps(out.get("formats", []), ensure_ascii=False)) > 500_000:
        raise HTTPException(422, "Formats are too large (500,000 character limit).")
    if out.get("reading_level", "") not in READING_LEVELS:
        raise HTTPException(422, "Unsupported reading level.")
    if not MODEL_RE.fullmatch(out.get("writer_model", "")):
        raise HTTPException(422, "Writer model contains unsupported characters.")
    if out.get("research_depth", "standard") not in ("standard", "deep"):
        raise HTTPException(422, "Research depth must be standard or deep.")
    for key in ("skip_title_gate", "skip_icp", "only_safe"):
        if key in out and not isinstance(out[key], bool):
            raise HTTPException(422, f"config.{key} must be true or false.")
    return out


def _validate_evaluations(raw) -> list[dict]:
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > 100:
        raise HTTPException(422, "evaluation_cases must contain at most 100 cases.")
    out = []
    for i, value in enumerate(_json_copy(raw)):
        if not isinstance(value, dict):
            raise HTTPException(422, f"evaluation_cases[{i}] must be an object.")
        unknown = set(value) - {
            "name", "company", "website", "facts", "expected_outputs", "notes", "active",
        }
        if unknown:
            raise HTTPException(
                422, f"Unsupported evaluation fields in case {i + 1}: {', '.join(sorted(unknown))}",
            )
        name = str(value.get("name") or "").strip()
        if not name or len(name) > 255:
            raise HTTPException(422, f"evaluation_cases[{i}].name is required (max 255 characters).")
        facts = value.get("facts") or {}
        expected = value.get("expected_outputs") or {}
        if not isinstance(facts, dict) or not isinstance(expected, dict):
            raise HTTPException(422, f"evaluation_cases[{i}] facts and expected_outputs must be objects.")
        out.append({
            "name": name,
            "company": str(value.get("company") or "")[:255],
            "website": str(value.get("website") or "")[:2000],
            "facts": facts,
            "expected_outputs": expected,
            "notes": str(value.get("notes") or "")[:10_000],
            "active": bool(value.get("active", True)),
        })
    return out


def normalize_bundle(payload: dict, current_state: dict) -> dict:
    """Validate an import and return the complete proposed state.

    Imports can be a full exported bundle or a partial {"config": {...}} patch.
    Missing sections preserve the current workspace.
    """
    if not isinstance(payload, dict):
        raise HTTPException(422, "Training package must be a JSON object.")
    forbidden = _forbidden_keys(payload)
    if forbidden:
        raise HTTPException(
            422, "Training packages cannot contain credentials or operational secrets: "
            + ", ".join(forbidden[:8]),
        )
    schema_version = payload.get("schema_version", SCHEMA_VERSION)
    if schema_version != SCHEMA_VERSION:
        raise HTTPException(422, f"Unsupported training schema version: {schema_version}")
    raw_config = payload.get("config", payload.get("training"))
    if raw_config is None:
        # Allow a compact package containing config fields at the top level.
        raw_config = {key: payload[key] for key in CONFIG_FIELDS if key in payload}
    if not raw_config and "evaluation_cases" not in payload:
        raise HTTPException(422, "Training package contains no supported changes.")
    proposed = copy.deepcopy(current_state)
    proposed["config"].update(_validate_config(raw_config))
    if "evaluation_cases" in payload:
        proposed["evaluation_cases"] = _validate_evaluations(payload["evaluation_cases"])
    # Enforce an absolute package bound after normalization.
    if len(json.dumps(proposed, ensure_ascii=False)) > 1_500_000:
        raise HTTPException(422, "Training package exceeds the 1.5 MB safety limit.")
    return proposed


def _summary(value) -> str:
    if isinstance(value, list):
        return f"{len(value)} items"
    if isinstance(value, dict):
        return f"{len(value)} fields"
    if isinstance(value, bool):
        return "on" if value else "off"
    text = str(value or "").replace("\n", " ").strip()
    return text[:120] + ("…" if len(text) > 120 else "")


def state_diff(current: dict, proposed: dict) -> list[dict]:
    changes = []
    for key in CONFIG_FIELDS:
        before, after = current["config"].get(key), proposed["config"].get(key)
        if before != after:
            changes.append({
                "section": key,
                "before": _summary(before),
                "after": _summary(after),
            })
    before_evals, after_evals = current.get("evaluation_cases", []), proposed.get("evaluation_cases", [])
    if before_evals != after_evals:
        changes.append({
            "section": "evaluation_cases",
            "before": _summary(before_evals),
            "after": _summary(after_evals),
        })
    return changes


def apply_config_state(cfg, state: dict) -> None:
    data = state["config"]
    cfg.profile = _json_copy(data["profile"])
    cfg.icp_definition = data["icp_definition"]
    cfg.formats = _json_copy(data["formats"])
    cfg.rules = data["rules"]
    cfg.skip_title_gate = int(bool(data["skip_title_gate"]))
    cfg.skip_icp = int(bool(data["skip_icp"]))
    cfg.only_safe = int(bool(data["only_safe"]))
    cfg.reading_level = data["reading_level"]
    cfg.writer_model = data["writer_model"]
    cfg.research_depth = data["research_depth"]


def replace_evaluations(db, workspace_id: int, cases: list[dict]) -> None:
    db.query(WorkspaceEvaluationCase).filter(
        WorkspaceEvaluationCase.workspace_id == workspace_id,
    ).delete(synchronize_session=False)
    for case in cases:
        db.add(WorkspaceEvaluationCase(workspace_id=workspace_id, **_json_copy(case)))


def score_evaluation_case(expected_outputs: dict, actual_outputs: dict,
                          quality_failures: dict | None = None) -> dict:
    """Score a golden case without paying for a second AI critic.

    An expected variable may be a plain approved example, or:
      {"example": "...", "required_terms": ["Monstatek", "$2.8 million"]}
    Approved prose is shown for human comparison; required_terms are the stable
    deterministic contract because good copy need not match one sentence exactly.
    """
    quality_failures = quality_failures or {}
    rows = []
    for name, raw_spec in (expected_outputs or {}).items():
        spec = raw_spec if isinstance(raw_spec, dict) else {"example": str(raw_spec or "")}
        expected = str(spec.get("example") or "")
        required = [str(x).strip() for x in (spec.get("required_terms") or []) if str(x).strip()]
        actual = str((actual_outputs or {}).get(name) or "").strip()
        missing = [term for term in required if term.casefold() not in actual.casefold()]
        failure = str(quality_failures.get(name) or "")
        score = 0
        if actual:
            score += 50
        if actual and not failure:
            score += 30
        if not required:
            score += 20 if actual and not failure else 0
        else:
            score += round(20 * (len(required) - len(missing)) / len(required))
        rows.append({
            "variable": name,
            "passed": bool(actual and not failure and not missing),
            "score": score,
            "actual": actual,
            "expected_example": expected,
            "required_terms": required,
            "missing_terms": missing,
            "quality_failure": failure,
        })
    overall = round(sum(row["score"] for row in rows) / len(rows)) if rows else 0
    return {
        "passed": bool(rows) and all(row["passed"] for row in rows),
        "score": overall,
        "variables": rows,
    }
