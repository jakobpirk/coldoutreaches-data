"""One-off: archive Notion lead pages that aren't part of the active pipeline
(raw scored / queued / demo_building / rejected), leaving only what you act on
(demo_live, drafted, sent, replied, won, lost). Env: NOTION_TOKEN, NOTION_DB_ID.
"""
import os
import requests

TOKEN = os.environ["NOTION_TOKEN"]
DB = os.environ["NOTION_DB_ID"]
API = "https://api.notion.com/v1"
H = {"Authorization": f"Bearer {TOKEN}", "Notion-Version": "2022-06-28",
     "Content-Type": "application/json"}
KEEP = {"demo_live", "drafted", "sent", "replied", "won", "lost"}


def main():
    n, cursor = 0, None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        r = requests.post(f"{API}/databases/{DB}/query", headers=H, json=body)
        r.raise_for_status()
        d = r.json()
        for p in d["results"]:
            st = ((p["properties"].get("State") or {}).get("select") or {}).get("name")
            if st not in KEEP:
                requests.patch(f"{API}/pages/{p['id']}", headers=H, json={"archived": True})
                n += 1
        if not d.get("has_more"):
            break
        cursor = d.get("next_cursor")
    print(f"archived {n} non-pipeline pages")


if __name__ == "__main__":
    main()
