"""
Incremental scrape: pull new OSM data, score ONLY companies we haven't seen before,
merge into existing results.json so we keep history without re-scoring everything.

Usage:
    python3 incremental_scrape.py --area svendborg

Each lead in results.json gets:
- "first_seen": date this lead was first discovered  (set on insert)
- "last_seen":  date most recently confirmed in OSM  (updated each run)
- "new_this_run": bool — true only for leads added during the latest run

The "key" we diff on is the OSM id ("node/12345" / "way/67890"), which is stable
across OSM updates.
"""
from __future__ import annotations
import sys
import json
import argparse
import time
import datetime as dt
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from discover import discover, AREAS
from scorer import score_url
from report import write_csv, write_markdown


def normalise_url(u: str) -> str:
    u = u.strip()
    if not u:
        return ""
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    return u


def run(area: str, workers: int, top: int, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().isoformat()

    # Load existing results (if any) and index by osm_id
    results_path = out_dir / "results.json"
    existing: list[dict] = []
    if results_path.exists():
        existing = json.loads(results_path.read_text())
    by_osm_id = {r.get("osm_id"): r for r in existing if r.get("osm_id")}
    print(f"existing leads: {len(existing)}  (with osm_id: {len(by_osm_id)})",
          file=sys.stderr)

    # Always reset the new_this_run flag on every lead before this run.
    # Also backfill first_seen for any legacy leads from before this feature
    # was added (so we don't accidentally mark them as "new").
    for r in existing:
        r["new_this_run"] = False
        if not r.get("first_seen"):
            r["first_seen"] = "pre-2026-06-04"

    # Discover fresh OSM data
    companies_path = out_dir / "companies.json"
    companies = discover(area, str(companies_path))

    # Dedupe by website URL within the new pull (same as run_mvp.py)
    seen_urls: set[str] = set()
    deduped: list[dict] = []
    for c in companies:
        if not c.get("website"):
            continue
        key = normalise_url(c["website"]).rstrip("/").lower()
        if key in seen_urls:
            continue
        seen_urls.add(key)
        deduped.append(c)

    # Split into "already known" (we just bump last_seen) and "new" (score them)
    new_companies = []
    confirmed_count = 0
    for c in deduped:
        oid = c.get("osm_id")
        if oid and oid in by_osm_id:
            by_osm_id[oid]["last_seen"] = today
            confirmed_count += 1
        else:
            new_companies.append(c)
    print(f"  -> {confirmed_count} already-known confirmed",
          file=sys.stderr)
    print(f"  -> {len(new_companies)} NEW companies to score",
          file=sys.stderr)

    if not new_companies:
        print("\nIngen nye fund. Dashboardet er stadig retvisende.",
              file=sys.stderr)
        # Still rewrite results.json so last_seen is updated
        results_path.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2))
        return existing, []

    # Score only the new ones
    def work(c):
        url = normalise_url(c["website"])
        return c, score_url(url, expected_name=c.get("name", ""))

    new_results: list[dict] = []
    t0 = time.time()
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(work, c) for c in new_companies]
        for f in as_completed(futures):
            try:
                c, r = f.result()
            except Exception:
                continue
            done += 1
            if done % 10 == 0:
                print(f"  scored {done}/{len(new_companies)}  "
                      f"({time.time()-t0:.0f}s)", file=sys.stderr)
            new_results.append({
                "name": c["name"],
                "category": c["category"],
                "subcategory": c["subcategory"],
                "website": c["website"],
                "final_url": r.final_url,
                "status": r.status,
                "score": r.score,
                "raw_score": r.raw_score,
                "modern_penalty": r.modern_penalty,
                "title": r.title,
                "error": r.error,
                "phone": c.get("phone", ""),
                "email": c.get("email", ""),
                "address": c.get("address", ""),
                "city": c.get("city", ""),
                "postcode": c.get("postcode", ""),
                "signals": [
                    {"name": s.name, "points": s.points, "evidence": s.evidence}
                    for s in r.signals
                ],
                "osm_id": c.get("osm_id", ""),
                "first_seen": today,
                "last_seen": today,
                "new_this_run": True,
            })

    # Merge + write
    merged = existing + new_results
    merged.sort(key=lambda r: (-r["score"], r["name"]))
    results_path.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2))
    (out_dir / "new_leads.json").write_text(
        json.dumps(new_results, ensure_ascii=False, indent=2))

    # Refresh CSV + markdown
    write_csv(merged, out_dir / "leads.csv")
    write_markdown(area, top, merged, out_dir / "leads.md")

    print(f"\nWrote: {out_dir}/results.json, leads.csv, leads.md, "
          f"new_leads.json", file=sys.stderr)
    print(f"NYE LEADS ({len(new_results)}):", file=sys.stderr)
    new_results.sort(key=lambda r: -r["score"])
    for r in new_results[:30]:
        print(f"  [{r['score']:>3}] {r['name']:35s} {r['subcategory']:18s} "
              f"{r['website']}", file=sys.stderr)

    return merged, new_results


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--area", default="svendborg", choices=list(AREAS))
    ap.add_argument("--workers", type=int, default=30)
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--out", default="output")
    args = ap.parse_args()
    run(args.area, args.workers, args.top, Path(args.out))
