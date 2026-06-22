"""
Generate a self-contained HTML dashboard from results.json + screenshots.

Output: output/dashboard.html  — open in a browser to browse leads.

Each lead is a card with:
- Score badge + bucket label
- Screenshot thumbnail (default view)
- "Vis live" toggle → swaps to iframe; falls back to "Åbn i ny fane" if blocked
- All signals, contact info, address

Filters: bucket, min score, category, free-text search.
Sort: score desc (default), name, category.
"""
from __future__ import annotations
import json
import re
import argparse
from pathlib import Path


HIJACK_SIGS = {"name_mismatch", "name_mismatch_promo",
               "parked_domain", "thin_or_stub"}
BIG_BRAND_DOMAINS = {
    "mcdonalds.dk", "louisnielsen.dk", "harald-nyborg.dk", "thansen.dk",
    "apoteket-online.dk", "danbolig.dk", "ufm.dk", "cancer.dk",
}


def slugify(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[æøå]", lambda m: {"æ":"ae","ø":"oe","å":"aa"}[m.group(0)], s)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:40] or "unknown"


def bucket_of(r):
    host = (r["website"] or "").lower()
    if any(d in host for d in BIG_BRAND_DOMAINS):
        return "brand"
    if r["status"] != 200:
        return "dead"
    sig_names = {s["name"] for s in r["signals"]}
    if sig_names & HIJACK_SIGS:
        return "hijacked"
    return "live"


def main(results_path: str, screenshots_dir: str,
         redesigns_dir: str, out_path: str):
    results = json.loads(Path(results_path).read_text())
    shots = {p.stem for p in Path(screenshots_dir).glob("*.png")}
    # A redesign is considered "ready" if its index.html exists
    redesigns = {p.parent.name for p in Path(redesigns_dir).glob("*/index.html")}

    leads = []
    for r in results:
        leads.append({
            "name": r["name"],
            "slug": slugify(r["name"]),
            "category": r["category"],
            "subcategory": r["subcategory"],
            "website": r["website"],
            "final_url": r["final_url"] or r["website"],
            "status": r["status"],
            "score": r["score"],
            "raw_score": r["raw_score"],
            "title": r["title"],
            "error": r["error"],
            "phone": r["phone"],
            "email": r["email"],
            "address": r["address"],
            "city": r["city"],
            "postcode": r["postcode"],
            "signals": [{"name": s["name"], "points": s["points"],
                         "evidence": s["evidence"]}
                        for s in r["signals"]],
            "bucket": bucket_of(r),
            "first_seen": r.get("first_seen", ""),
            "last_seen": r.get("last_seen", ""),
            "new_this_run": bool(r.get("new_this_run")),
        })

    # Stats
    by_bucket = {}
    for r in leads:
        by_bucket.setdefault(r["bucket"], 0)
        by_bucket[r["bucket"]] += 1

    data_json = json.dumps(leads, ensure_ascii=False)
    shots_json = json.dumps(sorted(shots))
    redesigns_json = json.dumps(sorted(redesigns))
    stats_json = json.dumps(by_bucket)

    html = HTML_TEMPLATE.replace("__DATA__", data_json) \
                        .replace("__SHOTS__", shots_json) \
                        .replace("__REDESIGNS__", redesigns_json) \
                        .replace("__STATS__", stats_json) \
                        .replace("__GENERATED__",
                                 __import__("datetime").datetime.now()
                                 .strftime("%Y-%m-%d %H:%M"))
    Path(out_path).write_text(html, encoding="utf-8")
    print(f"wrote {out_path}  ({len(leads)} leads, {len(shots)} screenshots)")


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="da">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lead Dashboard — Cold Outreaches</title>
<style>
  :root {
    --bg: #fafaf7;
    --panel: #ffffff;
    --border: #e8e3d8;
    --ink: #1d1c19;
    --muted: #6b6660;
    --accent: #d97706;
    --good: #15803d;
    --warn: #b91c1c;
    --bucket-live: #d97706;
    --bucket-dead: #b91c1c;
    --bucket-hijacked: #7c3aed;
    --bucket-brand: #6b6660;
  }
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, "Inter", "SF Pro Text", system-ui, sans-serif;
    margin: 0; padding: 0;
    background: var(--bg);
    color: var(--ink);
    font-size: 14px;
    line-height: 1.45;
  }
  header {
    position: sticky; top: 0; z-index: 10;
    background: var(--panel);
    border-bottom: 1px solid var(--border);
    padding: 14px 22px;
    box-shadow: 0 1px 0 rgba(0,0,0,0.02);
  }
  header h1 {
    font-size: 16px; font-weight: 700;
    margin: 0 0 10px 0;
    letter-spacing: -0.01em;
  }
  header .stats {
    display: flex; gap: 14px; flex-wrap: wrap;
    font-size: 12px; color: var(--muted);
    margin-bottom: 12px;
  }
  header .stats b { color: var(--ink); font-weight: 600; }
  .filters {
    display: flex; gap: 10px; flex-wrap: wrap; align-items: center;
  }
  .filters label {
    font-size: 12px; color: var(--muted);
    display: flex; align-items: center; gap: 6px;
  }
  .filters input[type="search"], .filters select {
    border: 1px solid var(--border); background: #fff;
    padding: 6px 10px; font-size: 13px;
    border-radius: 6px; color: var(--ink);
    font-family: inherit;
  }
  .filters input[type="range"] { width: 110px; }
  #scoreMinVal { min-width: 24px; display: inline-block; text-align: right;
                  font-variant-numeric: tabular-nums; }
  .hdr-btn {
    border: 1px solid var(--border); background: #fff;
    padding: 6px 10px; font-size: 12px;
    border-radius: 6px; cursor: pointer;
    font-family: inherit; color: var(--ink);
    transition: background 0.12s ease;
  }
  .hdr-btn:hover { background: var(--bg); }
  .hdr-btn.danger { color: var(--warn); border-color: #fecaca; }
  .hdr-btn.danger:hover { background: #fef2f2; }
  .hdr-btn.primary {
    background: var(--ink); color: #fff; border-color: var(--ink);
    font-weight: 500;
  }
  .hdr-btn.primary:hover { background: #000; }
  .new-badge {
    position: absolute; top: 8px; right: 8px;
    background: var(--good); color: #fff;
    font-size: 10px; font-weight: 700;
    padding: 3px 9px; border-radius: 100px;
    text-transform: uppercase; letter-spacing: 0.05em;
    box-shadow: 0 2px 10px rgba(21,128,61,0.35);
    z-index: 2;
  }
  .storage-hint {
    font-size: 11px; color: var(--muted);
    margin-top: 6px;
  }
  .storage-hint b { color: var(--good); font-weight: 500; }
  main {
    padding: 18px 22px 60px;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
    gap: 18px;
  }
  .card {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 10px;
    overflow: hidden;
    display: flex; flex-direction: column;
    transition: box-shadow 0.15s ease;
  }
  .card:hover { box-shadow: 0 4px 16px rgba(0,0,0,0.05); }
  .card-head {
    padding: 12px 14px 10px;
    border-bottom: 1px solid var(--border);
    display: flex; gap: 10px; align-items: flex-start;
  }
  .score {
    flex: 0 0 auto;
    width: 44px; height: 44px;
    border-radius: 8px;
    background: var(--ink); color: #fff;
    font-size: 18px; font-weight: 700;
    display: flex; align-items: center; justify-content: center;
    font-variant-numeric: tabular-nums;
  }
  .score.s0 { background: #c5c0b8; color: #fff; }
  .score.s5  { background: #f59e0b; }
  .score.s10 { background: #ea580c; }
  .score.s15 { background: #c2410c; }
  .score.s20 { background: #9a3412; }
  .card-head .meta { flex: 1 1 auto; min-width: 0; }
  .card-head .name {
    font-weight: 600; font-size: 14px;
    margin: 0 0 2px 0;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .card-head .sub {
    font-size: 11px; color: var(--muted);
    text-transform: uppercase; letter-spacing: 0.04em;
  }
  .bucket {
    display: inline-block;
    font-size: 10px; font-weight: 600;
    padding: 2px 7px; border-radius: 100px;
    text-transform: uppercase; letter-spacing: 0.04em;
    margin-left: 6px;
  }
  .bucket.live      { background: #fef3c7; color: #92400e; }
  .bucket.dead      { background: #fee2e2; color: #991b1b; }
  .bucket.hijacked  { background: #ede9fe; color: #5b21b6; }
  .bucket.brand     { background: #f3f4f6; color: #4b5563; }
  .preview {
    position: relative;
    background: #efece4;
    aspect-ratio: 4 / 3;
    overflow: hidden;
    display: flex; align-items: center; justify-content: center;
  }
  .preview img {
    width: 100%; height: 100%; object-fit: cover; object-position: top;
    display: block;
  }
  .preview .noshot {
    color: var(--muted); font-size: 12px;
    text-align: center; padding: 20px;
  }
  .preview iframe {
    width: 100%; height: 100%; border: 0; display: block;
  }
  .preview-toggle {
    position: absolute; bottom: 8px; right: 8px;
    background: rgba(29,28,25,0.85);
    color: #fff; font-size: 11px;
    padding: 5px 10px; border-radius: 100px;
    border: 0; cursor: pointer;
    backdrop-filter: blur(4px);
  }
  .preview-toggle:hover { background: rgba(29,28,25,1); }
  .card-body { padding: 12px 14px; flex: 1 1 auto; display: flex; flex-direction: column; gap: 8px; }
  .signals {
    display: flex; gap: 4px; flex-wrap: wrap;
  }
  .sig {
    font-size: 10px;
    padding: 2px 6px; border-radius: 4px;
    background: #fff7ed; color: #9a3412;
    border: 1px solid #fed7aa;
    font-variant-numeric: tabular-nums;
  }
  .sig.neg { background: #f0fdf4; color: #166534; border-color: #bbf7d0; }
  .contact {
    font-size: 12px; color: var(--muted);
    line-height: 1.7;
    border-top: 1px dashed var(--border); padding-top: 8px;
  }
  .contact a { color: var(--ink); text-decoration: none; }
  .contact a:hover { text-decoration: underline; }
  .contact .row { display: flex; align-items: center; gap: 4px; }
  .contact .label { color: var(--muted); width: 26px; flex: 0 0 auto; }
  .title-text { font-size: 11px; color: var(--muted); font-style: italic;
                overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .empty {
    grid-column: 1 / -1;
    padding: 40px; text-align: center; color: var(--muted);
    font-size: 14px;
  }
  .card.contacted { opacity: 0.55; background: #f8f6f0; }
  .card.contacted .preview img { filter: grayscale(0.7); }
  .card.in-progress { border-color: #7c3aed; }
  .card.in-progress .card-head { background: linear-gradient(to right, #faf5ff 0%, transparent 60%); }
  .in-progress-badge {
    position: absolute; bottom: 8px; left: 8px;
    background: #7c3aed; color: #fff;
    font-size: 10px; font-weight: 700;
    padding: 3px 9px; border-radius: 100px;
    text-transform: uppercase; letter-spacing: 0.05em;
    box-shadow: 0 2px 10px rgba(124,58,237,0.35);
    z-index: 2;
  }
  .redesign-btn.started {
    background: #ede9fe; color: #5b21b6; border-color: #c4b5fd;
  }
  .redesign-btn.started:hover { background: #ddd6fe; }
  .unmark-link {
    font-size: 11px; color: var(--muted);
    background: none; border: 0; cursor: pointer;
    text-decoration: underline; padding: 0;
    font-family: inherit;
  }
  .unmark-link:hover { color: var(--warn); }
  .card.irrelevant {
    opacity: 0.4; background: #fafafa;
    border-color: #d1d5db;
  }
  .card.irrelevant .card-head .name {
    text-decoration: line-through; color: var(--muted);
  }
  .card.irrelevant .preview img { filter: grayscale(1); }
  .irrelevant-badge {
    position: absolute; top: 8px; left: 8px;
    background: #4b5563; color: #fff;
    font-size: 10px; font-weight: 700;
    padding: 3px 9px; border-radius: 100px;
    text-transform: uppercase; letter-spacing: 0.05em;
    box-shadow: 0 2px 8px rgba(0,0,0,0.15);
    z-index: 2;
  }
  .irrelevant-btn {
    border: 1px solid #d1d5db; background: #fff;
    color: var(--muted); padding: 6px 12px;
    font-size: 12px; border-radius: 6px; cursor: pointer;
    font-family: inherit;
    align-self: flex-start;
    display: inline-flex; align-items: center; gap: 5px;
    transition: all 0.15s ease;
  }
  .irrelevant-btn:hover { background: #f9fafb; }
  .irrelevant-btn.active {
    background: #4b5563; color: #fff; border-color: #4b5563;
  }
  .irrelevant-btn.active:hover { background: #374151; }
  .contact-btn {
    border: 1px solid var(--border);
    background: #fff; color: var(--ink);
    padding: 6px 12px; font-size: 12px;
    border-radius: 6px; cursor: pointer;
    font-family: inherit;
    align-self: flex-start;
    margin-top: 2px;
    display: inline-flex; align-items: center; gap: 5px;
    transition: all 0.15s ease;
  }
  .action-row {
    display: flex; gap: 6px; flex-wrap: wrap;
    margin-top: 2px;
  }
  .redesign-btn {
    border: 1px solid #c2410c; background: #fff7ed;
    color: #9a3412; padding: 6px 12px; font-size: 12px;
    border-radius: 6px; cursor: pointer; font-family: inherit;
    text-decoration: none;
    display: inline-flex; align-items: center; gap: 5px;
    transition: all 0.15s ease;
  }
  .redesign-btn:hover { background: #ffedd5; }
  .redesign-btn.ready {
    background: #1d1c19; color: #fff; border-color: #1d1c19;
  }
  .redesign-btn.ready:hover { background: #000; }
  .contact-btn:hover { background: var(--bg); }
  .card.contacted .contact-btn {
    background: var(--good); color: #fff; border-color: var(--good);
  }
  .card.contacted .contact-btn:hover { background: #166534; }
  .contacted-badge {
    position: absolute; top: 8px; left: 8px;
    background: var(--good); color: #fff;
    font-size: 10px; font-weight: 600;
    padding: 3px 9px; border-radius: 100px;
    text-transform: uppercase; letter-spacing: 0.04em;
    box-shadow: 0 2px 8px rgba(21,128,61,0.3);
  }
  .contact-note {
    font-size: 11px; color: var(--muted);
    font-style: italic;
    margin-top: 2px;
  }
  .contact-note .date { color: var(--good); font-weight: 500; font-style: normal; }
</style>
</head>
<body>
<header>
  <h1>Lead Dashboard &nbsp;·&nbsp; Outdatede hjemmesider</h1>
  <div class="stats" id="stats"></div>
  <div class="storage-hint" id="storageHint"></div>
  <div class="filters">
    <label>Bucket:
      <select id="bucket">
        <option value="all">Alle</option>
        <option value="live" selected>Live grimme</option>
        <option value="dead">Døde sites</option>
        <option value="hijacked">Solgt/parkeret</option>
        <option value="brand">Kæder (skipped)</option>
      </select>
    </label>
    <label>Status:
      <select id="contacted">
        <option value="open" selected>Ikke kontaktet</option>
        <option value="done">Kontaktet</option>
        <option value="all">Alle</option>
      </select>
    </label>
    <label>Tilvækst:
      <select id="freshness">
        <option value="all" selected>Alle</option>
        <option value="new">Kun nye (sidste scan)</option>
      </select>
    </label>
    <label>Redesign:
      <select id="redesign">
        <option value="all" selected>Alle</option>
        <option value="none">Intet startet</option>
        <option value="started">Igangsat</option>
        <option value="done">Færdig</option>
      </select>
    </label>
    <label>Relevans:
      <select id="relevance">
        <option value="hide" selected>Skjul ikke-relevante</option>
        <option value="only">Kun ikke-relevante</option>
        <option value="all">Alle</option>
      </select>
    </label>
    <span style="display:flex;gap:6px;align-items:center;">
      <button id="exportBtn" type="button" class="hdr-btn">
        CSV ↓
      </button>
      <button id="backupBtn" type="button" class="hdr-btn" title="Download backup-fil med alle markerede leads (kan importeres senere)">
        Backup JSON ↓
      </button>
      <button id="restoreBtn" type="button" class="hdr-btn" title="Indlæs en tidligere backup-fil">
        Importér ↑
      </button>
      <input type="file" id="restoreFile" accept=".json,application/json" style="display:none;">
      <button id="resetBtn" type="button" class="hdr-btn danger" title="Slet alle markeringer">
        Nulstil
      </button>
      <span style="border-left:1px solid var(--border);height:24px;margin:0 4px;"></span>
      <button id="rescanBtn" type="button" class="hdr-btn primary"
        title="Kopiér en Cowork-prompt der starter et nyt scrape. Kun NYE sider rapporteres (eksisterende osm_id'er filtreres fra).">
        🔄 Nyt scrape
      </button>
    </span>
    <label>Branche:
      <select id="category">
        <option value="all">Alle</option>
      </select>
    </label>
    <label>Min score:
      <input type="range" id="scoreMin" min="0" max="50" step="1" value="5">
      <span id="scoreMinVal">5</span>
    </label>
    <label>Sort:
      <select id="sort">
        <option value="score">Score (høj→lav)</option>
        <option value="name">Navn (A→Å)</option>
        <option value="category">Branche</option>
      </select>
    </label>
    <label>Søg:
      <input type="search" id="search" placeholder="navn, by, branche…" style="width: 180px;">
    </label>
    <span style="margin-left: auto; font-size: 12px; color: var(--muted);"
          id="resultCount"></span>
  </div>
</header>

<main id="grid"></main>

<script>
const DATA = __DATA__;
const SHOTS = new Set(__SHOTS__);
const REDESIGNS = new Set(__REDESIGNS__);
const STATS = __STATS__;
const GENERATED = "__GENERATED__";

function buildRedesignPrompt(lead) {
  // A complete Cowork-ready prompt. Pasted into a fresh session, the
  // assistant will scrape, design, and write files to output/redesigns/<slug>/.
  const slug = lead.slug;
  const url = lead.final_url || lead.website;
  const sigs = lead.signals
    .filter(s => s.points > 0)
    .map(s => `${s.name} (+${s.points})`).join(", ") || "ingen";
  const addr = [lead.address, lead.postcode, lead.city].filter(Boolean).join(" ");
  const screenshotRef = SHOTS.has(slug)
    ? `output/screenshots/${slug}.png` : "(intet screenshot endnu)";
  return (
`Jeg vil have et komplet redesign af denne lokale virksomheds hjemmeside som mockup. Brug frontend-design skillen.

VIRKSOMHED
- Navn: ${lead.name}
- Branche: ${lead.subcategory || lead.category}
- Hjemmeside (kilde): ${url}
- Telefon: ${lead.phone || "(ikke kendt)"}
- Email: ${lead.email || "(ikke kendt)"}
- Adresse: ${addr || "(ikke kendt)"}
- Eksisterende screenshot (relativ sti i ColdOutreaches): ${screenshotRef}
- Nuværende side-titel: ${lead.title || "(tom)"}
- Vores outdated-score: ${lead.score} | signaler: ${sigs}

OPGAVE
1. Hent indholdet fra ${url} (fetch + parse HTML). Tag ALT meningsfuldt indhold med:
   - Forretningens navn, tagline, beskrivelse
   - Produkter / services / ydelser (komplet liste)
   - Priser hvor de findes
   - Åbningstider
   - Kontaktinfo, adresse, kort
   - Tekster, om-os, historie
   - Footer-info

BILLEDER - VIGTIGT
2. Scrape ALLE billeder fra deres hjemmeside (loop gennem <img>-tags, find baggrunds-billeder i CSS, hero-banners):
   - Hent absolutte URL'er for hvert billede
   - Note ALT-tekst / filnavn for kontekst (er det produkt-foto, hold-foto, lokale-billede, logo?)
   - Vurdér kvalitet pr. billede: er det skarpt nok til en moderne hero? Er det generisk eller forretningsspecifikt?
3. I redesignet skal du PRIMÆRT bruge deres egne billeder — referér dem direkte med absolutte URL'er (deres server hoster dem). Det er essentielt for at de genkender deres egen virksomhed.
4. Hvis et område mangler et godt billede (typisk hero, eller hvis siden næsten ingen billeder har):
   a. Først: prøv at finde et passende billede på deres egen Facebook/Instagram-side hvis linket findes
   b. Hvis stadig intet: brug et professionelt stock-billede fra Unsplash. Søg på branchen + lokalitet ("danish bakery interior", "sailmaker workshop", "winery vineyard denmark", etc.). Brug direkte Unsplash URL'er fra unsplash.com (find passende, kopier image URL — IKKE source.unsplash.com som er deprecated).
   c. Sidste udvej: pænt CSS-gradient eller solid-color hero med stor typografi-fokus (ingen brækkede billede-tags)
5. Hvis siden har undersider linket fra menuen, scrape dem også og inkludér deres indhold som separate sider i redesignet.
3. Brug frontend-design skillen til at lave et komplet, moderne redesign:
   - Hero med stærk tagline og call-to-action
   - Klar visuel hierarki, moderne typografi
   - Responsivt layout
   - Brug en stil der passer til branchen (varm for bager, klinisk for tandlæge, etc.)
   - Single-file HTML pr. side med inline CSS
   - Linkene mellem siderne skal virke relativt
6. Gem outputtet i: C:\\\\Users\\\\jakob\\\\WilbrandtWorks\\\\ColdOutreaches\\\\output\\\\redesigns\\\\${slug}\\\\
   - index.html som forside
   - underside1.html, underside2.html, ... hvis multi-page
   - Ingen separate CSS/JS-filer — alt inline
   - Ingen lokale image-filer — alle billeder skal være eksterne URL'er (deres egne eller stock)
7. Når du er færdig, vis mig filerne via present_files så jeg kan åbne dem.
8. Skriv kort hvilke af deres egne billeder du har genbrugt vs. hvilke stock-billeder du tilføjede, så jeg ved hvad de vil se er "deres".

VIGTIGT
- Brug INDHOLDET fra deres rigtige side — ikke generisk lorem ipsum. Det skal være troværdigt for dem at se "deres" tekst pænt sat op.
- Brug deres egne BILLEDER hvor det giver mening — det er det stærkeste argument når du viser dem mockuppen ("se, her er DIT lokale, DIN gårdbutik, DIN logo").
- Hvis du må bruge stock-billeder, vælg dem så de matcher branche + dansk/skandinavisk æstetik (ikke amerikansk corporate). Beskriv kort hvad du har erstattet, så de kan komme med deres egne billeder bagefter.
- Hvis siden er meget tom eller blokeret, så lav et best-effort baseret på branchen og det vi ved.
- Behold deres brand-navn og logo-tekst, men giv det moderne behandling.
`);
}

function copyToClipboard(text) {
  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(text);
  }
  // Fallback for file:// where clipboard API may be restricted
  return new Promise((resolve, reject) => {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try {
      const ok = document.execCommand("copy");
      document.body.removeChild(ta);
      ok ? resolve() : reject(new Error("copy failed"));
    } catch (e) {
      document.body.removeChild(ta);
      reject(e);
    }
  });
}

function showToast(msg, ms = 4500) {
  let toast = document.getElementById("toast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "toast";
    toast.style.cssText =
      "position:fixed;bottom:24px;left:50%;transform:translateX(-50%);" +
      "background:#1d1c19;color:#fff;padding:12px 18px;border-radius:8px;" +
      "font-size:13px;box-shadow:0 8px 30px rgba(0,0,0,0.25);z-index:1000;" +
      "max-width:480px;line-height:1.45;";
    document.body.appendChild(toast);
  }
  toast.innerHTML = msg;
  toast.style.display = "block";
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { toast.style.display = "none"; }, ms);
}

const BUCKET_LABEL = {
  live: "Live grimme", dead: "Død side", hijacked: "Solgt", brand: "Kæde"
};

// Persistent "kontaktet" state. localStorage survives page reloads.
const ContactStore = {
  KEY: "coldOutreach.contacted.v1",
  load() {
    try { return JSON.parse(localStorage.getItem(this.KEY) || "{}"); }
    catch (_) { return {}; }
  },
  save(obj) { localStorage.setItem(this.KEY, JSON.stringify(obj)); },
  get(key) { return this.load()[key]; },
  set(key, lead) {
    const all = this.load();
    all[key] = {
      date: new Date().toISOString().slice(0, 10),
      name: lead.name,
      website: lead.website,
    };
    this.save(all);
  },
  unset(key) {
    const all = this.load();
    delete all[key];
    this.save(all);
  },
  all() { return this.load(); },
};

function updateContactedCount() {
  const n = Object.keys(ContactStore.all()).length;
  const span = document.getElementById("contactedCount");
  if (span) span.textContent = n;
}

// Tracks which leads have had their redesign-prompt copied (i.e. work started)
// — separate from contact status. "Done" is detected from the filesystem
// (REDESIGNS set), so we only persist the "started but not yet done" state.
const RedesignStore = {
  KEY: "coldOutreach.redesignStarted.v1",
  load() {
    try { return JSON.parse(localStorage.getItem(this.KEY) || "{}"); }
    catch (_) { return {}; }
  },
  save(obj) { localStorage.setItem(this.KEY, JSON.stringify(obj)); },
  get(key) { return this.load()[key]; },
  set(key, lead) {
    const all = this.load();
    all[key] = {
      date: new Date().toISOString().slice(0, 10),
      name: lead.name,
    };
    this.save(all);
  },
  unset(key) {
    const all = this.load();
    delete all[key];
    this.save(all);
  },
  all() { return this.load(); },
};

function updateRedesignCount() {
  const n = Object.keys(RedesignStore.all()).length;
  const span = document.getElementById("redesignCount");
  if (span) span.textContent = n;
}

function redesignStatus(lead) {
  if (REDESIGNS.has(lead.slug)) return "done";
  if (RedesignStore.get(lead.osm_id || lead.slug)) return "started";
  return "none";
}

// Tracks leads the user has marked as "not relevant" — they get hidden by default
const IrrelevantStore = {
  KEY: "coldOutreach.irrelevant.v1",
  load() {
    try { return JSON.parse(localStorage.getItem(this.KEY) || "{}"); }
    catch (_) { return {}; }
  },
  save(obj) { localStorage.setItem(this.KEY, JSON.stringify(obj)); },
  get(key) { return this.load()[key]; },
  set(key, lead) {
    const all = this.load();
    all[key] = {
      date: new Date().toISOString().slice(0, 10),
      name: lead.name,
    };
    this.save(all);
  },
  unset(key) {
    const all = this.load();
    delete all[key];
    this.save(all);
  },
  all() { return this.load(); },
};

function updateIrrelevantCount() {
  const n = Object.keys(IrrelevantStore.all()).length;
  const span = document.getElementById("irrelevantCount");
  if (span) span.textContent = n;
}

function el(t, attrs = {}, children = []) {
  const e = document.createElement(t);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k === "html") e.innerHTML = v;
    else e.setAttribute(k, v);
  }
  for (const c of children) {
    if (c == null) continue;
    e.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return e;
}

function scoreClass(s) {
  if (s >= 20) return "score s20";
  if (s >= 15) return "score s15";
  if (s >= 10) return "score s10";
  if (s >= 5)  return "score s5";
  return "score s0";
}

function renderStats() {
  const total = DATA.length;
  const live = STATS.live || 0, dead = STATS.dead || 0,
        hij = STATS.hijacked || 0, brand = STATS.brand || 0;
  const ncontact = Object.keys(ContactStore.all()).length;
  const nnew = DATA.filter(d => d.new_this_run).length;
  const nstarted = Object.keys(RedesignStore.all()).length;
  const ndone = REDESIGNS.size;
  const nirr = Object.keys(IrrelevantStore.all()).length;
  document.getElementById("stats").innerHTML =
    `<span><b>${total}</b> samlet</span>
     <span><b>${live}</b> live grimme</span>
     <span><b>${dead}</b> døde</span>
     <span><b>${hij}</b> solgt/parkeret</span>
     <span><b>${brand}</b> kæder</span>
     <span style="color: var(--good); font-weight: 500;">
       ✓ <b id="contactedCount">${ncontact}</b> kontaktet</span>
     <span style="color: #7c3aed; font-weight: 500;">
       🛠 <b id="redesignCount">${nstarted}</b> igangsat</span>
     <span style="color: #1d1c19; font-weight: 500;">
       🎨 <b>${ndone}</b> færdig</span>
     <span style="color: #4b5563; font-weight: 500;">
       🚫 <b id="irrelevantCount">${nirr}</b> ikke relevant</span>` +
    (nnew > 0
      ? `<span style="color:var(--good);font-weight:500;">
           ✨ <b>${nnew}</b> ny i sidste scan</span>`
      : "") +
    `<span style="margin-left:auto;">Genereret ${GENERATED}</span>`;
}

function populateCategoryFilter() {
  const cats = new Set(DATA.map(d => d.subcategory).filter(Boolean));
  const sel = document.getElementById("category");
  [...cats].sort().forEach(c => {
    sel.appendChild(el("option", { value: c }, [c]));
  });
}

function makeCard(lead) {
  const slug = lead.slug;
  const status = redesignStatus(lead);
  const irrKey = lead.osm_id || lead.slug;
  const isIrrelevant = !!IrrelevantStore.get(irrKey);
  const hasShot = SHOTS.has(slug);
  const previewImg = hasShot
    ? el("img", { src: `screenshots/${slug}.png`, alt: lead.name, loading: "lazy" })
    : el("div", { class: "noshot" },
        ["Ingen screenshot — ", lead.bucket === "dead"
          ? "site er nede" : "ikke i top-N"]);

  const previewBox = el("div", { class: "preview" }, [previewImg]);
  if (lead.new_this_run) {
    previewBox.appendChild(el("div", { class: "new-badge" }, ["✨ NY"]));
  }
  if (status === "started") {
    previewBox.appendChild(el("div", { class: "in-progress-badge" },
      ["🛠 Redesign igangsat"]));
  }
  if (isIrrelevant) {
    previewBox.appendChild(el("div", { class: "irrelevant-badge" },
      ["🚫 Ikke relevant"]));
  }
  // Toggle to iframe
  const toggleBtn = el("button", { class: "preview-toggle" }, ["Vis live →"]);
  toggleBtn.addEventListener("click", () => {
    if (previewBox.querySelector("iframe")) {
      // back to screenshot
      previewBox.innerHTML = "";
      previewBox.appendChild(hasShot
        ? el("img", { src: `screenshots/${slug}.png`, alt: lead.name })
        : el("div", { class: "noshot" }, ["Ingen screenshot"]));
      previewBox.appendChild(toggleBtn);
      toggleBtn.textContent = "Vis live →";
    } else {
      const target = (lead.final_url || lead.website || "").trim();
      // Guard: only allow real http(s) URLs as iframe src. Otherwise the
      // browser defaults to the current page URL and we get a recursive
      // iframe (security error on file:// origins).
      if (!/^https?:\/\//i.test(target)) {
        showToast("⚠ Ingen gyldig URL for denne side - kan ikke vises live.", 3500);
        return;
      }
      previewBox.innerHTML = "";
      const iframe = el("iframe", {
        src: target, loading: "lazy",
        referrerpolicy: "no-referrer",
        sandbox: "allow-scripts allow-same-origin allow-popups"
      });
      previewBox.appendChild(iframe);
      previewBox.appendChild(toggleBtn);
      toggleBtn.textContent = "← Skjul";
    }
  });
  previewBox.appendChild(toggleBtn);

  // Score + meta
  const scoreEl = el("div", { class: scoreClass(lead.score) }, [String(lead.score)]);
  const bucketBadge = el("span",
    { class: `bucket ${lead.bucket}` },
    [BUCKET_LABEL[lead.bucket] || lead.bucket]);
  const nameEl = el("h2", { class: "name", title: lead.name }, [lead.name]);
  const subEl = el("div", { class: "sub" },
    [lead.subcategory || lead.category, bucketBadge]);
  const head = el("div", { class: "card-head" }, [
    scoreEl,
    el("div", { class: "meta" }, [nameEl, subEl])
  ]);

  // Body
  const posSigs = lead.signals.filter(s => s.points > 0);
  const negSigs = lead.signals.filter(s => s.points < 0);
  const sigList = el("div", { class: "signals" }, [
    ...posSigs.map(s => el("span", { class: "sig", title: s.evidence },
      [`${s.name} (+${s.points})`])),
    ...negSigs.map(s => el("span", { class: "sig neg", title: s.evidence },
      [`${s.name} (${s.points})`]))
  ]);

  const titleEl = lead.title ? el("div", { class: "title-text", title: lead.title },
    [`Titel: ${lead.title}`]) : null;

  // Contact
  const phoneEl = lead.phone ? el("div", { class: "row" }, [
    el("span", { class: "label" }, ["☏"]),
    el("a", { href: `tel:${lead.phone.replace(/\s/g,'')}` }, [lead.phone])
  ]) : null;
  const emailEl = lead.email ? el("div", { class: "row" }, [
    el("span", { class: "label" }, ["✉"]),
    el("a", { href: `mailto:${lead.email}` }, [lead.email])
  ]) : null;
  const addrParts = [lead.address, lead.postcode, lead.city].filter(Boolean).join(" ");
  const addrEl = addrParts ? el("div", { class: "row" }, [
    el("span", { class: "label" }, ["📍"]),
    document.createTextNode(addrParts)
  ]) : null;
  const urlEl = el("div", { class: "row" }, [
    el("span", { class: "label" }, ["🔗"]),
    el("a", { href: lead.final_url, target: "_blank", rel: "noopener" },
      [lead.final_url.replace(/^https?:\/\//, "").replace(/\/$/, "")])
  ]);
  const contact = el("div", { class: "contact" },
    [urlEl, phoneEl, emailEl, addrEl].filter(Boolean));

  // Kontaktet button + persistent state
  const key = lead.osm_id || lead.slug;
  const stored = ContactStore.get(key);
  const card = el("div", { class: "card" });
  if (stored) card.classList.add("contacted");
  if (status === "started") card.classList.add("in-progress");
  if (isIrrelevant) card.classList.add("irrelevant");

  const btn = el("button", { class: "contact-btn", type: "button" });
  const noteEl = el("div", { class: "contact-note" });

  function refreshBtn() {
    const cur = ContactStore.get(key);
    if (cur) {
      btn.innerHTML = "✓ Kontaktet (klik for at fjerne)";
      noteEl.innerHTML = `Kontaktet <span class="date">${cur.date}</span>`;
      card.classList.add("contacted");
      if (!previewBox.querySelector(".contacted-badge")) {
        previewBox.appendChild(el("div", { class: "contacted-badge" }, ["✓ Kontaktet"]));
      }
    } else {
      btn.innerHTML = "Markér som kontaktet";
      noteEl.innerHTML = "";
      card.classList.remove("contacted");
      const badge = previewBox.querySelector(".contacted-badge");
      if (badge) badge.remove();
    }
  }
  // Redesign action buttons (slug + status already declared above)
  const redesignReady = REDESIGNS.has(slug);
  const rsKey = lead.osm_id || lead.slug;
  const redesignBtn = el("button",
    { class: "redesign-btn" + (status === "started" ? " started" : ""),
      type: "button",
      title: status === "started"
        ? "Allerede markeret som igangsat. Klik for at re-kopiere prompten."
        : "Kopiér en færdig Cowork-prompt til udklipsholderen og markér " +
          "leadet som 'redesign igangsat'." },
    [status === "started" ? "🛠 Igangsat — re-kopiér prompt" : "✨ Start redesign"]);
  redesignBtn.addEventListener("click", async () => {
    try {
      await copyToClipboard(buildRedesignPrompt(lead));
      RedesignStore.set(rsKey, lead);
      updateRedesignCount();
      // re-render this card so badge + button reflect new state
      const fresh = makeCard(lead);
      card.replaceWith(fresh);
      showToast(
        `<b>✓ Redesign-prompt kopieret for ${lead.name}.</b><br>` +
        `Leadet er markeret som <b>igangsat</b>. Opret en ny Cowork-session ` +
        `(Ctrl/Cmd+N), paste, tryk Enter. Mockuppen gemmes i ` +
        `<code>output/redesigns/${slug}/</code>.`,
        7000
      );
    } catch (e) {
      showToast(`<b>⚠ Kunne ikke kopiere automatisk.</b> ` +
                `Browseren tillader ikke clipboard på file:// — ` +
                `åbn dashboardet via en lokal server, eller markér prompten manuelt.`,
                6000);
    }
  });

  // Unmark link — only visible when status is "started"
  let unmarkBtn = null;
  if (status === "started") {
    unmarkBtn = el("button", { class: "unmark-link", type: "button",
      title: "Fjern 'igangsat'-markeringen for dette lead" },
      ["✕ ikke længere igangsat"]);
    unmarkBtn.addEventListener("click", () => {
      RedesignStore.unset(rsKey);
      updateRedesignCount();
      const fresh = makeCard(lead);
      card.replaceWith(fresh);
    });
  }

  let openRedesignBtn = null;
  if (redesignReady) {
    openRedesignBtn = el("a",
      { class: "redesign-btn ready",
        href: `redesigns/${slug}/index.html`,
        target: "_blank", rel: "noopener" },
      ["🎨 Åbn redesign"]);
  }

  refreshBtn();
  btn.addEventListener("click", () => {
    if (ContactStore.get(key)) {
      ContactStore.unset(key);
    } else {
      ContactStore.set(key, lead);
    }
    refreshBtn();
    updateContactedCount();
    updateStorageHint();
    if (document.getElementById("contacted").value !== "all") {
      setTimeout(applyFilters, 100);
    }
  });

  const irrBtn = el("button",
    { class: "irrelevant-btn" + (isIrrelevant ? " active" : ""),
      type: "button",
      title: isIrrelevant
        ? "Fjern \"ikke relevant\"-markeringen for dette lead"
        : "Markér leadet som ikke relevant — det skjules som standard." },
    [isIrrelevant ? "✓ Ikke relevant" : "🚫 Ikke relevant"]);
  irrBtn.addEventListener("click", () => {
    if (IrrelevantStore.get(irrKey)) {
      IrrelevantStore.unset(irrKey);
    } else {
      IrrelevantStore.set(irrKey, lead);
    }
    updateIrrelevantCount();
    const fresh = makeCard(lead);
    card.replaceWith(fresh);
    if (document.getElementById("relevance").value !== "all") {
      setTimeout(applyFilters, 100);
    }
  });

  const actionRow = el("div", { class: "action-row" },
    [redesignBtn, openRedesignBtn, unmarkBtn, irrBtn].filter(Boolean));
  const body = el("div", { class: "card-body" },
    [titleEl, sigList, contact, actionRow, btn, noteEl].filter(Boolean));

  card.appendChild(head);
  card.appendChild(previewBox);
  card.appendChild(body);
  return card;
}

function applyFilters() {
  const bucket = document.getElementById("bucket").value;
  const category = document.getElementById("category").value;
  const scoreMin = parseInt(document.getElementById("scoreMin").value, 10);
  const sort = document.getElementById("sort").value;
  const search = document.getElementById("search").value.toLowerCase().trim();
  const contacted = document.getElementById("contacted").value;
  const freshness = document.getElementById("freshness").value;
  const redesignFilter = document.getElementById("redesign").value;
  const relevanceFilter = document.getElementById("relevance").value;
  document.getElementById("scoreMinVal").textContent = scoreMin;
  const contactedAll = ContactStore.all();
  const redesignAll = RedesignStore.all();
  const irrelevantAll = IrrelevantStore.all();

  let filtered = DATA.filter(d => {
    if (bucket !== "all" && d.bucket !== bucket) return false;
    if (category !== "all" && d.subcategory !== category) return false;
    if (d.score < scoreMin) return false;
    const key = d.osm_id || d.slug;
    const isContacted = !!contactedAll[key];
    if (contacted === "open" && isContacted) return false;
    if (contacted === "done" && !isContacted) return false;
    if (freshness === "new" && !d.new_this_run) return false;
    if (redesignFilter !== "all") {
      const rsk = d.osm_id || d.slug;
      const isDone = REDESIGNS.has(d.slug);
      const isStarted = !isDone && !!redesignAll[rsk];
      const cur = isDone ? "done" : (isStarted ? "started" : "none");
      if (cur !== redesignFilter) return false;
    }
    const irrK = d.osm_id || d.slug;
    const isIrr = !!irrelevantAll[irrK];
    if (relevanceFilter === "hide" && isIrr) return false;
    if (relevanceFilter === "only" && !isIrr) return false;
    if (search) {
      const blob = (d.name + " " + d.subcategory + " " + d.city +
                    " " + d.title).toLowerCase();
      if (!blob.includes(search)) return false;
    }
    return true;
  });

  if (sort === "score") {
    filtered.sort((a, b) => b.score - a.score || a.name.localeCompare(b.name));
  } else if (sort === "name") {
    filtered.sort((a, b) => a.name.localeCompare(b.name, "da"));
  } else if (sort === "category") {
    filtered.sort((a, b) => (a.subcategory || "").localeCompare(b.subcategory || "")
                          || b.score - a.score);
  }

  const grid = document.getElementById("grid");
  grid.innerHTML = "";
  if (!filtered.length) {
    grid.appendChild(el("div", { class: "empty" },
      ["Ingen leads matcher de filtre."]));
  } else {
    filtered.forEach(l => grid.appendChild(makeCard(l)));
  }
  document.getElementById("resultCount").textContent =
    `${filtered.length} vist`;
}

function exportContacted() {
  const all = ContactStore.all();
  if (!Object.keys(all).length) {
    alert("Ingen kontaktede leads endnu.");
    return;
  }
  // Enrich with current DATA (for phone/email/score/etc.)
  const byKey = {};
  DATA.forEach(d => { byKey[d.osm_id || d.slug] = d; });
  const rows = [["Dato","Navn","Branche","Hjemmeside","Score",
                 "Telefon","Email","Adresse","By"]];
  Object.entries(all).forEach(([key, c]) => {
    const d = byKey[key] || {};
    rows.push([c.date, c.name, d.subcategory || "", d.website || c.website,
               d.score ?? "", d.phone || "", d.email || "",
               d.address || "", d.city || ""]);
  });
  const csv = rows.map(r => r.map(c => `"${String(c).replace(/"/g,'""')}"`).join(",")).join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `kontaktede_${new Date().toISOString().slice(0,10)}.csv`;
  a.click();
}

function downloadBackupJson() {
  const all = ContactStore.all();
  const allRedesign = RedesignStore.all();
  const allIrr = IrrelevantStore.all();
  const payload = {
    _format: "coldOutreach.backup.v3",
    _exportedAt: new Date().toISOString(),
    _contactedCount: Object.keys(all).length,
    _redesignStartedCount: Object.keys(allRedesign).length,
    _irrelevantCount: Object.keys(allIrr).length,
    items: all,
    redesignStarted: allRedesign,
    irrelevant: allIrr,
  };
  const json = JSON.stringify(payload, null, 2);
  const blob = new Blob([json], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `kontaktede-backup-${new Date().toISOString().slice(0,10)}.json`;
  a.click();
}

function restoreBackupJson(file) {
  const reader = new FileReader();
  reader.onload = (ev) => {
    try {
      const data = JSON.parse(ev.target.result);
      const items = data.items || data;  // accept raw {key:lead} too
      const reditems = data.redesignStarted || {};
      const irritems = data.irrelevant || {};
      if (typeof items !== "object" || Array.isArray(items)) {
        throw new Error("ugyldig backup-fil");
      }
      const current = ContactStore.all();
      const merged = { ...current, ...items };
      ContactStore.save(merged);
      const curRed = RedesignStore.all();
      const mergedRed = { ...curRed, ...reditems };
      RedesignStore.save(mergedRed);
      const curIrr = IrrelevantStore.all();
      const mergedIrr = { ...curIrr, ...irritems };
      IrrelevantStore.save(mergedIrr);
      updateStorageHint();
      updateContactedCount();
      updateRedesignCount();
      updateIrrelevantCount();
      applyFilters();
      alert(`Importeret ${Object.keys(items).length} kontaktet + ` +
            `${Object.keys(reditems).length} igangsat + ` +
            `${Object.keys(irritems).length} ikke-relevant. ` +
            `Totalt nu: ${Object.keys(merged).length} / ${Object.keys(mergedRed).length} / ${Object.keys(mergedIrr).length}.`);
    } catch (e) {
      alert("Kunne ikke læse backup-fil: " + e.message);
    }
  };
  reader.readAsText(file);
}

function resetAll() {
  const nc = Object.keys(ContactStore.all()).length;
  const nr = Object.keys(RedesignStore.all()).length;
  const ni = Object.keys(IrrelevantStore.all()).length;
  if (nc + nr + ni === 0) { alert("Ingen markeringer at nulstille."); return; }
  if (!confirm(`Slet ALLE markeringer? Det fjerner ${nc} kontaktet + ${nr} ` +
               `igangsat + ${ni} ikke-relevant. Lav en backup først hvis du er i tvivl.`)) return;
  localStorage.removeItem(ContactStore.KEY);
  localStorage.removeItem(RedesignStore.KEY);
  localStorage.removeItem(IrrelevantStore.KEY);
  updateStorageHint();
  updateContactedCount();
  updateRedesignCount();
  updateIrrelevantCount();
  applyFilters();
}

function updateStorageHint() {
  const nc = Object.keys(ContactStore.all()).length;
  const nr = Object.keys(RedesignStore.all()).length;
  const total = nc + nr;
  const hint = document.getElementById("storageHint");
  if (total === 0) {
    hint.innerHTML = `Markeringer gemmes lokalt i denne browser (localStorage). ` +
      `Tip: tag en "Backup JSON" nu og igen i ny og næ — den er sikkerhedsnet ` +
      `hvis du rydder browser-data eller flytter dashboard.html.`;
  } else {
    hint.innerHTML = `<b>✓ ${nc} kontaktet + ${nr} igangsat gemt</b> i denne ` +
      `browsers localStorage — overlever lukning af browseren. ` +
      `Klik "Backup JSON" for en kopi du kan beholde uden for browseren.`;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  renderStats();
  updateStorageHint();
  populateCategoryFilter();
  ["bucket", "category", "scoreMin", "sort", "search", "contacted",
   "freshness", "redesign", "relevance"].forEach(id => {
    document.getElementById(id).addEventListener("input", applyFilters);
  });
  document.getElementById("exportBtn").addEventListener("click", exportContacted);
  document.getElementById("backupBtn").addEventListener("click", downloadBackupJson);
  document.getElementById("resetBtn").addEventListener("click", resetAll);
  document.getElementById("restoreBtn").addEventListener("click", () => {
    document.getElementById("restoreFile").click();
  });
  document.getElementById("restoreFile").addEventListener("change", (e) => {
    const f = e.target.files[0];
    if (f) restoreBackupJson(f);
    e.target.value = "";
  });
  document.getElementById("rescanBtn").addEventListener("click", async () => {
    const area = prompt(
      "Hvilket område skal scannes for NYE sider?\n\n" +
      "Eksisterende osm_id\'er filtreres fra — kun nye fund rapporteres.\n" +
      "(svendborg, sydfyn, fyn eller denmark)",
      "svendborg"
    );
    if (!area) return;
    const prompt_text =
`Kør et nyt scrape af lokale virksomheder i Danmark.

OPGAVE
1. cd til C:\\Users\\jakob\\WilbrandtWorks\\ColdOutreaches
2. Kør: SCORER_TIMEOUT=5 python3 -u incremental_scrape.py --area ${area} --workers 30
3. Det henter friske OSM-data og scorer KUN sider vi ikke har set før.
   Eksisterende leads' last_seen opdateres, men de re-scores ikke.
4. Når scrapingen er færdig, kør: python3 build_dashboard.py
5. Tag screenshots af de nye fund: python3 screenshot.py --all --workers 10
6. Genkør build_dashboard.py én gang til så screenshots inkluderes
7. Vis mig output/new_leads.json eller fortæl hvor mange nye fund der kom

VIGTIGT
- Området er: ${area}
- ARBEJD KUN inkrementelt — eksisterende leads i output/results.json skal IKKE re-scores
- Hvis Overpass returnerer 504 (timeout) på denmark, så chunk regionen ned i mindre bbox'er
- Når dashboardet er opdateret, åbn det igen i browseren (eller fortæl mig at jeg skal genindlæse)
`;
    try {
      await copyToClipboard(prompt_text);
      showToast(
        `<b>✓ Scrape-prompt kopieret for område: ${area}.</b><br>` +
        `Opret en ny Cowork-session (Ctrl/Cmd+N), paste, tryk Enter. ` +
        `Resultatet havner i <code>output/results.json</code> og dashboardet.`,
        9000
      );
    } catch (e) {
      showToast(`<b>⚠ Kunne ikke kopiere automatisk.</b> Browseren blokerer ` +
        `clipboard på file://. Kør i stedet i din terminal: <br>` +
        `<code style="user-select:all;">python3 incremental_scrape.py ` +
        `--area ${area}</code>`, 10000);
    }
  });
  window.addEventListener("storage", () => {
    updateStorageHint();
    updateContactedCount();
    applyFilters();
  });
  requestAnimationFrame(applyFilters);
});
</script>
</body>
</html>
"""

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="output/results.json")
    ap.add_argument("--screenshots", default="output/screenshots")
    ap.add_argument("--redesigns", default="output/redesigns")
    ap.add_argument("--out", default="output/dashboard.html")
    args = ap.parse_args()
    Path(args.redesigns).mkdir(parents=True, exist_ok=True)
    main(args.results, args.screenshots, args.redesigns, args.out)
