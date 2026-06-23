"""One-off backfill of Gmail outreach threads from gmail_backfill.json onto leads.
The JSON is a list of {email, direction ('in'/'out'), ts, subject, body}, where
`email` is the LEAD's address (the other party). Run once on the VPS, then
notion_sync.py.
"""
import json, os
import store


def main():
    path = "gmail_backfill.json"
    if not os.path.exists(path):
        print("gmail_backfill.json not found — skipping")
        return
    con = store.connect()
    store.init(con)
    data = json.load(open(path, encoding="utf-8"))
    n = 0
    for m in data:
        r = con.execute("SELECT id FROM leads WHERE lower(email)=?",
                        (m["email"].lower(),)).fetchone()
        if not r:
            continue
        store.log_message(con, r["id"], m.get("direction", "out"),
                          m.get("subject", ""), m.get("body", ""))
        n += 1
    print(f"backfilled {n} Gmail messages")


if __name__ == "__main__":
    main()
