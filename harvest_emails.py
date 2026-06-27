"""Fill in missing contact emails for leads, so a built+drafted demo can actually
be sent. Two sources, most-reliable first:

  1. the lead's own website  — front page, several contact-ish pages, with
     de-obfuscation of "info [at] domæne [dot] dk" style addresses.
  2. the CVR registry (cvrapi.dk) — Danish company register; great for SMBs that
     only show a phone/contact form on their site. Guarded by a name/domain match
     so an ambiguous search ("Build1" -> "CNT BUILD A/S") never writes a wrong
     address.

  python3 harvest_emails.py --limit 40
  python3 harvest_emails.py --state demo_live   # just the stuck-without-email ones

Wired into run_nightly.sh before notion_sync. Best-effort and polite.
"""
from __future__ import annotations
import os, re, time, json, argparse, html as htmllib
from urllib.parse import urljoin, urlparse, quote
import requests
import store

UA = "ColdOutreaches-LeadScout/0.2 (jakobwilbrandt@gmail.com)"
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
JUNK = ("example.com", "sentry", "wixpress", "godaddy", "your-email", "domain.com",
        "email@", "name@", "@2x", ".png", ".jpg", ".webp", ".gif", "@sentry",
        "wordpress", "yoast", "schema.org", "u003e", "react", "core-js", "@sentry.io")
CONTACT_PATHS = ("kontakt", "kontakt-os", "om-os", "om", "about", "contact",
                 "kontakt.html", "kontakt.php", "find-os", "impressum", "privatliv")
GENERIC_PREFIXES = ("noreply", "no-reply", "postmaster", "mailer-daemon", "abuse")
_STOP = {"aps", "a/s", "as", "i/s", "is", "ivs", "v", "og", "the", "danmark", "dk"}


def deobfuscate(html: str) -> str:
    """Turn common anti-scrape spellings into real @ / . so EMAIL_RE can match."""
    html = htmllib.unescape(html)                       # &#64; -> @, &#46; -> .
    html = re.sub(r"\s*[\[\(\{]\s*(?:at|snabel-?a|æt)\s*[\]\)\}]\s*", "@", html, flags=re.I)
    html = re.sub(r"\s*[\[\(\{]\s*(?:dot|punktum|prik)\s*[\]\)\}]\s*", ".", html, flags=re.I)
    return html


def emails_from_html(html: str) -> list[str]:
    html = deobfuscate(html)
    found = re.findall(r'mailto:([^"\'?>\s]+)', html, flags=re.I)
    found += EMAIL_RE.findall(html)
    out, seen = [], set()
    for e in found:
        e = e.strip().strip(".").lower()
        if not e or e in seen:
            continue
        if any(j in e for j in JUNK) or any(e.startswith(g) for g in GENERIC_PREFIXES):
            continue
        seen.add(e)
        out.append(e)
    return out


def fetch(url: str) -> str:
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": UA}, allow_redirects=True)
        if r.ok and "text/html" in r.headers.get("Content-Type", "text/html"):
            return r.text
    except Exception:
        pass
    return ""


def best_email(candidates: list[str], domain: str) -> str | None:
    if not candidates:
        return None
    same = [e for e in candidates if domain and e.split("@")[-1].endswith(domain)]
    pool = same or candidates
    for pref in ("info@", "kontakt@", "mail@", "hej@", "kontor@"):
        for e in pool:
            if e.startswith(pref):
                return e
    return pool[0]


def _tokens(name: str) -> set[str]:
    name = re.sub(r"[^a-z0-9æøå ]", " ", (name or "").lower())
    return {t for t in name.split() if len(t) >= 3 and t not in _STOP}


def _label(host: str) -> str:
    host = (host or "").lower().removeprefix("www.")
    parts = host.split(".")
    return parts[0] if parts else host


def cvr_lookup(name: str, domain: str) -> str | None:
    """Company email from the CVR register, only if it plausibly matches the lead."""
    try:
        r = requests.get(f"https://cvrapi.dk/api?search={quote(name)}&country=dk",
                         timeout=15, headers={"User-Agent": UA})
        d = r.json()
    except Exception:
        return None
    if not isinstance(d, dict) or d.get("error"):
        return None
    email = (d.get("email") or "").strip().lower()
    if not email or any(j in email for j in JUNK):
        return None
    # guard: accept only if the matched company looks like our lead
    name_ok = bool(_tokens(name) & _tokens(d.get("name", "")))
    dom_ok = domain and _label(email.split("@")[-1]) == _label(domain)
    return email if (name_ok or dom_ok) else None


def harvest_one(name: str, url: str) -> tuple[str | None, str]:
    base = url if url.startswith("http") else "http://" + url
    domain = urlparse(base).netloc.lower().removeprefix("www.")
    html = fetch(base)
    cands = emails_from_html(html) if html else []
    if not cands:
        for path in CONTACT_PATHS:
            html = fetch(urljoin(base + "/", path))
            if html:
                cands = emails_from_html(html)
                if cands:
                    break
    if cands:
        return best_email(cands, domain), "site"
    cvr = cvr_lookup(name, domain)
    if cvr:
        return cvr, "cvr"
    return None, "-"


def main(limit: int, state_filter: str | None):
    con = store.connect()
    store.init(con)
    sql = ("SELECT id, name, email, website, final_url FROM leads "
           "WHERE (email IS NULL OR email='') "
           "AND COALESCE(final_url, website, '') <> '' ")
    args: list = []
    if state_filter:
        sql += "AND state=? "; args.append(state_filter)
    else:
        sql += "AND state IN ('scored','queued','demo_building','demo_live','drafted') "
    sql += "ORDER BY score DESC LIMIT ?"; args.append(limit)
    rows = con.execute(sql, args).fetchall()
    print(f"[harvest] {len(rows)} leads missing an email")
    found = {"site": 0, "cvr": 0}
    for r in rows:
        email, src = harvest_one(r["name"], r["final_url"] or r["website"])
        if email:
            con.execute("UPDATE leads SET email=? WHERE id=?", (email, r["id"]))
            con.commit()
            found[src] = found.get(src, 0) + 1
            print(f"  + [{src}] {r['name']}: {email}")
        else:
            print(f"  -        {r['name']}: none found")
        time.sleep(1)
    print(f"[harvest] filled {sum(found.values())}/{len(rows)} "
          f"(site={found.get('site',0)}, cvr={found.get('cvr',0)})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=int(os.environ.get("HARVEST_LIMIT", "40")))
    ap.add_argument("--state", default=None)
    a = ap.parse_args()
    main(a.limit, a.state)
