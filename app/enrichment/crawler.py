"""Website crawler: homepage + a few high-signal internal pages (about,
services, pricing...), cleaned to text. Patterns carried over from the proven
outbound_personalization pipeline (browser headers, content budgets)."""
import json
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
               "simplification", "research", "method", "clarity", "lab")
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


def _page_type(url: str, title: str = "", text: str = "") -> str:
    """Classify a page so research can spend its token budget on proof first."""
    hay = f"{url} {title} {text[:500]}".lower()
    if any(k in hay for k in ("case-stud", "case stud", "success stor", "client stor", "impact")):
        return "case_study"
    if any(k in hay for k in ("/work", "our work", "portfolio", "project", "campaign")):
        return "work"
    if any(k in hay for k in ("methodolog", "framework", "process", "approach", "simplification")):
        return "methodology"
    if any(k in hay for k in ("service", "solution", "capabilit", "what-we-do")):
        return "services"
    if any(k in hay for k in ("client", "customer", "partner")):
        return "clients"
    if any(k in hay for k in ("award", "recognition")):
        return "awards"
    if any(k in hay for k in ("about", "team", "who-we")):
        return "about"
    return "homepage" if urlparse(url).path in ("", "/") else "other"


_PAGE_SCORES = {
    "case_study": 100, "work": 88, "methodology": 84, "clients": 82,
    "awards": 80, "services": 72, "about": 56, "homepage": 50, "other": 35,
}


def _candidate_score(url: str, hint: str = "") -> int:
    """Prioritise links that look like evidence, including image-card labels."""
    hay = f"{url} {hint}".lower()
    score = 0
    weighted = (
        (35, ("case stud", "success stor", "results", "impact")),
        (28, ("our work", "/work", "portfolio", "project", "campaign")),
        (24, ("method", "framework", "process", "simplification", "research", "clarity", "lab")),
        (20, ("client", "customer", "award")),
        (12, ("service", "solution", "about")),
    )
    for value, words in weighted:
        if any(w in hay for w in words):
            score = max(score, value)
    # Prefer concrete leaf pages over index pages when hints are otherwise equal.
    return score + min(urlparse(url).path.strip("/").count("/") * 2, 8)


def _image_metadata(soup: BeautifulSoup, page_url: str, page_type: str) -> list:
    """Extract useful visual context before BeautifulSoup text cleaning drops it.

    This cheap layer catches client logos and image-based card titles. A bounded
    subset is later eligible for multimodal analysis; decorative pixels never are.
    """
    out, seen = [], set()
    for img in soup.find_all("img"):
        candidates = [
            img.get("data-src"), img.get("data-lazy-src"), img.get("src"),
        ]
        for srcset in (img.get("data-srcset"), img.get("srcset")):
            if srcset:
                # The final srcset item is normally the highest-resolution asset.
                candidates.extend(
                    part.strip().split()[0] for part in srcset.split(",") if part.strip()
                )
        raw_src = next((str(x).strip() for x in candidates
                        if x and not str(x).strip().lower().startswith("data:")), "")
        src = urljoin(page_url, raw_src) if raw_src else ""
        parsed = urlparse(src)
        clean_path = parsed.path.lower()
        if parsed.scheme not in ("http", "https") or not parsed.netloc \
                or src in seen or clean_path.endswith((".gif", ".svg", ".ico")):
            continue
        seen.add(src)
        alt = (img.get("alt") or img.get("title") or img.get("aria-label") or "").strip()
        parent = img.find_parent(["figure", "a", "div"])
        caption = ""
        if parent:
            cap = parent.find("figcaption")
            caption = cap.get_text(" ", strip=True) if cap else ""
        filename = src.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
        context = " ".join(x for x in (alt, caption, filename) if x)
        low = context.lower()
        relevance = _PAGE_SCORES.get(page_type, 30)
        if any(k in low for k in ("logo", "client", "case", "award", "work", "project", "result")):
            relevance += 25
        if alt or caption:
            relevance += 10
        # Empty tracking/decoration images are not useful vision candidates.
        if not context or any(k in low for k in ("spacer", "pixel", "favicon", "facebook", "linkedin")):
            continue
        out.append({"url": src, "alt": alt, "caption": caption, "filename": filename,
                    "page_url": page_url, "page_type": page_type, "relevance": relevance})
    return sorted(out, key=lambda x: -x["relevance"])[:30]


