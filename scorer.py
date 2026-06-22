"""
Outdated-website scorer.

Takes a URL, fetches the page, parses the DOM, and returns:
- numeric score (0-100, higher = more outdated/uglier)
- list of triggered signals with evidence
- basic metadata (status code, final URL, page bytes)

The goal: high recall on "this site genuinely looks like it's from 2008".
Low scores on modern sites that just happen to be minimalist.

Usage:
    from scorer import score_url
    result = score_url("https://example.dk")
    print(result.score, result.signals)
"""
from __future__ import annotations

import re
import sys
import socket
import datetime as dt
from dataclasses import dataclass, field, asdict
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup, Comment

import os
USER_AGENT = (
    "Mozilla/5.0 (compatible; ColdOutreaches-LeadScout/0.1; "
    "+mailto:jakobwilbrandt@gmail.com)"
)
REQUEST_TIMEOUT = int(os.environ.get("SCORER_TIMEOUT", "12"))
THIS_YEAR = dt.date.today().year


@dataclass
class Signal:
    name: str
    points: int
    evidence: str = ""


@dataclass
class ScoreResult:
    url: str
    final_url: str = ""
    status: int = 0
    score: int = 0
    raw_score: int = 0           # before modern penalty
    modern_penalty: int = 0
    bytes_: int = 0
    error: str = ""
    signals: list[Signal] = field(default_factory=list)
    title: str = ""

    def to_dict(self):
        d = asdict(self)
        d["signals"] = [asdict(s) for s in self.signals]
        return d


# -------------------- fetch --------------------

def fetch(url: str) -> tuple[int, str, str, str, bytes]:
    """Returns (status, final_url, html, error, raw_bytes). Empty html on error."""
    try:
        # Ensure scheme
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        r = requests.get(
            url,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "da,en;q=0.7"},
            allow_redirects=True,
        )
        # Only treat HTML responses as scoreable content
        ctype = r.headers.get("content-type", "").lower()
        if "html" not in ctype and "xml" not in ctype:
            return r.status_code, r.url, "", f"non-html content-type: {ctype}", r.content
        # Some Danish sites are latin1 — let bs4 handle, but make sure text decodes
        return r.status_code, r.url, r.text, "", r.content
    except requests.exceptions.SSLError as e:
        # Retry over plain http — old sites often have broken SSL
        if url.startswith("https://"):
            try:
                r = requests.get(url.replace("https://", "http://", 1),
                                 timeout=REQUEST_TIMEOUT,
                                 headers={"User-Agent": USER_AGENT},
                                 allow_redirects=True)
                return r.status_code, r.url, r.text, f"ssl-fallback: {e.__class__.__name__}", r.content
            except Exception as e2:
                return 0, url, "", f"ssl+fallback-failed: {e2.__class__.__name__}", b""
        return 0, url, "", f"ssl: {e.__class__.__name__}", b""
    except (requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            socket.gaierror) as e:
        return 0, url, "", f"net: {e.__class__.__name__}", b""
    except Exception as e:
        return 0, url, "", f"err: {e.__class__.__name__}: {str(e)[:80]}", b""


# -------------------- detectors --------------------
# Each detector inspects (html, soup, url) and returns a Signal or None.

def detect_no_viewport(html, soup, url):
    if soup.find("meta", attrs={"name": re.compile(r"^viewport$", re.I)}):
        return None
    return Signal("no_viewport", 15, "no <meta name='viewport'> — not responsive")


