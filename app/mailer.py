"""System mail — the messages RevCadence sends as itself.

Deliberately separate from campaign mail. Campaign mail goes out through a
workspace's connected `MailboxConnection`, under the client's own name. This is
the other kind: account invites, credentials, notices. Two reasons it cannot
share that path:

- A brand-new client workspace has no mailbox connected yet, and the very first
  message we send is the one that creates the account. It cannot depend on a
  mailbox that only gets connected later, from inside the account.
- It should come from us, not from the client's sending domain. Putting login
  credentials on a cold-outreach domain is how they end up in a spam folder.

Three sources, in order, so a deployment works with whatever it actually has:

1. `SMTP_*` environment variables — a real transactional mailbox for the org.
2. The workspace's own connected mailbox, if it has one.
3. Any active mailbox the operator's org has connected anywhere.

If none of those exist, `send_system_mail` returns `(False, reason)` rather than
raising. That is a supported state, not a failure to paper over: the caller shows
the operator the credentials and lets them deliver the message themselves. Mail
this important is never silently dropped.
"""
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

from . import config
from .models.onboarding import MailboxConnection


# The wave mark, rasterised for mail (see scripts/make_email_logo.py). Email
# clients do not render SVG, so the app's inline path cannot be reused directly.
LOGO_PATH = Path(__file__).resolve().parent / "assets" / "revcadence-wave.png"


def env_smtp_configured() -> bool:
    """True when the environment can send on its own, with no mailbox connected."""
    return bool(config.SMTP_HOST and config.SMTP_FROM_EMAIL
                and config.SMTP_USERNAME and config.SMTP_PASSWORD)


def _fallback_mailbox(db, workspace_id: int | None, org_workspace_ids: list | None):
    """The workspace's mailbox first, then any active one the org has. Ordered
    that way so an invite still looks like it came from the team that sent it."""
    from .mailbox import service
    if workspace_id:
        mailbox = service.workspace_mailbox(db, workspace_id)
        if mailbox is not None:
            return mailbox
    if not org_workspace_ids:
        return None
    return (db.query(MailboxConnection)
            .filter(MailboxConnection.workspace_id.in_(org_workspace_ids),
                    MailboxConnection.active == True)  # noqa: E712
            .order_by(MailboxConnection.id.desc()).first())


def _attach_html(msg: EmailMessage, html: str, inline_images: dict) -> None:
    """Add the HTML alternative and any inline images it references.

    The result is text/plain + multipart/related(html, images) inside a
    multipart/alternative. That nesting is what makes a `cid:` image render
    inline rather than arriving as a download — and what lets a plain-text
    client ignore the whole branch and still read the message.
    """
    msg.add_alternative(html, subtype="html")
    html_part = msg.get_payload()[-1]
    for cid, path in (inline_images or {}).items():
        try:
            data = Path(path).read_bytes()
        except OSError:
            continue   # a missing logo is not a reason to withhold credentials
        html_part.add_related(data, maintype="image", subtype="png", cid=f"<{cid}>",
                              filename=f"{cid}.png",
                              disposition="inline")


def send_system_mail(db, *, to_email: str, subject: str, body: str, to_name: str = "",
                     html: str | None = None, inline_images: dict | None = None,
                     workspace_id: int | None = None,
                     org_workspace_ids: list | None = None) -> tuple[bool, str]:
    """Send one message, plain text with an optional HTML alternative. Returns
    (sent, detail) and never raises — the caller decides what to do when mail is
    not available, and for credentials that decision is always "show them to the
    operator instead"."""
    to_email = (to_email or "").strip()
    if not to_email:
        return False, "No recipient address"

    msg = EmailMessage()
    msg["To"] = formataddr((to_name.strip(), to_email)) if to_name.strip() else to_email
    msg["Subject"] = subject
    msg.set_content(body)
    if html:
        _attach_html(msg, html, inline_images or {})

    if env_smtp_configured():
        msg["From"] = formataddr((config.SMTP_FROM_NAME, config.SMTP_FROM_EMAIL))
        try:
            from .mailbox import transport
            transport.smtp_send(config.SMTP_HOST, config.SMTP_PORT,
                                config.SMTP_USERNAME, config.SMTP_PASSWORD, msg)
            return True, f"Sent from {config.SMTP_FROM_EMAIL}"
        except Exception as e:  # noqa: BLE001
            return False, f"SMTP send failed: {str(e)[:200]}"

    mailbox = _fallback_mailbox(db, workspace_id, org_workspace_ids)
    if mailbox is None:
        return False, ("No system mailbox is configured. Set SMTP_HOST, SMTP_USERNAME, "
                       "SMTP_PASSWORD and SMTP_FROM_EMAIL, or connect a mailbox under "
                       "Settings → Email Accounts.")
    del msg["From"]
    msg["From"] = (formataddr((mailbox.from_name, mailbox.email))
                   if mailbox.from_name else mailbox.email)
    try:
        from .mailbox import service
        service.deliver_mime(mailbox, msg)
        return True, f"Sent from {mailbox.email}"
    except Exception as e:  # noqa: BLE001
        return False, f"Send failed via {mailbox.email}: {str(e)[:200]}"
