"""
Screenshot top-scoring leads using thum.io's free public API.

Usage:
    python3 screenshot.py --top 12 --out output/screenshots
"""
from __future__ import annotations
import json
import argparse
import re
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

THUM_URL = "https://image.thum.io/get/width/1200/crop/900/png/noanimate/{url}"


def slugify(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[æøå]", lambda m: {"æ":"ae","ø":"oe","å":"aa"}[m.group(0)], s)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:40] or "unknown"


def fetch_one(name: str, url: str, out_dir: Path, skip_cached: bool = True):
    slug = slugify(name)
    png_path = out_dir / f"{slug}.png"
    if skip_cached and png_path.exists() and png_path.stat().st_size > 5000:
        return {"name": name, "screenshot": png_path.name,
                "bytes": png_path.stat().st_size, "cached": True}
    full = THUM_URL.format(url=url)
    try:
        r = requests.get(full, timeout=45,
                         headers={"User-Agent": "LeadScout/0.1"})
        if r.status_code == 200 and len(r.content) > 5000:
            png_path.write_bytes(r.content)
            return {"name": name, "screenshot": str(png_path.name),
                    "bytes": len(r.content)}
        return {"name": name, "error": f"HTTP {r.status_code} ({len(r.content)}B)"}
    except Exception as e:
        return {"name": name, "error": str(e)[:120]}


def run(results_path: str, out_dir: Path, top: int, workers: int,
        all_live: bool, include_hijacked: bool):
    results = json.loads(Path(results_path).read_text())
    HIJACK_SIGS = {"name_mismatch", "name_mismatch_promo",
                   "parked_domain", "thin_or_stub"}
    BIG_BRAND_DOMAINS = {"mcdonalds.dk","louisnielsen.dk","harald-nyborg.dk",
                         "thansen.dk","apoteket-online.dk","danbolig.dk",
                         "ufm.dk","cancer.dk"}
    candidates = []
    for r in results:
        if r["status"] != 200:
            continue
        host = (r["website"] or "").lower()
        if any(d in host for d in BIG_BRAND_DOMAINS):
            continue
        sig_names = {s["name"] for s in r["signals"]}
        is_hijacked = bool(sig_names & HIJACK_SIGS)
        if is_hijacked and not include_hijacked:
            continue
        if not all_live and r["score"] < 5:
            continue
        candidates.append(r)
    candidates.sort(key=lambda r: (-r["score"], r["name"]))
    # Dedup by website root
    seen = set()
    todo = []
    for r in candidates:
        key = (r.get("final_url") or r["website"]).rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        todo.append(r)
        if not all_live and len(todo) >= top:
            break

    print(f"will screenshot {len(todo)} sites")
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    shot_info = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(fetch_one, r["name"],
                             r.get("final_url") or r["website"], out_dir, True): r
                   for r in todo}
        for f in as_completed(futures):
            res = f.result()
            shot_info[res["name"]] = res
            tag = "cached" if res.get("cached") else ("ok" if "screenshot" in res else "fail")
            print(f"  [{tag}] {res['name']:40s} {res.get('screenshot') or res.get('error','')}")

    # Build a visual markdown
    md_path = out_dir.parent / "leads_visual.md"
    lines = ["# Visuel review af top leads", ""]
    lines.append(f"_{len(todo)} sites screenshotted via thum.io. "
                 "Sammenlign det visuelle med scoren._")
    lines.append("")
    # Limit md output to top 20 for readability — full set lives in the
    # dashboard which handles arbitrary size.
    for r in todo[:20]:
        info = shot_info.get(r["name"], {})
        name = r["name"]
        score = r["score"]
        url = r.get("final_url") or r["website"]
        sub = r.get("subcategory", "")
        sigs = ", ".join(
            f"{s['name']} (+{s['points']})"
            for s in r["signals"] if s["points"] > 0
        )[:200]
        lines.append(f"## {score} — {name} ({sub})")
        lines.append("")
        lines.append(f"**Site:** [{url}]({url})  ")
        lines.append(f"**Telefon:** {r.get('phone','')}  ")
        lines.append(f"**Email:** {r.get('email','')}  ")
        lines.append(f"**Adresse:** {r.get('address','')} {r.get('postcode','')} {r.get('city','')}  ")
        lines.append(f"**Signaler:** {sigs}")
        lines.append("")
        if info.get("screenshot"):
            lines.append(f"![screenshot](screenshots/{info['screenshot']})")
        elif info.get("error"):
            lines.append(f"_(screenshot failed: {info['error']})_")
        lines.append("")
        lines.append("---")
        lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote {md_path}  ({time.time()-t0:.0f}s)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default="output/results.json")
    ap.add_argument("--out", default="output/screenshots")
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--all", action="store_true",
                    help="screenshot ALL reachable live sites, not just top N")
    ap.add_argument("--include-hijacked", action="store_true",
                    help="also screenshot hijacked/parked domains")
    args = ap.parse_args()
    run(args.results, Path(args.out), args.top, args.workers,
        args.all, args.include_hijacked)
