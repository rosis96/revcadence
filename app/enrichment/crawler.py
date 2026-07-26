"""Website crawler: homepage + a few high-signal internal pages (about,
services, pricing...), cleaned to text. Patterns carried over from the proven
outbound_personalization pipeline (browser headers, content budgets)."""
import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
INTERESTING = ("about", "service", "product", "solution", "pricing", "team", "case", "industr",
               "who-we", "work", "portfolio", "result", "client", "story", "stories", "success",
               "resource", "approach", "expertise", "capabilit", "what-we")
TIMEOUT = 12

# Env cost levers — see ai.py note on the 22000-char runaway-spend incident.
import os  # noqa: E402


def _max_pages() -> int:
    return int(os.getenv("ENRICH_MAX_PAGES", "4"))


def _max_chars() -> int:
    return int(os.getenv("MAX_TOTAL_CONTENT_CHARS", "10000"))


def _clean(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "nav", "footer", "noscript", "svg", "form"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    return re.sub(r"\s{2,}", " ", text)


def normalize_url(website: str) -> str:
    website = (website or "").strip()
    if not website:
        return ""
    if not website.startswith(("http://", "https://")):
        website = "https://" + website
    return website


_SKIP_EXT = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".zip", ".mp4",
             ".mov", ".css", ".js", ".ico", ".woff", ".woff2", ".ttf", ".xml", ".rss")

# JS rendering (for SPA / JS-heavy sites). Configured via env — no browser install
# needed; a rendering API returns the fully-rendered HTML over HTTPS.
#   RENDER_PROVIDER = scrapingbee | scraperapi | browserless
#   RENDER_API_KEY  = <key>   (RENDER_API_URL optional, for browserless)
_THIN_CHARS = 400          # a page shorter than this is treated as JS-empty
_RENDER_TIMEOUT = 35


def render_enabled() -> bool:
    return bool(os.getenv("RENDER_API_KEY") and os.getenv("RENDER_PROVIDER"))


def _render_cap() -> int:
    return int(os.getenv("RENDER_MAX_PAGES", "15"))


def render_fetch(page_url: str) -> str:
    """Return JS-rendered HTML for a URL via the configured rendering API, or ''."""
    provider = os.getenv("RENDER_PROVIDER", "").lower()
    key = os.getenv("RENDER_API_KEY", "")
    if not (provider and key):
        return ""
    try:
        if provider == "scrapingbee":
            r = requests.get("https://app.scrapingbee.com/api/v1/",
                             params={"api_key": key, "url": page_url, "render_js": "true"}, timeout=_RENDER_TIMEOUT)
        elif provider == "scraperapi":
            r = requests.get("https://api.scraperapi.com/",
                             params={"api_key": key, "url": page_url, "render": "true"}, timeout=_RENDER_TIMEOUT)
        elif provider == "browserless":
            base = os.getenv("RENDER_API_URL", "https://chrome.browserless.io")
            r = requests.post(f"{base}/content?token={key}", json={"url": page_url}, timeout=_RENDER_TIMEOUT)
        else:
            return ""
        if r.status_code < 300 and r.text and len(r.text) > 200:
            return r.text
    except Exception:
        return ""
    return ""


def crawl_site(website: str, html_override: str = "", on_progress=None,
               max_pages: int = 0, max_chars: int = 0, follow_all: bool = False,
               render: bool = False) -> dict:
    """Returns {"url", "title", "meta_description", "text", "pages": [urls]}.
    html_override lets callers (tests, cached HTML) skip the network entirely.
    max_pages/max_chars (>0) override the env budgets — used for 'deep' research.
    follow_all=True crawls the WHOLE site (BFS across every same-domain page), not
    just high-signal pages — used to build the client brain from everything.
    render=True re-fetches JS-empty pages through the rendering API (SPA support)."""
    max_pages = max_pages or _max_pages()
    max_chars = max_chars or _max_chars()
    url = normalize_url(website)
    result = {"url": url, "title": "", "meta_description": "", "text": "", "pages": []}

    def note(msg):
        if on_progress:
            on_progress(msg)

    if html_override:
        soup = BeautifulSoup(html_override, "html.parser")
        result["title"] = soup.title.get_text(strip=True) if soup.title else ""
        md = soup.find("meta", attrs={"name": "description"})
        result["meta_description"] = (md.get("content") or "").strip() if md else ""
        result["text"] = _clean(soup)[:max_chars]
        result["pages"] = [url or "override"]
        return result

    if not url:
        return result

    note(f"fetching {url}")
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
    except Exception as e:
        result["error"] = f"homepage fetch failed: {e}"
        return result

    soup = BeautifulSoup(resp.text, "html.parser")
    do_render = render and render_enabled()
    host = urlparse(url).netloc
    seen = {url}
    queue = []

    def add_links(page_soup, base):
        for a in page_soup.find_all("a", href=True):
            full = urljoin(base, a["href"].split("#")[0]).split("?")[0].rstrip("/")
            if not full:
                continue
            p = urlparse(full)
            if p.scheme not in ("http", "https") or p.netloc != host or full in seen:
                continue
            if full.lower().endswith(_SKIP_EXT):
                continue
            if follow_all or any(k in full.lower() for k in INTERESTING):
                queue.append(full)
                seen.add(full)

    # Homepage: if it's a JS-empty shell, render it so we see real content + links.
    home_text = _clean(soup)
    if do_render and len(home_text) < _THIN_CHARS:
        rendered = render_fetch(url)
        if rendered:
            soup = BeautifulSoup(rendered, "html.parser")
            home_text = _clean(soup)
    result["title"] = soup.title.get_text(strip=True) if soup.title else ""
    md = soup.find("meta", attrs={"name": "description"})
    result["meta_description"] = (md.get("content") or "").strip() if md else ""
    page_texts = [[url, home_text]]      # [url, text] pairs so we can re-render thin ones
    result["pages"].append(url)

    add_links(soup, url)
    # BFS: fetch pages (static) and (when following all) discover deeper links from
    # each, bounded by max_pages and max_chars so it always terminates.
    total = len(home_text)
    while queue and len(result["pages"]) < max_pages and total < max_chars:
        link = queue.pop(0)
        note(f"fetching {link}")
        try:
            r = requests.get(link, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            s2 = BeautifulSoup(r.text, "html.parser")
            t = _clean(s2)
            page_texts.append([link, t])
            total += len(t)
            result["pages"].append(link)
            if follow_all:
                add_links(s2, link)
        except Exception:
            continue

    # Render pass: re-fetch JS-empty pages through the rendering API (cost-bounded —
    # only thin pages, up to RENDER_MAX_PAGES), replacing their text with real content.
    if do_render:
        rendered = 0
        cap = _render_cap()
        for pair in page_texts:
            if rendered >= cap:
                break
            if len(pair[1]) < _THIN_CHARS:
                note(f"rendering {pair[0]}")
                html = render_fetch(pair[0])
                if html:
                    pair[1] = _clean(BeautifulSoup(html, "html.parser"))
                    rendered += 1
        result["js_rendered"] = rendered

    result["text"] = " ".join(t for _, t in page_texts)[:max_chars]
    return result
