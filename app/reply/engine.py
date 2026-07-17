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


def enforce_style_rules(text: str, rules_text: str) -> str:
    """Deterministically enforce the handful of style rules an LLM tends to
    ignore even when told (em dashes are the classic 'AI tell'). Everything else
    is handled by injecting the rules into the prompt. Only acts when the
    operator's rules actually ask for it — never changes behavior otherwise."""
    if not text:
        return text
    r = (rules_text or "").lower()
    wants_no_dash = ("—" in (rules_text or "")) or any(
        k in r for k in ("em dash", "em-dash", "emdash", "no dash", "avoid dash", "without dash"))
    if wants_no_dash:
        for d in ("—", "–", "―"):
            text = text.replace(" " + d + " ", ", ").replace(d, ", ")
        text = re.sub(r"\s+,", ",", text)
        text = re.sub(r",\s*,", ",", text)
        text = re.sub(r",(?=\S)", ", ", text)
    return text


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
    """Remove a trailing sign-off the model/template added — on its own line
    ('Best regards,\\nRS'), inline ('… Regards, RS'), a bare name-placeholder
    line ('{{YourName}}'), or a non-standard closing the markers miss ('Looking
    forward to chatting,') — so the system appends exactly one clean signature."""
    body = (message or "").rstrip()
    lines = body.splitlines()

    def _trim_tail():
        # drop trailing blanks and lone placeholder lines like '{{YourName}}'
        while lines and (not lines[-1].strip()
                         or re.fullmatch(r"\s*\{\{[^{}]+\}\}\s*", lines[-1])):
            lines.pop()

    _trim_tail()
    # (a) valediction on its own line within the last 6 lines
    for i in range(len(lines) - 1, max(len(lines) - 6, -1), -1):
        if any(lines[i].strip().lower().startswith(m) for m in _SIG_MARKERS):
            del lines[i:]
            break
    else:
        # (a2) a short, comma-ended closing the markers don't cover
        #      ("Looking forward to chatting,", "Appreciate your help,")
        if lines and lines[-1].strip().endswith(",") and len(lines[-1].split()) <= 6:
            lines.pop()
    _trim_tail()
    body = "\n".join(lines).rstrip()

    # (b) inline sign-off tacked onto the final line ("… invitation. Regards, RS")
    lines = body.splitlines()
    if lines:
        last = lines[-1]
        m = re.search(r"[.!?]\s+((?:best|kind|warm)?\s*regards|cheers|thanks|thank you|sincerely|"
                      r"talk soon|speak soon|warmly)\b.*$", last, re.I)
        if m:
            lines[-1] = last[:m.start() + 1].rstrip()
            return "\n".join(lines).rstrip()
    return body


def _name_from_signoff(message: str) -> str:
    """Recover the name the model wrote under its own sign-off (e.g. after
    'Kind regards,\\n\\nRosis Sitoula'), so we don't lose it when Sender name is
    blank. Skips URLs / emails / initials-only lines."""
    lines = (message or "").rstrip().splitlines()
    for i in range(len(lines) - 1, max(len(lines) - 6, -1), -1):
        if any(lines[i].strip().lower().startswith(m) for m in _SIG_MARKERS):
            for j in range(i + 1, min(i + 4, len(lines))):
                cand = lines[j].strip().rstrip(",")
                if not cand:
                    continue
                low = cand.lower()
                if "{{" in cand or "}}" in cand:
                    return ""            # unresolved placeholder like {{YourName}} — not a name
                if "http" in low or "@" in cand or "." in cand.split()[0] or "/" in cand:
                    return ""            # it's a website/handle, not a name
                if len(cand) <= 3 and cand.isupper():
                    return ""            # initials only (e.g. "RS") — skip
                return cand
            break
    return ""


