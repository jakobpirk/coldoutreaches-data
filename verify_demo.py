"""
Playwright verification of a demo after an iteration. Renders the (re)deployed
demo in a real browser at desktop + mobile, captures full-page screenshots and
any console/page errors, then asks Claude (vision) two things:
  1. are the customer's requested changes visibly implemented?
  2. is anything obviously broken (blank page, broken layout, errors, missing img)?

Returns a verdict dict {meets, broken, issues[], rationale} — logged via obs, so
we have proof an iteration actually did what was asked and didn't break the rest.

    python3 verify_demo.py <url> "<change text>" [--name X]

Env: CLAUDE_CMD. Needs `playwright` + chromium installed.
"""
from __future__ import annotations
import os, sys, argparse, pathlib
import obs

CLAUDE_CMD = os.environ.get("CLAUDE_CMD", "claude")
VIEWPORTS = {"desktop": (1280, 900), "mobile": (390, 844)}
OUT = pathlib.Path("output/verify")


def capture(url: str, prefix: str, timeout_ms: int = 35000) -> dict:
    from playwright.sync_api import sync_playwright
    OUT.mkdir(parents=True, exist_ok=True)
    shots, console, page_errors, status = [], [], [], None
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox"])
        for vp, (w, h) in VIEWPORTS.items():
            ctx = b.new_context(viewport={"width": w, "height": h})
            page = ctx.new_page()
            page.on("console", lambda m: console.append(f"{m.type}: {m.text}"[:200])
                    if m.type in ("error", "warning") else None)
            page.on("pageerror", lambda e: page_errors.append(str(e)[:200]))
            try:
                resp = page.goto(url, wait_until="networkidle", timeout=timeout_ms)
                status = resp.status if resp else status
                page.wait_for_timeout(1500)
            except Exception as e:
                page_errors.append(f"goto {vp}: {e}"[:200])
            path = OUT / f"{prefix}-{vp}.png"
            try:
                page.screenshot(path=str(path), full_page=True)
                shots.append(str(path))
            except Exception as e:
                page_errors.append(f"shot {vp}: {e}"[:200])
            ctx.close()
        b.close()
    return {"status": status, "console": console[:30],
            "page_errors": page_errors[:20], "shots": shots}


def verify(lead_name: str, change_text: str, cap: dict) -> dict:
    if not cap["shots"]:
        return {"meets": False, "broken": True,
                "issues": ["ingen screenshots — siden kunne ikke renderes"] + cap["page_errors"],
                "rationale": "Playwright kunne ikke hente siden."}
    refs = "\n".join(f"- {s}" for s in cap["shots"])
    prompt = f"""Du verificerer en webdesign-iteration for "{lead_name}". Læs screenshot-filerne (desktop + mobil):
{refs}

Kundens ønskede ændringer, som SKULLE være implementeret nu:
\"\"\"{(change_text or '(ingen tekst)')[:1500]}\"\"\"

Browser-signaler: HTTP-status={cap.get('status')}, konsol-fejl={cap.get('console')[:5]}, side-fejl={cap.get('page_errors')[:5]}.

Vurdér ud fra billederne:
1) Er de ønskede ændringer synligt implementeret?
2) Er noget åbenlyst gået i stykker (tom/hvid side, brudt layout, manglende billeder, synlige fejl)?

Output KUN JSON: {{"meets":true/false,"broken":true/false,"issues":["konkret hvad mangler/er brudt"],"rationale":"<kort dansk begrundelse>"}}"""
    try:
        _, parsed = obs.claude(CLAUDE_CMD, prompt, label=f"verify:{lead_name}",
                               expect_json=True, allowed_tools="Read", timeout=180)
        if parsed:
            return parsed
    except Exception as e:
        obs.event("verify_error", error=str(e)[:160])
    return {"meets": None, "broken": bool(cap.get("page_errors")),
            "issues": cap.get("page_errors", []), "rationale": "vision-verifikation fejlede"}


def run(url: str, lead_name: str, change_text: str, prefix: str = "verify") -> dict:
    cap = capture(url, prefix)
    v = verify(lead_name, change_text, cap)
    v["shots"] = cap["shots"]
    v["status"] = cap["status"]
    obs.event("verify_done", name=lead_name,
              ok=bool(v.get("meets") and not v.get("broken")),
              error="; ".join(v.get("issues", []))[:200] if not v.get("meets") else "")
    return v


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("change", nargs="?", default="")
    ap.add_argument("--name", default="demo")
    ap.add_argument("--prefix", default="verify")
    a = ap.parse_args()
    import json
    print(json.dumps(run(a.url, a.name, a.change, a.prefix), ensure_ascii=False, indent=2))
