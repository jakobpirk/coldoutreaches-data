"""
Auto-release finished demos: send the offer WITHOUT manual approval — but only
after a Playwright quality test passes (responsive view, working burger menu,
no text overflow / breakage). PASS -> send the drafted offer + mark sent.
FAIL -> keep in demo_live and flag for manual review (never email a broken demo).

Safety:
- live sending is gated by AUTO_SEND_DEMOS=1 (default OFF). With it off (or
  --dry-run) it validates and logs who WOULD be emailed, but sends nothing.
- the validator is an independent model (verify_demo VERIFY_MODEL=sonnet), not the
  one that built the demo.
- honours the existing 'Reject' state; rate-limited via RELEASE_LIMIT.

    python3 release_demos.py --dry-run        # validate + show, send nothing
    AUTO_SEND_DEMOS=1 python3 release_demos.py --limit 10
Env: SIMPLY_*, NOTION_TOKEN/DB, RENDER (for verify), CLAUDE_CMD, LEADS_DB.
"""
import os, sys, argparse, datetime
import store, obs, verify_demo
from send_outbox import send, save_to_sent, parse, with_demo_nb   # reuse SMTP + Sent + draft + NB

AUTO = os.environ.get("AUTO_SEND_DEMOS", "0") == "1"


def eligible(con):
    return con.execute(
        "SELECT * FROM leads WHERE state IN ('demo_live','drafted') "
        "AND email IS NOT NULL AND email!='' "
        "AND email_draft IS NOT NULL AND email_draft!='' "
        "AND demo_url IS NOT NULL AND demo_url!='' "
        "ORDER BY score DESC").fetchall()


def main(limit, dry):
    live_send = AUTO and not dry
    with obs.run("release_demos", live_send=live_send):
        con = store.connect(); store.init(con)
        rows = eligible(con)
        if limit:
            rows = rows[:limit]
        print(f"[release] {len(rows)} demo(s) ready · live_send={live_send} "
              f"(AUTO_SEND_DEMOS={'1' if AUTO else '0'}, dry={dry})")
        sent = held = 0
        for r in rows:
            lead = dict(r)
            v = verify_demo.validate_demo(lead["demo_url"], lead["name"], prefix=f"send{lead['id']}")
            if not v.get("ok"):
                issues = "; ".join(v.get("issues", []))[:300]
                con.execute("UPDATE leads SET next_action=? WHERE id=?",
                            (f"⚠️ Auto-send holdt (kvalitet): {issues}", lead["id"]))
                con.commit()
                obs.event("release_held", lead_id=lead["id"], error=issues)
                held += 1
                print(f"  HOLD #{lead['id']} {lead['name']}: {issues[:90]}")
                continue
            if not live_send:
                obs.event("release_would_send", lead_id=lead["id"])
                print(f"  WOULD SEND #{lead['id']} {lead['name']} -> {lead['email']}")
                continue
            subj, body = parse(lead["email_draft"])
            body = with_demo_nb(body)   # guarantee the demo NB on the cold offer
            try:
                msg = send(lead["email"], subj, body)
                save_to_sent(msg)
            except Exception as e:
                obs.event("release_send_error", lead_id=lead["id"], error=str(e)[:160])
                print(f"  SEND FAIL #{lead['id']}: {e}")
                continue
            store.log_message(con, lead["id"], "out", subj, body)
            con.execute("UPDATE leads SET state='sent', followup_date=NULL, "
                        "next_action='Tilbud auto-sendt (valideret)', contacted_at=? WHERE id=?",
                        (datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                         lead["id"]))
            con.commit()
            obs.event("release_sent", lead_id=lead["id"], state="sent")
            sent += 1
            print(f"  SENT #{lead['id']} {lead['name']} -> {lead['email']}")
        print(f"[release] done: sent {sent}, held {held}")
        con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=int(os.environ.get("RELEASE_LIMIT", "10")))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    main(a.limit, a.dry_run)
