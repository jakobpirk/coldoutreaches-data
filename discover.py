"""
Discovery: pull local businesses with websites from OpenStreetMap (Overpass API).

OSM has a surprisingly rich dataset for Danish businesses:
- craft=* (carpenter, electrician, plumber, painter, etc.) — håndværkere
- shop=* (butikker)
- office=* (advokater, revisorer, ejendomsmæglere, ...)
- amenity=dentist|veterinary|restaurant|cafe|pharmacy|...
- healthcare=* (klinikker)

Many entries already have `website`, `phone`, `email` tags filled in.
Free, no auth, no rate-limit-per-day to worry about.

Output: a JSON file with normalised business records:
{
    "name": str, "category": str, "subcategory": str,
    "website": str (may be empty), "phone": str, "email": str,
    "address": str, "city": str, "postcode": str,
    "lat": float, "lon": float, "osm_id": str
}
"""
from __future__ import annotations
import sys
import os
import json
import argparse
import time
import requests
from pathlib import Path

USER_AGENT = "ColdOutreaches-LeadScout/0.1 (jakobwilbrandt@gmail.com)"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
# The main public Overpass server 504s under load — try mirrors in turn.
# A custom endpoint in $OVERPASS_URL (if set) is tried first.
OVERPASS_MIRRORS = [m for m in [
    os.environ.get("OVERPASS_URL"),
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
] if m]

# Bounding boxes — (south, west, north, east)
AREAS = {
    "svendborg": (55.00, 10.50, 55.13, 10.78),         # Svendborg by + omegn
    "sydfyn":    (54.85, 10.20, 55.30, 11.00),         # Sydfyn bredere
    "fyn":       (54.70, 9.70,  55.75, 11.10),         # Hele Fyn
    "denmark":   None,                                  # chunked into REGIONS
}

# Bounding boxes for chunked Denmark-wide queries.
# Slight overlap is fine; we dedup by (name, lat, lon).
REGIONS = [
    ("nordjylland",  (56.60, 8.00, 57.80, 11.20)),
    ("midtjylland",  (55.70, 8.00, 57.10, 11.50)),
    ("syddanmark",   (54.40, 8.10, 55.75, 11.10)),
    ("sjaelland",    (54.50, 10.90, 55.85, 12.70)),
    ("hovedstaden",  (55.50, 11.70, 56.20, 12.80)),
    ("bornholm",     (54.95, 14.65, 55.35, 15.25)),
]

# Which tag categories to pull. We pull craft without requiring 'website',
# because håndværkere often only have phone in OSM — we can still try a URL
# from the name afterwards. For other categories we require a website to keep
# the list short and high-signal.
def overpass_query(bbox: tuple[float, float, float, float]) -> str:
    s, w, n, e = bbox
    box = f"{s},{w},{n},{e}"
    return f"""
[out:json][timeout:60];
(
  // Håndværkere — anything with craft tag, website optional
  node["craft"]({box});
  way["craft"]({box});
  // Butikker, kontorer, klinikker, restauranter — kræv website
  node["shop"]({box})["website"];
  way["shop"]({box})["website"];
  node["office"]({box})["website"];
  way["office"]({box})["website"];
  node["healthcare"]({box})["website"];
  way["healthcare"]({box})["website"];
  node["amenity"~"^(dentist|veterinary|restaurant|cafe|pharmacy|fast_food|pub|bar|car_wash|car_rental|driving_school|fuel)$"]({box})["website"];
  way["amenity"~"^(dentist|veterinary|restaurant|cafe|pharmacy|fast_food|pub|bar|car_wash|car_rental|driving_school|fuel)$"]({box})["website"];
  // Mindre, hjemmesidefri butikker — vi tager dem med, scoren bliver bare 'no-website'
  node["shop"]({box});
  way["shop"]({box});
);
out tags center;
""".strip()