# Content-bearing keys inside embedded JSON (JSON-LD, __NEXT_DATA__, __NUXT__,
# generic application/json). Harvesting these recovers real text on JS-rendered
# sites WITHOUT a paid render key — the content ships in <script> tags that _clean
# strips, so on SPA/agency sites the visible HTML is an empty shell.
_JSON_CONTENT_KEYS = (
    "name", "title", "description", "headline", "text", "label", "caption", "body",
    "summary", "alt", "heading", "quote", "author", "client", "service", "subtitle",
    "excerpt", "content", "tagline", "role", "company", "industry", "result", "outcome",
    "award", "project", "partner", "value", "question", "answer", "richtext",
)
_META_CONTENT_PROPS = ("og:title", "og:description", "og:site_name",
                       "twitter:title", "twitter:description")


def _collect_json_strings(obj, out: list, key: str = "", depth: int = 0):
    """Pull human-readable string VALUES from content-bearing keys in embedded JSON."""
    if depth > 8 or len(out) > 400:
        return
    if isinstance(obj, str):
        s = obj.strip()
        if (key.lower() in _JSON_CONTENT_KEYS and 2 <= len(s) <= 400
                and not s.startswith(("http", "/", "#", "{", "["))
                and any(c.isalpha() for c in s)):
            out.append(s)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _collect_json_strings(v, out, str(k), depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            _collect_json_strings(v, out, key, depth + 1)


def _structured_text(soup: BeautifulSoup) -> str:
    """Render-free content recovery: OpenGraph/Twitter meta + JSON-LD + framework
    JSON payloads (__NEXT_DATA__/__NUXT__/application/json). This is what lets us
    read Next.js/Nuxt/Webflow sites that serve an empty shell to a static fetch."""
    parts = []
    for m in soup.find_all("meta"):
        prop = (m.get("property") or m.get("name") or "").lower()
        if prop in _META_CONTENT_PROPS and (m.get("content") or "").strip():
            parts.append(m["content"].strip())
    for sc in soup.find_all("script"):
        t = (sc.get("type") or "").lower()
        sid = (sc.get("id") or "").lower()
        if not (t in ("application/ld+json", "application/json") or sid in ("__next_data__", "__nuxt__")):
            continue
        raw = (sc.string or sc.get_text() or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        _collect_json_strings(data, parts)
    seen, out = set(), []
    for p in parts:
        k = p.lower()
        if k not in seen:
            seen.add(k)
            out.append(p)
    return " ".join(out)[:8000]


def _page_record(page_url: str, html: str) -> tuple[dict, BeautifulSoup]:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    md = soup.find("meta", attrs={"name": "description"})
    description = (md.get("content") or "").strip() if md else ""
    # Work on a second soup because _clean mutates it.
    text = _clean(BeautifulSoup(html, "html.parser"))
    # Recover embedded structured content (JSON-LD / framework payloads / OG meta)
    # so JS-rendered shells still yield real, checkable text without a render key.
    structured = _structured_text(soup)
    if structured:
        text = f"{text} {structured}".strip()
    kind = _page_type(page_url, title, text)
    images = _image_metadata(soup, page_url, kind)
    # Image labels are real page metadata and often the only names on portfolio grids.
    labels = [x["alt"] or x["caption"] for x in images if x["alt"] or x["caption"]]
    if labels:
        text = f"{text} Image labels: {'; '.join(labels[:30])}"
    record = {"url": page_url, "title": title, "meta_description": description,
              "page_type": kind, "score": _PAGE_SCORES.get(kind, 35),
              "text": text, "text_length": len(text), "images": images}
    return record, soup


def _render_recommended(html: str, record: dict, soup: BeautifulSoup) -> bool:
    """Detect hybrid/JS pages even when static navigation makes them look non-thin."""
    if record["text_length"] < _THIN_CHARS:
        return True
    raw = (html or "").lower()
    hydration = any(k in raw for k in ("__next_data__", "__nuxt__", "data-reactroot",
                                       "data-hydration", "webpackchunk", "application/ld+json"))
    lazy = len(soup.select("[data-src], [data-lazy-src], [loading='lazy']"))
    usable_links = len([a for a in soup.find_all("a", href=True) if a.get_text(" ", strip=True)])
    image_heavy = len(soup.find_all("img")) >= 8 and usable_links < 5
    return (hydration and usable_links < 8) or lazy >= 6 or image_heavy


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
    """Pull page URLs from direct sitemaps and bounded sitemap indexes."""
    out, seen, visited = [], set(), set()
    queue = [urljoin(base_url, sm) for sm in
             ("/sitemap.xml", "/sitemap-index.xml", "/sitemap_index.xml")]
    while queue and len(visited) < 8 and len(out) < 1000:
        sitemap_url = queue.pop(0)
        if sitemap_url in visited:
            continue
        visited.add(sitemap_url)
        try:
            r = requests.get(sitemap_url, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code >= 300 or "<" not in r.text:
                continue
            for m in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", r.text):
                m = m.split("#")[0].split("?")[0].rstrip("/")
                p = urlparse(m)
                if p.netloc != host:
                    continue
                if p.path.lower().endswith(".xml"):
                    if m not in visited and m not in queue:
                        queue.append(m)
                elif not p.path.lower().endswith(_SKIP_EXT) and m not in seen:
                    seen.add(m)
                    out.append(m)
        except Exception:
            continue
    return out[:1000]


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
            "pages_failed": 0, "fallback_method": "static", "signals_text_len": 0,
            "images_discovered": 0, "vision_candidates": 0, "page_types": {}}
    result = {"url": url, "title": "", "meta_description": "", "text": "",
              "pages": [], "page_records": [], "image_candidates": [], "diagnostics": diag}

    def note(msg):
        if on_progress:
            on_progress(msg)

    if html_override:
        rec, _ = _page_record(url or "override", html_override)
        result["title"] = rec["title"]
        result["meta_description"] = rec["meta_description"]
        result["text"] = rec["text"][:max_chars]
        result["pages"] = [url or "override"]
        result["page_records"] = [rec]
        result["image_candidates"] = rec["images"]
        diag.update({"fallback_method": "html_override", "pages_crawled": 1,
                     "raw_html_len": len(html_override), "signals_text_len": len(result["text"]),
                     "images_discovered": len(rec["images"]),
                     "vision_candidates": len(rec["images"]), "page_types": {rec["page_type"]: 1}})
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
        url = final.rstrip("/")
        result["url"] = url
        host = urlparse(url).netloc
    if html:
        diag["raw_html_len"] = len(html)

    # Homepage extraction. Render both empty SPA shells and hybrid pages whose
    # static HTML contains a header but hides the useful cards/links behind JS.
    home_rec, home_soup = _page_record(url, html) if html else (None, None)
    if do_render and (not html or _render_recommended(html, home_rec, home_soup)):
        note("rendering homepage")
        rhtml = render_fetch(url)
        if rhtml:
            html = rhtml
            home_rec, home_soup = _page_record(url, rhtml)
            diag["fallback_method"] = "render(home)" if not diag.get("raw_html_len") else "static+render(home)"
            diag["rendered_pages"] += 1
            diag["raw_html_len"] = max(diag["raw_html_len"], len(rhtml))

    if not html or not home_rec or not home_rec["text"]:
        # Research failed at the fetch/render stage — report it; DO NOT fabricate.
        result["error"] = (f"homepage returned no usable content (HTTP {status})"
                           if status else "homepage fetch failed")
        return result

    soup = home_soup
    result["title"] = home_rec["title"]
    result["meta_description"] = home_rec["meta_description"]
    page_records = [home_rec]
    result["pages"].append(url)

    seen = {url}
    fetched_final = {url}
    queue = []

    def add_candidate(full, hint=""):
        full = full.split("#")[0].split("?")[0].rstrip("/")
        if not full:
            return
        p = urlparse(full)
        if p.scheme not in ("http", "https") or p.netloc != host:
            return
        if full.lower().endswith(_SKIP_EXT):
            return
        score = _candidate_score(full, hint)
        if full in seen:
            # A sitemap often discovers a useful leaf page first with no context.
            # Upgrade that queued item when a work/case-study card later supplies
            # a meaningful label instead of leaving it at sitemap priority zero.
            for queued in queue:
                if queued["url"] == full and score > queued["score"]:
                    queued.update({"hint": hint, "score": score})
                    break
            return
        if follow_all or any(k in f"{full} {hint}".lower() for k in INTERESTING):
            queue.append({"url": full, "hint": hint, "score": score})
            seen.add(full)

    def add_links(page_soup, base):
        for a in page_soup.find_all("a", href=True):
            hint = a.get_text(" ", strip=True)
            if not hint:
                img = a.find("img")
                hint = (img.get("alt") or img.get("title") or "") if img else ""
            parent = a.find_parent(["article", "figure"])
            if parent:
                hint = f"{hint} {parent.get_text(' ', strip=True)[:240]}".strip()
                img = parent.find("img")
                if img:
                    hint = f"{hint} {img.get('alt') or ''}".strip()
            add_candidate(urljoin(base, a["href"]), hint)

    add_links(soup, url)
    diag["internal_links_found"] = len(queue)

    # Discovery: sitemap-indexed pages + common seed paths, so image/JS navs don't
    # hide the /work and case-study pages. Prioritise high-signal URLs to the front.
    discovered = _discover_sitemap(url, host)
    diag["sitemap_urls"] = len(discovered)
    for cand in discovered:
        add_candidate(cand, "sitemap")
    for path in _SEED_PATHS:
        add_candidate(urljoin(url, "/" + path), f"seed {path}")

    # Evidence-first crawl. Re-sort as work/index pages reveal case-study links.
    total = home_rec["text_length"]
    high_score_streak = 0
    while queue and len(result["pages"]) < max_pages and total < max_chars:
        # Python's stable sort preserves the site's editorial/card order for
        # equally strong pages. Alphabetical URL ordering buried flagship work.
        queue.sort(key=lambda x: -x["score"])
        pick = 0
        if high_score_streak >= 5:
            # Avoid spending the entire crawl on a large portfolio grid. Pull in
            # the strongest methodology/service page, then resume case studies.
            pick = next((i for i, q in enumerate(queue) if 20 <= q["score"] < 35), 0)
        item = queue.pop(pick)
        high_score_streak = high_score_streak + 1 if item["score"] >= 35 else 0
        link = item["url"]
        note(f"fetching {link}")
        h2, _st, _fin = _fetch_static(link)
        if not h2:
            diag["pages_failed"] += 1
            continue
        final_link = (_fin or link).split("#")[0].split("?")[0].rstrip("/")
        rec, s2 = _page_record(final_link, h2)
        if do_render and diag["rendered_pages"] < _render_cap() and _render_recommended(h2, rec, s2):
            note(f"rendering {link}")
            rhtml = render_fetch(link)
            if rhtml:
                rec, s2 = _page_record(final_link, rhtml)
                diag["rendered_pages"] += 1
        if final_link in fetched_final:
            if follow_all:
                add_links(s2, final_link)
            continue
        fetched_final.add(final_link)
        rec["discovery_hint"] = item["hint"]
        rec["score"] += min(item["score"], 30)
        page_records.append(rec)
        total += rec["text_length"]
        result["pages"].append(final_link)
        if follow_all:
            add_links(s2, final_link)

    # Preserve pages and provenance. Backward-compatible `text` is now ranked by
    # research value instead of network order, preventing navigation/about copy
    # from pushing case-study proof beyond the model's content window.
    page_records.sort(key=lambda x: (-x["score"], -x["text_length"], x["url"]))
    images, image_seen = [], set()
    type_counts = {}
    for rec in page_records:
        type_counts[rec["page_type"]] = type_counts.get(rec["page_type"], 0) + 1
        for image in rec["images"]:
            if image["url"] not in image_seen:
                image_seen.add(image["url"])
                images.append(image)
    images.sort(key=lambda x: -x["relevance"])
    result["page_records"] = page_records
    result["image_candidates"] = images[:20]
    result["text"] = " ".join(rec["text"] for rec in page_records)[:max_chars]
    result["js_rendered"] = diag["rendered_pages"]
    diag["pages_crawled"] = len(result["pages"])
    diag["signals_text_len"] = len(result["text"])
    diag["images_discovered"] = len(images)
    diag["vision_candidates"] = len(result["image_candidates"])
    diag["page_types"] = type_counts
    return result
