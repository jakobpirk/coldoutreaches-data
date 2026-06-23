"""Nightly inbox check — read only NEW mail (since the last run) from the Simply
inbox and route each message through inbound.py (reply states, follow-ups,
tickets). The last processed UID is kept in data/last_uid.txt so nothing is
handled twice. First run just records the watermark (no backlog processing).
Env: SIMPLY_IMAP_HOST, SIMPLY_MAIL_USER, SIMPLY_MAIL_PASS, NOTION_TOKEN.
"""
import os, imaplib, email, email.utils, pathlib
from email.header import decode_header
import store, inbound

HOST = os.environ.get("SIMPLY_IMAP_HOST", "mail.simply.com")
USER = os.environ["SIMPLY_MAIL_USER"]
PASS = os.environ["SIMPLY_MAIL_PASS"]
WATERMARK = pathlib.Path("data/last_uid.txt")


def dec(s):
    if not s:
        return ""
    return "".join(t.decode(c or "utf-8", "ignore") if isinstance(t, bytes) else t
                   for t, c in decode_header(s))


def body_text(msg):
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and \
                    "attachment" not in str(part.get("Content-Disposition", "")):
                try:
                    return part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", "ignore")
                except Exception:
                    pass
        return ""
    try:
        return msg.get_payload(decode=True).decode(
            msg.get_content_charset() or "utf-8", "ignore")
    except Exception:
        return msg.get_payload() or ""


def main():
    con = store.connect()
    store.init(con)
    M = imaplib.IMAP4(HOST, 143)
    M.starttls()
    M.login(USER, PASS)
    M.select("INBOX", readonly=True)
    all_uids = M.uid("search", None, "ALL")[1][0].split()
    maxuid = int(all_uids[-1]) if all_uids else 0

    if not WATERMARK.exists():
        WATERMARK.parent.mkdir(parents=True, exist_ok=True)
        WATERMARK.write_text(str(maxuid))
        print(f"[inbox] baseline set at UID {maxuid}; no backlog processed")
        M.logout()
        return

    last = int(WATERMARK.read_text() or 0)
    todo = [u for u in all_uids if int(u) > last]
    print(f"[inbox] {len(todo)} new messages since UID {last}")
    for u in todo:
        raw = M.uid("fetch", u, "(BODY.PEEK[])")[1][0][1]
        msg = email.message_from_bytes(raw)
        frm = email.utils.parseaddr(dec(msg.get("From")))[1]
        subj, body = dec(msg.get("Subject")), body_text(msg)
        inbound.route(con, {"from": frm, "subject": subj, "body": body})
        lead = con.execute("SELECT id FROM leads WHERE lower(email)=?", (frm.lower(),)).fetchone()
        if lead:
            store.log_message(con, lead["id"], "in", subj, body)
    WATERMARK.write_text(str(maxuid))
    M.logout()


if __name__ == "__main__":
    main()