def overpass_query_dk(bbox: tuple[float, float, float, float]) -> str:
    """Nationwide region query — tradesmen (craft=*) with a website ONLY.
    This is the segment we target, and dropping shops/offices/restaurants cuts
    the query volume hugely, which avoids the 504/429 throttling on the public
    Overpass servers."""
    s, w, n, e = bbox
    box = f"{s},{w},{n},{e}"
    return f"""
[out:json][timeout:120];
area["ISO3166-1"="DK"][admin_level=2]->.dk;
(
  node["craft"]["website"](area.dk)({box});
  way["craft"]["website"](area.dk)({box});
);
out tags center;
""".strip()


def normalize(el: dict) -> dict | None:
    tags = el.get("tags", {})
    name = tags.get("name") or tags.get("operator")
    if not name:
        return None
    if el.get("type") == "node":
        lat, lon = el.get("lat"), el.get("lon")
    else:
        c = el.get("center") or {}
        lat, lon = c.get("lat"), c.get("lon")

    category = ("craft" if "craft" in tags else
                "shop" if "shop" in tags else
                "office" if "office" in tags else
                "healthcare" if "healthcare" in tags else
                "amenity" if "amenity" in tags else "other")
    subcategory = tags.get(category, "")

    website = (tags.get("website") or tags.get("contact:website")
               or tags.get("url") or "")
    return {
        "name": name.strip(),
        "category": category,
        "subcategory": subcategory,
        "website": website.strip(),
        "phone": (tags.get("phone") or tags.get("contact:phone") or "").strip(),
        "email": (tags.get("email") or tags.get("contact:email") or "").strip(),
        "address": (
            f"{tags.get('addr:street','')} {tags.get('addr:housenumber','')}".strip()
        ),
        "postcode": tags.get("addr:postcode", "").strip(),
        "city": tags.get("addr:city", "").strip(),
        "lat": lat,
        "lon": lon,
        "osm_id": f"{el.get('type','')}/{el.get('id','')}",
    }


def _fetch_one_bbox(bbox, query_fn, label, timeout):
    print(f"  querying Overpass: {label} bbox={bbox}", file=sys.stderr)
    q = query_fn(bbox)
    last = None
    for url in OVERPASS_MIRRORS:
        for attempt in range(2):
            try:
                r = requests.post(url, data={"data": q}, timeout=timeout,
                                  headers={"User-Agent": USER_AGENT})
                r.raise_for_status()
                elements = r.json().get("elements", [])
                print(f"    -> {len(elements)} elements (via {url})", file=sys.stderr)
                return elements
            except Exception as e:
                last = e
                print(f"    overpass {url} attempt {attempt+1} failed: {e!r}",
                      file=sys.stderr)
                time.sleep(3)
    raise RuntimeError(f"all Overpass mirrors failed: {last!r}")


def discover(area: str = "svendborg", out_path: str = None) -> list[dict]:
    if area not in AREAS:
        raise ValueError(f"unknown area '{area}' (have: {list(AREAS)})")
    if area == "denmark":
        elements = []
        for label, bbox in REGIONS:
            try:
                elements += _fetch_one_bbox(bbox, overpass_query_dk, label, timeout=180)
            except Exception as e:
                print(f"    region {label} FAILED: {e!r}", file=sys.stderr)
            time.sleep(6)  # be polite to the free Overpass servers (avoid 429)
    else:
        elements = _fetch_one_bbox(AREAS[area], overpass_query, area, timeout=120)
    print(f"  raw elements total: {len(elements)}", file=sys.stderr)
    seen = set()
    records = []
    for el in elements:
        rec = normalize(el)
        if not rec:
            continue
        # Dedup on (name, lat, lon) — OSM sometimes has node+way pair
        key = (rec["name"].lower(), round(rec["lat"] or 0, 4),
               round(rec["lon"] or 0, 4))
        if key in seen:
            continue
        seen.add(key)
        records.append(rec)
    print(f"  unique records: {len(records)}", file=sys.stderr)
    with_site = [r for r in records if r["website"]]
    print(f"  with website: {len(with_site)}", file=sys.stderr)

    if out_path:
        Path(out_path).write_text(json.dumps(records, ensure_ascii=False, indent=2))
        print(f"  wrote {out_path}", file=sys.stderr)
    return records


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--area", default="svendborg", choices=list(AREAS))
    ap.add_argument("--out", default="output/companies.json")
    args = ap.parse_args()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    discover(args.area, args.out)
