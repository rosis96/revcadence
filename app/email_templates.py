"""HTML email templates.

Three constraints shape everything here, and they are why this looks nothing
like the app's CSS:

- **Tables, not flexbox.** Outlook renders mail through Word's layout engine.
  Grid, flex and modern positioning do not exist there.
- **Inline styles, not classes.** Gmail strips most of <style>, so every rule
  that matters for layout is written on the element itself. The <style> block is
  progressive enhancement only — the mail must be correct without it.
- **Literal colours.** CSS custom properties are unsupported across mail clients,
  so `var(--accent)` cannot be used. The values below are copied from
  styles.css's light theme and are the one place in the codebase where that is
  the right call: an email cannot read the stylesheet it is trying to match.

Every interpolated value is escaped. A workspace named `Ben & Jerry's <Co>` is
ordinary, and it must not be able to break the layout or inject markup.
"""
from html import escape

# Copied from styles.css :root — keep in step if the light theme moves.
INK = "#172033"
MUTED = "#5F6C80"
MUTED_2 = "#7D899A"
ACCENT = "#4F46E5"
BORDER = "#E1E6EF"
CARD = "#FFFFFF"
PAGE = "#F1F3F8"
SOFT = "#F7F9FC"
WARN_SOFT = "#FFF4E5"
WARN_BORDER = "#F0D9B5"
WARN_TEXT = "#A14C08"

LOGO_CID = "revcadence-wave"

_FONT = ("-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',"
         "Arial,sans-serif")
_MONO = "ui-monospace,SFMono-Regular,Menlo,Consolas,'Liberation Mono',monospace"


def _row(label: str, value: str, *, mono: bool = True, last: bool = False) -> str:
    """One credential line: label above the value, and the value in its own
    bordered box on a white ground.

    There is deliberately no copy button here. Mail clients strip JavaScript, so
    a copy button in an email cannot copy anything — it is a control that looks
    live and does nothing, which is worse than no control at all. The box does
    the same job the honest way: it makes the value a distinct, selectable
    target that a long-press or a double-click selects cleanly, on every client
    including Gmail, where a run of inline text would not.

    Label above value, not beside it — a long email address in a narrow column
    is the fastest way to break a mail layout.
    """
    border = "" if last else f"border-bottom:1px solid {BORDER};"
    family = _MONO if mono else _FONT
    return f"""
              <tr>
                <td style="padding:12px 16px;{border}">
                  <div style="font:600 11px/1.4 {_FONT};letter-spacing:.06em;
                    text-transform:uppercase;color:{MUTED_2};padding-bottom:6px;">{escape(label)}</div>
                  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
                    style="background:{CARD};border:1px solid {BORDER};border-radius:7px;">
                    <tr>
                      <td style="padding:9px 12px;font:500 14px/1.5 {family};color:{INK};
                        word-break:break-all;">{escape(value)}</td>
                    </tr>
                  </table>
                </td>
              </tr>"""


def client_invite_text(*, app_name: str, workspace_name: str, link: str,
                       email: str, password: str, name: str = "") -> str:
    """The plain-text part. Not a fallback nobody reads: it is what plain-text
    clients, screen readers and most spam filters actually see, so it carries the
    same information rather than 'view this in a browser'."""
    greeting = f"Hi {name.split()[0]}," if name.strip() else "Hello,"
    return (
        f"{greeting}\n\n"
        f"Your {workspace_name} workspace on {app_name} is ready.\n\n"
        f"Open it here:\n{link}\n\n"
        f"Sign in with:\n"
        f"  Email:    {email}\n"
        f"  Password: {password}\n\n"
        f"This password is temporary — you will be asked to choose your own the "
        f"first time you sign in, and it stops working once you do.\n\n"
        f"Inside you will find:\n"
        f"  - Overview — where your launch is and what it is waiting on\n"
        f"  - Launch Plan — every step between today and your first send\n"
        f"  - Docs and Whiteboards — what we are writing, as we write it\n"
        f"  - Email Sequences — the emails going out under your name, for your approval\n\n"
        f"Reply to this email if anything is unclear.\n\n"
        f"If you were not expecting this email, please ignore it and let us know.\n"
    )


