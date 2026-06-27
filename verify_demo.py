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
# Independent evaluator: a DIFFERENT model than the implementer (iterate_demo uses
# EDIT_MODEL=opus), and a separate `claude -p` process with no shared context — it
# never sees the edit/diff, only the rendered screenshots + the requirement. So the
# agent that built the change is not the one grading it.
VERIFY_MODEL = os.environ.get("VERIFY_MODEL", "claude-sonnet-4-6")
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
    prompt = f"""Du er en UAFHÆNGIG kvalitetskontrollør. Du har IKKE selv lavet ændringerne — antag
intet om at de er udført korrekt; vurdér kun kritisk ud fra det, billederne faktisk viser.
Du verificerer en webdesign-iteration for "{lead_name}". Læs screenshot-filerne (desktop + mobil):
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
                               expect_json=True, allowed_tools="Read", timeout=180,
                               model=VERIFY_MODEL)
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


# ---- pre-send quality validation (responsive, burger menu, overflow) --------

def capture_quality(url: str, prefix: str, timeout_ms: int = 35000) -> dict:
    """Render desktop + mobile, measure horizontal overflow, and actually CLICK
    the mobile burger menu to check it opens (a common breakage, e.g. Solbjerggård).
    Returns screenshots + signals for a vision verdict."""
    from playwright.sync_api import sync_playwright
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"shots": [], "console": [], "page_errors": [], "status": None,
           "overflow": {}, "burger": {}}

    def _overflow(page):
        try:
            ov = page.evaluate("() => ({sw: document.documentElement.scrollWidth, iw: window.innerWidth})")
            return ov["sw"] > ov["iw"] + 2
        except Exception:
            return None

    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox"])
        # desktop
        ctx = b.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        page.on("console", lambda m: res["console"].append(f"{m.type}: {m.text}"[:200])
                if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: res["page_errors"].append(str(e)[:200]))
        try:
            r = page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            res["status"] = r.status if r else None
            page.wait_for_timeout(1200)
        except Exception as e:
            res["page_errors"].append(f"goto desktop: {e}"[:200])
        res["overflow"]["desktop"] = _overflow(page)
        d = OUT / f"{prefix}-desktop.png"
        try:
            page.screenshot(path=str(d), full_page=True); res["shots"].append(str(d))
        except Exception as e:
            res["page_errors"].append(f"shot desktop: {e}"[:200])
        ctx.close()
        # mobile
        ctx = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        page = ctx.new_page()
        page.on("pageerror", lambda e: res["page_errors"].append(str(e)[:200]))
        try:
            page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            page.wait_for_timeout(1200)
        except Exception as e:
            res["page_errors"].append(f"goto mobile: {e}"[:200])
        res["overflow"]["mobile"] = _overflow(page)
        m = OUT / f"{prefix}-mobile.png"
        try:
            page.screenshot(path=str(m), full_page=True); res["shots"].append(str(m))
        except Exception as e:
            res["page_errors"].append(f"shot mobile: {e}"[:200])
        # burger menu: count visible nav links, click the toggle, count again
        try:
            vis = ("els => els.filter(e => { const r = e.getBoundingClientRect(); "
                   "return e.offsetParent !== null && r.height > 0 && r.width > 0; }).length")
            before = page.eval_on_selector_all("nav a, header a", vis)
            sel = ("[aria-label*='menu' i], [aria-expanded], button.navbar-toggler, "
                   ".hamburger, .menu-toggle, .burger, [class*='burger'], [class*='hamburger'], "
                   "[class*='menu-toggle'], header button, nav button")
            tog = page.query_selector(sel)
            if tog:
                try:
                    tog.click(timeout=3000)
                except Exception:
                    try:
                        tog.click(timeout=3000, force=True)
                    except Exception:
                        pass
                page.wait_for_timeout(800)
                after = page.eval_on_selector_all("nav a, header a", vis)
                mo = OUT / f"{prefix}-mobile-menu.png"
                try:
                    page.screenshot(path=str(mo), full_page=False); res["shots"].append(str(mo))
                except Exception:
                    pass
                res["burger"] = {"found": True, "links_before": before,
                                 "links_after": after, "works": after > before}
            else:
                res["burger"] = {"found": False, "links_before": before}
        except Exception as e:
            res["burger"] = {"found": False, "error": str(e)[:120]}
        ctx.close()
        b.close()
    return res


def validate(name: str, cap: dict) -> dict:
    if not cap["shots"]:
        return {"ok": False, "issues": ["kunne ikke rendere siden"] + cap["page_errors"],
                "rationale": "Playwright kunne ikke hente siden."}
    refs = "\n".join(f"- {s}" for s in cap["shots"])
    b = cap.get("burger", {})
    prompt = f"""Du er en UAFHÆNGIG kvalitetskontrollør for en NY demo-hjemmeside til "{name}",
FØR den sendes til kunden. Du har ikke bygget siden; vurdér kritisk kun ud fra billederne + signalerne.
Screenshots (desktop, mobil, evt. mobil med menu åbnet):
{refs}

Automatiske signaler:
- HTTP={cap.get('status')}, fejl={(cap.get('console') or [])[:4]} {cap.get('page_errors')[:4]}
- Vandret overflow (elementer/tekst flyder ud): desktop={cap.get('overflow', {}).get('desktop')}, mobil={cap.get('overflow', {}).get('mobile')}
- Burger-menu (mobil): {b}  (hvis found=true men works=false, eller links_after ikke er højere end links_before, er menuen sandsynligvis i stykker)

Vurdér om siden er KLAR til at sende:
1) Ser den professionel og hel ud (intet brudt layout, tomme/placeholder-sektioner)?
2) Tekst-overflow, overlap eller afklippet tekst — især på mobil?
3) Virker burger-menuen på mobil (åbner og viser links)?

Output KUN JSON: {{"ok":true/false,"issues":["konkret hvad er galt"],"rationale":"<kort dansk>"}}
'ok' er KUN true hvis siden er præsentabel uden væsentlige fejl."""
    try:
        _, parsed = obs.claude(CLAUDE_CMD, prompt, label=f"validate:{name}",
                               expect_json=True, allowed_tools="Read", timeout=180,
                               model=VERIFY_MODEL)
        if parsed:
            return parsed
    except Exception as e:
        obs.event("validate_error", error=str(e)[:160])
    # programmatic fallback verdict
    issues = []
    if cap.get("overflow", {}).get("mobile"):
        issues.append("vandret overflow på mobil")
    if b.get("found") and b.get("works") is False:
        issues.append("burger-menu åbner ikke")
    issues += cap.get("page_errors", [])[:3]
    return {"ok": not issues, "issues": issues, "rationale": "programmatisk fallback"}


def validate_demo(url: str, name: str, prefix: str = "validate") -> dict:
    cap = capture_quality(url, prefix)
    v = validate(name, cap)
    v["shots"] = cap["shots"]
    v["burger"] = cap.get("burger")
    v["overflow"] = cap.get("overflow")
    obs.event("validate_done", name=name, ok=bool(v.get("ok")),
              error="; ".join(v.get("issues", []))[:200] if not v.get("ok") else "")
    return v


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("change", nargs="?", default="")
    ap.add_argument("--name", default="demo")
    ap.add_argument("--prefix", default="verify")
    ap.add_argument("--validate", action="store_true", help="pre-send quality check (burger/overflow)")
    a = ap.parse_args()
    import json
    out = validate_demo(a.url, a.name, a.prefix) if a.validate else run(a.url, a.name, a.change, a.prefix)
    print(json.dumps(out, ensure_ascii=False, indent=2))
