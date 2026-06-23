"""One-off backfill: log your existing Simply correspondence (Sent + Inbox) onto
the matching leads, so the full history shows on their Notion pages. Run once on
the VPS, then notion_sync.py. Env: SIMPLY_IMAP_HOST, SIMPLY_MAIL_USER, SIMPLY_MAIL_PASS.
"""
import os, imaplib, email, email.utils
from email.header import decode_header
import store

HOST = os.environ.get("SIMPLY_IMAP_HOST", "mail.simply.com")
USER = os.environ["SIMPLY_MAIL_USER"]
PASS = os.environ["SIMPLY_MAIL_PASS"]


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
        return msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", "ignore")
    except Exception:
        return msg.get_payload() or ""


def lead_id(con, addr):
    if not addr:
        return None
    r = con.execute("SELECT id FROM leads WHERE lower(email)=?", (addr.lower(),)).fetchone()
    return r["id"] if r else None


def process(con, M, folder, direction, addr_field):
    typ, _ = M.select(f'"{folder}"', readonly=True)
    if typ != "OK":
        print(f"  (no folder {folder})")
        return 0
    ids = M.search(None, "ALL")[1][0].split()
    n = 0
    for i in ids:
        raw = M.fetch(i, "(BODY.PEEK[])")[1][0][1]
        msg = email.message_from_bytes(raw)
        who = email.utils.parseaddr(dec(msg.get(addr_field)))[1]
        lid = lead_id(con, who)
        if not lid:
            continue
        store.log_message(con, lid, direction, dec(msg.get("Subject")), body_text(msg))
        n += 1
    return n


def main():
    con = store.connect()
    store.init(con)
    M = imaplib.IMAP4(HOST, 143)
    M.starttls()
    M.login(USER, PASS)
    out = process(con, M, "Sent", "out", "To")
    inn = process(con, M, "INBOX", "in", "From")
    M.logout()
    print(f"backfilled {out} sent + {inn} received Simply messages")


if __name__ == "__main__":
    main()
