"""
One-off: write the in-session vision classifications into the store and build
an HTML review sheet (screenshot + verdict + reasoning) so Jakob can eyeball
and correct. In production this output comes from the overnight `claude -p`
step; this script just demonstrates the shape and seeds the learning loop.

    LEADS_DB=/tmp/cold/leads.db python3 review_demo.py
"""
from __future__ import annotations
import os, html, sqlite3
import store

# (lead_id, verdict, confidence, reasons)
# verdict: ugly | borderline | fine | parked | blocked
VERDICTS = [
    (1,  "parked",     0.92, "Screenshot shows a generic accommodation/flights booking affiliate page ('Offers count 11205'), not the restaurant — the domain looks parked/hijacked. Not a redesign target."),
    (2,  "ugly",       0.95, "Cramped centered text, clip-art crab logo, a tiny thumbnail photo grid, no hierarchy — classic early-2000s site. Strong target."),
    (3,  "fine",       0.80, "Modern hero photo, clean nav, 'Book dit bord' CTA — a current template. Heuristic over-flagged it; not a priority."),
    (6,  "borderline", 0.60, "Functional modern nav, but a dense two-column menu on a dark wood background. Cluttered rather than dated."),
    (5,  "borderline", 0.60, "Plain, low-effort single page — generic layout, raw machine photo, weak hierarchy. Bland; an upgrade candidate."),
    (4,  "borderline", 0.65, "A listing on the shared antikvitet.net marketplace (m.antikvitet.net), not the business's own site. Dated catalog look, but not a clean redesign target."),
    (7,  "ugly",       0.70, "Dated banner-collage layout with several small shop logos, cluttered 2010s style, weak structure. Target."),
    (9,  "ugly",       0.90, "Dated green template, cramped multi-column body, old typography, clip-art grape logo. Strong target."),
    (8,  "borderline", 0.60, "Dated serif header with a clip-art sailing ship and a big embedded video; generic layout. Refresh candidate."),
    (13, "borderline", 0.55, "Clean white layout, clover logo, clear type — simple but tidy. Light upgrade at most."),
    (12, "ugly",       0.90, "Essentially unstyled: plain stacked text (address, hours) and a raw photo, no branding or layout. Strong target."),
    (11, "fine",       0.75, "Modern template — clean hero with a foot-care photo, 'Book online' CTA. Current."),
    (10, "fine",       0.70, "Clean modern card grid with food photos and a dark nav. Looks current."),
    (15, "blocked",    0.40, "Screenshot dominated by a cookie-consent modal; visible header looks somewhat dated. Needs a re-shot. (Lead 14 is the same business.)"),
    (14, "blocked",    0.40, "Duplicate of lead 15 (Blomsterværkstedet Tine P) — same cookie-modal capture. Needs a re-shot."),
    (20, "ugly",       0.80, "Sparse, dated single page: red wordmark, one storefront photo, tiny centered contact text, lots of empty space. Target."),
    (19, "fine",       0.70, "Modern warm template — hero pretzel-sign photo, clean nav, CTA. Current."),
    (18, "borderline", 0.60, "Styled (teal + gold script) but very traditional, centered, dated typography. Upgrade candidate."),
    (17, "fine",       0.70, "Modern photo-driven template — family/animals hero, clean nav. Current."),
    (21, "borderline", 0.60, "Plain green template, table-like product listing, weak hierarchy. Functional but dated-ish; polish target."),
    (23, "fine",       0.75, "Clean modern minimal — salon photo, tidy nav, opening hours on white. Current."),
    (22, "fine",       0.65, "Modern hero (cattle photo), scroll cue, two-column text. Current template."),
    (24, "ugly",       0.90, "Dated 2000s template: left sidebar pizza menu, clip-art smiley logo, cluttered, Facebook box. Strong target."),
    (28, "fine",       0.70, "Modern warm bakery template — bread hero, icon row. Current."),
    (27, "fine",       0.80, "Sleek modern dark template — serif hero, clean CTAs. Current; not a target."),
    (26, "fine",       0.65, "Clean modern minimal with a charming hand-drawn logo. Sparse but current."),
    (25, "ugly",       0.80, "Cluttered, dense dated template — red nav, cramped text blocks, poor hierarchy. Target."),
    (30, "blocked",    0.40, "Cookie modal covers most of the page; visible parts look plain/dated. Re-shot needed."),
    (29, "borderline", 0.60, "Dated photo-overlay header, italic serif over a building photo, generic Italian-restaurant template. Refresh candidate."),
    (33, "fine",       0.65, "Reasonably modern dark hero with icon row. Current-ish; low priority."),
    (32, "blocked",    0.40, "Cookie modal blocks view; behind it a dated candy webshop catalog (aromaland.dk). Re-shot needed."),
    (31, "borderline", 0.60, "Dated yellow/blue template, generic 'Welcome' hero, weak hierarchy. Refresh target."),
    (34, "borderline", 0.55, "Fairly modern dark hero (naturkvæg) but some clutter and a cookie bar. Low priority."),
    (36, "fine",       0.70, "Modern faded-hero template, clean logo and CTA. Current."),
    (35, "borderline", 0.50, "Dated red dropdown nav and a large empty hero area (image failed to load in capture). Re-shot would help."),
    (39, "fine",       0.75, "Clean, current minimal design — photo collage, soft palette, tidy. Not a target."),
    (38, "blocked",    0.30, "Age-verification modal blocks the page; visible parts look like a standard webshop. Re-shot needed."),
    (37, "fine",       0.75, "Modern atmospheric restaurant template — dark lamp hero, gold nav, booking CTA. Current."),
]

