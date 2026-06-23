"""
Pull the two agent-guidance pages from Notion into the local files the agents
read, so your edits in Notion steer the next scoring + design runs. These pages
act like an editable CLAUDE.md for the agents.

Runs at the start of the nightly job (before scoring) and before designing.
Env: NOTION_TOKEN.
"""
import os, pathlib
import requests

TOKEN = os.environ["NOTION_TOKEN"]
API = "https://api.notion.com/v1"
H = {"Authorization": f"Bearer {TOKEN}", "Notion-Version": "2022-06-28"}

# Notion page -> local file the agent reads
PAGES = {
    "3889aedb-43b4-8155-b223-fcef90bfc570": "classification-feedback.md",  # scoring/selection
    "3889aedb-43b4-8148-b3e1-e91cb6a8c793": "design-preferences.md",        # design
}

PREFIX = {"heading_1": "# ", "heading_2": "## ", "heading_3": "### ",
          "bulleted_list_item": "- ", "numbered_list_item": "- ", "quote": "> ",
          "to_do": "- "}


def page_text(page_id: str) -> str:
    out, cursor = [], None
    while True:
        params = {"page_size": 100}
        if cursor:
            params["start_cursor"] = cursor
        r = requests.get(f"{API}/blocks/{page_id}/children", headers=H, params=params)
        r.raise_for_status()
        data = r.json()
        for b in data["results"]:
            t = b.get("type")
            block = b.get(t) or {}
            rich = block.get("rich_text")
            if rich is None:
                continue
            line = "".join(x.get("plain_text", "") for x in rich)
            out.append(PREFIX.get(t, "") + line)
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return ("\n".join(out)).strip()


def main():
    for pid, fname in PAGES.items():
        try:
            txt = page_text(pid)
        except Exception as e:
            print(f"[guidance] {fname}: fetch failed ({e}); keeping existing file")
            continue
        if txt:
            pathlib.Path(fname).write_text(txt + "\n", encoding="utf-8")
            print(f"[guidance] {fname} <- Notion ({len(txt)} chars)")
        else:
            print(f"[guidance] {fname}: page empty; kept existing file")


if __name__ == "__main__":
    main()
