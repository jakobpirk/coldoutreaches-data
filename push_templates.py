"""
Push any reply types in reply-templates.md that are NOT yet on the Notion
"Svar-skabeloner" page (idempotent — appends missing ## sections only). Use after
adding new types in code; day-to-day you edit the types in Notion and
pull_guidance.py pulls them back down. Env: NOTION_TOKEN.
"""
import os, json, pathlib, requests

API = "https://api.notion.com/v1"
H = {"Authorization": f"Bearer {os.environ['NOTION_TOKEN']}",
     "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
TEMPLATES = pathlib.Path("reply-templates.md")
IDS = pathlib.Path("data/reply_ids.json")


def existing_headings(page_id):
    out, cursor = set(), None
    while True:
        params = {"page_size": 100}
        if cursor:
            params["start_cursor"] = cursor
        d = requests.get(f"{API}/blocks/{page_id}/children", headers=H, params=params).json()
        for b in d.get("results", []):
            if b.get("type") == "heading_2":
                out.add("".join(x.get("plain_text", "")
                                for x in b["heading_2"]["rich_text"]).strip())
        if not d.get("has_more"):
            break
        cursor = d["next_cursor"]
    return out


def sections():
    out, cur = {}, None
    for line in TEMPLATES.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            cur = line[3:].strip(); out[cur] = []
        elif cur is not None and line.strip():
            out[cur].append(line.strip())
    return out


def main():
    page = json.loads(IDS.read_text())["templates_page"]
    have = existing_headings(page)
    blocks = []
    for name, lines in sections().items():
        if name in have:
            continue
        blocks.append({"object": "block", "type": "heading_2",
                       "heading_2": {"rich_text": [{"type": "text", "text": {"content": name}}]}})
        for ln in lines:
            blocks.append({"object": "block", "type": "paragraph",
                           "paragraph": {"rich_text": [{"type": "text", "text": {"content": ln[:1900]}}]}})
        print(f"  + {name}")
    if not blocks:
        print("templates page already up to date")
        return
    for i in range(0, len(blocks), 100):
        requests.patch(f"{API}/blocks/{page}/children", headers=H,
                       json={"children": blocks[i:i+100]}).raise_for_status()
    print(f"appended {len(blocks)} blocks")


if __name__ == "__main__":
    main()
