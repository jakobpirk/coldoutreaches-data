"""
Single overnight runner: discover -> score -> (screenshot) -> ingest into store.

This is the one command n8n will call on a schedule. Deterministic; no Claude.
The claude -p prep (classify/research/draft) runs as a separate step afterwards.

    python3 run_scan.py --area svendborg                 # full run
    python3 run_scan.py --skip-discover --limit 8         # quick bounded test
    python3 run_scan.py --area svendborg --no-screens     # skip screenshots

Writes: output/companies.json, output/results.json, and the SQLite store
(output/leads.db by default, or $LEADS_DB).
"""
from __future__ import annotations
import sys
import os
import json
import time
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import discover
import scorer
import report
import store


def normalise_url(u: str) -> str:
    u = (u or "").strip()
    if not u:
        return ""
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    return u


def gather_companies(area: str, out_dir: Path, skip_discover: bool) -> list[dict]:
    path = out_dir / "companies.json"
    if skip_discover and path.exists():
        companies = json.loads(path.read_text())
        print(f"[scan] loaded {len(companies)} companies from cache", file=sys.stderr)
    else:
        companies = discover.discover(area, str(path))
    return companies


def dedupe(companies: list[dict]) -> list[dict]:
    seen, out = set(), []
    for c in companies:
        if not c.get("website"):
            continue
        key = normalise_url(c["website"]).rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def score_all(companies: list[dict], workers: int) -> list[dict]:
    def work(c):
        r = scorer.score_url(normalise_url(c["website"]), expected_name=c.get("name", ""))
        return c, r

    results, t0, done = [], time.time(), 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(work, c) for c in companies]
        for f in as_completed(futures):
            try:
                c, r = f.result()
            except Exception:
                continue
            done += 1
            if done % 10 == 0:
                print(f"[scan]   scored {done}/{len(companies)} ({time.time()-t0:.0f}s)",
                      file=sys.stderr)
            results.append({
                "name": c["name"], "category": c["category"],
                "subcategory": c["subcategory"], "website": c["website"],
                "final_url": r.final_url, "status": r.status, "score": r.score,
                "raw_score": r.raw_score, "modern_penalty": r.modern_penalty,
                "title": r.title, "error": r.error, "phone": c.get("phone", ""),
                "email": c.get("email", ""), "address": c.get("address", ""),
                "city": c.get("city", ""), "postcode": c.get("postcode", ""),
                "signals": [{"name": s.name, "points": s.points, "evidence": s.evidence}
                            for s in r.signals],
                "osm_id": c.get("osm_id", ""),
                "first_seen": c.get("first_seen", ""), "last_seen": c.get("last_seen", ""),
            })
    results.sort(key=lambda r: (-r["score"], r["name"]))
    return results


def run(area, workers, top, limit, skip_discover, no_screens, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    companies = dedupe(gather_companies(area, out_dir, skip_discover))
    if limit:
        companies = companies[:limit]
    print(f"[scan] scoring {len(companies)} websites ...", file=sys.stderr)
    results = score_all(companies, workers)

    # don't clobber the canonical results file during bounded test runs
    results_path = out_dir / ("results.test.json" if limit else "results.json")
    results_path.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    if not limit:
        report.write_csv(results, out_dir / "leads.csv")
        report.write_markdown(area, top, results, out_dir / "leads.md")

    con = store.connect()
    store.init(con)
    print("[scan] ingest:", store.ingest(con, str(results_path)))

    if not no_screens:
        import screenshot
        screenshot.run(str(out_dir / "results.json"), out_dir / "screenshots",
                       top=int(os.environ.get("SHOT_LIMIT", "200")), workers=6,
                       all_live=False, include_hijacked=False)
        print(f"[scan] linked {store.link_screenshots(con, str(out_dir / 'screenshots'))} screenshots")

    store.stats(con)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--area", default="svendborg", choices=list(discover.AREAS))
    ap.add_argument("--workers", type=int, default=30)
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--limit", type=int, default=0, help="cap companies scored (testing)")
    ap.add_argument("--skip-discover", action="store_true", help="use cached companies.json")
    ap.add_argument("--no-screens", action="store_true")
    ap.add_argument("--out", default="output")
    a = ap.parse_args()
    run(a.area, a.workers, a.top, a.limit, a.skip_discover, a.no_screens, Path(a.out))
