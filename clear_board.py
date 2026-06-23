"""One-off: archive every page in the Notion Leads database so we can rebuild it
clean. Env: NOTION_TOKEN, NOTION_DB_ID."""
import os, requests

TOKEN = os.environ["NOTION_TOKEN"]
DB = os.environ["NOTION_DB_ID"]
API = "https://api.notion.com/v1"
H = {"Authorization": f"Bearer {TOKEN}", "Notion-Version": "2022-06-28",
     "Content-Type": "application/json"}


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
            requests.patch(f"{API}/pages/{p['id']}", headers=H, json={"archived": True})
            n += 1
        if not d.get("has_more"):
            break
        cursor = d.get("next_cursor")
    print(f"archived {n} board pages")


if __name__ == "__main__":
    main()
