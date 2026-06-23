"""Send-on-approval outbox. Sends the Email draft for any lead you ticked
'Send now' in Notion, via Simply SMTP (from hej@wilbrandtworks.dk), then unticks
it, marks the lead 'sent', and clears the follow-up. Run from cron (nightly or
more often). Env: NOTION_TOKEN, NOTION_DB_ID, SIMPLY_SMTP_HOST/PORT,
SIMPLY_MAIL_USER/PASS.
"""
import os, ssl, smtplib, datetime
from email.message import EmailMessage
import requests
import store

TOKEN = os.environ["NOTION_TOKEN"]
DB = os.environ["NOTION_DB_ID"]
API = "https://api.notion.com/v1"
H = {"Authorization": f"Bearer {TOKEN}", "Notion-Version": "2022-06-28",
     "Content-Type": "application/json"}
SMTP_HOST = os.environ.get("SIMPLY_SMTP_HOST", "smtp.simply.com")
SMTP_PORT = int(os.environ.get("SIMPLY_SMTP_PORT", "587"))
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
    msg.set_content(body)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.starttls(context=ssl.create_default_context())
        s.login(USER, PASS)
        s.send_message(msg)


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
        lead_id = (pr.get("Lead ID") or {}).get("number")
        if not to or not draft:
            print(f"  skip {p['id'][:8]} (missing email or draft)")
            continue
        subj, body = parse(draft)
        try:
            send(to, subj, body)
        except Exception as e:
            print(f"  send to {to} FAILED: {e}")
            continue
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
    con.commit()
    print(f"[outbox] sent {n}")


if __name__ == "__main__":
    main()
