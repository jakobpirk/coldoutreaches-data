"""
One-time (idempotent) setup of the Notion side of the auto-reply system:

  📨 Autosvar                         (container page, under Email guidance)
   ├─ Svar-skabeloner                 (config page — per-type reply templates,
   │                                    pulled into reply-templates.md each run)
   └─ Svar – Inbox  (database)        (one row per inbound mail needing a reply,
                                        with the AI draft + a "Send svar" tick)

IDs are saved to data/reply_ids.json so re-runs reuse the same objects instead of
creating duplicates. Run once:  python3 setup_replies.py
Env: NOTION_TOKEN. The container is created under the Email-guidance page (the
only top-level page the integration can write under); drag it wherever you like
in Notion afterwards — the integration keeps access.
"""
import os, json, pathlib, requests

T = os.environ["NOTION_TOKEN"]
API = "https://api.notion.com/v1"
H = {"Authorization": f"Bearer {T}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
EMAIL_GUIDANCE_PAGE = "3899aedb-43b4-81c9-b399-dc2e917e25a0"   # accessible top-level page
IDS = pathlib.Path("data/reply_ids.json")
TEMPLATES = pathlib.Path("reply-templates.md")

# Svar – Inbox database schema
DB_PROPS = {
    "Subject": {"title": {}},
    "From": {"email": {}},
    "Received": {"date": {}},
    "Reply type": {"select": {"options": [
        {"name": "redesign_eksisterende"}, {"name": "ny_side"}, {"name": "pris"},
        {"name": "interesseret_svar"}, {"name": "ikke_interesseret"},
        {"name": "andet"}, {"name": "ignorer"}]}},
    "Status": {"select": {"options": [
        {"name": "drafted", "color": "yellow"}, {"name": "sent", "color": "green"},
        {"name": "rejected", "color": "gray"}, {"name": "error", "color": "red"}]}},
    "Reply draft": {"rich_text": {}},
    "AI-udkast": {"rich_text": {}},
    "Dine rettelser": {"rich_text": {}},
    "Send svar": {"checkbox": {}},
    "Afvis": {"checkbox": {}},
    "Lead ID": {"number": {}},
    "Original": {"rich_text": {}},
    "Message-ID": {"rich_text": {}},
    "UID": {"number": {}},
}


def load_ids():
    return json.loads(IDS.read_text()) if IDS.exists() else {}


def save_ids(d):
    IDS.parent.mkdir(parents=True, exist_ok=True)
    IDS.write_text(json.dumps(d, indent=2))


def page_exists(pid):
    return pid and requests.get(f"{API}/pages/{pid}", headers=H).ok


def db_exists(did):
    return did and requests.get(f"{API}/databases/{did}", headers=H).ok


def templates_blocks():
    """Turn reply-templates.md into Notion blocks (heading per ## type)."""
    blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [
        {"type": "text", "text": {"content":
            "Rediger skabelonerne her. Hver ## er en mail-type. 'Beskrivelse' "
            "bruges til at genkende typen; 'Skabelon' styrer svaret. Tilføj gerne "
            "nye typer."}}]}}]
    for line in TEMPLATES.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            blocks.append({"object": "block", "type": "heading_2",
                           "heading_2": {"rich_text": [{"type": "text", "text": {"content": line[3:]}}]}})
        elif line.strip():
            blocks.append({"object": "block", "type": "paragraph",
                           "paragraph": {"rich_text": [{"type": "text", "text": {"content": line[:1900]}}]}})
    return blocks


def main():
    ids = load_ids()

    # 1. container page
    if not page_exists(ids.get("container_page")):
        r = requests.post(f"{API}/pages", headers=H, json={
            "parent": {"type": "page_id", "page_id": EMAIL_GUIDANCE_PAGE},
            "icon": {"type": "emoji", "emoji": "📨"},
            "properties": {"title": [{"text": {"content": "Autosvar"}}]}})
        r.raise_for_status()
        ids["container_page"] = r.json()["id"]
        print("created container page")
    container = ids["container_page"]

    # 2. templates config page (seeded from reply-templates.md)
    if not page_exists(ids.get("templates_page")):
        r = requests.post(f"{API}/pages", headers=H, json={
            "parent": {"type": "page_id", "page_id": container},
            "properties": {"title": [{"text": {"content": "Svar-skabeloner"}}]},
            "children": templates_blocks()})
        r.raise_for_status()
        ids["templates_page"] = r.json()["id"]
        print("created Svar-skabeloner page (seeded)")

    # 3. Svar – Inbox database (create, or add any newly-introduced properties)
    if not db_exists(ids.get("inbox_db")):
        r = requests.post(f"{API}/databases", headers=H, json={
            "parent": {"type": "page_id", "page_id": container},
            "title": [{"text": {"content": "Svar – Inbox"}}],
            "properties": DB_PROPS})
        r.raise_for_status()
        ids["inbox_db"] = r.json()["id"]
        print("created Svar – Inbox database")
    else:
        cur = requests.get(f"{API}/databases/{ids['inbox_db']}", headers=H).json()
        missing = {k: v for k, v in DB_PROPS.items() if k not in cur.get("properties", {})}
        if missing:
            requests.patch(f"{API}/databases/{ids['inbox_db']}", headers=H,
                           json={"properties": missing})
            print(f"added missing properties: {', '.join(missing)}")

    save_ids(ids)
    print("\nreply_ids.json:")
    print(json.dumps(ids, indent=2))
    print(f"\nOpen the container in Notion: https://www.notion.so/{container.replace('-','')}")


if __name__ == "__main__":
    main()
