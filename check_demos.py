"""
Demo liveness monitor — runs nightly so a dead preview never sits unnoticed in a
prospect's inbox. For every lead in an active state it resolves the demo link
(the `demo_url` field, else the link inside the outgoing mail we logged), HTTP
checks it, and records a `demo_status`:

  live     reachable (HTTP < 400). If demo_url was blank, we backfill it here
           (self-heal) so the structured "Demo site" field matches what we sent.
  offline  a demo link exists but is unreachable — the prospect's link is dead.
  none     no demo link anywhere — cold mail sent without a preview.

The result syncs to Notion via the "Demo status" select property (created here if
missing), so you can filter a "Dead demos" view and re-pitch or rebuild.

    python3 check_demos.py            # check + heal + flag, then it's picked up by notion_sync
    python3 check_demos.py --quiet

Env: NOTION_TOKEN, NOTION_DB_ID (to ensure the property exists), LEADS_DB.
"""
from __future__ import annotations
import os
import sys
import ssl
import urllib.request
import datetime as dt

import store

ACTIVE = ("demo_live", "drafted", "sent", "replied", "won", "lost")
UA = {"User-Agent": "Mozilla/5.0 (compatible; WW-demo-monitor/1.0)"}
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def is_live(url: str, attempts: int = 2) -> bool:
    """True if the URL is reachable (final status < 400). Retries once to avoid
    flagging a demo dead on a transient blip."""
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, method="GET", headers=UA)
            with urllib.request.urlopen(req, timeout=20, context=_CTX) as r:
                return getattr(r, "status", 200) < 400
        except urllib.error.HTTPError as e:
            return e.code < 400
        except Exception:
            if i == attempts - 1:
                return False
    return False


def demo_link_for(con, lead) -> str | None:
    if lead["demo_url"]:
        return lead["demo_url"]
    body = " ".join((m["body"] or "") for m in con.execute(
        "SELECT body FROM messages WHERE lead_id=? AND direction='out'", (lead["id"],)))
    return store.extract_demo_url(body)


def ensure_notion_property():
    """Add the 'Demo status' select property to the board if it isn't there yet."""
    token, db = os.environ.get("NOTION_TOKEN"), os.environ.get("NOTION_DB_ID")
    if not (token and db):
        return
    import requests
    h = {"Authorization": f"Bearer {token}", "Notion-Version": "2022-06-28",
         "Content-Type": "application/json"}
    cur = requests.get(f"https://api.notion.com/v1/databases/{db}", headers=h)
    if cur.ok and "Demo status" in cur.json().get("properties", {}):
        return
    requests.patch(f"https://api.notion.com/v1/databases/{db}", headers=h, json={
        "properties": {"Demo status": {"select": {"options": [
            {"name": "live", "color": "green"},
            {"name": "offline", "color": "red"},
            {"name": "none", "color": "gray"}]}}}})
    print("[demos] ensured 'Demo status' property on Notion board")


def run(quiet=False):
    ensure_notion_property()
    con = store.connect()
    store.init(con)
    ts = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    rows = [dict(r) for r in con.execute(
        f"SELECT * FROM leads WHERE state IN ({','.join('?'*len(ACTIVE))})", ACTIVE)]
    live = offline = none = healed = 0
    dead_list = []
    for l in rows:
        url = demo_link_for(con, l)
        if not url:
            status = "none"
            none += 1
        elif is_live(url):
            status = "live"
            live += 1
            if not l["demo_url"]:               # self-heal: fill the blank field
                con.execute("UPDATE leads SET demo_url=? WHERE id=?", (url, l["id"]))
                healed += 1
        else:
            status = "offline"
            offline += 1
            dead_list.append((l["id"], l["name"], url))
        con.execute("UPDATE leads SET demo_status=?, demo_checked_at=? WHERE id=?",
                    (status, ts, l["id"]))
    con.commit()
    print(f"[demos] checked {len(rows)}: live={live} offline={offline} none={none} "
          f"(healed {healed} blank demo_url fields)")
    if dead_list and not quiet:
        print("[demos] OFFLINE — prospect link is dead:")
        for i, name, url in dead_list:
            print(f"    #{i:5} {(name or '')[:28]:28} {url}")
    con.close()
    return {"live": live, "offline": offline, "none": none, "healed": healed}


if __name__ == "__main__":
    run(quiet="--quiet" in sys.argv)
