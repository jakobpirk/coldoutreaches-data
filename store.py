"""
Lead store + lifecycle state machine for ColdOutreaches.

The durable backbone the cloud pipeline rests on. SQLite so it's a single
portable file (lives in the private data repo); no server needed.

Lifecycle:
    discovered -> scored -> queued -> demo_building -> demo_live
                -> drafted -> sent -> replied -> won / lost
    (any state -> rejected, when you bin a lead)

Dedup key: osm_id if present, else the normalised website URL. A lead already
past `sent` is never re-surfaced for outreach.

CLI:
    python3 store.py init
    python3 store.py ingest output/results.json
    python3 store.py link-screenshots output/screenshots
    python3 store.py stats
    python3 store.py list --state scored --top 20 [--qualified]
    python3 store.py move <lead_id> <new_state> [--note "..."]
"""
from __future__ import annotations
import sys
import os
import re
import json
import argparse
import sqlite3
import datetime as dt
from urllib.parse import urlsplit

DB_PATH = os.environ.get("LEADS_DB", "output/leads.db")

# ---- lifecycle ----------------------------------------------------------

STATES = [
    "discovered", "scored", "queued", "demo_building", "demo_live",
    "drafted", "sent", "replied", "won", "lost", "rejected",
]

# Allowed forward transitions. `rejected` is reachable from anywhere.
TRANSITIONS = {
    "discovered": {"scored", "rejected"},
    "scored": {"queued", "rejected"},
    "queued": {"demo_building", "rejected"},
    "demo_building": {"demo_live", "rejected"},
    "demo_live": {"drafted", "rejected"},
    "drafted": {"sent", "rejected"},
    "sent": {"replied", "won", "lost"},
    "replied": {"won", "lost"},
    "won": set(),
    "lost": set(),
    "rejected": set(),
}
# A lead at or beyond this point must never re-enter the outreach queue.
CONTACTED_STATES = {"sent", "replied", "won", "lost"}


def can_transition(src: str, dst: str) -> bool:
    if dst == "rejected":
        return True
    return dst in TRANSITIONS.get(src, set())


# ---- helpers ------------------------------------------------------------

