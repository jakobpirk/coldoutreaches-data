"""Sync tickets from SQLite into the Notion Tickets board. Upserts on 'Ref'
(the SQLite ticket id) so re-runs update rather than duplicate. Env: NOTION_TOKEN.
"""
import os
import requests
import store

TOKEN = os.environ["NOTION_TOKEN"]
DB = "2cd2eb54ee6b4a459791ee2750418563"  # ColdOutreaches — Tickets
API = "https://api.notion.com/v1"
H = {"Authorization": f"Bearer {TOKEN}", "Notion-Version": "2022-06-28",
     "Content-Type": "application/json"}


def _rt(t):
    t = (t or "")[:1900]
    return [{"type": "text", "text": {"content": t}}] if t else []


def props(t):
    return {
        "Title": {"title": [{"type": "text", "text": {"content": (t["title"] or "?")[:200]}}]},
        "Ref": {"number": t["id"]},
        "Customer": {"rich_text": _rt(t["customer"])},
        "Customer email": {"email": t["customer_email"] or None},
        "Status": {"select": {"name": t["status"]}},
        "Type": ({"select": {"name": t["type"]}} if t["type"] else {"select": None}),
        "Auto-fixable": "__YES__" if t["auto_fixable"] else "__NO__",
        "Summary": {"rich_text": _rt(t["summary"])},
        "Original email": {"rich_text": _rt(t["original_email"])},
        "Repo": {"rich_text": _rt(t["repo"])},
        "GitHub issue": {"url": t["github_issue_url"] or None},
        "Staging preview": {"url": t["staging_url"] or None},
    }


def find(tid):
    r = requests.post(f"{API}/databases/{DB}/query", headers=H,
                      json={"filter": {"property": "Ref", "number": {"equals": tid}}, "page_size": 1})
    r.raise_for_status()
    res = r.json().get("results", [])
    return res[0]["id"] if res else None


def main():
    con = store.connect()
    store.init(con)
    try:
        rows = con.execute("SELECT * FROM tickets ORDER BY id").fetchall()
    except Exception:
        print("no tickets table yet")
        return
    counts = {"created": 0, "updated": 0}
    for t in rows:
        p = props(t)
        pid = find(t["id"])
        if pid:
            r = requests.patch(f"{API}/pages/{pid}", headers=H, json={"properties": p})
            action = "updated"
        else:
            r = requests.post(f"{API}/pages", headers=H,
                              json={"parent": {"database_id": DB}, "properties": p})
            action = "created"
        if not r.ok:
            print(f"  ticket #{t['id']} sync failed {r.status_code}: {r.text[:200]}")
            continue
        counts[action] += 1
    print(f"tickets synced -> {counts}")


if __name__ == "__main__":
    main()
