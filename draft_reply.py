"""
Auto-draft email replies for anything that needs a response. DRAFTS ONLY — they
land on the Notion item (Inbox row / ticket) as a "Reply draft" field for you to
approve; n8n sends from Simply after your OK. Never auto-sent.

Routes it drafts for:
  prospect_reply  — a lead replied to your cold offer.
  ticket_ack      — a customer asked for a fix you're handling; acknowledge + "preview soon".
  ticket_done     — the fix is live on staging; invite them to look + OK to publish.
  ticket_needs_you— bigger/ambiguous request; acknowledge, promise to come back, no specifics.
  message         — a general email that just needs a human reply.

    python3 draft_reply.py prospect_reply email.json --name "Jensens" --demo-url https://...
    echo '{...}' | python3 draft_reply.py message -
"""
from __future__ import annotations
import os, sys, json, subprocess, argparse, pathlib

EMAIL_STYLE = pathlib.Path("email-style.md")
CLAUDE_CMD = os.environ.get("CLAUDE_CMD", "claude")

INTENT = {
    "prospect_reply": "They replied to your cold website-design offer. Warmly move toward a short call / next step. If a demo link is given, point to it.",
    "ticket_ack": "They asked for a website change you're already handling. Acknowledge, say you're on it, and that you'll send a preview link shortly. Don't over-promise timing.",
    "ticket_done": "Their requested change is now live on a staging preview. Invite them to look and ask for the OK before you publish it.",
    "ticket_needs_you": "They asked for something bigger or unclear. Acknowledge warmly, say you'll look into it and come back with options. Make NO specific promises.",
    "message": "A general email that needs a brief, helpful human reply.",
}


def _style() -> str:
    return EMAIL_STYLE.read_text(encoding="utf-8")[:1500] if EMAIL_STYLE.exists() else ""


def _claude(prompt, timeout=120):
    r = subprocess.run([CLAUDE_CMD, "-p", prompt], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[:200])
    return r.stdout.strip()


def draft(route: str, email: dict, ctx: dict) -> str:
    intent = INTENT.get(route, INTENT["message"])
    demo = ctx.get("demo_url") or ""
    prompt = f"""Write a short reply email in DANISH.

Situation: {intent}
Their email — subject: {email.get('subject')}
Body: \"\"\"{email.get('body','')[:1200]}\"\"\"
Context: recipient/business = {ctx.get('name') or 'kunden'}; staging/demo link = {demo or '(none)'}.

Voice rules — follow exactly:
{_style()}

Output the email as plain text: first line "Subject: ...", then a blank line,
then the body. Sign as Jakob, Wilbrandt Works."""
    try:
        return _claude(prompt)
    except Exception:
        return _fallback(route, email, ctx)


def _fallback(route, email, ctx) -> str:
    subj = email.get("subject", "din mail")
    name = ctx.get("name") or ""
    demo = ctx.get("demo_url") or ""
    hi = f"Hej{(' ' + name) if name else ''},"
    bodies = {
        "prospect_reply": f"{hi}\n\nFedt, du skriver tilbage. "
            + (f"Du kan se mit udkast her: {demo}\n\n" if demo else "")
            + "Skal vi tage en kort snak om det? Så ringer jeg, når det passer dig.",
        "ticket_ack": f"{hi}\n\nTak — jeg er på den. Jeg sender dig et link til en "
            "opdateret version om lidt, så du kan se det, inden det går live.",
        "ticket_done": f"{hi}\n\nSå er ændringen klar til at se her: {demo}\n\n"
            "Sig til, hvis det ser rigtigt ud, så lægger jeg det live.",
        "ticket_needs_you": f"{hi}\n\nTak for det — det kigger jeg på og vender "
            "tilbage med et par muligheder.",
        "message": f"{hi}\n\nTak for din mail. [svar her]",
    }
    body = bodies.get(route, bodies["message"])
    return f"Subject: SV: {subj}\n\n{body}\n\nVh Jakob\nWilbrandt Works"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("route", choices=list(INTENT))
    ap.add_argument("file", help="email JSON file, or - for stdin")
    ap.add_argument("--name", default="")
    ap.add_argument("--demo-url", default="")
    a = ap.parse_args()
    raw = sys.stdin.read() if a.file == "-" else open(a.file, encoding="utf-8").read()
    print(draft(a.route, json.loads(raw), {"name": a.name, "demo_url": a.demo_url}))
