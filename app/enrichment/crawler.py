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
# A second, different browser fingerprint used on retry — some CDNs (Squarespace,
# Cloudflare) serve a different/empty response to the first UA but honour another.
_ALT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/",
}
INTERESTING = ("about", "service", "product", "solution", "pricing", "team", "case", "industr",
               "who-we", "work", "portfolio", "result", "client", "story", "stories", "success",
               "resource", "approach", "expertise", "capabilit", "what-we", "project", "insight",
               "simplification")
# Candidate pages to probe even when the homepage doesn't link them in crawlable
# HTML (common on image/JS nav) — the real proof usually lives here.
_SEED_PATHS = ("about", "about-us", "services", "work", "our-work", "case-studies",
               "case-study", "clients", "portfolio", "team", "insights", "projects",
               "results", "simplification", "what-we-do")
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


def _fetch_static(u: str):
    """Static GET with browser headers, redirects, and a second-fingerprint retry.
    Returns (html, status_code, final_url) or (None, status_code, None)."""
    status = None
    for h in (HEADERS, _ALT_HEADERS):
        try:
            r = requests.get(u, headers=h, timeout=TIMEOUT, allow_redirects=True)
            status = r.status_code
            if r.status_code < 400 and r.text:
                return r.text, r.status_code, str(r.url)
        except Exception:
            continue
    return None, status, None


def _discover_sitemap(base_url: str, host: str) -> list:
    """Pull indexed page URLs from /sitemap.xml (Squarespace, WordPress, etc.) so we
    find /work and case-study pages the homepage nav may not link in crawlable HTML."""
    out, seen = [], set()
    for sm in ("/sitemap.xml", "/sitemap-index.xml", "/sitemap_index.xml"):
        try:
            r = requests.get(urljoin(base_url, sm), headers=HEADERS, timeout=TIMEOUT)
            if r.status_code >= 300 or "<" not in r.text:
                continue
            for m in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", r.text):
                m = m.split("#")[0].split("?")[0].rstrip("/")
                p = urlparse(m)
                if p.netloc == host and not m.lower().endswith(_SKIP_EXT) and m not in seen:
                    seen.add(m)
                    out.append(m)
        except Exception:
            continue
    return out


def crawl_site(website: str, html_override: str = "", on_progress=None,
               max_pages: int = 0, max_chars: int = 0, follow_all: bool = False,
               render: bool = False) -> dict:
    """Returns {"url","title","meta_description","text","pages":[urls],"diagnostics":{...}}.
    html_override lets callers (tests, cached HTML) skip the network entirely.
    max_pages/max_chars (>0) override the env budgets — used for 'deep' research.
    follow_all=True crawls the WHOLE site (BFS across every same-domain page).
    render=True re-fetches JS-empty pages through the rendering API (SPA support).

    Fetch hierarchy per the fallback workflow: static → alt-headers retry → (when a
    render key is set) headless render → sitemap/seed-path discovery of internal
    pages. Every stage is recorded in `diagnostics` so a failure can be traced to
    fetching, rendering, extraction, or the model."""
    max_pages = max_pages or _max_pages()
    max_chars = max_chars or _max_chars()
    url = normalize_url(website)
    diag = {"http_status": None, "final_url": url, "raw_html_len": 0, "rendered_pages": 0,
            "internal_links_found": 0, "sitemap_urls": 0, "pages_crawled": 0,
            "pages_failed": 0, "fallback_method": "static", "signals_text_len": 0}
    result = {"url": url, "title": "", "meta_description": "", "text": "", "pages": [], "diagnostics": diag}

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
        diag.update({"fallback_method": "html_override", "pages_crawled": 1,
                     "raw_html_len": len(html_override), "signals_text_len": len(result["text"])})
        return result

    if not url:
        result["error"] = "no website"
        return result

    do_render = render and render_enabled()
    host = urlparse(url).netloc

    note(f"fetching {url}")
    html, status, final = _fetch_static(url)
    diag["http_status"] = status
    if final:
        diag["final_url"] = final
    if html:
        diag["raw_html_len"] = len(html)

    # Homepage extraction, with render fallbacks: render if static failed OR the
    # page is a JS-empty shell (and a render key is configured).
    home_text = _clean(BeautifulSoup(html, "html.parser")) if html else ""
    if do_render and (not html or len(home_text) < _THIN_CHARS):
        note("rendering homepage")
        rhtml = render_fetch(url)
        if rhtml:
            html = rhtml
            home_text = _clean(BeautifulSoup(rhtml, "html.parser"))
            diag["fallback_method"] = "render(home)" if not diag.get("raw_html_len") else "static+render(home)"
            diag["rendered_pages"] += 1
            diag["raw_html_len"] = max(diag["raw_html_len"], len(rhtml))

    if not html or not home_text:
        # Research failed at the fetch/render stage — report it; DO NOT fabricate.
        result["error"] = (f"homepage returned no usable content (HTTP {status})"
                           if status else "homepage fetch failed")
        return result

    soup = BeautifulSoup(html, "html.parser")
    result["title"] = soup.title.get_text(strip=True) if soup.title else ""
    md = soup.find("meta", attrs={"name": "description"})
    result["meta_description"] = (md.get("content") or "").strip() if md else ""
    page_texts = [[url, home_text]]
    result["pages"].append(url)

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

    add_links(soup, url)
    diag["internal_links_found"] = len(queue)

    # Discovery: sitemap-indexed pages + common seed paths, so image/JS navs don't
    # hide the /work and case-study pages. Prioritise high-signal URLs to the front.
    discovered = _discover_sitemap(url, host)
    diag["sitemap_urls"] = len(discovered)
    for cand in discovered + [urljoin(url, "/" + p) for p in _SEED_PATHS]:
        cand = cand.split("#")[0].split("?")[0].rstrip("/")
        if cand and cand not in seen and not cand.lower().endswith(_SKIP_EXT) \
                and urlparse(cand).netloc == host:
            seen.add(cand)
            if any(k in cand.lower() for k in INTERESTING):
                queue.insert(0, cand)   # high-signal first
            else:
                queue.append(cand)

    # BFS fetch (static, render thin pages later), bounded by max_pages/max_chars.
    total = len(home_text)
    while queue and len(result["pages"]) < max_pages and total < max_chars:
        link = queue.pop(0)
        note(f"fetching {link}")
        h2, _st, _fin = _fetch_static(link)
        if not h2:
            diag["pages_failed"] += 1
            continue
        s2 = BeautifulSoup(h2, "html.parser")
        t = _clean(s2)
        page_texts.append([link, t])
        total += len(t)
        result["pages"].append(link)
        if follow_all:
            add_links(s2, link)

    # Render pass: re-fetch JS-empty pages through the rendering API (cost-bounded).
    if do_render:
        cap = _render_cap()
        for pair in page_texts:
            if diag["rendered_pages"] >= cap:
                break
            if len(pair[1]) < _THIN_CHARS:
                note(f"rendering {pair[0]}")
                rhtml = render_fetch(pair[0])
                if rhtml:
                    pair[1] = _clean(BeautifulSoup(rhtml, "html.parser"))
                    diag["rendered_pages"] += 1

    result["text"] = " ".join(t for _, t in page_texts)[:max_chars]
    result["js_rendered"] = diag["rendered_pages"]
    diag["pages_crawled"] = len(result["pages"])
    diag["signals_text_len"] = len(result["text"])
    return result