COLORS = {"ugly": "#c0392b", "borderline": "#d68910", "fine": "#1e8449",
          "parked": "#7f8c8d", "blocked": "#7d3c98"}
ORDER = {"ugly": 0, "borderline": 1, "blocked": 2, "parked": 3, "fine": 4}


def main():
    con = store.connect()
    for lid, verdict, conf, reasons in VERDICTS:
        con.execute("UPDATE leads SET cls_verdict=?, cls_confidence=?, cls_reasons=? WHERE id=?",
                    (verdict, conf, reasons, lid))
    con.commit()

    rows = con.execute(
        "SELECT id, name, score, final_url, website, screenshot_path, "
        "cls_verdict, cls_confidence, cls_reasons FROM leads "
        "WHERE cls_verdict IS NOT NULL").fetchall()
    rows = sorted(rows, key=lambda r: (ORDER.get(r["cls_verdict"], 9), -(r["score"] or 0)))

    counts = {}
    for r in rows:
        counts[r["cls_verdict"]] = counts.get(r["cls_verdict"], 0) + 1
    summary = " · ".join(f"<b style='color:{COLORS[k]}'>{k}: {counts[k]}</b>"
                         for k in sorted(counts, key=lambda k: ORDER[k]))

    cards = []
    for r in rows:
        shot = (r["screenshot_path"] or "").split("/")[-1]
        url = r["final_url"] or r["website"] or ""
        c = COLORS.get(r["cls_verdict"], "#555")
        cards.append(f"""
        <div class="card">
          <img src="screenshots/{html.escape(shot)}" loading="lazy">
          <div class="meta">
            <div class="row">
              <span class="badge" style="background:{c}">{r['cls_verdict']}</span>
              <span class="conf">conf {r['cls_confidence']:.2f}</span>
              <span class="score">heur {r['score']}</span>
              <span class="id">#{r['id']}</span>
            </div>
            <div class="name">{html.escape(r['name'] or '')}</div>
            <a href="{html.escape(url)}" target="_blank">{html.escape(url)}</a>
            <p>{html.escape(r['cls_reasons'] or '')}</p>
          </div>
        </div>""")

    doc = f"""<!doctype html><meta charset=utf-8>
<title>Lead classification review</title>
<style>
 body{{font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#f4f5f7;color:#1a1a1a}}
 header{{padding:20px 28px;background:#fff;border-bottom:1px solid #e3e3e3;position:sticky;top:0}}
 h1{{margin:0 0 6px;font-size:20px}} .sum{{font-size:14px;color:#333}}
 .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:16px;padding:20px 28px}}
 .card{{background:#fff;border:1px solid #e3e3e3;border-radius:10px;overflow:hidden;display:flex;flex-direction:column}}
 .card img{{width:100%;height:230px;object-fit:cover;object-position:top;background:#eee;border-bottom:1px solid #eee}}
 .meta{{padding:12px 14px}} .row{{display:flex;gap:8px;align-items:center;margin-bottom:6px;flex-wrap:wrap}}
 .badge{{color:#fff;padding:2px 9px;border-radius:20px;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.04em}}
 .conf,.score,.id{{font-size:12px;color:#777}}
 .name{{font-weight:700;font-size:16px;margin:2px 0}} a{{font-size:12px;color:#2563c9;word-break:break-all}}
 .meta p{{margin:8px 0 0;font-size:13.5px;color:#333}}
</style>
<header>
  <h1>Lead classification review — {len(rows)} qualified leads</h1>
  <div class="sum">{summary}</div>
  <div class="sum" style="margin-top:4px;color:#777">Sorted: ugly → borderline → blocked → parked → fine. "heur" = old heuristic score. Correct me by lead # and I'll log it to classification-feedback.md.</div>
</header>
<div class="grid">{''.join(cards)}</div>
"""
    out = os.path.join("output", "review.html")
    open(out, "w", encoding="utf-8").write(doc)
    print(f"wrote {out} with {len(rows)} cards; verdicts: {counts}")


if __name__ == "__main__":
    main()
