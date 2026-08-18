"""Central configuration. Everything comes from environment variables so the
same code runs locally (SQLite fallback) and on Railway (Postgres)."""
import os
from pathlib import Path

# Local development reads ./.env. `override=False` is the whole point: a real
# environment variable — Railway's, or one a test sets before importing this
# module — always beats the file, so the same code path serves both.
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
except ModuleNotFoundError:  # dotenv is optional; deployments set real env vars
    pass


def _env(name: str, default: str = "") -> str:
    """`os.getenv` with a default, treating an EMPTY value as absent.

    A key left blank in a .env file or a Railway variable set to "" both read as
    "" rather than None, which would otherwise defeat every default below —
    silently pointing the app at an empty database URL instead of the SQLite
    fallback it is supposed to land on."""
    return (os.getenv(name) or "").strip() or default


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _normalize_db_url(url: str) -> str:
    # Railway/Heroku legacy scheme
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


DATABASE_URL = _normalize_db_url(_env("DATABASE_URL", "sqlite:///./revcadence.db"))

# Secret used to sign JWTs. MUST be set in production (Railway → Variables).
JWT_SECRET = _env("JWT_SECRET", "dev-only-secret-change-me")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_HOURS = _env_int("ACCESS_TOKEN_HOURS", 720)  # 30 days — no constant re-login
REFRESH_TOKEN_DAYS = _env_int("REFRESH_TOKEN_DAYS", 180)  # sliding, persistent browser session
REFRESH_COOKIE_NAME = _env("REFRESH_COOKIE_NAME", "rc_refresh_token")

APP_NAME = "RevCadence"
VERSION = "0.1.0"

# ---------------------------------------------------------------- system mail
# Mail RevCadence sends AS ITSELF — client invites, credentials, notifications.
# Deliberately separate from campaign mail, which goes through a workspace's
# connected MailboxConnection: a brand-new client workspace has no mailbox yet,
# so the one message that creates the account cannot depend on one existing.
# Unset is a supported state — see app/mailer.py, which then reports "not
# configured" and hands the credentials back for the operator to deliver.
SMTP_HOST = _env("SMTP_HOST")
SMTP_PORT = _env_int("SMTP_PORT", 587)
SMTP_USERNAME = _env("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")   # not stripped: spaces can be significant
SMTP_FROM_EMAIL = _env("SMTP_FROM_EMAIL")
SMTP_FROM_NAME = _env("SMTP_FROM_NAME", APP_NAME)

# The origin used to build links inside those emails. Without it an invite would
# carry a link to nowhere, so the invite endpoint falls back to the request's own
# origin and this only has to be set when the app sits behind a proxy or CDN.
PUBLIC_BASE_URL = _env("PUBLIC_BASE_URL").rstrip("/")

# Where the client's workspace lives — e.g. https://app.revcadence.com.
#
# This is deliberately NOT PUBLIC_BASE_URL. That one is load-bearing for things
# only we should ever see: the OAuth redirect URI registered with Google and
# Microsoft, and the inbound capture endpoint clients paste into their own site.
# Repointing it at a client-facing host would break both. So the client host is
# its own setting, and the two can move independently.
#
# Unset is supported: links then fall back to the operator host's hash route,
# which serves the same screens. A working link in development beats a broken one
# in an email.
CLIENT_BASE_URL = _env("CLIENT_BASE_URL").rstrip("/")

# Hosts that serve the client app rather than the operator one. `app.<domain>` is
# recognised by prefix (see app/main.py); this is for anything that is not shaped
# that way, such as a client's own vanity domain.
CLIENT_HOSTS = tuple(h.strip().lower() for h in _env("CLIENT_HOSTS").split(",") if h.strip())


def client_workspace_url(slug: str = "", fallback: str = "") -> str:
    """The link we hand a client for their workspace.

    Prefers the client host, where a workspace is a real path — the address
    `https://app.revcadence.com/w/acme-inc` names the client, which is what
    belongs in an email. Without one configured it falls back to the operator
    host's hash route, which reaches the same screen.
    """
    slug = (slug or "").strip("/")
    if CLIENT_BASE_URL:
        return f"{CLIENT_BASE_URL}/w/{slug}" if slug else CLIENT_BASE_URL
    root = (PUBLIC_BASE_URL or fallback or "").rstrip("/")
    if not root:
        return ""
    return f"{root}/#/w/{slug}" if slug else f"{root}/#/w"


def client_form_url(token: str, fallback: str = "") -> str:
    """The link on a form invite. Same rule as the workspace link above: the
    client host if there is one, the operator host's hash route if there is not.

    A form is answered before the account exists, so this is often the first
    address a client ever sees from us. It belongs on the client host for the
    same reason the workspace does.
    """
    if CLIENT_BASE_URL:
        return f"{CLIENT_BASE_URL}/f/{token}"
    root = (PUBLIC_BASE_URL or fallback or "").rstrip("/")
    return f"{root}/#/f/{token}" if root else ""

# Worker poll interval (seconds) for the job queue.
WORKER_POLL_SECONDS = int(os.getenv("WORKER_POLL_SECONDS", "5"))
