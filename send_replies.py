"""
Approve-and-send for the auto-reply drafts. Reads the "Svar – Inbox" Notion
database: any row you ticked "Send svar" gets mailed (as a proper threaded reply
from hej@wilbrandtworks.dk), saved to Sent, marked Status=sent and unticked.
Rows you ticked "Afvis" are marked Status=rejected and unticked. Never sends
anything you didn't tick. Runs right after reply_agent.py (every ~30 min).

Env: NOTION_TOKEN, SIMPLY_SMTP_HOST/PORT, SIMPLY_IMAP_HOST/PORT, SIMPLY_MAIL_USER/PASS.
"""
import os, ssl, json, smtplib, imaplib, datetime, pathlib
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
import requests
import store
from send_outbox import save_to_sent   # reuse the Sent-folder copier

API = "https://api.notion.com/v1"
H = {"Authorization": f"Bearer {os.environ['NOTION_TOKEN']}",
     "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
SMTP_HOST = os.environ.get("SIMPLY_SMTP_HOST", "smtp.simply.com")
SMTP_PORT = int(os.environ.get("SIMPLY_SMTP_PORT", "587"))
USER = os.environ["SIMPLY_MAIL_USER"]
PASS = os.environ["SIMPLY_MAIL_PASS"]
IDS = pathlib.Path("data/reply_ids.json")


def rt(prop):
    return "".join(x.get("plain_text", "") for x in (prop or {}).get("rich_text", []))


def parse(draft):
    subj, body = "SV:", draft or ""
    if body.lower().startswith("subject:") or body.lower().startswith("sv:"):
        line, _, rest = body.partition("\n")
        subj = line.split(":", 1)[1].strip() if ":" in line else line.strip()
        if not subj.lower().startswith("sv"):
            subj = "SV: " + subj
        body = rest.lstrip("\n")
    return subj, body


def send(to, subj, body, in_reply_to=None):
    msg = EmailMessage()
    msg["From"] = USER
    msg["To"] = to
    msg["Subject"] = subj
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="wilbrandtworks.dk")
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.set_content(body)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.starttls(context=ssl.create_default_context())
        s.login(USER, PASS)
        s.send_message(msg)
    return msg


def query(db, prop):
    r = requests.post(f"{API}/databases/{db}/query", headers=H,
                      json={"filter": {"property": prop, "checkbox": {"equals": True}}})
    r.raise_for_status()
    return r.json()["results"]


def main():
    if not IDS.exists():
        raise SystemExit("data/reply_ids.json missing — run setup_replies.py first")
    db = json.loads(IDS.read_text())["inbox_db"]
    con = store.connect(); store.init(con)

    sent = 0
    for p in query(db, "Send svar"):
        pr = p["properties"]
        to = (pr.get("From") or {}).get("email")
        draft = rt(pr.get("Reply draft"))
        irt = rt(pr.get("Message-ID")) or None
        lead_id = (pr.get("Lead ID") or {}).get("number")
        rtype = ((pr.get("Reply type") or {}).get("select") or {}).get("name")
        question = rt(pr.get("Original"))
        if not (to and draft):
            requests.patch(f"{API}/pages/{p['id']}", headers=H, json={"properties": {
                "Send svar": {"checkbox": False},
                "Status": {"select": {"name": "error"}}}})
            print(f"  skip {to or p['id'][:8]} (missing email or draft)")
            continue
        subj, body = parse(draft)
        try:
            msg = send(to, subj, body, in_reply_to=irt)
        except Exception as e:
            requests.patch(f"{API}/pages/{p['id']}", headers=H, json={"properties": {
                "Send svar": {"checkbox": False}, "Status": {"select": {"name": "error"}}}})
            print(f"  send to {to} FAILED: {e}")
            continue
        save_to_sent(msg)
        requests.patch(f"{API}/pages/{p['id']}", headers=H, json={"properties": {
            "Send svar": {"checkbox": False}, "Status": {"select": {"name": "sent"}}}})
        if lead_id:
            store.log_message(con, int(lead_id), "out", subj, body)
        # remember this approved answer so the next mail of this type reuses it
        store.add_reply_to_bank(con, rtype, question, body, int(lead_id) if lead_id else None)
        sent += 1
        print(f"  sent reply to {to}")

    rejected = 0
    for p in query(db, "Afvis"):
        requests.patch(f"{API}/pages/{p['id']}", headers=H, json={"properties": {
            "Afvis": {"checkbox": False}, "Status": {"select": {"name": "rejected"}}}})
        rejected += 1
    con.commit()
    print(f"[replies] sent {sent}, rejected {rejected}")


if __name__ == "__main__":
    main()
