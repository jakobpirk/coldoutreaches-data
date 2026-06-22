"""Report writers: produce CSV + Markdown from scored results."""
from __future__ import annotations
import csv
from pathlib import Path

BIG_BRAND_DOMAINS = {
    "mcdonalds.dk", "louisnielsen.dk", "harald-nyborg.dk", "thansen.dk",
    "apoteket-online.dk", "danbolig.dk", "ufm.dk", "cancer.dk",
    "synoptik.dk", "matas.dk", "imerco.dk", "ikea.com",
}


def is_big_brand(r):
    host = (r["website"] or "").lower()
    return any(d in host for d in BIG_BRAND_DOMAINS)


def has_signal(r, name):
    return any(s["name"] == name for s in r["signals"])


def write_csv(results, path: Path):
    with path.open("w", newline="", encoding="utf-8") as f:
        cols = ["score", "name", "subcategory", "category", "website",
                "final_url", "status", "city", "postcode", "phone", "email",
                "title", "top_signals", "error"]
        w = csv.writer(f)
        w.writerow(cols)
        for r in results:
            top_sigs = "; ".join(
                f"{s['name']}(+{s['points']})" for s in r["signals"]
                if s["points"] > 0
            )
            w.writerow([r["score"], r["name"], r["subcategory"], r["category"],
                        r["website"], r["final_url"], r["status"],
                        r["city"], r["postcode"], r["phone"], r["email"],
                        r["title"], top_sigs, r["error"]])


def write_markdown(area, top, results, path: Path):
    reached = [r for r in results if r["status"] == 200]
    broken = [r for r in results
              if (r["status"] == 0 or r["status"] >= 400)
              and not is_big_brand(r)]
    big_brand_skipped = [r for r in results if is_big_brand(r)]
    hijacked = [r for r in reached
                if has_signal(r, "name_mismatch")
                or has_signal(r, "parked_domain")
                or has_signal(r, "thin_or_stub")]
    real_outdated = [r for r in reached
                     if r not in hijacked and r["score"] >= 5]

    L = []
    L.append(f"# Outdated-website leads - {area.title()}")
    L.append("")
    L.append(f"_{len(results)} sites scored. Higher score = more outdated._")
    L.append("")

    # Bucket 1: dead websites
    L.append(f"## Dode hjemmesider - aktivt firma, hjemmeside nede ({len(broken)})")
    L.append("")
    L.append("Disse virksomheder er listet i OSM (altsa aktive), men "
             "hjemmesiden svarer ikke. **Det er guldleads** - de har "
             "bevisligt brug for en ny side. Ring til telefonen for at "
             "bekraefte firmaet stadig findes.")
    L.append("")
    if broken:
        L.append("Virksomhed | Branche | Hjemmeside | Status | Fejl | Telefon")
        L.append("---|---|---|---|---|---")
        for r in broken[:40]:
            name = r["name"].replace("|", "\\|")
            L.append(f"{name} | {r['subcategory']} | {r['website']} | "
                     f"{r['status']} | {r['error'][:50]} | {r['phone']}")
    else:
        L.append("_(ingen)_")
    L.append("")

    # Bucket 2: real outdated
    L.append(f"## Grimme/foraeldede hjemmesider - top {top} "
             f"({len(real_outdated)} samlet, score >= 5)")
    L.append("")
    L.append("Disse sites svarer, men har klare tegn pa at vaere ude af tiden.")
    L.append("")
    L.append("Score | Virksomhed | Branche | Hjemmeside | Signaler")
    L.append("---:|---|---|---|---")
    for r in real_outdated[:top]:
        sigs = ", ".join(
            f"{s['name']} (+{s['points']})"
            for s in r["signals"] if s["points"] > 0
        )[:200]
        name = r["name"].replace("|", "\\|")
        url = r["final_url"] or r["website"]
        L.append(f"{r['score']} | {name} | {r['subcategory']} | "
                 f"[{url}]({url}) | {sigs}")
    L.append("")

    # Bucket 3: hijacked/parked
    if hijacked:
        L.append(f"## Solgt/parkeret domaene - firma findes, "
                 f"men har mistet sit domaene ({len(hijacked)})")
        L.append("")
        L.append("Domaenet er solgt eller parkeret. Firmaet findes stadig - "
                 "men besogende lander pa en irrelevant side. **Staerkt lead** "
                 "for et nyt domaene + ny side.")
        L.append("")
        L.append("Virksomhed | Branche | Domaene | Titel der vises | Telefon")
        L.append("---|---|---|---|---")
        for r in hijacked[:20]:
            name = r["name"].replace("|", "\\|")
            L.append(f"{name} | {r['subcategory']} | {r['website']} | "
                     f"{(r['title'] or '')[:60]} | {r['phone']}")
        L.append("")

    # Bucket 4: skipped big brands
    if big_brand_skipped:
        L.append(f"## Sprunget over: kaeder og store brands "
                 f"({len(big_brand_skipped)})")
        L.append("")
        for r in big_brand_skipped:
            L.append(f"- {r['name']} ({r['website']})")
        L.append("")

    # Stats
    if reached:
        avg = sum(r["score"] for r in reached) / len(reached)
        L.append("## Stats")
        L.append("")
        L.append(f"- Sites reached: {len(reached)} / {len(results)}")
        L.append(f"- Mean outdated-score (reached): {avg:.1f}")
        for thr in (30, 20, 10, 5):
            n = sum(1 for r in reached if r["score"] >= thr)
            L.append(f"- Sites with score >= {thr}: {n}")
        L.append("")

    path.write_text("\n".join(L), encoding="utf-8")
