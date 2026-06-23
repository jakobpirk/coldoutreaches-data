"""One-off: reset the store to your REAL pipeline.
- Rejects the wrong-segment (Sydfyn shops) auto-discovered leads.
- Imports the businesses you've actually emailed (Simply + Gmail) with their real
  state, so the board reflects who you've contacted and who replied.
Run before notion_sync.py (after clear_board.py).
"""
import datetime
import store

# entries: (domain, email, state, contact_person)
# Simply Sent — tradesmen, all just 'sent'
TRADES = [
    ("riistomrer.dk", "lasse@riistomrer.dk"),
    ("resolut.dk", "resolut@resolut.dk"),
    ("byens-laase.dk", "post@byens-laase.dk"),
    ("el-hjoernet.dk", "el-hjoernet@mail.tele.dk"),
    ("sydjyskglas.dk", "info@sydjyskglas.dk"),
    ("gjglas.dk", "tilbud@mgglas.dk"),
    ("toemrerservicedanmark.dk", "service@toemrerservicedanmark.dk"),
    ("dansktoemrerservice.dk", "info@dansktoemrerservice.dk"),
    ("glarmester-juhl.dk", "info@glarmester-juhl.dk"),
    ("glasottsen.dk", "jtglas@esenet.dk"),
    ("brd-glarmester.dk", "mail@brd-glarmester.dk"),
    ("glarmester-stender.dk", "info@glarmester-stender.dk"),
    ("glarmesterbruun.dk", "info@glarmesterbruun.dk"),
    ("glarmestera.dk", "allan@glarmestera.dk"),
    ("vejgaardvvsteknik.dk", "info@vejgaardvvsteknik.dk"),
    ("ttgbyg.dk", "toemrertg@gmail.com"),
    ("bmbmurer.dk", "allan@bmbmurer.dk"),
    ("elling-tomrer.dk", "mail@elling-tomrer.dk"),
    ("murer-klaus.dk", "klaus@murer-klaus.dk"),
    ("ttgulv.dk", "tiptopgulvafslibning@godmail.dk"),
    ("riberproduction.dk", "nr@riberproduction.dk"),
    ("rysholt-tomrer.dk", "kontakt@rysholt-tomrer.dk"),
    ("landevejens.dk", "dean@landevejens.dk"),
    ("byens-bygningssnedker.dk", "byensbygningssnedker@gmail.com"),
    ("knud-kyndesen.dk", "claus@kyndesen.net"),
    ("barendorff.dk", "barendorff@godmail.dk"),
    ("nordjyskmalerfirma.dk", "njmalerfirma@gmail.com"),
    ("sonderso-malerfirma.dk", "allan@sonderso-malerfirma.dk"),
    ("pallemaler.dk", "palle@pallemaler.dk"),
    ("an-maler.dk", "anmaler9800@gmail.com"),
    ("hobromalerfirma.dk", "niels@hobromalerfirma.dk"),
    ("hr-plade.dk", "hr@hr-plade.dk"),
    ("slvvs.dk", "info@slvvs.dk"),
    ("aktivel.dk", "aktivel@aktivel.dk"),
]

# Gmail Sent — earlier Sydfyn/misc outreach, with real reply status
GMAIL = [
    ("svendborgvingaard.dk", "christiankaarejeppesen@gmail.com", "replied", "Christian (positiv — vender tilbage i juli)"),
    ("vinfruen.dk", "post@vinfruen.dk", "lost", "(takkede nej — beholder nuværende side)"),
    ("paskram.dk", "paskram@paskram.dk", "sent", ""),
    ("bo-h.dk", "ole@bo-h.dk", "sent", "Ole"),
    ("bgrevision.dk", "info@bgrevision.dk", "sent", ""),
    ("stensandgrus.dk", "dennis@stensandgrus.dk", "sent", "Dennis"),
    ("biologiforbundet.dk", "kontakt@biologiforbundet.dk", "sent", ""),
    ("", "c.hallberg@jubii.dk", "sent", "Hallberg (gæstgiveri)"),
]


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def upsert(con, domain, email, state, contact, ts):
    key = ("url:" + domain.lower()) if domain else ("email:" + email.lower())
    name = (domain.split(".")[0].replace("-", " ").title() if domain
            else (contact or email))
    site = ("https://" + domain) if domain else ""
    con.execute(
        """INSERT INTO leads (dedup_key, name, website, final_url, email,
           contact_person, qualified, state, first_seen, last_seen, discovered_at,
           updated_at, state_changed_at, contacted_at)
           VALUES (?,?,?,?,?,?,1,?,?,?,?,?,?,?)
           ON CONFLICT(dedup_key) DO UPDATE SET
             email=excluded.email, contact_person=excluded.contact_person,
             state=excluded.state, qualified=1, contacted_at=excluded.contacted_at""",
        (key, name, site, site, email, contact, state, ts, ts, ts, ts, ts, ts))


def main():
    con = store.connect()
    store.init(con)
    con.execute("UPDATE leads SET state='rejected', qualified=0")  # drop wrong-segment noise
    ts = now()
    for domain, email in TRADES:
        upsert(con, domain, email, "sent", "", ts)
    for domain, email, state, contact in GMAIL:
        upsert(con, domain, email, state, contact, ts)
    con.commit()
    total = len(TRADES) + len(GMAIL)
    print(f"imported {total} contacted businesses "
          f"({len(TRADES)} tradesmen + {len(GMAIL)} Gmail); old leads rejected")


if __name__ == "__main__":
    main()
