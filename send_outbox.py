"""Send-on-approval outbox. Sends the Email draft for any lead you ticked
'Send now' in Notion, via Simply SMTP (from hej@wilbrandtworks.dk), then unticks
it, marks the lead 'sent', and clears the follow-up. Run from cron (nightly or
more often). Env: NOTION_TOKEN, NOTION_DB_ID, SIMPLY_SMTP_HOST/PORT,
SIMPLY_MAIL_USER/PASS.
"""
import os, ssl, smtplib, imaplib, datetime
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
import requests
import store

TOKEN = os.environ["NOTION_TOKEN"]
DB = os.environ["NOTION_DB_ID"]
API = "https://api.notion.com/v1"
H = {"Authorization": f"Bearer {TOKEN}", "Notion-Version": "2022-06-28",
     "Content-Type": "application/json"}
SMTP_HOST = os.environ.get("SIMPLY_SMTP_HOST", "smtp.simply.com")
SMTP_PORT = int(os.environ.get("SIMPLY_SMTP_PORT", "587"))
IMAP_HOST = os.environ.get("SIMPLY_IMAP_HOST", "mail.simply.com")
IMAP_PORT = int(os.environ.get("SIMPLY_IMAP_PORT", "143"))
USER = os.environ["SIMPLY_MAIL_USER"]
PASS = os.environ["SIMPLY_MAIL_PASS"]


def rt(prop):
    return "".join(x.get("plain_text", "") for x in (prop or {}).get("rich_text", []))


def parse(draft):
    subj, body = "Opfølgning", draft or ""
    if body.lower().startswith("subject:"):
        line, _, rest = body.partition("\n")
        subj = line.split(":", 1)[1].strip()
        body = rest.lstrip("\n")
    return subj, body


def send(to, subj, body):
    msg = EmailMessage()
    msg["From"] = USER
    msg["To"] = to
    msg["Subject"] = subj
    # Date + Message-ID matter for deliverability — without them some receiving
    # servers silently drop the mail or route it straight to spam.
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="wilbrandtworks.dk")
    msg.set_content(body)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.starttls(context=ssl.create_default_context())
        s.login(USER, PASS)
        s.send_message(msg)
    return msg


def save_to_sent(msg):
    """APPEND a copy to the Simply 'Sent' folder so it shows in webmail.
    Best-effort — never let a Sent-copy failure look like a send failure."""
    try:
        m = imaplib.IMAP4(IMAP_HOST, IMAP_PORT)
        m.starttls(ssl_context=ssl.create_default_context())
        m.login(USER, PASS)
        # Find the Sent folder (Dovecot naming varies between hosts).
        target = None
        typ, boxes = m.list()
        if typ == "OK":
            for b in boxes:
                line = b.decode(errors="ignore")
                name = line.split(' "')[-1].strip().strip('"')
                if name.lower().split("/")[-1].split(".")[-1] in ("sent", "sent messages", "sent items"):
                    target = name
                    break
        target = target or "Sent"
        m.append(target, "(\\Seen)", imaplib.Time2Internaldate(datetime.datetime.now()),
                 msg.as_bytes())
        m.logout()
        return True
    except Exception as e:
        print(f"    (could not save Sent copy: {e})")
        return False


def main():
    con = store.connect()
    store.init(con)
    r = requests.post(f"{API}/databases/{DB}/query", headers=H,
                      json={"filter": {"property": "Send now", "checkbox": {"equals": True}}})
    r.raise_for_status()
    pages = r.json()["results"]
    n = 0
    for p in pages:
        pr = p["properties"]
        to = (pr.get("Email address") or {}).get("email")
        draft = rt(pr.get("Email draft"))
        name = "".join(x.get("plain_text", "") for x in (pr.get("Name") or {}).get("title", []))
        lead_id = (pr.get("Lead ID") or {}).get("number")
        if not to and not draft:
            print(f"  skip {name or p['id'][:8]} (no email AND no draft)")
            continue
        if not to:
            print(f"  skip {name or p['id'][:8]} (no email address on file — can't send)")
            continue
        if not draft:
            print(f"  skip {name or p['id'][:8]} (no Email draft)")
            continue
        subj, body = parse(draft)
        try:
            msg = send(to, subj, body)
        except Exception as e:
            print(f"  send to {to} FAILED: {e}")
            continue
        save_to_sent(msg)
        requests.patch(f"{API}/pages/{p['id']}", headers=H, json={"properties": {
            "Send now": {"checkbox": False}, "State": {"select": {"name": "sent"}},
            "Follow-up date": {"date": None}, "Next action": {"rich_text": []}}})
        if lead_id:
            store.log_message(con, int(lead_id), "out", subj, body)
            con.execute("UPDATE leads SET state='sent', followup_date=NULL, next_action=NULL, "
                        "contacted_at=? WHERE id=?",
                        (datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                         int(lead_id)))
        n += 1
        print(f"  sent to {to}")

    # rejected: tick 'Reject' -> mark the lead rejected, nothing sent
    rej = 0
    rr = requests.post(f"{API}/databases/{DB}/query", headers=H,
                       json={"filter": {"property": "Reject", "checkbox": {"equals": True}}})
    if rr.ok:
        for p in rr.json()["results"]:
            lead_id = (p["properties"].get("Lead ID") or {}).get("number")
            requests.patch(f"{API}/pages/{p['id']}", headers=H, json={"properties": {
                "Reject": {"checkbox": False}, "State": {"select": {"name": "rejected"}}}})
            if lead_id:
                con.execute("UPDATE leads SET state='rejected', followup_date=NULL, "
                            "next_action=NULL WHERE id=?", (int(lead_id),))
            rej += 1
    con.commit()
    print(f"[outbox] sent {n}, rejected {rej}")


if __name__ == "__main__":
    main()