def client_invite_html(*, app_name: str, workspace_name: str, link: str,
                       email: str, password: str, name: str = "") -> str:
    greeting = f"Hi {escape(name.split()[0])}," if name.strip() else "Hello,"
    ws = escape(workspace_name)
    safe_link = escape(link, quote=True)

    inside = "".join(
        f"""
              <tr>
                <td width="18" valign="top" style="padding:0 0 10px;font:700 14px/1.6 {_FONT};color:{ACCENT};">&#8226;</td>
                <td valign="top" style="padding:0 0 10px;font:400 14px/1.6 {_FONT};color:{MUTED};">
                  <span style="color:{INK};font-weight:600;">{escape(title)}</span> — {escape(blurb)}
                </td>
              </tr>"""
        for title, blurb in (
            ("Overview", "where your launch is, and what it is waiting on"),
            ("Launch Plan", "every step between today and your first send"),
            ("Docs & Whiteboards", "what we are writing, while we write it"),
            ("Email Sequences", "the emails going out under your name, for your approval"),
        )
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="x-apple-disable-message-reformatting">
<meta name="color-scheme" content="light">
<meta name="supported-color-schemes" content="light">
<title>Your {ws} workspace is ready</title>
<style>
  /* Progressive enhancement only — the layout above does not depend on it. */
  @media only screen and (max-width:620px) {{
    .rc-shell {{ width:100% !important; }}
    .rc-pad {{ padding-left:24px !important; padding-right:24px !important; }}
    .rc-btn a {{ display:block !important; }}
  }}
  a {{ color:{ACCENT}; }}
</style>
</head>
<body style="margin:0;padding:0;background:{PAGE};-webkit-font-smoothing:antialiased;">
  <!-- Inbox preview line. Hidden in the body; it is the second thing after the
       subject that decides whether this gets opened at all. -->
  <div style="display:none;max-height:0;overflow:hidden;opacity:0;mso-hide:all;">
    Your sign-in details for {ws} are inside — link, email and a temporary password.
    &#847;&zwnj;&nbsp;&#847;&zwnj;&nbsp;&#847;&zwnj;&nbsp;&#847;&zwnj;&nbsp;&#847;&zwnj;&nbsp;
  </div>

  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
    style="background:{PAGE};">
    <tr>
      <td align="center" style="padding:40px 12px;">

        <table role="presentation" class="rc-shell" width="600" cellpadding="0" cellspacing="0" border="0"
          style="width:600px;max-width:600px;">

          <!-- mark -->
          <tr>
            <td align="center" style="padding:0 0 26px;">
              <img src="cid:{LOGO_CID}" width="132" alt="{escape(app_name, quote=True)}"
                style="display:block;width:132px;max-width:132px;height:auto;border:0;outline:none;">
            </td>
          </tr>

          <tr>
            <td style="background:{CARD};border:1px solid {BORDER};border-radius:14px;">

              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td class="rc-pad" style="padding:38px 40px 0;">
                    <h1 style="margin:0 0 14px;font:650 24px/1.3 {_FONT};color:{INK};
                      letter-spacing:-.01em;">Your {ws} workspace is ready</h1>
                    <p style="margin:0 0 8px;font:400 15px/1.65 {_FONT};color:{MUTED};">{greeting}</p>
                    <p style="margin:0 0 26px;font:400 15px/1.65 {_FONT};color:{MUTED};">
                      We have set up your workspace on {escape(app_name)}. It is where you and our
                      team work from the same page — your launch, the work in progress, and
                      everything waiting on a decision.
                    </p>
                  </td>
                </tr>

                <!-- button. A table cell, not a padded <a>: Outlook ignores
                     padding on inline elements and the button collapses to text. -->
                <tr>
                  <td class="rc-pad" style="padding:0 40px 28px;">
                    <table role="presentation" cellpadding="0" cellspacing="0" border="0" class="rc-btn">
                      <tr>
                        <td align="center" bgcolor="{ACCENT}" style="border-radius:9px;">
                          <a href="{safe_link}" target="_blank"
                            style="display:inline-block;padding:14px 30px;font:600 15px/1 {_FONT};
                            color:#FFFFFF;text-decoration:none;border-radius:9px;">Open workspace</a>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>

                <!-- credentials. Each value sits in its own bordered box so it
                     is a selectable target rather than a run of body text. -->
                <tr>
                  <td class="rc-pad" style="padding:0 40px;">
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
                      style="background:{SOFT};border:1px solid {BORDER};border-radius:11px;">
                      <tr>
                        <td style="padding:12px 16px 4px;font:400 12.5px/1.5 {_FONT};color:{MUTED_2};">
                          Tap and hold (or double-click) a value to select and copy it.
                        </td>
                      </tr>
                      {_row("Sign-in link", link)}
                      {_row("Email", email)}
                      {_row("Temporary password", password, last=True)}
                    </table>
                  </td>
                </tr>

                <tr>
                  <td class="rc-pad" style="padding:16px 40px 0;">
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
                      style="background:{WARN_SOFT};border:1px solid {WARN_BORDER};border-radius:9px;">
                      <tr>
                        <td style="padding:12px 15px;font:400 13.5px/1.6 {_FONT};color:{WARN_TEXT};">
                          This password is temporary. You will be asked to choose your own the first
                          time you sign in, and this one stops working the moment you do.
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>

                <tr>
                  <td class="rc-pad" style="padding:30px 40px 0;">
                    <div style="height:1px;background:{BORDER};font-size:0;line-height:0;">&nbsp;</div>
                  </td>
                </tr>

                <tr>
                  <td class="rc-pad" style="padding:24px 40px 34px;">
                    <div style="font:600 12px/1.4 {_FONT};letter-spacing:.06em;text-transform:uppercase;
                      color:{MUTED_2};padding-bottom:14px;">What is inside</div>
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">{inside}
                    </table>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <tr>
            <td class="rc-pad" style="padding:24px 24px 0;">
              <p style="margin:0 0 8px;font:400 13px/1.65 {_FONT};color:{MUTED_2};text-align:center;">
                Button not working? Paste this into your browser:<br>
                <a href="{safe_link}" target="_blank" style="color:{ACCENT};word-break:break-all;">{escape(link)}</a>
              </p>
              <p style="margin:14px 0 0;font:400 13px/1.65 {_FONT};color:{MUTED_2};text-align:center;">
                Reply to this email if anything is unclear — it reaches your team directly.<br>
                If you were not expecting this, please ignore it and let us know.
              </p>
              <p style="margin:18px 0 0;font:400 12px/1.5 {_FONT};color:{MUTED_2};text-align:center;">
                Sent by {escape(app_name)}
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
