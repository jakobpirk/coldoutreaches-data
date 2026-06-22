"""
Overnight prep — the `claude -p` lane. For the qualified leads it:
  1. classifies the screenshot   (vision: ugly/borderline/fine/parked/blocked)
  2. researches the business      (contact person + pitch angle)
  3. drafts the outreach email    (Danish, your informal tone) — only once a demo exists

…and writes everything back into the store. Idempotent: only fills what's missing.
Runs on the VPS via run_nightly.sh, drawing your Max subscription through the
Claude Code CLI (`claude -p`, needs CLAUDE_CODE_OAUTH_TOKEN). To move off the
subscription lane later, point CLAUDE_CMD at a wrapper that calls the API.

    python3 prep.py                 # do all stages for everything that needs it
    python3 prep.py --limit 5       # throttle (protect the weekly cap)
    python3 prep.py --stage classify
"""
from __future__ import annotations
import os, re, json, subprocess, argparse, pathlib
import store

CLAUDE_CMD = os.environ.get("CLAUDE_CMD", "claude")
FEEDBACK = pathlib.Path("classification-feedback.md")
EMAIL_STYLE = pathlib.Path("email-style.md")


def claude(prompt: str, timeout: int = 300) -> str:
    """Run the Claude Code CLI headless, restricted to the Read tool so the agent
    can look at the screenshot but can NOT run project scripts or other commands.
    Prompt goes via stdin to avoid flag/arg parsing collisions."""
    r = subprocess.run([CLAUDE_CMD, "-p", "--allowedTools", "Read"],
                       input=prompt, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"claude -p failed: {r.stderr[:400]}")
    return r.stdout.strip()


def _json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0)) if m else {}


def _read(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


# ---- stage 1: vision classification ------------------------------------

def classify(lead: dict) -> dict:
    shot = lead.get("screenshot_path") or ""
    prompt = f"""Read the screenshot image file at `{shot}` and judge whether this
Danish business website is outdated/ugly enough to be worth pitching a redesign.

Business: {lead['name']} ({lead.get('category')}/{lead.get('subcategory')}).
Current URL: {lead.get('final_url') or lead.get('website')}.

Apply these rules learned from past corrections:
{_read(FEEDBACK)[:2000]}

Definitions:
- "ugly"       = clearly dated/poor; a strong redesign target.
- "borderline" = some merit but improvable.
- "fine"       = modern/current; NOT a target.
- "parked"     = parked/hijacked domain or not the business's own site.
- "blocked"    = a cookie/age modal hides the page — don't guess, flag for re-shot.

Output ONLY this JSON, nothing else:
{{"verdict":"<one of the five>","confidence":<0-1>,"reasons":"<1-2 sentences>"}}"""
    return _json(claude(prompt))


# ---- stage 2: research / enrichment ------------------------------------

def research(lead: dict) -> dict:
    prompt = f"""Research the Danish business "{lead['name']}" (its site:
{lead.get('final_url') or lead.get('website')}). Find, if available: the owner or
a named contact person, and the single most compelling, specific angle for
offering them a new website (what's concretely weak about their current online
presence). Be concrete, not generic.

Output ONLY JSON: {{"contact_person":"<name or empty>","angle":"<one sentence>"}}"""
    return _json(claude(prompt))


# ---- stage 3: outreach email draft -------------------------------------

def draft(lead: dict) -> str:
    prompt = f"""Write a short cold-outreach email in DANISH to {lead['name']}
offering a redesigned website. A live demo already exists at: {lead.get('demo_url')}.

Voice and rules — follow exactly:
{_read(EMAIL_STYLE)[:1500]}

Context you may use:
- Contact person: {lead.get('contact_person') or '(unknown — keep it general)'}
- Why we reached out: {lead.get('cls_reasons') or ''}
- Sent from: hej@wilbrandtworks.dk (Wilbrandt Works).

Include a clear subject line. Link the demo. Keep it brief and human.
Output the email as plain text: first line "Subject: …", then a blank line, then the body."""
    return claude(prompt)


# ---- orchestration -----------------------------------------------------

def run(stage: str, limit: int):
    con = store.connect()
    leads = [dict(r) for r in con.execute(
        "SELECT * FROM leads WHERE qualified=1 AND state NOT IN "
        "('sent','replied','won','lost','rejected') ORDER BY score DESC")]
    n = 0
    for lead in leads:
        if limit and n >= limit:
            break
        touched = False
        if stage in ("all", "classify") and not lead.get("cls_verdict") and lead.get("screenshot_path"):
            d = classify(lead)
            con.execute("UPDATE leads SET cls_verdict=?, cls_confidence=?, cls_reasons=? WHERE id=?",
                        (d.get("verdict"), d.get("confidence"), d.get("reasons"), lead["id"]))
            lead.update(cls_verdict=d.get("verdict"), cls_reasons=d.get("reasons"))
            touched = True
        if stage in ("all", "research") and not lead.get("contact_person") \
                and (lead.get("cls_verdict") in ("ugly", "borderline")):
            d = research(lead)
            con.execute("UPDATE leads SET contact_person=? WHERE id=?",
                        (d.get("contact_person"), lead["id"]))
            touched = True
        if stage in ("all", "draft") and lead.get("demo_url") and not lead.get("email_draft"):
            con.execute("UPDATE leads SET email_draft=? WHERE id=?", (draft(lead), lead["id"]))
            touched = True
        if touched:
            con.commit()
            n += 1
            print(f"[prep] #{lead['id']} {lead['name']}")
    print(f"[prep] processed {n} leads (stage={stage})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["all", "classify", "research", "draft"], default="all")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    run(args.stage, args.limit)