def add_signature(message: str, sender_name: str, website: str) -> str:
    # Effective name: configured Sender name first, else recover the name the AI
    # already signed with — NEVER emit "Best regards," + blank line + website.
    name = (sender_name or "").strip() or _name_from_signoff(message)
    body = strip_existing_signature(message)
    sig = "\n\nBest regards,"
    if name:
        sig += "\n" + name
    if website:
        sig += "\n" + website.strip()
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
    booking = (getattr(rws, "calendly_scheduling_url", "") or "").strip()
    greet = f"by first name ('{first}')" if first else "by first name"

    system = "\n".join(filter(None, [
        "You are an expert B2B email responder writing ONE reply on behalf of the client below. "
        "Work in strict order:",

        "STEP 1 — CLASSIFY. Read the prospect's LATEST inbound message and match it to exactly ONE of "
        "the RESPONSE TYPES using their intent + examples. Put that type's id in \"intent\". If nothing "
        "clearly matches, set human_review_needed=true and confidence \"low\" (do not force a type).",

        "STEP 2 — READ THE STAGE & URGENCY. Judge where the conversation is going and how ready the "
        "prospect is, and reply to THAT — not with a generic pitch:",
        "  • If they have ALREADY agreed to a call, asked to schedule, or show urgency (e.g. \"let's set "
        "up a call\", \"tomorrow\", \"send the invite\", \"yes let's talk\"): reply SHORT — a one-line "
        "acknowledgement, then propose times, then stop. Do NOT re-explain what we do; they are past that.",
        "  • If they asked a specific question (pricing, how it works, timing): answer THAT one thing "
        "concisely. Do not dump the full value proposition.",
        "  • Only give a fuller explanation of the offer when they are genuinely early/curious and asked "
        "for it.",

        "STEP 3 — FOLLOW THE FORMAT. If the matched response type has a template, keep its structure and "
        "only fill the placeholders — do not add extra pitch paragraphs. MATCH YOUR LENGTH TO THEIRS: "
        "never answer a short, ready-to-book message with a multi-paragraph pitch.",

        "SCHEDULING RULE (critical): Propose ONLY specific dates/times that appear verbatim in SCHEDULING "
        "CONTEXT below. If there is NO scheduling context, DO NOT invent any times — instead invite them "
        "to pick a time"
        + (f" via {booking}" if booking else " via the booking link") +
        ", or ask what times suit them. Never fabricate availability.",

        f"FORMATTING (main_reply AND every follow-up): open with a greeting line addressed to the prospect "
        f"{greet}, then a blank line, then short paragraphs separated by blank lines (a real email, never "
        "a wall of text). Use actual line breaks (\\n). Do NOT output the literal '{{firstName}}' — use "
        + (f"'{first}'" if first else "the real first name") +
        ". NEVER include a sign-off or signature (no 'Best', 'Regards', name, or website) — the system appends one.",

        "Return STRICT JSON: {\"intent\": str, \"confidence\": \"high|medium|low\", "
        "\"human_review_needed\": bool, \"main_reply\": str, \"followup_1\": str, … up to \"followup_6\"}.",

        (f"PROSPECT: first name = {first}"
         + (f", company = {prospect.get('company')}" if prospect.get("company") else "")) if first else "",
        "CLIENT PROFILE:\n" + json.dumps(rws.client_profile or {}),
        "RESPONSE TYPES (classify into exactly one; obey its rules/template/auto_send):\n"
        + json.dumps(fmt.get("response_types", [])),
        "FOLLOW-UP SPECS:\n" + json.dumps(fmt.get("followups", [])),
        (f"BOOKING LINK: {booking}" if booking else ""),
        ("MANDATORY OPERATOR RULES (obey every line):\n" + "\n".join(rules)) if rules else "",
    ]))

    convo = "\n\n".join(f"[{m.get('direction', '?').upper()}] {m.get('text', '')}" for m in thread)
    last_in = next((m.get("text", "") for m in reversed(thread) if m.get("direction") == "in"), "")
    prompt = ("EMAIL THREAD (oldest → newest):\n" + convo
              + (f"\n\nRESPOND TO THE PROSPECT'S LATEST MESSAGE:\n{last_in}" if last_in else "")
              + (("\n\nSCHEDULING CONTEXT (propose ONLY these real times):\n" + scheduling_context)
                 if scheduling_context else "\n\nSCHEDULING CONTEXT: none available — do NOT invent times."))
    return prompt, system


def generate_reply(rws, thread: list, scheduling_context: str = "", prospect: dict = None) -> dict:
    """THE single reply-generation path. Both the live worker and the Test Thread
    screen call this, so a paste-in test produces the SAME intent/decision/reply/
    follow-ups the production pipeline would — they can never drift apart.

    Returns: {intent, confidence, action, main_reply, followups[], model_ran}.
    main_reply/follow-ups are cleaned (name filled, style rules, spacing) but the
    signature is NOT appended here — the caller adds it at send/preview time so
    the exact same body is stored and sent."""
    prospect = prospect or {}
    first = (prospect.get("first_name") or "").strip()
    prompt, system = build_reply_prompt(rws, thread, scheduling_context=scheduling_context,
                                        prospect=prospect)
    ai = call_llm(prompt, system, build_ai_cfg(rws))

    def _clean(t):
        return normalize_reply(enforce_style_rules(fill_name(str(t or ""), first), rws.ai_rules))

    main = _clean(ai.get("main_reply", ""))
    followups = [_clean(ai.get(f"followup_{i}")) for i in range(1, 7) if ai.get(f"followup_{i}")]
    last_in = next((m.get("text", "") for m in reversed(thread) if m.get("direction") == "in"), "")
    action = decide_reply_action(ai, rws.reply_format or {}, last_in)
    # a detectable model fallback is never auto-sent (a stop/unsubscribe still wins)
    if ai.get("_fallback") and action == "send":
        action = "skip_enrich"
    return {
        "intent": str(ai.get("intent", "")),
        "confidence": str(ai.get("confidence", "")),
        "action": action,
        "main_reply": main,
        "followups": followups,
        "model_ran": not ai.get("_fallback"),
    }


