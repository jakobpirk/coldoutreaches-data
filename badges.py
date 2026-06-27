"""
Badge engine — a human-readable "where is this lead in the process" layer on top
of the SQLite state machine. The single `state` stays the engine (dedup, pipeline
logic); badges are DERIVED from facts we already track (state, email, demo_status,
follow-up date, the direction of the last logged mail, last reply sentiment) and
written to a Notion multi-select called "Badges". You never move leads by hand —
this recomputes every run.

    python3 badges.py                 # recompute + push badges for active leads
    python3 badges.py --backfill      # first classify existing inbound mail
                                      #   (sets last_reply_sentiment), then recompute
    python3 badges.py --no-push       # DB only, don't touch Notion

Env: NOTION_TOKEN, NOTION_DB_ID, LEADS_DB. Backfill also needs CLAUDE_CMD.
"""
from __future__ import annotations
import os, sys, json, datetime as dt
import requests
import store

API = "https://api.notion.com/v1"
H = {"Authorization": f"Bearer {os.environ.get('NOTION_TOKEN','')}",
     "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
DB = os.environ.get("NOTION_DB_ID")
ACTIVE = ("demo_live", "drafted", "sent", "replied", "won",
          "iterating", "impl_approved", "lost")

# canonical badges (names must not contain commas — Notion multi-select rule)
BADGE_COLORS = {
    "Aftale lukket": "green", "Tabt": "gray",
    "Kunde svarede – din tur": "red", "Afventer kunde": "yellow",
    "Tilbud sendt": "purple", "Mangler opfølgning": "orange",
    "Demo klar": "green", "Mangler email": "orange", "Demo offline": "red",
    "Interesseret": "blue", "Ikke interesseret": "brown",
    # delivery / iteration loop
    "Afventer ændringsønsker": "yellow", "Ændringer modtaget": "blue",
    "Review-iteration": "purple", "Implementation godkendt": "green",
}


def compute_badges(con, lead) -> list[str]:
    state = lead["state"]
    if state == "lost":
        return ["Tabt"]
    if state == "rejected":
        return []
    b: list[str] = []
    dirs = [r["direction"] for r in con.execute(
        "SELECT direction FROM messages WHERE lead_id=? ORDER BY ts DESC, id DESC",
        (lead["id"],))]
    has_in = "in" in dirs
    last_dir = dirs[0] if dirs else None
    today = dt.date.today().isoformat()

    # post-close delivery loop
    if state == "impl_approved":
        return ["Implementation godkendt"]
    if state == "won":
        out = ["Aftale lukket"]
        out.append("Ændringer modtaget" if (lead["change_requests"] or "").strip()
                   else "Afventer ændringsønsker")
        return out
    if state == "iterating":
        out = ["Review-iteration"]
        out.append("Kunde svarede – din tur" if last_dir == "in" else "Afventer kunde")
        return out

    # pre-send readiness
    if state in ("demo_live", "drafted"):
        if (lead["email"] or "").strip():
            b.append("Demo klar")
        else:
            b.append("Mangler email")
    if lead["demo_status"] == "offline":
        b.append("Demo offline")

    # conversation flow
    if has_in:
        b.append("Kunde svarede – din tur" if last_dir == "in" else "Afventer kunde")
    elif state == "sent":
        b.append("Tilbud sendt")
        if lead["followup_date"] and lead["followup_date"] <= today:
            b.append("Mangler opfølgning")

    # sentiment (a colour on top of the flow badge)
    s = lead["last_reply_sentiment"]
    if s == "interested":
        b.append("Interesseret")
    elif s == "not_interested":
        b.append("Ikke interesseret")

    # de-dup, preserve order
    seen, out = set(), []
    for x in b:
        if x not in seen:
            seen.add(x); out.append(x)
    return out


def ensure_notion_property():
    if not (H["Authorization"].split()[-1] and DB):
        return
    cur = requests.get(f"{API}/databases/{DB}", headers=H)
    if cur.ok and "Badges" in cur.json().get("properties", {}):
        return
    requests.patch(f"{API}/databases/{DB}", headers=H, json={"properties": {
        "Badges": {"multi_select": {"options": [
            {"name": n, "color": c} for n, c in BADGE_COLORS.items()]}}}})
    print("[badges] ensured 'Badges' property on Notion board")


def _find_page(lead_id):
    r = requests.post(f"{API}/databases/{DB}/query", headers=H, json={
        "filter": {"property": "Lead ID", "number": {"equals": lead_id}}, "page_size": 1})
    res = r.json().get("results", []) if r.ok else []
    return res[0]["id"] if res else None


def _push(lead_id, badges):
    pid = _find_page(lead_id)
    if not pid:
        return False
    r = requests.patch(f"{API}/pages/{pid}", headers=H, json={"properties": {
        "Badges": {"multi_select": [{"name": b} for b in badges]}}})
    return r.ok


def backfill_sentiment(con):
    """Classify the latest inbound mail per lead so 'Interesseret/Ikke
    interesseret' badges reflect what people actually wrote. Cheap — only leads
    that have inbound mail."""
    import inbound
    rows = con.execute(
        "SELECT DISTINCT lead_id FROM messages WHERE direction='in'").fetchall()
    n = 0
    for r in rows:
        lid = r["lead_id"]
        m = con.execute("SELECT subject, body FROM messages WHERE lead_id=? AND "
                        "direction='in' ORDER BY ts DESC, id DESC LIMIT 1", (lid,)).fetchone()
        if not m:
            continue
        try:
            c = inbound.classify_reply({"subject": m["subject"], "body": m["body"]})
            sent = c.get("sentiment")
        except Exception:
            sent = None
        if sent in ("interested", "not_interested", "question", "auto_reply"):
            con.execute("UPDATE leads SET last_reply_sentiment=? WHERE id=?", (sent, lid))
            n += 1
    con.commit()
    print(f"[badges] backfilled sentiment on {n} leads with inbound mail")


def run(push=True, backfill=False):
    if push:
        ensure_notion_property()
    con = store.connect(); store.init(con)
    if backfill:
        backfill_sentiment(con)
    rows = [dict(r) for r in con.execute(
        f"SELECT * FROM leads WHERE state IN ({','.join('?'*len(ACTIVE))})", ACTIVE)]
    from collections import Counter
    tally = Counter()
    pushed = 0
    for l in rows:
        badges = compute_badges(con, l)
        con.execute("UPDATE leads SET badges=? WHERE id=?", (json.dumps(badges, ensure_ascii=False), l["id"]))
        for b in badges:
            tally[b] += 1
        if push and _push(l["id"], badges):
            pushed += 1
    con.commit()
    print(f"[badges] computed for {len(rows)} leads; pushed {pushed} to Notion")
    for b, c in tally.most_common():
        print(f"    {b:26} {c}")
    con.close()


if __name__ == "__main__":
    run(push="--no-push" not in sys.argv, backfill="--backfill" in sys.argv)
