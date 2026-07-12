"""Reply engine — behavioral port of the legacy main.py. Every guard below was
a fixed production incident; see docs/REPLY_PORT_SPEC.md and the legacy
CLAUDE_HANDOFF §4 for the WHY of each one.

SAFETY: auto-send is gated behind AUTO_SEND_ENABLED (env, default OFF). Until
it's flipped, every would-be auto-send lands in Needs Review with action
'would_send' — so the port can run against real webhooks with zero send risk.
"""
import json
import os
import re

import requests

from ..crypto import decrypt

# ---------------------------------------------------------------- decision logic (legacy)
STOP_INTENTS = {"unsubscribe", "opt_out", "not_interested_final", "wrong_person",
                "out_of_office", "auto_reply", "automated"}
STOP_KEYWORDS = ("unsubscribe", "remove me", "stop emailing", "out of office",
                 "auto-reply", "automatic reply", "no longer with", "wrong person")
LEGACY_AUTO_SEND = {"simple_positive"}  # keyword fallback for old formats


def auto_send_types(reply_format: dict) -> set:
    types = {t.get("id") or t.get("type") for t in (reply_format or {}).get("response_types", [])
             if t.get("auto_send")}
    return {t for t in types if t} or LEGACY_AUTO_SEND


def decide_reply_action(ai_result: dict, reply_format: dict, prospect_text: str = "") -> str:
    """send / skip_enrich / stop — exact legacy semantics. STOP intents are
    never drafted-for-send or enriched, by design."""
    intent = str(ai_result.get("intent", "")).lower()
    text = (prospect_text or "").lower()
    if intent in STOP_INTENTS or any(k in text for k in STOP_KEYWORDS):
        return "stop"
    if ai_result.get("human_review_needed"):
        return "skip_enrich"
    if intent in auto_send_types(reply_format):
        return "send"
    return "skip_enrich"


def auto_send_enabled() -> bool:
    return os.getenv("AUTO_SEND_ENABLED", "0") == "1"


# ---------------------------------------------------------------- signatures (exactly one)
_SIG_MARKERS = ("best regards", "kind regards", "regards,", "best,", "cheers,", "thanks,",
                "thank you,", "sincerely", "warm regards")


def strip_existing_signature(message: str) -> str:
    lines = (message or "").rstrip().splitlines()
    for i in range(len(lines) - 1, max(len(lines) - 6, -1), -1):
        if any(lines[i].strip().lower().startswith(m) for m in _SIG_MARKERS):
            return "\n".join(lines[:i]).rstrip()
    return (message or "").rstrip()


def add_signature(message: str, sender_name: str, website: str) -> str:
    body = strip_existing_signature(message)
    sig = "\n\nBest regards,\n" + (sender_name or "").strip()
    if website:
        sig += f"\n{website.strip()}"
    return body + sig


# ---------------------------------------------------------------- LLM layer (legacy _call_llm)
_FALLBACK = {"intent": "human_review", "confidence": "low", "human_review_needed": True,
             "main_reply": "", "_fallback": True}


def _parse_llm_json(raw: str) -> dict:
    """Tolerates code fences and surrounding noise (legacy fix)."""
    if not raw:
        return dict(_FALLBACK)
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return dict(_FALLBACK)
    try:
        return json.loads(m.group(0))
    except Exception:
        try:
            return json.loads(m.group(0).replace("\n", " "))
        except Exception:
            return dict(_FALLBACK)


def _openai(prompt: str, system: str, api_key: str, model: str) -> dict:
    r = requests.post("https://api.openai.com/v1/chat/completions",
                      headers={"Authorization": f"Bearer {api_key}"},
                      json={"model": model.lower(),  # legacy fix: capitalized ids silently failed
                            "temperature": 0.6,
                            "response_format": {"type": "json_object"},
                            "messages": [{"role": "system", "content": system},
                                         {"role": "user", "content": prompt}]},
                      timeout=90)
    r.raise_for_status()
    return _parse_llm_json(r.json()["choices"][0]["message"]["content"])


