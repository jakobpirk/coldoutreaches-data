"""Nightly follow-up maintenance:
- ONE 10-day nudge per sent, no-reply lead (tracked via nudged_at, so a lead
  never gets a second nudge),
- draft a short Danish nudge into the outbox (email_draft) for due follow-ups,
- auto-clear follow-ups that are more than 3 months overdue and never actioned.
"""
import datetime
import store

NUDGE = ("Subject: Opfølgning – nyt design\n\nHej{contact},\n\nJeg ville lige "
         "følge op på min tidligere mail om et nyt design til jeres hjemmeside. "
         "Sig endelig til, hvis det har interesse — så viser jeg dig gerne "
         "udkastet.\n\nVh Jakob\nWilbrandt Works")


def main():
    con = store.connect()
    store.init(con)
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

    # 1. exactly one nudge per sent lead, 10 days after they were contacted
    con.execute(
        "UPDATE leads SET followup_date=date(COALESCE(contacted_at,updated_at),'+10 days'), "
        "next_action='Følg op — intet svar endnu', nudged_at=? "
        "WHERE state='sent' AND nudged_at IS NULL", (ts,))

    # 2. draft a nudge into the outbox for due follow-ups that have no draft yet
    due = con.execute(
        "SELECT id, contact_person FROM leads WHERE followup_date IS NOT NULL "
        "AND followup_date<=date('now') AND (email_draft IS NULL OR email_draft='')"
    ).fetchall()
    for r in due:
        c = r["contact_person"].split(" (")[0] if r["contact_person"] else ""
        con.execute("UPDATE leads SET email_draft=? WHERE id=?",
                    (NUDGE.format(contact=(" " + c) if c else ""), r["id"]))

    # 3. auto-expire follow-ups older than 3 months
    cleared = con.execute(
        "UPDATE leads SET followup_date=NULL, next_action=NULL "
        "WHERE followup_date IS NOT NULL AND followup_date < date('now','-3 months')"
    ).rowcount

    con.commit()
    print(f"[followups] nudges ensured; {len(due)} drafts written; {cleared} stale cleared")


if __name__ == "__main__":
    main()