def detect_generator_old(html, soup, url):
    g = soup.find("meta", attrs={"name": re.compile(r"^generator$", re.I)})
    if not g:
        return None
    content = (g.get("content") or "").lower()
    # Ancient builders — high confidence
    ancient = ["frontpage", "dreamweaver", "iweb", "golive",
               "microsoft office", "publisher", "namo webeditor",
               "openelement", "wysiwyg web builder", "kompozer", "nvu"]
    for b in ancient:
        if b in content:
            return Signal("generator_ancient", 15, f"<meta generator>={content[:80]}")
    # One.com Web Editor — the cheapest DK site-builder. STRONG lead signal.
    if "one.com web editor" in content or "one.com webeditor" in content:
        return Signal("generator_one_com", 18,
                      f"One.com Web Editor — cheap DK builder ({content[:60]})")
    # TYPO3 — old enterprise CMS, rare for new sites
    if "typo3" in content:
        return Signal("generator_typo3", 12,
                      f"TYPO3 CMS — old enterprise CMS ({content[:60]})")
    # Old Divi (WordPress theme builder) — 4.x is 2020-2022, 3.x older
    m = re.search(r"divi\s*v?\.?\s*([\d.]+)", content)
    if m:
        try:
            major = int(m.group(1).split(".")[0])
            if major <= 4:
                return Signal("generator_old_divi", 7,
                              f"old Divi {m.group(1)} ({content[:60]})")
        except ValueError:
            pass
    # Older Jimdo / Wix-free / Squarespace 5 / Mobirise
    if "mobirise" in content or "squarespace 5" in content:
        return Signal("generator_old_builder", 6, f"old builder ({content[:60]})")
    # Old WordPress
    m = re.search(r"wordpress\s*([\d.]+)", content)
    if m:
        try:
            major = int(m.group(1).split(".")[0])
            if major < 5:
                return Signal("generator_old_wp", 8,
                              f"old WordPress generator={content[:80]}")
        except ValueError:
            pass
    return None


def detect_table_layout(html, soup, url):
    tables = soup.find_all("table")
    if not tables:
        return None
    # Count tables that have NO <th> and many rows — likely layout
    layout_tables = 0
    for t in tables:
        if t.find("th"):
            continue
        rows = t.find_all("tr")
        if len(rows) >= 2:
            # Check role attribute
            if t.get("role") == "presentation":
                layout_tables += 1
                continue
            # Heuristic: width attribute or many nested tags = layout
            if (t.get("width") or t.get("cellpadding") or t.get("cellspacing")
                    or t.find("table")):
                layout_tables += 1
    if layout_tables >= 1:
        return Signal("table_layout", 12,
                      f"{layout_tables} layout-table(s) with width/cellpadding")
    return None


def detect_legacy_tags(html, soup, url):
    tags = ["font", "center", "marquee", "blink", "frameset", "frame", "applet"]
    found = []
    for t in tags:
        if soup.find(t):
            found.append(t)
    if not found:
        return None
    points = min(15, 8 * len(found))
    return Signal("legacy_tags", points, "tags: " + ",".join(found))


def detect_old_jquery(html, soup, url):
    # Look for jQuery 1.x in any script src
    scripts = soup.find_all("script", src=True)
    for s in scripts:
        src = s.get("src", "")
        m = re.search(r"jquery[/-]?([\d.]+)", src, re.I)
        if m:
            try:
                major = int(m.group(1).split(".")[0])
                if major < 2:
                    return Signal("old_jquery", 6, f"jQuery {m.group(1)} ({src[:70]})")
            except ValueError:
                pass
    return None


def detect_http_only(html, soup, url):
    """If we ended up on http:// after redirects, the site has no SSL maintenance."""
    if url.startswith("http://"):
        return Signal("http_only", 12, "no HTTPS (abandonment signal)")
    return None


def detect_old_copyright(html, soup, url):
    text = soup.get_text(" ", strip=True)[:8000]  # head + start of body
    # Find © YYYY or Copyright YYYY or &copy; YYYY patterns
    years = re.findall(r"(?:©|\(c\)|copyright|copyrights?)[\s ]*(\d{4})",
                       text, flags=re.I)
    if not years:
        # Also try a footer-only check
        footer = soup.find("footer") or soup.body
        if footer:
            years = re.findall(r"\b(20\d{2})\b", footer.get_text(" ", strip=True)[-300:])
    if not years:
        return None
    try:
        latest = max(int(y) for y in years if 2000 <= int(y) <= THIS_YEAR)
    except ValueError:
        return None
    gap = THIS_YEAR - latest
    if gap >= 3:
        return Signal("old_copyright", 6, f"latest year in page: {latest} ({gap}y old)")
    return None


