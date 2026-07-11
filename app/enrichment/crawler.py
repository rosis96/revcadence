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
INTERESTING = ("about", "service", "product", "solution", "pricing", "team", "case", "industr", "who-we")
MAX_PAGES = 4
MAX_CHARS = 9000
TIMEOUT = 12


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


def crawl_site(website: str, html_override: str = "", on_progress=None) -> dict:
    """Returns {"url", "title", "meta_description", "text", "pages": [urls]}.
    html_override lets callers (tests, cached HTML) skip the network entirely."""
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
        result["text"] = _clean(soup)[:MAX_CHARS]
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

    # follow a few same-domain, high-signal links
    host = urlparse(url).netloc
    seen, queue = {url}, []
    for a in soup.find_all("a", href=True):
        full = urljoin(url, a["href"].split("#")[0])
        if urlparse(full).netloc != host or full in seen:
            continue
        if any(k in full.lower() for k in INTERESTING):
            queue.append(full)
            seen.add(full)
    for link in queue[:MAX_PAGES - 1]:
        note(f"fetching {link}")
        try:
            r = requests.get(link, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            texts.append(_clean(BeautifulSoup(r.text, "html.parser")))
            result["pages"].append(link)
        except Exception:
            continue

    result["text"] = " ".join(texts)[:MAX_CHARS]
    return result
