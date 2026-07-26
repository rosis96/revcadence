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


def crawl_site(website: str, html_override: str = "", on_progress=None,
               max_pages: int = 0, max_chars: int = 0, follow_all: bool = False) -> dict:
    """Returns {"url", "title", "meta_description", "text", "pages": [urls]}.
    html_override lets callers (tests, cached HTML) skip the network entirely.
    max_pages/max_chars (>0) override the env budgets — used for 'deep' research.
    follow_all=True crawls the WHOLE site (BFS across every same-domain page), not
    just high-signal pages — used to build the client brain from everything."""
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
    result["title"] = soup.title.get_text(strip=True) if soup.title else ""
    md = soup.find("meta", attrs={"name": "description"})
    result["meta_description"] = (md.get("content") or "").strip() if md else ""
    texts = [_clean(soup)]
    result["pages"].append(url)

    # discover same-domain links (BFS when follow_all, else just high-signal pages)
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

    add_links(soup, url)
    # BFS: fetch pages and (when following all) discover deeper links from each,
    # bounded by max_pages and max_chars so it always terminates.
    total = len(texts[0])
    while queue and len(result["pages"]) < max_pages and total < max_chars:
        link = queue.pop(0)
        note(f"fetching {link}")
        try:
            r = requests.get(link, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            s2 = BeautifulSoup(r.text, "html.parser")
            t = _clean(s2)
            texts.append(t)
            total += len(t)
            result["pages"].append(link)
            if follow_all:
                add_links(s2, link)
        except Exception:
            continue

    result["text"] = " ".join(texts)[:max_chars]
    return result
