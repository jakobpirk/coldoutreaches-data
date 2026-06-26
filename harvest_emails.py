"""Fill in missing contact emails by scraping each lead's own website.

Many OSM craft listings have only a phone number, so after a demo is built and
drafted there's no address to send to ('skip — no email address on file' in the
outbox). This visits the lead's site (front page + a likely contact page),
extracts the best email, and writes it to leads.email so notion_sync surfaces it
and send_outbox can actually send.

  python3 harvest_emails.py --limit 40

Wired into run_nightly.sh before notion_sync. Best-effort and polite.
"""
from __future__ import annotations
import os, re, time, argparse
from urllib.parse import urljoin, urlparse
import requests
import store

UA = "ColdOutreaches-LeadScout/0.1 (jakobwilbrandt@gmail.com)"
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
# Addresses that are never a real human contact for the business.
JUNK = ("example.com", "sentry", "wixpress", "godaddy", "your-email", "domain.com",
        "email@", "name@", "@2x", ".png", ".jpg", ".webp", ".gif", "@sentry",
        "wordpress", "yoast", "schema.org", "u003e", "react", "core-js")
# Contact-ish pages worth checking if the front page has nothing.
CONTACT_PATHS = ("kontakt", "kontakt-os", "om-os", "about", "contact")
# When several candidates, prefer real mailboxes over these generic prefixes —
# but still accept them if nothing better exists (info@ is fine to email).
GENERIC_PREFIXES = ("noreply", "no-reply", "postmaster", "mailer-daemon", "abuse")


def emails_from_html(html: str) -> list[str]:
    found = []
    for m in re.findall(r'mailto:([^"\'?>\s]+)', html, flags=re.I):
        found.append(m)
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
    # Prefer an address on the business's own domain.
    same = [e for e in candidates if domain and e.split("@")[-1].endswith(domain)]
    pool = same or candidates
    # Prefer info@/kontakt@ over a random personal address for cold outreach.
    for pref in ("info@", "kontakt@", "mail@", "hej@", "kontor@"):
        for e in pool:
            if e.startswith(pref):
                return e
    return pool[0]


def harvest_one(url: str) -> str | None:
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
    return best_email(cands, domain)


def main(limit: int):
    con = store.connect()
    store.init(con)
    rows = con.execute(
        "SELECT id, name, email, website, final_url FROM leads "
        "WHERE (email IS NULL OR email='') "
        "AND COALESCE(final_url, website, '') <> '' "
        "AND state IN ('scored','queued','demo_building','demo_live','drafted') "
        "ORDER BY score DESC LIMIT ?", (limit,)).fetchall()
    print(f"[harvest] {len(rows)} leads missing an email")
    found = 0
    for r in rows:
        url = r["final_url"] or r["website"]
        email = harvest_one(url)
        if email:
            con.execute("UPDATE leads SET email=? WHERE id=?", (email, r["id"]))
            con.commit()
            found += 1
            print(f"  + {r['name']}: {email}")
        else:
            print(f"  - {r['name']}: none found")
        time.sleep(1)
    print(f"[harvest] filled {found}/{len(rows)} emails")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=int(os.environ.get("HARVEST_LIMIT", "40")))
    main(ap.parse_args().limit)
