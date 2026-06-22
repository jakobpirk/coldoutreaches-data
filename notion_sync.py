"""
Push qualified leads from the SQLite store into a Notion database.

READY but not yet runnable — needs Phase 0:
    export NOTION_TOKEN=secret_xxx          # internal integration token
    export NOTION_DB_ID=xxxxxxxxxxxx        # the lead board database id
    export LEADS_DB=output/leads.db

Then:
    python3 notion_sync.py            # upserts all qualified, non-rejected leads

Upsert is keyed on the "Lead ID" number property, so re-runs update rather than
duplicate. Create the database with the properties in NOTION_SCHEMA.md first
(or call `python3 notion_sync.py --print-schema` to dump the property JSON).

Notion API version pinned to 2022-06-28.
"""
from __future__ import annotations
import os
import sys
import json
import sqlite3

import store  # reuse connect()

NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
NOTION_DB_ID = os.environ.get("NOTION_DB_ID")
API = "https://api.notion.com/v1"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

# Notion property schema for the lead board. Used to create the DB and as the
# contract notion_sync writes against. See NOTION_SCHEMA.md for the rationale.
PROPERTY_SCHEMA = {
    "Name": {"title": {}},
    "Lead ID": {"number": {}},
    "State": {"select": {"options": [
        {"name": s} for s in store.STATES]}},
    "Score": {"number": {}},
    "Qualified": {"checkbox": {}},
    "Verdict": {"select": {"options": [
        {"name": "ugly"}, {"name": "borderline"}, {"name": "fine"}]}},
    "Confidence": {"number": {}},
    "Original site": {"url": {}},
    "Demo site": {"url": {}},
    "Screenshot": {"url": {}},
    "Contact person": {"rich_text": {}},
    "Email address": {"email": {}},
    "Phone": {"phone_number": {}},
    "City": {"rich_text": {}},
    "Category": {"rich_text": {}},
    "Email draft": {"rich_text": {}},
    "Reasons": {"rich_text": {}},
}


def _rt(text):
    text = (text or "")[:1900]
    return [{"type": "text", "text": {"content": text}}] if text else []


def lead_to_properties(row: sqlite3.Row) -> dict:
    return {
        "Name": {"title": [{"type": "text", "text": {"content": row["name"] or "?"}}]},
        "Lead ID": {"number": row["id"]},
        "State": {"select": {"name": row["state"]}},
        "Score": {"number": row["score"]},
        "Qualified": {"checkbox": bool(row["qualified"])},
        "Verdict": ({"select": {"name": row["cls_verdict"]}} if row["cls_verdict"] else {"select": None}),
        "Confidence": {"number": row["cls_confidence"]},
        "Original site": {"url": row["final_url"] or row["website"] or None},
        "Demo site": {"url": row["demo_url"] or None},
        "Screenshot": {"url": row["screenshot_path"] or None},
        "Contact person": {"rich_text": _rt(row["contact_person"])},
        "Email address": {"email": row["email"] or None},
        "Phone": {"phone_number": row["phone"] or None},
        "City": {"rich_text": _rt(row["city"])},
        "Category": {"rich_text": _rt(f"{row['category']}/{row['subcategory']}")},
        "Email draft": {"rich_text": _rt(row["email_draft"])},
        "Reasons": {"rich_text": _rt(row["cls_reasons"])},
    }


def _require_creds():
    if not (NOTION_TOKEN and NOTION_DB_ID):
        sys.exit("NOTION_TOKEN and NOTION_DB_ID must be set (Phase 0).")
    import requests  # noqa
    return requests


def find_page(requests, lead_id: int):
    r = requests.post(f"{API}/databases/{NOTION_DB_ID}/query",
                      headers=HEADERS, json={
                          "filter": {"property": "Lead ID", "number": {"equals": lead_id}},
                          "page_size": 1})
    r.raise_for_status()
    res = r.json().get("results", [])
    return res[0]["id"] if res else None


def upsert(requests, row) -> str:
    props = lead_to_properties(row)
    page_id = find_page(requests, row["id"])
    if page_id:
        r = requests.patch(f"{API}/pages/{page_id}", headers=HEADERS,
                           json={"properties": props})
        action = "updated"
    else:
        r = requests.post(f"{API}/pages", headers=HEADERS, json={
            "parent": {"database_id": NOTION_DB_ID}, "properties": props})
        action = "created"
    r.raise_for_status()
    return action


def sync(only_qualified=True):
    requests = _require_creds()
    con = store.connect()
    sql = "SELECT * FROM leads WHERE state != 'rejected'"
    if only_qualified:
        sql += " AND qualified=1"
    sql += " ORDER BY score DESC"
    rows = con.execute(sql).fetchall()
    counts = {"created": 0, "updated": 0}
    for row in rows:
        counts[upsert(requests, row)] += 1
    print(f"synced {len(rows)} leads -> {counts}")


if __name__ == "__main__":
    if "--print-schema" in sys.argv:
        print(json.dumps(PROPERTY_SCHEMA, indent=2, ensure_ascii=False))
    else:
        sync(only_qualified="--all" not in sys.argv)
