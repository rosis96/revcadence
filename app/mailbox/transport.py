"""SMTP send + IMAP receive transport (v1: app-password over TLS).

All real network I/O lives here and nowhere else, so the service layer stays pure
and testable (tests monkeypatch `smtp_send` / `imap_fetch`). Swapping to an
OAuth/aggregator transport later means replacing only this file.
"""
import email
import imaplib
import smtplib
import socket
from email.message import EmailMessage


# ---------------------------------------------------------------------------
# Force IPv4. Many container hosts publish no IPv6 route, but Gmail/Outlook
# resolve to an AAAA (IPv6) record first — Python then tries IPv6 and fails with
# "[Errno 101] Network is unreachable" before it ever reaches IPv4. Resolving the
# A record ourselves and connecting to it (while keeping the hostname for TLS
# SNI/cert checks) avoids that whole class of failure.
# ---------------------------------------------------------------------------
def _ipv4_addr(host: str, port: int) -> tuple:
    infos = socket.getaddrinfo(host, int(port), socket.AF_INET, socket.SOCK_STREAM)
    if not infos:
        raise OSError(f"No IPv4 address found for {host}")
    return infos[0][4]   # (ip, port)


class _SMTP4(smtplib.SMTP):
    """smtplib.SMTP that dials over IPv4 only (hostname preserved for TLS)."""
    def _get_socket(self, host, port, timeout):
        return socket.create_connection(_ipv4_addr(host, port), timeout, self.source_address)


class _SMTP_SSL4(smtplib.SMTP_SSL):
    """smtplib.SMTP_SSL (implicit TLS, port 465) that dials over IPv4 only."""
    def _get_socket(self, host, port, timeout):
        sock = socket.create_connection(_ipv4_addr(host, port), timeout, self.source_address)
        return self.context.wrap_socket(sock, server_hostname=self._host)


class _IMAP4_SSL4(imaplib.IMAP4_SSL):
    """imaplib.IMAP4_SSL that dials over IPv4 only (hostname preserved for SNI)."""
    def _create_socket(self, timeout=None):
        sock = socket.create_connection(_ipv4_addr(self.host, self.port), timeout)
        return self.ssl_context.wrap_socket(sock, server_hostname=self.host)


def _open_smtp(host: str, port: int, username: str, password: str, timeout: int):
    """Open + authenticate one SMTP session. Port 465 = implicit TLS (SSL);
    anything else = STARTTLS. Caller closes."""
    port = int(port)
    if port == 465:
        s = _SMTP_SSL4(host, port, timeout=timeout)
    else:
        s = _SMTP4(host, port, timeout=timeout)
        s.starttls()
    s.login(username, password)
    return s


# Submission ports to try, in order, when the configured one is blocked. Some
# hosts filter 587 but allow 465 (or vice-versa); we try the other before failing.
def _smtp_ports(port: int) -> list[int]:
    port = int(port)
    order = [port]
    for alt in (587, 465):
        if alt not in order:
            order.append(alt)
    return order


def smtp_test(host: str, port: int, username: str, password: str) -> tuple[bool, str]:
    """Verify we can authenticate for sending. Returns (ok, error). Tries the
    configured port, then falls back to the other submission port."""
    first_err = ""
    for p in _smtp_ports(port):
        try:
            s = _open_smtp(host, p, username, password, timeout=15)
            try:
                s.quit()
            except Exception:  # noqa: BLE001
                pass
            return True, ""
        except Exception as e:  # noqa: BLE001
            first_err = first_err or str(e)[:300]
    return False, first_err


def smtp_send(host: str, port: int, username: str, password: str, msg: EmailMessage) -> None:
    """Send a fully-built MIME message. Raises on failure. Tries the configured
    port, then the other submission port before giving up."""
    last_err = None
    for p in _smtp_ports(port):
        try:
            s = _open_smtp(host, p, username, password, timeout=25)
            try:
                s.send_message(msg)
            finally:
                try:
                    s.quit()
                except Exception:  # noqa: BLE001
                    pass
            return
        except Exception as e:  # noqa: BLE001
            last_err = e
    if last_err:
        raise last_err


def imap_fetch_unseen(host: str, port: int, username: str, password: str, limit: int = 25) -> list[dict]:
    """Fetch UNSEEN messages from the inbox and return parsed dicts. Marks them
    seen. Best-effort; returns [] on failure. Only transport — matching to a
    conversation happens in the service layer."""
    out = []
    try:
        m = _IMAP4_SSL4(host, int(port), timeout=15)
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


def imap_fetch_since(host: str, port: int, username: str, password: str,
                     days: int = 60, limit: int = 200, folder: str = "INBOX") -> list[dict]:
    """Backfill: fetch messages received in the last `days` from a folder, WITHOUT
    marking them read (readonly select + BODY.PEEK). Best-effort; returns [] on
    failure or an unknown folder."""
    import datetime as _dt
    out = []
    try:
        m = _IMAP4_SSL4(host, int(port), timeout=15)
        m.login(username, password)
        typ, _ = m.select(folder, readonly=True)   # readonly → never sets \Seen
        if typ != "OK":
            m.logout()
            return []
        since = (_dt.date.today() - _dt.timedelta(days=max(1, days))).strftime("%d-%b-%Y")
        typ, data = m.search(None, f"(SINCE {since})")
        if typ != "OK":
            m.logout()
            return []
        ids = (data[0].split() or [])[-limit:]
        for num in ids:
            typ, msg_data = m.fetch(num, "(BODY.PEEK[])")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            out.append(parse_message(msg_data[0][1]))
        m.logout()
    except Exception:  # noqa: BLE001
        return out
    return out


def parse_message(raw: bytes) -> dict:
    """Parse a raw RFC822 message into the fields we care about (pure — unit tested).
    `participants` = every address on From/To/Cc (lowercased), for known-lead matching."""
    msg = email.message_from_bytes(raw)
    body = _plain_body(msg)
    participants = []
    for hdr in ("From", "To", "Cc"):
        for _, addr in email.utils.getaddresses(msg.get_all(hdr, [])):
            a = (addr or "").lower().strip()
            if a and a not in participants:
                participants.append(a)
    return {
        "from_email": email.utils.parseaddr(msg.get("From", ""))[1].lower(),
        "to_email": email.utils.parseaddr(msg.get("To", ""))[1].lower(),
        "cc": [a for _, a in email.utils.getaddresses(msg.get_all("Cc", []))],
        "participants": participants,
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