def detect_fixed_width(html, soup, url):
    """Pre-responsive sites often have body { width: 960px } or wrapper width=980."""
    # Inline width attributes
    for el in soup.find_all(["body", "div", "table"], width=True):
        try:
            w = int(re.sub(r"[^\d]", "", str(el.get("width"))))
            if 700 <= w <= 1100:
                return Signal("fixed_width", 6,
                              f"<{el.name} width='{el.get('width')}'>")
        except (ValueError, TypeError):
            pass
    # CSS width on body/wrapper
    css_text = " ".join(s.get_text() for s in soup.find_all("style"))
    style_attrs = " ".join(el.get("style", "") for el in
                           soup.find_all(style=True))
    blob = css_text + " " + style_attrs
    m = re.search(r"width\s*:\s*(960|970|980|990|1000)px", blob)
    if m:
        return Signal("fixed_width", 5, f"CSS width: {m.group(1)}px (fixed)")
    return None


def detect_presentational_attrs(html, soup, url):
    """bgcolor, align, valign, color= on tags — pre-CSS arvegods."""
    bad_attrs = ["bgcolor", "background", "alink", "vlink", "link",
                 "topmargin", "leftmargin", "marginwidth", "marginheight"]
    count = 0
    for attr in bad_attrs:
        count += len(soup.find_all(attrs={attr: True}))
    # also count align= on non-cell elements
    aligns = soup.find_all(["body", "div", "p", "table"], align=True)
    count += len(aligns)
    if count == 0:
        return None
    if count >= 3:
        return Signal("presentational_attrs", 4,
                      f"{count} pre-CSS attributes (bgcolor/align/etc)")
    return None


def detect_flash_or_embed(html, soup, url):
    # .swf references and <embed>/<object> for movies
    if re.search(r"\.swf\b", html, re.I):
        return Signal("flash", 5, "found .swf reference")
    embed = soup.find("embed")
    if embed and (embed.get("type", "").startswith("application/x-shockwave")
                  or ".swf" in (embed.get("src") or "")):
        return Signal("flash_embed", 5, "<embed> with shockwave/swf")
    # GIF banner in header
    headers = soup.find_all(["header", "div"], limit=20)
    for h in headers:
        for img in h.find_all("img", limit=5):
            src = (img.get("src") or "").lower()
            if src.endswith(".gif") and "icon" not in src and "ico" not in src:
                return Signal("animated_gif_banner", 3,
                              f"GIF in header: {src[:60]}")
    return None


def detect_made_with_phrases(html, soup, url):
    text = html.lower()
    phrases = [
        "best viewed in", "optimized for internet explorer",
        "designed for 1024x768", "1024x768", "made with frontpage",
        "made with dreamweaver", "powered by simplesite",
        "hit counter", "you are visitor number",
        "guestbook", "underconstruction",
        "site map", "this site was last updated",
    ]
    found = [p for p in phrases if p in text]
    if not found:
        return None
    return Signal("retro_phrases", 5, "phrases: " + ", ".join(found[:3]))


def detect_no_favicon(html, soup, url):
    if soup.find("link", attrs={"rel": re.compile(r"icon", re.I)}):
        return None
    return Signal("no_favicon", 2, "no <link rel='icon'>")


def detect_no_og(html, soup, url):
    if soup.find("meta", attrs={"property": re.compile(r"^og:", re.I)}):
        return None
    if soup.find("script", attrs={"type": "application/ld+json"}):
        return None
    return Signal("no_og_or_jsonld", 3, "no OpenGraph and no JSON-LD")


def detect_no_modern_css(html, soup, url):
    """Likely pre-2017 layout: no flex/grid in any style, lots of floats."""
    css = " ".join(s.get_text() for s in soup.find_all("style"))
    inline = " ".join(el.get("style", "") for el in soup.find_all(style=True))
    blob = (css + " " + inline).lower()
    # Don't trigger if css blob is tiny (probably external)
    if len(blob) < 200:
        return None
    has_flex = "flex" in blob or "grid" in blob
    has_float = "float:" in blob or "float :" in blob
    if not has_flex and has_float:
        return Signal("css_floats_no_flex", 3,
                      "inline/embedded CSS uses float but no flex/grid")
    return None


def detect_old_doctype(html, soup, url):
    head = html[:300].lower()
    if "<!doctype html>" in head:
        return None
    if "xhtml" in head or "html 4.01" in head or "transitional" in head:
        return Signal("old_doctype", 4, "XHTML/HTML4 doctype")
    return None