def _gemini(prompt: str, system: str, api_key: str, model: str) -> dict:
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model.lower()}:generateContent",
        params={"key": api_key},
        json={"systemInstruction": {"parts": [{"text": system}]},
              "contents": [{"parts": [{"text": prompt}]}],
              "generationConfig": {"temperature": 0.6, "responseMimeType": "application/json"}},
        timeout=90)
    r.raise_for_status()
    return _parse_llm_json(r.json()["candidates"][0]["content"]["parts"][0]["text"])


def build_ai_cfg(rws) -> dict:
    """Per-workspace provider + key overrides falling back to global env keys."""
    return {
        "provider": (rws.ai_provider or "openai").lower(),
        "fallback": bool(rws.ai_fallback),
        "openai_key": decrypt(rws.openai_key_enc) or os.getenv("OPENAI_API_KEY", ""),
        "gemini_key": decrypt(rws.gemini_key_enc) or os.getenv("GEMINI_API_KEY", ""),
        "openai_model": os.getenv("REPLY_OPENAI_MODEL", "gpt-4.1"),
        "gemini_model": os.getenv("REPLY_GEMINI_MODEL", "gemini-2.5-pro"),
    }


def call_llm(prompt: str, system: str, cfg: dict) -> dict:
    order = ["openai", "gemini"] if cfg["provider"] == "openai" else ["gemini", "openai"]
    if not cfg["fallback"]:
        order = order[:1]
    for provider in order:
        key = cfg[f"{provider}_key"]
        if not key:
            continue
        for _ in range(2):  # retry once per provider
            try:
                out = (_openai if provider == "openai" else _gemini)(
                    prompt, system, key, cfg[f"{provider}_model"])
                if out and not out.get("_fallback"):
                    return out
            except Exception:
                continue
    return dict(_FALLBACK)  # detectable sentinel — never silently sent


# ---------------------------------------------------------------- prompt (legacy shape)
def build_reply_prompt(rws, thread: list, scheduling_context: str = "") -> tuple:
    fmt = rws.reply_format or {}
    rules = [ln.strip() for ln in (rws.ai_rules or "").splitlines() if ln.strip()]
    system = (
        "You are an expert B2B email responder writing on behalf of the client below. "
        "Read the prospect's energy and match their tone. STEP 0: if the matched response "
        "type has a template, keep its structure and only fill the placeholders. "
        "NEVER include a sign-off or signature — the system appends it. "
        "Return STRICT JSON: {\"intent\": str, \"confidence\": \"high|medium|low\", "
        "\"human_review_needed\": bool, \"main_reply\": str, "
        "\"followup_1\": str, ... up to \"followup_6\"}.\n"
        "CLIENT PROFILE:\n" + json.dumps(rws.client_profile or {}) +
        "\nRESPONSE TYPES (match the incoming reply to one; obey its rules/template/auto_send):\n"
        + json.dumps(fmt.get("response_types", [])) +
        "\nFOLLOW-UP SPECS:\n" + json.dumps(fmt.get("followups", [])) +
        ("\nMANDATORY OPERATOR RULES (obey every line):\n" + "\n".join(rules) if rules else "")
    )
    convo = "\n\n".join(f"[{m.get('direction', '?').upper()}] {m.get('text', '')}" for m in thread)
    prompt = ("EMAIL THREAD (oldest → newest):\n" + convo +
              (("\n\nSCHEDULING CONTEXT (propose ONLY these times):\n" + scheduling_context)
               if scheduling_context else ""))
    return prompt, system


# ---------------------------------------------------------------- platform sends (legacy fixes)
def bison_headers(api_key):
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def fetch_bison_thread(lead_id: str, api_key: str, base_url: str) -> list:
    thread = []
    try:
        sent = requests.get(f"{base_url}/api/leads/{lead_id}/sent-emails",
                            headers=bison_headers(api_key), timeout=30).json().get("data", [])
        for s in sent:
            thread.append({"direction": "out", "text": s.get("body") or s.get("text_body") or "",
                           "at": s.get("created_at")})
    except Exception:
        pass
    try:
        replies = requests.get(f"{base_url}/api/leads/{lead_id}/replies",
                               headers=bison_headers(api_key), timeout=30).json().get("data", [])
        for r in replies:
            thread.append({"direction": "in", "text": r.get("text_body") or r.get("body") or "",
                           "at": r.get("created_at"), "reply_id": r.get("id")})
    except Exception:
        pass
    return sorted(thread, key=lambda m: str(m.get("at") or ""))