def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def normalise_url(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return ""
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    parts = urlsplit(u)
    host = parts.netloc.lower().lstrip("www.")
    return f"{host}{parts.path}".rstrip("/")


def dedup_key(rec: dict) -> str:
    osm = (rec.get("osm_id") or "").strip()
    if osm:
        return f"osm:{osm}"
    nu = normalise_url(rec.get("website") or rec.get("final_url") or "")
    return f"url:{nu}" if nu else f"name:{(rec.get('name') or '').strip().lower()}"


def slugify(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[æøå]", lambda m: {"æ": "ae", "ø": "oe", "å": "aa"}[m.group(0)], s)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:40] or "unknown"


# Hosts that are marketplaces / directories / social — a listing here is NOT
# the business's own website, so it's an invalid redesign target no matter how
# dated the page looks. (Jakob's correction: #4 Antikhjørnet was a stall on
# antikvitet.net, not an own-site.) Extend as new ones show up.
MARKETPLACE_HOSTS = {
    "antikvitet.net", "dba.dk", "guloggratis.dk", "facebook.com", "instagram.com",
    "etsy.com", "trustpilot.com", "tripadvisor.com", "tripadvisor.dk", "booking.com",
    "just-eat.dk", "wolt.com", "krak.dk", "degulesider.dk", "findsmiley.dk",
    "linktr.ee", "youtube.com",
}


def _host(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    host = urlsplit(u).netloc.lower()
    for p in ("www.", "m."):
        if host.startswith(p):
            host = host[len(p):]
    return host


def is_marketplace(url: str) -> bool:
    host = _host(url)
    return any(host == b or host.endswith("." + b) for b in MARKETPLACE_HOSTS)


def qualify(rec: dict) -> int:
    """Heuristic pre-qualification until the vision-classify step refines it."""
    if rec.get("status") != 200:
        return 0
    if (rec.get("score") or 0) < 8:
        return 0
    hijack = {"name_mismatch", "name_mismatch_promo", "parked_domain", "thin_or_stub"}
    sig_names = {s.get("name") for s in rec.get("signals", [])}
    if sig_names & hijack:
        return 0
    # invalid target: a marketplace/directory listing is not an own-site
    if is_marketplace(rec.get("final_url") or rec.get("website") or ""):
        return 0
    return 1


# ---- schema -------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dedup_key TEXT UNIQUE NOT NULL,
    osm_id TEXT,
    name TEXT,
    category TEXT,
    subcategory TEXT,
    website TEXT,
    final_url TEXT,
    http_status INTEGER,
    title TEXT,
    error TEXT,
    score INTEGER,
    raw_score INTEGER,
    modern_penalty INTEGER,
    signals_json TEXT,
    phone TEXT,
    email TEXT,
    address TEXT,
    city TEXT,
    postcode TEXT,
    screenshot_path TEXT,
    qualified INTEGER DEFAULT 0,
    -- filled later by the overnight claude -p prep:
    cls_verdict TEXT,
    cls_confidence REAL,
    cls_reasons TEXT,
    contact_person TEXT,
    demo_repo TEXT,
    demo_url TEXT,
    email_draft TEXT,
    -- lifecycle:
    state TEXT NOT NULL DEFAULT 'scored',
    first_seen TEXT,
    last_seen TEXT,
    discovered_at TEXT,
    updated_at TEXT,
    state_changed_at TEXT,
    contacted_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_leads_state ON leads(state);
CREATE INDEX IF NOT EXISTS idx_leads_score ON leads(score);

CREATE TABLE IF NOT EXISTS lead_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER NOT NULL,
    ts TEXT NOT NULL,
    from_state TEXT,
    to_state TEXT,
    note TEXT,
    FOREIGN KEY (lead_id) REFERENCES leads(id)
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER NOT NULL,
    ts TEXT,
    direction TEXT,   -- 'in' or 'out'
    subject TEXT,
    body TEXT,
    synced INTEGER DEFAULT 0
);

-- Answer bank: every reply you APPROVE is stored under its type, so the next
-- mail of the same type reuses your proven answer instead of being written from
-- scratch. You answer each kind of question once; the system reuses it after.
CREATE TABLE IF NOT EXISTS reply_bank (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id INTEGER,
    type TEXT,
    question TEXT,
    answer TEXT,
    ts TEXT
);
"""


def connect(path: str = DB_PATH) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)
    for col in ("next_action TEXT", "followup_date TEXT", "nudged_at TEXT",
                "demo_status TEXT", "demo_checked_at TEXT",
                "badges TEXT", "last_reply_sentiment TEXT"):
        try:
            con.execute(f"ALTER TABLE leads ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass
    con.commit()


# ---- operations ---------------------------------------------------------

def ingest(con: sqlite3.Connection, results_path: str) -> dict:
    records = json.loads(open(results_path, encoding="utf-8").read())
    inserted = updated = skipped_contacted = 0
    for rec in records:
        key = dedup_key(rec)
        row = con.execute("SELECT id, state FROM leads WHERE dedup_key=?", (key,)).fetchone()
        sig = json.dumps(rec.get("signals", []), ensure_ascii=False)
        q = qualify(rec)
        ts = now()
        if row is None:
            con.execute(
                """INSERT INTO leads
                (dedup_key, osm_id, name, category, subcategory, website, final_url,
                 http_status, title, error, score, raw_score, modern_penalty,
                 signals_json, phone, email, address, city, postcode, qualified,
                 state, first_seen, last_seen, discovered_at, updated_at, state_changed_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (key, rec.get("osm_id"), rec.get("name"), rec.get("category"),
                 rec.get("subcategory"), rec.get("website"), rec.get("final_url"),
                 rec.get("status"), rec.get("title"), rec.get("error"),
                 rec.get("score"), rec.get("raw_score"), rec.get("modern_penalty"),
                 sig, rec.get("phone"), rec.get("email"), rec.get("address"),
                 rec.get("city"), rec.get("postcode"), q,
                 "scored", rec.get("first_seen"), rec.get("last_seen"),
                 ts, ts, ts),
            )
            lead_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
            _log(con, lead_id, None, "scored", "ingested")
            inserted += 1
        else:
            # Refresh scan fields but never regress lifecycle. A contacted lead
            # keeps its state; we just update last_seen / scores.
            if row["state"] in CONTACTED_STATES:
                skipped_contacted += 1
            con.execute(
                """UPDATE leads SET name=?, category=?, subcategory=?, website=?,
                   final_url=?, http_status=?, title=?, error=?, score=?, raw_score=?,
                   modern_penalty=?, signals_json=?, phone=?, email=?, address=?,
                   city=?, postcode=?, qualified=?, last_seen=?, updated_at=?
                   WHERE id=?""",
                (rec.get("name"), rec.get("category"), rec.get("subcategory"),
                 rec.get("website"), rec.get("final_url"), rec.get("status"),
                 rec.get("title"), rec.get("error"), rec.get("score"),
                 rec.get("raw_score"), rec.get("modern_penalty"), sig,
                 rec.get("phone"), rec.get("email"), rec.get("address"),
                 rec.get("city"), rec.get("postcode"), q,
                 rec.get("last_seen"), ts, row["id"]),
            )
            updated += 1
    con.commit()
    return {"inserted": inserted, "updated": updated,
            "skipped_contacted": skipped_contacted, "total": len(records)}


def link_screenshots(con: sqlite3.Connection, shots_dir: str) -> int:
    linked = 0
    for row in con.execute("SELECT id, name FROM leads").fetchall():
        path = os.path.join(shots_dir, f"{slugify(row['name'])}.png")
        if os.path.exists(path) and os.path.getsize(path) > 5000:
            con.execute("UPDATE leads SET screenshot_path=? WHERE id=?", (path, row["id"]))
            linked += 1
    con.commit()
    return linked


def requalify(con: sqlite3.Connection) -> int:
    """Recompute the `qualified` flag for every lead from stored fields.
    Run after changing qualification rules — no re-scan needed."""
    n = 0
    for row in con.execute(
            "SELECT id, http_status, score, signals_json, final_url, website FROM leads"):
        rec = {"status": row["http_status"], "score": row["score"],
               "signals": json.loads(row["signals_json"] or "[]"),
               "final_url": row["final_url"], "website": row["website"]}
        con.execute("UPDATE leads SET qualified=? WHERE id=?", (qualify(rec), row["id"]))
        n += 1
    con.commit()
    return n


def move(con: sqlite3.Connection, lead_id: int, dst: str, note: str = "") -> None:
    row = con.execute("SELECT state FROM leads WHERE id=?", (lead_id,)).fetchone()
    if row is None:
        raise SystemExit(f"no lead {lead_id}")
    src = row["state"]
    if dst not in STATES:
        raise SystemExit(f"unknown state '{dst}'. valid: {', '.join(STATES)}")
    if not can_transition(src, dst):
        raise SystemExit(f"illegal transition {src} -> {dst}")
    ts = now()
    contacted = ts if dst in CONTACTED_STATES else None
    con.execute(
        "UPDATE leads SET state=?, state_changed_at=?, updated_at=?, "
        "contacted_at=COALESCE(contacted_at,?) WHERE id=?",
        (dst, ts, ts, contacted, lead_id))
    _log(con, lead_id, src, dst, note)
    con.commit()
    print(f"lead {lead_id}: {src} -> {dst}")


def _log(con, lead_id, src, dst, note):
    con.execute(
        "INSERT INTO lead_events (lead_id, ts, from_state, to_state, note) VALUES (?,?,?,?,?)",
        (lead_id, now(), src, dst, note))


# Hosts we deploy demo previews on. A non-WW link to one of these inside an
# outgoing mail IS the demo we pitched, so we can recover demo_url from the body.
DEMO_HOSTS = ("pages.dev", "onrender.com", "netlify.app", "vercel.app", "github.io")


def extract_demo_url(body: str) -> str | None:
    """First demo-preview link in an email body (not our own site), or None."""
    for u in re.findall(r"https?://[^\s>)\]\"']+", body or ""):
        u = u.rstrip(".,) ")
        if "wilbrandtworks" in u:
            continue
        if any(h in u for h in DEMO_HOSTS):
            return u
    return None


def log_message(con, lead_id, direction, subject, body):
    """Record an email (in/out) against a lead — synced to its Notion page.
    Self-heals demo_url: if an outgoing mail carries a demo link and the lead has
    none on file, capture it — so the structured field never goes blank again
    regardless of how the lead was onboarded (manual/backfill/automated)."""
    con.execute("INSERT INTO messages (lead_id, ts, direction, subject, body) VALUES (?,?,?,?,?)",
                (lead_id, now(), direction, subject, (body or "")[:4000]))
    if direction == "out":
        u = extract_demo_url(body)
        if u:
            con.execute("UPDATE leads SET demo_url=COALESCE(NULLIF(demo_url,''),?) WHERE id=?",
                        (u, lead_id))
    con.commit()


def add_reply_to_bank(con, rtype, question, answer, lead_id=None):
    """Record an approved reply so the next mail of this type reuses it."""
    if not (rtype and answer):
        return
    con.execute("INSERT INTO reply_bank (lead_id, type, question, answer, ts) "
                "VALUES (?,?,?,?,?)",
                (lead_id, rtype, (question or "")[:1000], (answer or "")[:3000], now()))
    con.commit()


def recent_bank(con, per_type: int = 1) -> dict:
    """Latest approved answer(s) per reply type: {type: [{question, answer}, ...]}."""
    out: dict = {}
    for r in con.execute("SELECT type, question, answer FROM reply_bank ORDER BY id DESC"):
        out.setdefault(r["type"], [])
        if len(out[r["type"]]) < per_type:
            out[r["type"]].append({"question": r["question"], "answer": r["answer"]})
    return out


def stats(con: sqlite3.Connection) -> None:
    total = con.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
    qual = con.execute("SELECT COUNT(*) FROM leads WHERE qualified=1").fetchone()[0]
    shots = con.execute("SELECT COUNT(*) FROM leads WHERE screenshot_path IS NOT NULL").fetchone()[0]
    print(f"leads: {total}   qualified: {qual}   with screenshot: {shots}")
    print("by state:")
    for r in con.execute("SELECT state, COUNT(*) c FROM leads GROUP BY state ORDER BY c DESC"):
        print(f"  {r['state']:14s} {r['c']}")


def list_leads(con, state=None, top=20, qualified_only=False) -> None:
    sql = "SELECT id, score, state, qualified, name, final_url FROM leads WHERE 1=1"
    args = []
    if state:
        sql += " AND state=?"; args.append(state)
    if qualified_only:
        sql += " AND qualified=1"
    sql += " ORDER BY score DESC, name LIMIT ?"; args.append(top)
    print(f"{'id':>4} {'score':>5} {'q':>1} {'state':14} name")
    for r in con.execute(sql, args):
        print(f"{r['id']:>4} {r['score']:>5} {r['qualified']:>1} {r['state']:14} "
              f"{(r['name'] or '')[:38]:38} {r['final_url'] or ''}")


# ---- cli ----------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    p = sub.add_parser("ingest"); p.add_argument("results")
    p = sub.add_parser("link-screenshots"); p.add_argument("dir")
    sub.add_parser("stats")
    sub.add_parser("requalify")
    p = sub.add_parser("list")
    p.add_argument("--state"); p.add_argument("--top", type=int, default=20)
    p.add_argument("--qualified", action="store_true")
    p = sub.add_parser("move")
    p.add_argument("lead_id", type=int); p.add_argument("state")
    p.add_argument("--note", default="")
    args = ap.parse_args()

    con = connect()
    init(con)
    if args.cmd == "init":
        print(f"initialised {DB_PATH}")
    elif args.cmd == "ingest":
        print(ingest(con, args.results))
    elif args.cmd == "link-screenshots":
        print(f"linked {link_screenshots(con, args.dir)} screenshots")
    elif args.cmd == "requalify":
        print(f"requalified {requalify(con)} leads")
    elif args.cmd == "stats":
        stats(con)
    elif args.cmd == "list":
        list_leads(con, args.state, args.top, args.qualified)
    elif args.cmd == "move":
        move(con, args.lead_id, args.state, args.note)


if __name__ == "__main__":
    main()
