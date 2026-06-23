"""
List who you've emailed from your Simply mailbox (the Sent folder), so we can
reconcile the lead board to businesses you've actually contacted.

  python3 sent_list.py
Env: SIMPLY_IMAP_HOST, SIMPLY_MAIL_USER, SIMPLY_MAIL_PASS  (already in .env)
"""
import os, imaplib, email
from email.header import decode_header

HOST = os.environ.get("SIMPLY_IMAP_HOST", "mail.simply.com")
USER = os.environ["SIMPLY_MAIL_USER"]
PASS = os.environ["SIMPLY_MAIL_PASS"]


def dec(s):
    if not s:
        return ""
    return "".join(t.decode(c or "utf-8", "ignore") if isinstance(t, bytes) else t
                   for t, c in decode_header(s))


def main():
    M = imaplib.IMAP4(HOST, 143)
    M.starttls()
    M.login(USER, PASS)

    # find the Sent folder — the mailbox name is the last token on the LIST line
    sent, folders = None, M.list()[1]
    for raw in folders:
        line = raw.decode(errors="ignore")
        folder = line.rsplit(None, 1)[-1].strip('"')
        if "\\Sent" in line or folder.lower() in ("sent", "sent items", "inbox.sent"):
            sent = folder
            break
    if not sent:
        print("Could not find a Sent folder. Folders are:")
        for raw in folders:
            print("  ", raw.decode(errors="ignore"))
        return

    typ, _ = M.select(f'"{sent}"', readonly=True)
    if typ != "OK":
        print(f"could not select Sent folder '{sent}'")
        return
    ids = M.search(None, "ALL")[1][0].split()
    print(f"# {len(ids)} messages in '{sent}'\n")
    seen = set()
    for i in reversed(ids):  # newest first
        d = M.fetch(i, "(BODY.PEEK[HEADER.FIELDS (TO SUBJECT DATE)])")[1]
        msg = email.message_from_bytes(d[0][1])
        to = dec(msg["To"])
        if to in seen:
            continue
        seen.add(to)
        print(f"{to:45s} | {dec(msg['Subject'])[:45]:45s} | {msg['Date']}")
    M.logout()


if __name__ == "__main__":
    main()