# ---------------------------------------------------------------- platform sends (legacy fixes)
def lookup_instantly_reply_target(api_key: str, lead_email: str, campaign_id: str = "", diag: dict = None) -> dict:
    """Recover {reply_to_uuid, eaccount} from Instantly when the webhook didn't
    include them (e.g. a lead_interested / tag event): list the lead's emails via
    the API, pick the prospect's INBOUND email (ue_type 2 / from-address ==
    prospect) — its id is reply_to_uuid and its eaccount is the mailbox that
    received it. NEVER falls back to one of our sent emails (would reply to self).
    Returns {} on failure; `diag` (if provided) is filled with what happened so
    the caller can report a precise reason instead of a guess."""
    d = diag if diag is not None else {}
    d.update({"lead_email": lead_email, "reason": ""})
    if not (api_key and lead_email):
        d["reason"] = "no API key on the reply space" if not api_key else "lead has no email on record"
        return {}

    def _list(params):
        import time
        for attempt in range(2):
            try:
                r = requests.get("https://api.instantly.ai/api/v2/emails",
                                 headers={"Authorization": f"Bearer {api_key}"},
                                 params=params, timeout=20)
                d["http_status"] = r.status_code
                if r.status_code == 429 and attempt == 0:
                    time.sleep(2); continue
                if r.status_code >= 300:
                    d["reason"] = f"Instantly /emails returned HTTP {r.status_code}: {(r.text or '')[:160]}"
                    return []
                body = r.json()
                raw = body.get("items") or body.get("data") or (body if isinstance(body, list) else [])
                return [e for e in raw if isinstance(e, dict)]
            except Exception as e:
                d["reason"] = f"request error: {str(e)[:160]}"
                return []
        return []

    # do NOT filter by campaign_id — received replies often have null campaign_id.
    items = _list({"search": lead_email, "email_type": "received",
                   "latest_of_thread": "true", "limit": 25})
    if not items:
        items = _list({"search": lead_email, "email_type": "received", "limit": 25})
    all_items = items
    if not all_items:
        all_items = _list({"search": lead_email, "limit": 25})
    d["total_emails"] = len(all_items)

    def from_addr(e):
        return str(e.get("from_address_email") or e.get("from_email")
                   or (e.get("from_address_json") or {}).get("email") or "").lower()

    le = str(lead_email).lower()
    received = [e for e in all_items if e.get("ue_type") == 2 or from_addr(e) == le]
    d["received_emails"] = len(received)
    pick = (next((e for e in received if e.get("ue_type") == 2 and from_addr(e) == le), None)
            or next((e for e in received if e.get("ue_type") == 2), None)
            or next((e for e in received if from_addr(e) == le), None))
    if not pick:
        if not d.get("reason"):
            if d.get("total_emails", 0) == 0:
                d["reason"] = (f"Instantly returned no emails for {lead_email} with this API key — "
                               "the key likely belongs to a different Instantly workspace than the "
                               "one that owns this campaign.")
            else:
                d["reason"] = (f"found {d['total_emails']} email(s) for {lead_email} but none received "
                               "FROM the prospect — can't reply without their inbound email.")
        return {}
    uuid = pick.get("id") or pick.get("uuid") or pick.get("message_id")
    eaccount = pick.get("eaccount") or pick.get("email_account")
    if not (uuid and eaccount):
        d["reason"] = "found the prospect's email but it lacked an id or eaccount field."
        return {}
    d["reason"] = "ok"
    return {"reply_to_uuid": uuid, "eaccount": eaccount}


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


