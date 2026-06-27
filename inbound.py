"""
Inbound email router — ONE inbox, content-based routing. Decides what each email
is before anything happens, so we never create wrong tickets or change code we
shouldn't. Address-independent: a ticket on hej@ and a reply on support@ route
the same way — by *who* sent it and *what* they ask.

Routes:
  - prospect_reply : a lead you've contacted replied to an offer ->
                     analyse sentiment, mark the lead `replied` (Notion updates).
  - ticket         : a customer asks to change THEIR site -> create a ticket;
                     auto-fix only if small + safe + confident, else `needs_you`.
  - message        : a customer email that's NOT a change request (thanks / question)
                     -> no ticket, no code change.
  - unknown        : not a known contact -> stays in your inbox, nothing created.

Driven by n8n's IMAP trigger:
    echo '{"from":"x@y.dk","subject":"...","body":"..."}' | python3 inbound.py -

Uses `claude -p`; falls back to a heuristic offline so it still runs in tests.
"""
from __future__ import annotations
import os, re, sys, json, subprocess, datetime as dt
import store, tickets, obs

AUTO_FIX_MIN_CONFIDENCE = float(os.environ.get("AUTO_FIX_MIN_CONFIDENCE", "0.7"))
CLAUDE_CMD = os.environ.get("CLAUDE_CMD", "claude")


def _claude(prompt, timeout=180, label="inbound"):
    _, parsed = obs.claude(CLAUDE_CMD, prompt, label=label, timeout=timeout, expect_json=True)
    if parsed is None:
        raise RuntimeError("no json in claude output")
    return parsed


def sender_kind(con, sender: str):
    sender = (sender or "").strip().lower()
    row = con.execute(
        "SELECT * FROM leads WHERE lower(email)=? "
        "ORDER BY (state IN ('won','live')) DESC, (state IN ('sent','replied')) DESC LIMIT 1",
        (sender,)).fetchone()
    if not row:
        return "unknown", None
    lead = dict(row)
    if lead["state"] in ("won", "live", "iterating", "impl_approved"):
        return "customer", lead
    if lead["state"] in ("drafted", "sent", "replied", "demo_live"):
        return "prospect", lead
    return "other", lead


# ---- classification (claude -p, with heuristic fallback) ---------------

def classify_reply(email):
    try:
        return _claude(f"""A prospect replied to a cold website-design offer.
Subject: {email.get('subject')}
Body: \"\"\"{email.get('body','')[:1200]}\"\"\"
Output JSON: {{"sentiment":"interested|not_interested|question|auto_reply",
"summary":"<one sentence>",
"followup_date":"<ISO date YYYY-MM-DD if a follow-up is warranted (e.g. they say they'll come back later), else empty>",
"next_action":"<short Danish next step, or empty>",
"rationale":"<one sentence: why this sentiment>"}}""", label="inbound:reply")
    except Exception:
        import datetime
        t = f"{email.get('subject','')} {email.get('body','')}".lower()
        if any(w in t for w in ("nej tak", "ikke interesseret", "ellers tak", "frabeder", "afmeld")):
            s = "not_interested"
        elif "?" in t:
            s = "question"
        else:
            s = "interested"
        fu = ((datetime.date.today() + datetime.timedelta(days=14)).isoformat()
              if s in ("interested", "question") else "")
        return {"sentiment": s, "summary": email.get("body", "")[:120].replace("\n", " "),
                "followup_date": fu, "next_action": "Følg op" if fu else ""}


