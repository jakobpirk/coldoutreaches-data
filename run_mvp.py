"""
MVP orchestrator: discover -> score -> rank -> report.

Usage:
    python3 run_mvp.py --area svendborg --workers 30 --top 40
"""
from __future__ import annotations
import sys
import json
import argparse
import time
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


def run(area, workers, top, out_dir: Path, refresh_discovery: bool):
    out_dir.mkdir(parents=True, exist_ok=True)
    companies_path = out_dir / "companies.json"

    if refresh_discovery or not companies_path.exists():
        companies = discover(area, str(companies_path))
    else:
        companies = json.loads(companies_path.read_text())
        print(f"loaded {len(companies)} companies from cache",
              file=sys.stderr)

    seen_urls: set[str] = set()
    to_score = []
    for c in companies:
        if not c.get("website"):
            continue
        key = normalise_url(c["website"]).rstrip("/").lower()
        if key in seen_urls:
            continue
        seen_urls.add(key)
        to_score.append(c)
    print(f"scoring {len(to_score)} websites (deduped) ...", file=sys.stderr)

    def work(c):
        url = normalise_url(c["website"])
        r = score_url(url, expected_name=c.get("name", ""))
        return c, r

    results = []
    t0 = time.time()
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(work, c) for c in to_score]
        for f in as_completed(futures):
            try:
                c, r = f.result()
            except Exception:
                continue
            done += 1
            if done % 10 == 0:
                print(f"  {done}/{len(to_score)} ({time.time()-t0:.0f}s)",
                      file=sys.stderr)
            results.append({
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
            })

    results.sort(key=lambda r: (-r["score"], r["name"]))
    (out_dir / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2))
    write_csv(results, out_dir / "leads.csv")
    write_markdown(area, top, results, out_dir / "leads.md")
    print(f"\nWrote: {out_dir}/leads.csv, leads.md, results.json",
          file=sys.stderr)
    return results


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--area", default="svendborg", choices=list(AREAS))
    ap.add_argument("--workers", type=int, default=30)
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--out", default="output")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()
    run(args.area, args.workers, args.top, Path(args.out), args.refresh)