def detect_parked_or_thin(html, soup, url):
    """A real business site has substantial content. A parked/sold domain is tiny
    or contains classic parking-page boilerplate."""
    body = soup.body
    text = body.get_text(" ", strip=True) if body else ""
    parking_phrases = [
        "domain is for sale", "buy this domain", "this domain is parked",
        "domain parking", "denne side er reserveret", "domænet er til salg",
        "this web site is currently unavailable",
        "find your hygge",  # one we saw in the wild
        "godaddy", "sedo", "namecheap",
    ]
    h = html.lower()
    if any(p in h for p in parking_phrases) and len(text) < 500:
        return Signal("parked_domain", -50,
                      f"likely parked/for-sale domain (body text: {len(text)} chars)")
    if len(html) < 1500 and len(text) < 200:
        return Signal("thin_or_stub", -30,
                      f"page too thin to be a real site: {len(html)} bytes html, "
                      f"{len(text)} chars text")
    return None


def detect_default_template(html, soup, url):
    """Sites built on Simplesite, Wix-free, old Jimdo etc. often have telltale markup."""
    indicators = {
        "simplesite": ("simplesite", 4),
        "homepage.dk": ("homepage.dk", 4),
        "easywebshop": ("easywebshop", 3),
        "old_jimdo": ("jimdo", 2),
    }
    h = html.lower()
    for key, (marker, pts) in indicators.items():
        if marker in h:
            return Signal(f"template_{key}", pts, f"hosting/builder hint: {marker}")
    return None


def detect_modern_stack(html, soup, url) -> int:
    """Return points to SUBTRACT from raw score if site is clearly modern."""
    penalty = 0
    h = html.lower()
    reasons = []
    # Frameworks
    if "/_next/" in h or "__next" in h:
        penalty += 15; reasons.append("Next.js")
    if "data-reactroot" in h or "react-dom" in h or '"__react"' in h:
        penalty += 8;  reasons.append("React")
    if "data-v-" in h and "vue" in h:
        penalty += 8;  reasons.append("Vue")
    if "svelte" in h and ("__svelte" in h or "svelte-" in h):
        penalty += 8;  reasons.append("Svelte")
    # Modern CSS frameworks
    if "tailwind" in h or re.search(r"class=\"[^\"]*\b(?:flex|grid|mx-auto|md:|lg:)\b", h):
        penalty += 10; reasons.append("Tailwind/utility CSS")
    if re.search(r"bootstrap[^\"]*[45]\.", h):
        penalty += 5;  reasons.append("Bootstrap 4/5")
    # Modern WP/Elementor — still might be ugly but it's not 2008
    if "elementor" in h or "wp-block" in h or "/wp-content/" in h:
        penalty += 3;  reasons.append("modern WordPress (blocks/Elementor)")
    return penalty, reasons




def detect_agency_built_modern(html, soup, url):
    """Penalise sites that combine multiple modern HTML markers — likely
    agency-built recently. Lighter penalty so genuine 'abandoned modern' sites
    (e.g. old Divi + http-only + animated gif) can still rank as leads."""
    score = 0
    reasons = []
    if soup.find("meta", attrs={"name": re.compile(r"^viewport$", re.I)}):
        score += 1
    if soup.find("meta", attrs={"property": re.compile(r"^og:", re.I)}):
        score += 1; reasons.append("og")
    if soup.find("script", attrs={"type": "application/ld+json"}):
        score += 1; reasons.append("jsonld")
    if soup.find("picture") or soup.find("img", srcset=True):
        score += 1; reasons.append("picture/srcset")
    blob = " ".join(s.get_text() for s in soup.find_all("style"))
    if re.search(r"display\s*:\s*(flex|grid)", blob.lower()):
        score += 1; reasons.append("flex/grid")
    if score == 5:
        return Signal("agency_built_modern", -10,
                      f"modern markers: {reasons}")
    if score == 4:
        return Signal("agency_built_partial", -4,
                      f"partial modern markers: {reasons}")
    return None