def classify_ticket(email, customer):
    try:
        return _claude(f"""A known customer ({customer['name']}) emailed. Their site
repo: {customer.get('demo_repo')}.
Subject: {email.get('subject')}
Body: \"\"\"{email.get('body','')[:1500]}\"\"\"
Decide. Output JSON: {{"is_ticket": true/false, "type":"content|copy|styling|bug|feature|other",
"auto_fixable": true/false, "confidence": 0-1, "title":"...", "summary":"...",
"reason":"..."}}.
is_ticket=true ONLY if they ask to CHANGE their existing website. Thank-yous,
questions, invoices, anything else -> is_ticket=false. auto_fixable=true ONLY for
small, safe edits; large/ambiguous/risky -> false.""")
    except Exception:
        body = email.get("body", "")
        t = f"{email.get('subject','')} {body}".lower()
        change = any(h in t for h in tickets.AUTO_FIX_HINTS) or "kan i" in t
        big = any(w in t for w in ("webshop", "betaling", "shop", "integration", "system", "login"))
        is_ticket = change or big
        return {"is_ticket": is_ticket, "type": "feature" if big else "content",
                "auto_fixable": bool(change and not big and len(body) < 600),
                "confidence": 0.8 if (change and not big) else 0.5,
                "title": (email.get("subject") or body[:50]).strip(),
                "summary": body[:140].strip().replace("\n", " "),
                "reason": "heuristic"}


# ---- routing -----------------------------------------------------------

def route(con, email):
    kind, lead = sender_kind(con, email.get("from"))
    if kind == "unknown":
        print(f"[inbound] unknown sender {email.get('from')!r} -> stays in inbox, nothing created.")
        return {"route": "unknown"}

    if kind in ("prospect", "other"):
        c = classify_reply(email)
        if lead["state"] in ("drafted", "sent", "demo_live"):
            try:
                store.move(con, lead["id"], "replied", note=f"reply: {c['sentiment']}")
            except SystemExit:
                pass
        con.execute("UPDATE leads SET last_reply_sentiment=? WHERE id=?",
                    (c.get("sentiment"), lead["id"]))
        if c.get("followup_date") or c.get("next_action"):
            con.execute("UPDATE leads SET followup_date=COALESCE(?,followup_date), "
                        "next_action=COALESCE(?,next_action) WHERE id=?",
                        (c.get("followup_date") or None, c.get("next_action") or None, lead["id"]))
        con.commit()
        print(f"[inbound] prospect_reply from {lead['name']} -> sentiment={c['sentiment']}; "
              f"lead #{lead['id']} -> replied; follow-up={c.get('followup_date') or '-'}.")
        return {"route": "prospect_reply", **c}

    # kind == customer
    c = classify_ticket(email, lead)
    if not c.get("is_ticket"):
        print(f"[inbound] message from customer {lead['name']} (not a change request) "
              f"-> no ticket, no code change. ({c.get('summary','')[:60]})")
        return {"route": "message", **c}

    auto = bool(c.get("auto_fixable") and (c.get("confidence", 0) >= AUTO_FIX_MIN_CONFIDENCE))
    status = "new" if auto else "needs_you"
    ts = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    cur = con.execute(
        """INSERT INTO tickets (lead_id, customer, customer_email, repo, status, type,
           auto_fixable, title, summary, original_email, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (lead["id"], lead["name"], lead.get("email"), lead.get("demo_repo"), status,
         c.get("type", "other"), 1 if auto else 0, c.get("title", "")[:120],
         c.get("summary", ""), f"From: {email.get('from')}\nSubject: {email.get('subject')}"
         f"\n\n{email.get('body','')}", ts, ts))
    con.commit()
    tid = cur.lastrowid
    gate = "AUTO-FIX (branch->staging)" if auto else f"needs_you (conf={c.get('confidence')}, no code change)"
    print(f"[inbound] ticket #{tid} '{c.get('title')}' ({c.get('type')}) for {lead['name']} -> {gate}")
    return {"route": "ticket", "ticket_id": tid, "auto_fix": auto, **c}


if __name__ == "__main__":
    raw = sys.stdin.read() if (len(sys.argv) > 1 and sys.argv[1] == "-") else open(sys.argv[1]).read()
    con = store.connect(); tickets.init(con)
    route(con, json.loads(raw))
