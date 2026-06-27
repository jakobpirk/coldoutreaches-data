"""
Learn Jakob's email voice from the mails he has actually sent, so future drafts
read like him — not like a template. Reads the outgoing messages logged in the
store (which grows every time you approve/send a reply), asks Claude once to
distil the recurring style and pick a few real representative examples, and
writes them to email-examples.md.

That file is injected (as few-shot) by reply_agent.py and prep.py — ALONGSIDE the
hand-written email-style.md (which stays yours to edit in Notion). So you get:
  email-style.md      = the rules you set
  email-examples.md   = what the system learned from your real mails  ← this file

The loop tightens over time: every reply you approve becomes part of the corpus,
so the more you send, the closer the drafts get.

    python3 learn_style.py            # refresh email-examples.md
    python3 learn_style.py --min 5    # need at least N sent mails before learning

Wired into run_nightly.sh. Env: CLAUDE_CMD, LEADS_DB.
"""
from __future__ import annotations
import os, re, json, subprocess, argparse, pathlib
import store

CLAUDE_CMD = os.environ.get("CLAUDE_CMD", "claude")
OUT = pathlib.Path("email-examples.md")
MAX_CORPUS = 25          # cap how many mails we hand the model
MAX_BODY = 1200          # per-mail char cap


def corpus(con) -> list[dict]:
    rows = con.execute(
        "SELECT subject, body FROM messages WHERE direction='out' "
        "AND LENGTH(COALESCE(body,'')) > 120 ORDER BY id DESC LIMIT ?", (MAX_CORPUS,)).fetchall()
    seen, out = set(), []
    for r in rows:
        body = (r["body"] or "").strip()
        key = body[:80]
        if key in seen:
            continue
        seen.add(key)
        out.append({"subject": r["subject"] or "", "body": body[:MAX_BODY]})
    return out


def claude(prompt: str, timeout: int = 240) -> str:
    r = subprocess.run([CLAUDE_CMD, "-p"], input=prompt, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[:300])
    return r.stdout


def learn(mails: list[dict]) -> dict:
    listing = "\n\n".join(
        f"[{i}] Emne: {m['subject']}\n{m['body']}" for i, m in enumerate(mails))
    prompt = f"""Her er rigtige e-mails, Jakob fra Wilbrandt Works har sendt. Analysér HANS stil.

{listing}

Beskriv kort, konkret hvordan han skriver (tone, længde, opbygning, gentagne
vendinger, hilsen/underskrift, hvad han undgår). Vælg derefter de 2-3 numre, der
bedst repræsenterer hans stil som eksempler at efterligne.

Output KUN JSON:
{{"style_notes":"<5-8 korte punkter om hans stil, på dansk>","picks":[<indeks>, ...]}}"""
    txt = claude(prompt)
    m = re.search(r"\{.*\}", txt, re.S)
    if not m:
        raise RuntimeError("no JSON from claude")
    return json.loads(m.group(0))


def write(mails: list[dict], result: dict):
    notes = result.get("style_notes", "")
    if isinstance(notes, list):
        notes = "\n".join(f"- {str(x).strip()}" for x in notes)
    notes = str(notes).strip()
    picks = [i for i in result.get("picks", []) if isinstance(i, int) and 0 <= i < len(mails)]
    if not picks:
        picks = list(range(min(3, len(mails))))
    lines = ["# Lært fra dine afsendte mails (auto-genereret af learn_style.py — rediger ikke)",
             "", "## Destilleret stil", notes, "", "## Rigtige eksempler"]
    for n, i in enumerate(picks, 1):
        lines += [f"### Eksempel {n}", f"Emne: {mails[i]['subject']}", "", mails[i]["body"], ""]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[learn] wrote {OUT} ({len(notes)} chars notes, {len(picks)} examples)")


def main(min_mails: int):
    con = store.connect(); store.init(con)
    mails = corpus(con)
    if len(mails) < min_mails:
        print(f"[learn] only {len(mails)} sent mails (<{min_mails}) — skip, keep existing")
        return
    try:
        result = learn(mails)
    except Exception as e:
        print(f"[learn] claude failed ({e}); keeping existing email-examples.md")
        return
    write(mails, result)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--min", type=int, default=3)
    main(ap.parse_args().min)