DETECTORS = [
    detect_parked_or_thin,   # run first — its negative score should kill false positives
    detect_no_viewport,
    detect_generator_old,
    detect_table_layout,
    detect_legacy_tags,
    detect_old_jquery,
    detect_http_only,
    detect_old_copyright,
    detect_fixed_width,
    detect_presentational_attrs,
    detect_flash_or_embed,
    detect_made_with_phrases,
    detect_no_favicon,
    detect_no_og,
    detect_no_modern_css,
    detect_old_doctype,
    detect_default_template,
    detect_agency_built_modern,
]


def check_name_match(soup, expected_name: str, final_url: str = "") -> Signal | None:
    """If we have a company name from OSM, check the site's title or h1 actually
    mentions it. Mismatch usually means hijacked/sold domain."""
    if not expected_name:
        return None
    title_l = (soup.title.string or "").lower() if (soup.title and soup.title.string) else ""
    h1 = soup.find("h1")
    h1_l = h1.get_text(" ").lower() if h1 else ""
    body_l = ""
    if soup.body:
        body_l = soup.body.get_text(" ", strip=True)[:800].lower()
    # Strip occurrences of the literal domain string from body — those tell us
    # nothing about whether the site actually talks about the business.
    if final_url:
        host = re.sub(r"^https?://(www\.)?", "", final_url.lower()).split("/")[0]
        # remove "domain.dk", "domain.com" and the bare slug "domain"
        body_l = body_l.replace(host, " ")
        slug = host.rsplit(".", 1)[0]
        # only strip slug if it's a multi-word domain like "china-house"
        if "-" in slug or "_" in slug:
            body_l = body_l.replace(slug, " ")
            for part in re.split(r"[.\-_]", slug):
                if len(part) >= 4 and part not in title_l and part not in h1_l:
                    body_l = body_l.replace(part, " ")
    bag = title_l + " " + h1_l + " " + body_l
    # Look for any non-trivial word from the business name
    words = [w.lower() for w in re.findall(r"[a-zæøåA-ZÆØÅ]{5,}", expected_name)]
    if not words:
        return None
    # Require all meaningful name words to appear somewhere; otherwise the
    # domain might have been sold/parked.
    missing = [w for w in words if w not in bag]
    if missing and len(missing) >= len(words):  # nothing matched at all
        return Signal("name_mismatch", -40,
                      f"none of {words[:3]} found - likely sold/parked")
    if missing and len(missing) >= max(1, len(words) // 2):
        title_l = (soup.title.string or "").lower() if soup.title else ""
        seller_phrases = ["book unique", "find your", "for sale", "stays today",
                          "click here", "domain", "we offer", "discover the",
                          "premium domain", "this domain", "hygge in",
                          "best deals", "available"]
        if any(p in title_l for p in seller_phrases):
            return Signal("name_mismatch_promo", -35,
                          f"missing {missing} + promo title: {title_l[:60]}")
    return None


# -------------------- main entrypoint --------------------

def score_url(url: str, expected_name: str = "") -> ScoreResult:
    status, final_url, html, error, raw = fetch(url)
    result = ScoreResult(url=url, final_url=final_url, status=status,
                        bytes_=len(raw), error=error)
    if not html or status >= 400 or status == 0:
        return result

    # Lenient parser — many legacy sites are unparseable as strict XHTML
    soup = BeautifulSoup(html, "lxml")
    # Title for the report
    if soup.title and soup.title.string:
        result.title = soup.title.string.strip()[:120]

    # Name-match check (only if we have a name)
    name_sig = check_name_match(soup, expected_name, final_url)
    if name_sig:
        result.signals.append(name_sig)

    for det in DETECTORS:
        try:
            sig = det(html, soup, final_url)
        except Exception as e:
            sig = None  # never let a detector crash the whole scoring
        if sig:
            result.signals.append(sig)

    raw_score = sum(s.points for s in result.signals)
    # Cap to 100 BEFORE penalty so a single signal can't blow past
    raw_score = min(raw_score, 100)
    penalty, modern_reasons = detect_modern_stack(html, soup, final_url)
    if modern_reasons:
        result.signals.append(Signal("modern_stack", -penalty,
                                     "modern: " + ", ".join(modern_reasons)))
    result.raw_score = raw_score
    result.modern_penalty = penalty
    result.score = max(0, raw_score - penalty)
    return result
