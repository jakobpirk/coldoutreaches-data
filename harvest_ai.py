"""
AI email finder for the hard cases harvest_emails.py can't crack — form-only sites
with no address on the page or in CVR. Claude (web search + fetch) hunts the
business's real contact email across its site, Facebook, and Danish directories
(krak, degulesider, CVR). We accept ONLY a high-confidence result that plausibly
belongs to the lead (its own domain, or a name token in the address), reusing
harvest_emails' guards — so we never write a wrong address. Logged via obs.

    python3 harvest_ai.py --limit 20            # demo_live/drafted missing email
    python3 harvest_ai.py --state demo_live
Env: CLAUDE_CMD, LEADS_DB. Needs claude web tools (WebSearch/WebFetch).
"""
from __future__ import annotations
import os, time, argparse
from urllib.parse import urlparse
import store, obs
from harvest_emails import _tokens, _label, JUNK, GENERIC_PREFIXES

CLAUDE_CMD = os.environ.get("CLAUDE_CMD", "claude")
FIND_TOOLS = os.environ.get("EMAIL_TOOLS", "WebSearch WebFetch")
MIN_CONF = float(os.environ.get("EMAIL_MIN_CONF", "0.7"))


def _domain(url: str) -> str:
    base = url if (url or "").startswith("http") else "http://" + (url or "")
    return urlparse(base).netloc.lower().removeprefix("www.")


def plausible(email: str, name: str, domain: str) -> bool:
    """Accept only if the address clearly belongs to this lead: its own domain, or
    a name token appears in the address. Guards against a confidently-wrong email."""
    e = (email or "").strip().lower()
    if "@" not in e:
        return False
    if any(j in e for j in JUNK) or any(e.startswith(g) for g in GENERIC_PREFIXES):
        return False
    dom_ok = bool(domain) and _label(e.split("@")[-1]) == _label(domain)
    tok_ok = any(t in e for t in _tokens(name))
    return dom_ok or tok_ok


def find_one(lead: dict) -> dict:
    url = lead.get("final_url") or lead.get("website") or ""
    domain = _domain(url)
    prompt = f"""Find den ægte kontakt-email til den danske virksomhed "{lead['name']}".
Hjemmeside: {url} (domæne: {domain}).
Brug web-søgning og -hentning. Kig på deres kontaktside og footer, deres Facebook-side,
og danske registre/kataloger (krak.dk, degulesider.dk, CVR/cvrapi.dk).
Returnér KUN en email du er sikker på tilhører netop DENNE virksomhed — ikke en generisk
no-reply, ikke et tilfældigt bureau, ikke en gæt. Hvis du ikke kan finde en sikker, så lad email være tom.

Output KUN JSON: {{"email":"<email eller tom>","confidence":0.0-1.0,"source":"<hvor fundet>","rationale":"<kort dansk>"}}"""
    try:
        _, parsed = obs.claude(CLAUDE_CMD, prompt, label=f"email:{lead['id']}",
                               expect_json=True, allowed_tools=FIND_TOOLS, timeout=300)
        return parsed or {}
    except Exception as e:
        obs.event("email_error", lead_id=lead["id"], error=str(e)[:160])
        return {}


def main(limit, state):
    con = store.connect(); store.init(con)
    sql = "SELECT * FROM leads WHERE (email IS NULL OR email='') "
    args = []
    if state:
        sql += "AND state=? "; args.append(state)
    else:
        sql += "AND state IN ('demo_live','drafted') "
    sql += "ORDER BY score DESC LIMIT ?"; args.append(limit)
    rows = [dict(r) for r in con.execute(sql, args).fetchall()]
    with obs.run("harvest_ai", n=len(rows)):
        print(f"[harvest_ai] {len(rows)} lead(s) missing an email")
        filled = 0
        for lead in rows:
            domain = _domain(lead.get("final_url") or lead.get("website") or "")
            res = find_one(lead)
            email = (res.get("email") or "").strip().lower()
            conf = res.get("confidence") or 0
            if email and conf >= MIN_CONF and plausible(email, lead["name"], domain):
                con.execute("UPDATE leads SET email=? WHERE id=?", (email, lead["id"]))
                con.commit()
                filled += 1
                obs.event("email_found", lead_id=lead["id"], src=res.get("source"))
                print(f"  + {lead['name']}: {email} (conf={conf}, {res.get('source')})")
            else:
                obs.event("email_miss", lead_id=lead["id"])
                print(f"  - {lead['name']}: {email or 'none'} (conf={conf}) -> skip")
            time.sleep(1)
        print(f"[harvest_ai] filled {filled}/{len(rows)}")
    con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=int(os.environ.get("HARVEST_AI_LIMIT", "20")))
    ap.add_argument("--state", default=None)
    main(*(lambda a: (a.limit, a.state))(ap.parse_args()))
