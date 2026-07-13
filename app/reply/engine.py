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


# ---------------------------------------------------------------- names & spacing
# Fill literal name placeholders the model sometimes echoes verbatim, plus give a
# graceful fallback ("there") when we don't know the prospect's first name.
_NAME_TOKENS = re.compile(r"\{\{\s*(first[\s_]?name|firstname|fname|name|lead[\s_]?name)\s*\}\}", re.I)


def first_name_of(full: str) -> str:
    return (full or "").strip().split(" ")[0] if (full or "").strip() else ""


def fill_name(text: str, first_name: str) -> str:
    if not text:
        return text
    return _NAME_TOKENS.sub((first_name or "").strip() or "there", text)


def normalize_reply(text: str) -> str:
    """Tidy spacing so replies read like a real email: normalize newlines, trim
    trailing spaces, and collapse 3+ blank lines to a single blank line (one gap
    between paragraphs). Never merges paragraphs — only cleans up."""
    if not text:
        return ""
    lines = [ln.rstrip() for ln in str(text).replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    out, blanks = [], 0
    for ln in lines:
        if ln == "":
            blanks += 1
            if blanks <= 1 and out:      # at most one blank line, never leading
                out.append("")
        else:
            blanks = 0
            out.append(ln)
    return "\n".join(out).strip()


# ---------------------------------------------------------------- signatures (exactly one)
_SIG_MARKERS = ("best regards", "kind regards", "regards", "best,", "cheers", "thanks,",
                "thank you,", "sincerely", "warm regards", "warmly", "talk soon", "speak soon")


def strip_existing_signature(message: str) -> str:
    """Remove a trailing sign-off the model may have added, whether on its own
    line ('Best regards,\\nRS') or inline as the last line ('… Regards, RS'), so
    the system can append exactly one clean signature."""
    body = (message or "").rstrip()
    lines = body.splitlines()
    # (a) sign-off on its own line within the last 6 lines
    for i in range(len(lines) - 1, max(len(lines) - 6, -1), -1):
        if any(lines[i].strip().lower().startswith(m) for m in _SIG_MARKERS):
            return "\n".join(lines[:i]).rstrip()
    # (b) inline sign-off tacked onto the final line ("… invitation. Regards, RS")
    if lines:
        last = lines[-1]
        m = re.search(r"[.!?]\s+((?:best|kind|warm)?\s*regards|cheers|thanks|thank you|sincerely|"
                      r"talk soon|speak soon|warmly)\b.*$", last, re.I)
        if m:
            lines[-1] = last[:m.start() + 1].rstrip()
            return "\n".join(lines).rstrip()
    return body


def add_signature(message: str, sender_name: str, website: str) -> str:
    body = strip_existing_signature(message)
    sig = "\n\nBest regards,\n" + (sender_name or "").strip()
    if website:
        sig += f"\n{website.strip()}"
    return body + sig


# ---------------------------------------------------------------- quoted thread
def strip_quoted_history(text: str) -> str:
    """Return only the prospect's NEW message — drop everything from the first
    quoted block ('On … wrote:', a run of '>' lines, or '-----Original')
    so we don't re-quote the history that's already in their reply."""
    if not text:
        return ""
    t = str(text).replace("\r\n", "\n").replace("\r", "\n")
    m = re.search(r"\n\s*On .{0,160}? wrote:\s*\n", t)
    if m:
        t = t[:m.start()]
    out = []
    for ln in t.split("\n"):
        s = ln.lstrip()
        if s.startswith(">") or s.startswith("-----Original") or s.startswith("________"):
            break
        out.append(ln)
    return "\n".join(out).strip()


def build_reply_quote(name: str, email: str, date_str: str, new_message: str) -> tuple:
    """Gmail-style quote of the prospect's message → (html, text). Empty if there
    is nothing to quote."""
    import html as _html
    msg = strip_quoted_history(new_message)
    if not msg:
        return "", ""
    who = (name or "").strip() or (email or "").strip() or "they"
    when = (date_str or "").strip()
    hdr = (f"On {when}, " if when else "") + who + (f" <{email}>" if email else "") + " wrote:"
    text = f"\n\n{hdr}\n" + "\n".join("> " + ln for ln in msg.split("\n"))
    html_body = "<br>".join(_html.escape(ln) for ln in msg.split("\n"))
    html = (f'<br><br><div>{_html.escape(hdr)}</div>'
            f'<blockquote type="cite" style="margin:0 0 0 0.8ex;border-left:1px solid #ccc;padding-left:1ex;color:#555;">'
            f'{html_body}</blockquote>')
    return html, text


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
def build_reply_prompt(rws, thread: list, scheduling_context: str = "", prospect: dict = None) -> tuple:
    fmt = rws.reply_format or {}
    rules = [ln.strip() for ln in (rws.ai_rules or "").splitlines() if ln.strip()]
    prospect = prospect or {}
    first = (prospect.get("first_name") or "").strip()
    system = (
        "You are an expert B2B email responder writing on behalf of the client below. "
        "Read the prospect's energy and match their tone. STEP 0: if the matched response "
        "type has a template, keep its structure and only fill the placeholders. "
        "NEVER include a sign-off or signature (no 'Best', 'Regards', name, or website) — "
        "the system appends exactly one.\n"
        "FORMATTING (applies to main_reply AND every follow-up): open with a greeting line "
        + (f"addressed to the prospect by first name ('{first}')" if first
           else "addressed to the prospect by first name") +
        ", then a blank line, then the body as SHORT paragraphs separated by a blank line "
        "(a real email, never one dense wall of text), and a blank line before any closing "
        "question. Use actual line breaks (\\n). Do NOT output the literal token "
        "'{{firstName}}' — use the real first name" + (f" ('{first}')" if first else "") + ".\n"
        "Return STRICT JSON: {\"intent\": str, \"confidence\": \"high|medium|low\", "
        "\"human_review_needed\": bool, \"main_reply\": str, "
        "\"followup_1\": str, ... up to \"followup_6\"}.\n"
        + (f"PROSPECT: first name = {first}"
           + (f", company = {prospect.get('company')}" if prospect.get("company") else "") + "\n" if first else "") +
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
def lookup_instantly_reply_target(api_key: str, lead_email: str, campaign_id: str = "") -> dict:
    """Recover {reply_to_uuid, eaccount} from Instantly when the webhook didn't
    include them (e.g. a lead_interested / tag event). This is the exact method
    the previous working system used (find_instantly_reply_target): list the
    lead's emails via the API, pick the prospect's INBOUND email (from-address ==
    prospect) — its id is reply_to_uuid and its eaccount is the mailbox that
    received the reply — falling back to the most recent email. Returns {} on any
    failure (caller then reports the clear error)."""
    if not (api_key and lead_email):
        return {}

    def _list(params):
        # /api/v2/emails is rate-limited (~20 req/min) — retry once on 429.
        import time
        for attempt in range(2):
            try:
                r = requests.get("https://api.instantly.ai/api/v2/emails",
                                 headers={"Authorization": f"Bearer {api_key}"},
                                 params=params, timeout=20)
                if r.status_code == 429 and attempt == 0:
                    time.sleep(2); continue
                if r.status_code >= 300:
                    return []
                body = r.json()
                raw = body.get("items") or body.get("data") or (body if isinstance(body, list) else [])
                return [e for e in raw if isinstance(e, dict)]
            except Exception:
                return []
        return []

    # IMPORTANT: do NOT filter by campaign_id — a prospect's received reply
    # often has a null campaign_id and would be excluded (this was returning {}
    # and producing the "webhook didn't include them" error). Ask for received
    # emails only, newest thread first; fall back to all emails if none come back.
    items = _list({"search": lead_email, "email_type": "received",
                   "latest_of_thread": "true", "limit": 25})
    if not items:
        items = _list({"search": lead_email, "email_type": "received", "limit": 25})
    if not items:
        items = _list({"search": lead_email, "limit": 25})
    if not items:
        return {}

    def from_addr(e):
        return str(e.get("from_address_email") or e.get("from_email")
                   or (e.get("from_address_json") or {}).get("email") or "").lower()

    le = str(lead_email).lower()
    # Prefer a RECEIVED email actually from the prospect (ue_type 2 == Received).
    # Never fall back to one of OUR sent emails (ue_type 1/3) — replying to that
    # would send the reply back to ourselves. If we can't find an inbound target,
    # return {} so the caller reports a clear, honest error.
    pick = (next((e for e in items if e.get("ue_type") == 2 and from_addr(e) == le), None)
            or next((e for e in items if e.get("ue_type") == 2), None)
            or next((e for e in items if from_addr(e) == le), None))
    if not pick:
        return {}
    uuid = pick.get("id") or pick.get("uuid") or pick.get("message_id")
    eaccount = pick.get("eaccount") or pick.get("email_account")
    return {"reply_to_uuid": uuid, "eaccount": eaccount} if (uuid and eaccount) else {}


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
    qhtml, _ = build_reply_quote(send_meta.get("to_name"),
                                 send_meta.get("to_email") or send_meta.get("lead_email"),
                                 send_meta.get("reply_date", ""), send_meta.get("reply_text_new", ""))
    r = requests.post(f"{rws.base_url}/api/replies",
                      headers=bison_headers(api_key),
                      json={"reply_id": send_meta.get("reply_id"),
                            "message": message.replace("\n", "<br>") + qhtml,
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
    if not api_key:
        raise RuntimeError("No Instantly API key set on this reply space (Setup → API key).")
    reply_to_uuid = send_meta.get("reply_to_uuid")
    eaccount = send_meta.get("eaccount")
    # Some Instantly webhooks (e.g. lead_interested) don't carry the reply
    # target. Recover it from the lead's most recent email so we can still send.
    if not (reply_to_uuid and eaccount):
        found = lookup_instantly_reply_target(api_key, send_meta.get("lead_email"), send_meta.get("campaign_id"))
        reply_to_uuid = reply_to_uuid or found.get("reply_to_uuid")
        eaccount = eaccount or found.get("eaccount")
    # Instantly's reply API MUST know which email to reply to and from which
    # mailbox. If we still can't find them, say so plainly instead of letting
    # Instantly return a cryptic 400.
    missing = [k for k, v in (("reply_to_uuid", reply_to_uuid), ("eaccount", eaccount)) if not v]
    if missing:
        raise RuntimeError(
            "Instantly reply needs " + " and ".join(missing) + ", but the webhook payload didn't include "
            + ("it" if len(missing) == 1 else "them") + ". Make sure the Instantly webhook fires on the "
            "reply event (which carries the email id + sending account), not just a tag/status change.")
    # Gmail-style quoted thread so the reply reads like a real conversation.
    qhtml, qtext = build_reply_quote(send_meta.get("to_name"),
                                     send_meta.get("to_email") or send_meta.get("lead_email"),
                                     send_meta.get("reply_date", ""), send_meta.get("reply_text_new", ""))
    body_html = "<br>".join(message.splitlines()) + qhtml
    body_text = message + qtext
    try:
        r = requests.post("https://api.instantly.ai/api/v2/emails/reply",
                          headers={"Authorization": f"Bearer {api_key}"},
                          json={"reply_to_uuid": reply_to_uuid, "eaccount": eaccount,
                                "subject": subject or send_meta.get("subject", ""),
                                "body": {"html": body_html, "text": body_text}},
                          timeout=20)
    except requests.Timeout:
        raise RuntimeError("Instantly did not respond in time (timeout). Try again in a moment.")
    except requests.RequestException as e:
        raise RuntimeError(f"Could not reach Instantly: {e}")
    if r.status_code >= 300:
        raise RuntimeError(f"Instantly API {r.status_code}: {(r.text or '')[:400]}")
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
    """Backstop follow-up guard: any *campaign* OR *subsequence* field equal to
    the follow-up campaign id anywhere in the payload (legacy §8). Instantly runs
    follow-ups as a subsequence, so a reply that arrives on the follow-up
    subsequence must also be caught — not just one tagged with campaign_id."""
    if not target:
        return False
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = str(k).lower()
            if ("campaign" in key or "subsequence" in key) and str(v) == str(target):
                return True
            if scan_for_campaign_id(v, target):
                return True
    elif isinstance(obj, list):
        return any(scan_for_campaign_id(i, target) for i in obj)
    return False
