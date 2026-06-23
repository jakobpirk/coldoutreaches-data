"""
Phase 2 — deploy-rail scaffold generator.

Given a lead id, produce a ready-to-design site folder:
    sites/{slug}/
        index.html     placeholder (NO design — Claude designs it from scratch)
        render.yaml     Render static-site config
        seed.json       the business's data (overnight prep enriches this)
        CLAUDE.md       the design brief the Claude Code session reads

n8n will (on the VPS) turn this folder into a GitHub repo + Render preview.
Deterministic; no Claude. The DESIGN happens later, when you open the repo in
Claude Code and the frontend-design skill builds the site from this brief.

    python3 scaffold.py 9            # scaffold lead #9
    python3 scaffold.py 9 --out output/sites
"""
from __future__ import annotations
import os, re, json, argparse
import store


def slugify(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[æøå]", lambda m: {"æ":"ae","ø":"oe","å":"aa"}[m.group(0)], s)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:40] or "site"


RENDER_YAML = """services:
  - type: web
    name: {slug}-site
    runtime: static
    buildCommand: ""
    staticPublishPath: .
    routes:
      - type: rewrite
        source: /*
        destination: /index.html
"""

INDEX_PLACEHOLDER = """<!doctype html>
<html lang="da"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name}</title></head>
<body>
<!-- Placeholder only. Claude designs this site from scratch via the
     frontend-design skill, using CLAUDE.md + seed.json. -->
<main><h1>{name}</h1><p>Demo under opbygning.</p></main>
</body></html>
"""


def build_brief(lead: dict) -> str:
    name = lead["name"]
    cat = "/".join(x for x in [lead.get("category"), lead.get("subcategory")] if x)
    site = lead.get("final_url") or lead.get("website") or ""
    city = lead.get("city") or "Sydfyn"
    verdict = lead.get("cls_verdict") or "?"
    reasons = lead.get("cls_reasons") or ""
    prefs = ""
    try:
        prefs = ("\n\n## House design guidance (kept in sync from Notion)\n"
                 + open("design-preferences.md", encoding="utf-8").read())
    except FileNotFoundError:
        pass
    return f"""# Design brief — {name}

You are redesigning the website for **{name}**, a local Danish business
({cat}) in/near {city}. Build a brand-new, **bespoke** static site from
scratch. Do **not** use a template and do **not** copy the current site's
layout — design it fresh.

## Use the frontend-design skill
Run the `frontend-design` skill and design to a high, distinctive standard —
this demo is the pitch, so it must look clearly better than what they have.

## What's wrong with the current site (why we're pitching)
Verdict: **{verdict}**. {reasons}

## Use THEIR content — this is a re-skin, not a rewrite
The pitch is "your own content, finally looking good." So preserve what they have:
- **Fetch their current site ({site})** and reuse their **real text** — services,
  about, opening hours, prices, history. Tidy and re-typeset it; do NOT invent,
  replace, or pad it with generic marketing copy.
- **Reuse their real images.** Pull the actual photos from their current site and
  use them (reference the original URLs, or save them into this folder). Only fall
  back to tasteful placeholders where they genuinely have no usable image.
- **Mirror their pages.** If the original has several pages (menu, about, gallery,
  contact), recreate those same pages and keep the same information architecture.
- `seed.json` has the structured contact data we already hold.
- Keep all copy in **Danish**, in the tone of a {cat} business.

## Requirements
- Mobile-first, fast, accessible. Recreate their page structure (not just one
  landing page) when the original has multiple pages.
- Per page, keep the sections the original has: hero, about, products/services,
  opening hours, gallery, contact (phone/email/address + map link).
- Reflect the character of the business (warm/rustic for a farm shop, elegant for
  a jeweller) — never a generic SaaS look.
- **The test:** the owner should instantly recognise it as *their* site — same
  content, same photos — just dramatically better designed.

## Output
- Write the finished site into this folder (`index.html` + assets).
- When you commit, Render auto-deploys the preview; review it as a live page.
{prefs}"""


def scaffold(lead_id: int, out_root: str) -> str:
    con = store.connect()
    row = con.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    if row is None:
        raise SystemExit(f"no lead {lead_id}")
    lead = dict(row)
    slug = slugify(lead["name"])
    d = os.path.join(out_root, slug)
    os.makedirs(d, exist_ok=True)

    open(os.path.join(d, "render.yaml"), "w").write(RENDER_YAML.format(slug=slug))
    open(os.path.join(d, "index.html"), "w", encoding="utf-8").write(
        INDEX_PLACEHOLDER.format(name=lead["name"]))
    seed = {k: lead.get(k) for k in ("id", "name", "category", "subcategory",
            "final_url", "website", "phone", "email", "address", "city",
            "postcode", "cls_verdict", "cls_reasons", "screenshot_path")}
    open(os.path.join(d, "seed.json"), "w", encoding="utf-8").write(
        json.dumps(seed, ensure_ascii=False, indent=2))
    open(os.path.join(d, "CLAUDE.md"), "w", encoding="utf-8").write(build_brief(lead))

    # advance lifecycle: this lead now has a repo being built
    if lead["state"] in ("scored", "queued"):
        try:
            store.move(con, lead_id, "queued" if lead["state"] == "scored" else lead["state"])
        except SystemExit:
            pass
    print(f"scaffolded {d}: " + ", ".join(sorted(os.listdir(d))))
    return d


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("lead_id", type=int)
    ap.add_argument("--out", default="output/sites")
    a = ap.parse_args()
    scaffold(a.lead_id, a.out)
