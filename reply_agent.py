"""
Auto-reply DRAFTER — runs every ~30 min (separate from the heavy design pipeline).

For each NEW message in the Simply inbox it:
  1. classifies the mail into one of your reply types (Svar-skabeloner in Notion),
  2. writes a Danish DRAFT reply using that type's template + the lead context,
  3. creates a row in the "Svar – Inbox" Notion database with the draft and a
     "Send svar" checkbox — and STOPS. Nothing is ever sent here; you approve a
     draft by ticking "Send svar", and send_replies.py mails it.

Type "ignorer" (spam / newsletters / no-reply / auto-replies) gets no draft and
no row. A separate watermark (data/reply_uid.txt) means this never fights the
nightly inbox_poll.py, and the first run only sets a baseline (no backlog spam).

Env: SIMPLY_IMAP_HOST/PORT, SIMPLY_MAIL_USER/PASS, NOTION_TOKEN, CLAUDE_CMD.
"""
from __future__ import annotations
import os, re, json, ssl, imaplib, email, email.utils, pathlib, subprocess
from email.header import decode_header
import requests
import store

API = "https://api.notion.com/v1"
H = {"Authorization": f"Bearer {os.environ.get('NOTION_TOKEN','')}",
     "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
IMAP_HOST = os.environ.get("SIMPLY_IMAP_HOST", "mail.simply.com")
IMAP_PORT = int(os.environ.get("SIMPLY_IMAP_PORT", "143"))
USER = os.environ["SIMPLY_MAIL_USER"]
PASS = os.environ["SIMPLY_MAIL_PASS"]
CLAUDE_CMD = os.environ.get("CLAUDE_CMD", "claude")
WATERMARK = pathlib.Path("data/reply_uid.txt")
IDS = pathlib.Path("data/reply_ids.json")
TEMPLATES = pathlib.Path("reply-templates.md")
EMAIL_STYLE = pathlib.Path("email-style.md")
EMAIL_EXAMPLES = pathlib.Path("email-examples.md")   # learned from your sent mails
NO_REPLY = ("noreply", "no-reply", "no_reply", "mailer-daemon", "postmaster",
            "donotreply", "bounce", "notifications@", "newsletter")


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


def parse_templates() -> dict:
    """reply-templates.md -> {type_key: {'desc':..., 'template':...}}."""
    out, cur = {}, None
    for line in TEMPLATES.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            cur = line[3:].strip()
            out[cur] = {"desc": "", "template": ""}
        elif cur and line.lower().startswith("beskrivelse:"):
            out[cur]["desc"] = line.split(":", 1)[1].strip()
        elif cur and line.lower().startswith("skabelon:"):
            out[cur]["template"] = line.split(":", 1)[1].strip()
    return out


def claude_json(prompt, timeout=180):
    r = subprocess.run([CLAUDE_CMD, "-p"], input=prompt, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[:200])
    m = re.search(r"\{.*\}", r.stdout, re.S)
    if not m:
        raise RuntimeError("no json in claude output")
    return json.loads(m.group(0))


def classify_and_draft(types: dict, mail: dict, lead: dict | None) -> dict:
    type_block = "\n".join(
        f"- {k}: {v['desc']}\n    skabelon-retning: {v['template']}" for k, v in types.items())
    style = EMAIL_STYLE.read_text(encoding="utf-8")[:1200] if EMAIL_STYLE.exists() else ""
    examples = EMAIL_EXAMPLES.read_text(encoding="utf-8")[:2200] if EMAIL_EXAMPLES.exists() else ""
    ctx = (f"Afsender er et kendt lead: {lead['name']}. "
           f"Demo: {lead.get('demo_url') or '(ingen)'}." if lead else
           "Afsenderen er ikke et kendt lead.")
    prompt = f"""Du er assistent for Jakob, Wilbrandt Works (webdesign). En mail er kommet ind.
Vælg den rigtige svar-TYPE fra listen, og skriv et kort dansk SVAR-UDKAST i den retning typen angiver.

Svar-typer:
{type_block}

Indkommen mail:
Fra: {mail['from']}
Emne: {mail['subject']}
Tekst: \"\"\"{(mail['body'] or '')[:1400]}\"\"\"

Kontekst: {ctx}

Stilregler for svaret — følg dem:
{style}

Sådan skriver Jakob i virkeligheden (efterlign tone og opbygning i disse rigtige eksempler):
{examples or '(ingen eksempler endnu)'}

Hvis typen er "ignorer", så skriv intet udkast.
Output KUN JSON: {{"type":"<en af typerne>","subject":"SV: ...","body":"<svaret, underskrevet Jakob, Wilbrandt Works>"}}
For "ignorer": {{"type":"ignorer"}}"""
    try:
        return claude_json(prompt)
    except Exception as e:
        # heuristic fallback so the loop still runs offline / on claude failure
        t = f"{mail['subject']} {mail['body']}".lower()
        if "redesign" in t or "eksisterende" in t:
            ty = "redesign_eksisterende"
        elif "ny side" in t or "ny hjemmeside" in t:
            ty = "ny_side"
        elif "pris" in t or "koster" in t or "tilbud" in t:
            ty = "pris"
        elif any(w in t for w in ("nej tak", "ikke interesseret", "ellers tak")):
            ty = "ikke_interesseret"
        else:
            ty = "andet"
        name = lead["name"] if lead else ""
        return {"type": ty, "subject": f"SV: {mail['subject']}",
                "body": f"Hej{(' ' + name) if name else ''},\n\nTak for din mail. "
                        f"[udkast kunne ikke genereres automatisk: {e}]\n\nVh Jakob\nWilbrandt Works"}


def rt(s):
    s = (s or "")[:1900]
    return [{"type": "text", "text": {"content": s}}] if s else []


def create_row(db, mail, result, lead):
    props = {
        "Subject": {"title": [{"type": "text", "text": {"content": (mail["subject"] or "(uden emne)")[:200]}}]},
        "From": {"email": mail["from"] or None},
        "Received": {"date": {"start": mail["date"]}} if mail.get("date") else {"date": None},
        "Reply type": {"select": {"name": result["type"]}},
        "Status": {"select": {"name": "drafted"}},
        "Reply draft": {"rich_text": rt(f"{result.get('subject','')}\n\n{result.get('body','')}")},
        "Send svar": {"checkbox": False},
        "Afvis": {"checkbox": False},
        "Original": {"rich_text": rt(mail["body"])},
        "Message-ID": {"rich_text": rt(mail.get("message_id"))},
        "UID": {"number": mail["uid"]},
    }
    if lead:
        props["Lead ID"] = {"number": lead["id"]}
    r = requests.post(f"{API}/pages", headers=H, json={"parent": {"database_id": db}, "properties": props})
    if not r.ok:
        raise RuntimeError(f"Notion row create {r.status_code}: {r.text[:300]}")


def main():
    if not IDS.exists():
        raise SystemExit("data/reply_ids.json missing — run setup_replies.py first")
    db = json.loads(IDS.read_text())["inbox_db"]
    types = parse_templates()
    con = store.connect(); store.init(con)

    M = imaplib.IMAP4(IMAP_HOST, IMAP_PORT)
    M.starttls(ssl_context=ssl.create_default_context())
    M.login(USER, PASS)
    M.select("INBOX", readonly=True)
    uids = M.uid("search", None, "ALL")[1][0].split()
    maxuid = int(uids[-1]) if uids else 0

    if not WATERMARK.exists():
        WATERMARK.parent.mkdir(parents=True, exist_ok=True)
        WATERMARK.write_text(str(maxuid))
        print(f"[reply] baseline set at UID {maxuid}; no backlog drafted")
        M.logout(); return

    last = int(WATERMARK.read_text() or 0)
    todo = [u for u in uids if int(u) > last]
    print(f"[reply] {len(todo)} new message(s) since UID {last}")
    drafted = ignored = 0
    for u in todo:
        raw = M.uid("fetch", u, "(BODY.PEEK[])")[1][0][1]
        msg = email.message_from_bytes(raw)
        frm = email.utils.parseaddr(dec(msg.get("From")))[1]
        mail = {"uid": int(u), "from": frm, "subject": dec(msg.get("Subject")),
                "body": body_text(msg), "message_id": msg.get("Message-ID", ""),
                "date": None}
        try:
            dtup = email.utils.parsedate_to_datetime(msg.get("Date"))
            mail["date"] = dtup.isoformat()
        except Exception:
            pass
        if any(n in (frm or "").lower() for n in NO_REPLY):
            ignored += 1; print(f"  ignore (no-reply): {frm}"); continue
        lead_row = con.execute("SELECT * FROM leads WHERE lower(email)=?", (frm.lower(),)).fetchone()
        lead = dict(lead_row) if lead_row else None
        result = classify_and_draft(types, mail, lead)
        if result.get("type") == "ignorer":
            ignored += 1; print(f"  ignore (classified): {frm} — {mail['subject'][:50]}"); continue
        create_row(db, mail, result, lead)
        drafted += 1
        print(f"  drafted [{result['type']}] for {frm} — {mail['subject'][:50]}")
    WATERMARK.write_text(str(maxuid))
    M.logout()
    print(f"[reply] done: {drafted} drafted, {ignored} ignored")


if __name__ == "__main__":
    main()