def send_bison_reply(rws, send_meta: dict, message: str) -> dict:
    api_key = decrypt(rws.api_key_enc)
    r = requests.post(f"{rws.base_url}/api/replies",
                      headers=bison_headers(api_key),
                      json={"reply_id": send_meta.get("reply_id"),
                            "message": message.replace("\n", "<br>"),
                            "to_name": send_meta.get("to_name"),
                            "to_email": send_meta.get("to_email")},
                      timeout=45)
    r.raise_for_status()
    return {"ok": True}


def merge_bison_variables(rws, lead_id: str, new_vars: dict) -> dict:
    """Bison PUT replaces ALL custom variables — read existing, merge ours on
    top, retry dropping unknown-variable names the API rejects (legacy fix)."""
    api_key = decrypt(rws.api_key_enc)
    existing = {}
    try:
        got = requests.get(f"{rws.base_url}/api/leads/{lead_id}/custom-variables",
                           headers=bison_headers(api_key), timeout=30).json().get("data", [])
        existing = {v.get("name"): v.get("value") for v in got if v.get("name")}
    except Exception:
        pass
    merged = {**existing, **new_vars}
    for _ in range(4):
        r = requests.put(f"{rws.base_url}/api/leads/{lead_id}/custom-variables",
                         headers=bison_headers(api_key),
                         json={"custom_variables": [{"name": k, "value": v} for k, v in merged.items()]},
                         timeout=45)
        if r.status_code < 400:
            return {"ok": True, "written": len(merged)}
        bad = re.findall(r"custom variable named\s+([\w\-]+)", r.text)
        if not bad:
            return {"ok": False, "error": r.text[:300]}
        for b in bad:
            merged.pop(b, None)
    return {"ok": False, "error": "retries exhausted"}


def send_instantly_reply(rws, send_meta: dict, message: str, subject: str = "") -> dict:
    """Replies to the PROSPECT'S inbound email (legacy fix: replying to our own
    last sent message sent replies to ourselves) using its eaccount as sender."""
    api_key = decrypt(rws.api_key_enc)
    quote_html = send_meta.get("quote_html", "")
    body_html = "<br>".join(message.splitlines()) + (f"<br><br>{quote_html}" if quote_html else "")
    r = requests.post("https://api.instantly.ai/api/v2/emails/reply",
                      headers={"Authorization": f"Bearer {api_key}"},
                      json={"reply_to_uuid": send_meta.get("reply_to_uuid"),
                            "eaccount": send_meta.get("eaccount"),
                            "subject": subject or send_meta.get("subject", ""),
                            "body": {"html": body_html, "text": message}},
                      timeout=45)
    r.raise_for_status()
    return {"ok": True}


# ---------------------------------------------------------------- misc legacy helpers
def deep_find_lead_id(obj):
    """Recursively locate a lead id in a nested webhook payload (legacy)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("lead_id", "taggable_id") and v:
                return v
            found = deep_find_lead_id(v)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = deep_find_lead_id(item)
            if found:
                return found
    return None


def scan_for_campaign_id(obj, target: str) -> bool:
    """Backstop follow-up guard: any *campaign* field equal to the follow-up
    campaign id anywhere in the payload (legacy §8)."""
    if not target:
        return False
    if isinstance(obj, dict):
        for k, v in obj.items():
            if "campaign" in str(k).lower() and str(v) == str(target):
                return True
            if scan_for_campaign_id(v, target):
                return True
    elif isinstance(obj, list):
        return any(scan_for_campaign_id(i, target) for i in obj)
    return False