def _html_to_text(html: str) -> str:
    import html as _h
    if not html:
        return ""
    t = re.sub(r"(?i)<br\s*/?>", "\n", html)
    t = re.sub(r"(?i)</(p|div)>", "\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    return _h.unescape(t)


def fetch_instantly_thread(api_key: str, lead_email: str, campaign_id: str = "") -> list:
    """Reconstruct the FULL conversation for an Instantly lead so the AI reads
    the whole back-and-forth, not just the latest reply. Lists the lead's emails
    (oldest→newest), tags each as 'in' (ue_type 2 = received) or 'out', and
    strips each message's quoted history so every turn is clean. Returns []
    (caller falls back to the single webhook reply) on any failure."""
    if not (api_key and lead_email):
        return []
    params = {"lead": lead_email, "sort_order": "asc", "limit": 50}
    if campaign_id:
        params["campaign_id"] = campaign_id
    import time
    items = []
    for attempt in range(2):
        try:
            r = requests.get("https://api.instantly.ai/api/v2/emails",
                             headers={"Authorization": f"Bearer {api_key}"}, params=params, timeout=20)
            if r.status_code == 429 and attempt == 0:
                time.sleep(2); continue
            if r.status_code >= 300:
                return []
            items = r.json().get("items", []) or []
            break
        except Exception:
            return []
    thread = []
    for e in items:
        if not isinstance(e, dict):
            continue
        body = e.get("body") or {}
        raw = body.get("text") or _html_to_text(body.get("html", "")) or e.get("content_preview", "")
        text = strip_quoted_history(raw)          # just this turn, not the quoted chain
        if not text.strip():
            continue
        thread.append({"direction": "in" if e.get("ue_type") == 2 else "out",
                       "text": text, "at": e.get("timestamp_email") or e.get("timestamp_created")})
    return thread


def push_instantly_followups(rws, lead_email: str, campaign_id: str, followups: list, main_reply: str = "") -> dict:
    """Write the generated follow-ups onto the Instantly lead as custom variables
    (followup_1, followup_2, …) so an Instantly follow-up campaign/subsequence
    can send them. Per the API, PATCH-ing a lead's custom_variables also declares
    them on the campaign automatically. Returns {ok, written|error}."""
    api_key = decrypt(rws.api_key_enc)
    if not api_key:
        return {"ok": False, "error": "no Instantly API key on this reply space"}
    if not lead_email:
        return {"ok": False, "error": "no lead email to match in Instantly"}
    H = {"Authorization": f"Bearer {api_key}"}

    def _find_lead(scoped):
        body = {"contacts": [lead_email], "limit": 1}
        if scoped and campaign_id:
            body["campaign"] = campaign_id
        try:
            r = requests.post("https://api.instantly.ai/api/v2/leads/list", headers=H, json=body, timeout=20)
            if r.status_code >= 300:
                return None, f"leads/list HTTP {r.status_code}: {(r.text or '')[:160]}"
            items = r.json().get("items", [])
            return (items[0] if items else None), ""
        except Exception as e:
            return None, f"leads/list error: {str(e)[:160]}"

    lead, err = _find_lead(True)
    if lead is None and campaign_id:      # retry unscoped by campaign
        lead, err = _find_lead(False)
    if lead is None:
        return {"ok": False, "error": err or f"lead {lead_email} not found in Instantly"}
    lead_id = lead.get("id")

    cv = {f"followup_{i + 1}": (f or "") for i, f in enumerate(followups)}
    if main_reply:
        cv["ai_main_reply"] = main_reply
    try:
        r2 = requests.patch(f"https://api.instantly.ai/api/v2/leads/{lead_id}", headers=H,
                            json={"custom_variables": cv}, timeout=20)
        if r2.status_code >= 300:
            return {"ok": False, "error": f"patch lead HTTP {r2.status_code}: {(r2.text or '')[:160]}"}
    except Exception as e:
        return {"ok": False, "error": f"patch lead error: {str(e)[:160]}"}
    return {"ok": True, "written": len(cv), "lead_id": lead_id}


def send_instantly_reply(rws, send_meta: dict, message: str, subject: str = "") -> dict:
    """Replies to the PROSPECT'S inbound email (legacy fix: replying to our own
    last sent message sent replies to ourselves) using its eaccount as sender."""
    api_key = decrypt(rws.api_key_enc)
    if not api_key:
        raise RuntimeError("No Instantly API key set on this reply space (Setup → API key).")
    reply_to_uuid = send_meta.get("reply_to_uuid")
    eaccount = send_meta.get("eaccount")
    # Most Instantly webhooks (e.g. lead_interested) don't carry the reply target.
    # Recover it by looking up the prospect's inbound email via the API.
    diag = {}
    if not (reply_to_uuid and eaccount):
        found = lookup_instantly_reply_target(api_key, send_meta.get("lead_email"),
                                              send_meta.get("campaign_id"), diag=diag)
        reply_to_uuid = reply_to_uuid or found.get("reply_to_uuid")
        eaccount = eaccount or found.get("eaccount")
    # If we still can't find them, report the ACTUAL reason from the lookup.
    if not (reply_to_uuid and eaccount):
        reason = diag.get("reason") or "the reply target wasn't in the webhook and couldn't be found."
        raise RuntimeError("Couldn't send via Instantly — " + reason)
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
