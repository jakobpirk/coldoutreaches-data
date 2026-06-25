"""One-off: reject leads with a German (.de) website — they slipped into the pool
before the Denmark-only scan filter. Only touches the raw pool (scored/queued).
Run on the VPS, then notion_sync.py. Env: LEADS_DB (from .env).
"""
from urllib.parse import urlsplit
import store


def host(u):
    u = (u or "").strip()
    if not u:
        return ""
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    return urlsplit(u).netloc.lower()


def main():
    con = store.connect()
    store.init(con)
    rows = con.execute("SELECT id, final_url, website FROM leads "
                       "WHERE state IN ('scored', 'queued')").fetchall()
    n = 0
    for r in rows:
        if host(r["final_url"] or r["website"]).endswith(".de"):
            con.execute("UPDATE leads SET state='rejected', qualified=0 WHERE id=?", (r["id"],))
            n += 1
    con.commit()
    print(f"rejected {n} German (.de) leads from the pool")


if __name__ == "__main__":
    main()
