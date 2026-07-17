"""SMTP send + IMAP receive transport (v1: app-password over TLS).

All real network I/O lives here and nowhere else, so the service layer stays pure
and testable (tests monkeypatch `smtp_send` / `imap_fetch`). Swapping to an
OAuth/aggregator transport later means replacing only this file.
"""
import email
import imaplib
import smtplib
from email.message import EmailMessage


def smtp_test(host: str, port: int, username: str, password: str) -> tuple[bool, str]:
    """Verify we can authenticate for sending. Returns (ok, error)."""
    try:
        with smtplib.SMTP(host, int(port), timeout=20) as s:
            s.starttls()
            s.login(username, password)
        return True, ""
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:300]


def smtp_send(host: str, port: int, username: str, password: str, msg: EmailMessage) -> None:
    """Send a fully-built MIME message. Raises on failure."""
    with smtplib.SMTP(host, int(port), timeout=30) as s:
        s.starttls()
        s.login(username, password)
        s.send_message(msg)


def imap_fetch_unseen(host: str, port: int, username: str, password: str, limit: int = 25) -> list[dict]:
    """Fetch UNSEEN messages from the inbox and return parsed dicts. Marks them
    seen. Best-effort; returns [] on failure. Only transport — matching to a
    conversation happens in the service layer."""
    out = []
    try:
        m = imaplib.IMAP4_SSL(host, int(port))
        m.login(username, password)
        m.select("INBOX")
        typ, data = m.search(None, "UNSEEN")
        if typ != "OK":
            m.logout()
            return []
        ids = (data[0].split() or [])[-limit:]
        for num in ids:
            typ, msg_data = m.fetch(num, "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0][1]
            out.append(parse_message(raw))
        m.logout()
    except Exception:  # noqa: BLE001
        return out
    return out


def parse_message(raw: bytes) -> dict:
    """Parse a raw RFC822 message into the fields we care about (pure — unit tested)."""
    msg = email.message_from_bytes(raw)
    body = _plain_body(msg)
    return {
        "from_email": email.utils.parseaddr(msg.get("From", ""))[1].lower(),
        "to_email": email.utils.parseaddr(msg.get("To", ""))[1].lower(),
        "subject": msg.get("Subject", ""),
        "rfc_message_id": (msg.get("Message-ID", "") or "").strip(),
        "in_reply_to": (msg.get("In-Reply-To", "") or "").strip(),
        "references": (msg.get("References", "") or "").strip(),
        "body_text": body,
    }


def _plain_body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition", "")):
                try:
                    return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
                except Exception:  # noqa: BLE001
                    continue
        return ""
    try:
        return msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", "replace")
    except Exception:  # noqa: BLE001
        return msg.get_payload() or ""
