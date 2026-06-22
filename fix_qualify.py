"""One-off: recompute qualified flags with the marketplace rule + report.
(Logic mirrors store.qualify; standalone so it runs on a fresh path.)"""
import os, json, sqlite3
from urllib.parse import urlsplit

DB = os.environ.get("LEADS_DB", "output/leads.db")
MARKET = {
    "antikvitet.net", "dba.dk", "guloggratis.dk", "facebook.com", "instagram.com",
    "etsy.com", "trustpilot.com", "tripadvisor.com", "tripadvisor.dk", "booking.com",
    "just-eat.dk", "wolt.com", "krak.dk", "degulesider.dk", "findsmiley.dk",
    "linktr.ee", "youtube.com",
}

def host(u):
    u = (u or "").strip()
    if not u:
        return ""
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    h = urlsplit(u).netloc.lower()
    for p in ("www.", "m."):
        if h.startswith(p):
            h = h[len(p):]
    return h

def is_market(u):
    h = host(u)
    return any(h == b or h.endswith("." + b) for b in MARKET)

def qual(status, score, signals, url):
    if status != 200:
        return 0
    if (score or 0) < 8:
        return 0
    if {s.get("name") for s in signals} & {"name_mismatch", "name_mismatch_promo",
                                            "parked_domain", "thin_or_stub"}:
        return 0
    if is_market(url):
        return 0
    return 1

con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
before = con.execute("SELECT COUNT(*) FROM leads WHERE qualified=1").fetchone()[0]
n = 0
for r in con.execute("SELECT id,http_status,score,signals_json,final_url,website FROM leads"):
    q = qual(r["http_status"], r["score"], json.loads(r["signals_json"] or "[]"),
             r["final_url"] or r["website"] or "")
    con.execute("UPDATE leads SET qualified=? WHERE id=?", (q, r["id"]))
    n += 1
con.commit()
after = con.execute("SELECT COUNT(*) FROM leads WHERE qualified=1").fetchone()[0]
print(f"requalified {n} leads; qualified {before} -> {after}")
print("  #4:", dict(con.execute("SELECT id,name,qualified,final_url FROM leads WHERE id=4").fetchone()))
mk = [x for x in con.execute("SELECT name,final_url,qualified FROM leads").fetchall()
      if is_market(x["final_url"] or "")]
print(f"  marketplace listings: {len(mk)} | still qualified among them: {sum(m['qualified'] for m in mk)}")
