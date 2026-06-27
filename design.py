"""
design.py — auto-design scaffolded sites on the VPS via `claude -p` (your Max
subscription), using the bundled frontend-design skill.

  python3 design.py --limit 2          # design up to 2 'demo_building' leads

HEAVY: building a whole site is a long agentic session and burns your weekly
Claude budget — keep --limit / DESIGN_LIMIT small. Sandboxed to the customer
repo (Read/Write/Edit/WebFetch only, no Bash); produces a STAGING preview, never
production. You review the previews and bin the misses before any outreach.
"""
from __future__ import annotations
import os, sys, subprocess, argparse, re, pathlib
import store

CLAUDE_CMD = os.environ.get("CLAUDE_CMD", "claude")
# Tools the design agent may use — enough to read the brief, write the site, and
# fetch the customer's existing content. Deliberately NO Bash.
DESIGN_TOOLS = os.environ.get("DESIGN_TOOLS", "Read Edit Write WebFetch")

PROMPT = (
    "Design and build this business's website now. Read CLAUDE.md and seed.json "
    "in this folder for the brief, contact details and content. Use the "
    "frontend-design skill. IMPORTANT: this is a re-skin of THEIR content, not a "
    "rewrite — fetch their current site (URL in the brief), reuse their real text, "
    "their real images, and their page structure; recreate their multiple pages if "
    "they have them. Don't invent copy or swap in stock photos unless they have "
    "none. Write the finished static site into this folder, replacing the "
    "placeholder index.html (plus CSS/JS/asset/extra pages as needed). All copy in "
    "Danish. The owner should recognise it as their own site, just far better "
    "designed. Do not run git or shell commands — only create/edit files.\n\n"
    "HARD REQUIREMENTS (the demo is served over HTTPS and gets auto-validated):\n"
    "- Every asset URL (img src, background-image, link, script) MUST be https:// "
    "— NEVER http://, or the browser blocks it (mixed content) and the section goes "
    "blank. If an image only exists on http and https 404s, use a tasteful "
    "CSS/gradient background or omit the image — never reference one that fails.\n"
    "- NO empty or placeholder sections. Every section must have real, visible "
    "content. If you lack content or a working image for a section, REMOVE that "
    "section rather than leaving a blank area.\n"
    "- The mobile burger menu MUST open and reveal the nav links when tapped — "
    "verify the toggle logic works, don't just style it.\n"
    "- No horizontal overflow on mobile; text must not overlap or get clipped."
)

ASSET_EXT = (".html", ".htm", ".css", ".js")


def harden(repo_dir: str) -> int:
    """Deterministic post-process: rewrite http:// -> https:// in the generated
    files so a forgotten http asset can't blank out a section as mixed content.
    Returns the number of files changed."""
    changed = 0
    for p in pathlib.Path(repo_dir).rglob("*"):
        if p.suffix.lower() not in ASSET_EXT or ".git" in p.parts:
            continue
        try:
            txt = p.read_text(encoding="utf-8")
        except Exception:
            continue
        new = re.sub(r"http://", "https://", txt)
        if new != txt:
            p.write_text(new, encoding="utf-8")
            changed += 1
    return changed


def design_one(repo_dir: str) -> str:
    r = subprocess.run([CLAUDE_CMD, "-p", "--allowedTools", DESIGN_TOOLS],
                       input=PROMPT, cwd=repo_dir, capture_output=True,
                       text=True, timeout=1800)
    if r.returncode != 0:
        raise RuntimeError(f"claude -p failed: {r.stderr[:400]}")
    return r.stdout.strip()


def git_push(repo_dir: str):
    for a in (["add", "-A"], ["commit", "-m", "auto-design"], ["push"]):
        subprocess.run(["git", "-C", repo_dir, *a], capture_output=True, text=True)


def run(limit: int):
    con = store.connect()
    rows = con.execute("SELECT id, name, demo_repo, demo_url FROM leads "
                       "WHERE state='demo_building' ORDER BY score DESC").fetchall()
    n = 0
    for row in rows:
        if limit and n >= limit:
            break
        slug = (row["demo_repo"] or "").split("/")[-1].removesuffix("-site")
        repo_dir = os.path.join("output/sites", slug)
        if not os.path.isdir(repo_dir):
            print(f"  [design] #{row['id']} no repo dir {repo_dir} — skip")
            continue
        print(f"[design] #{row['id']} {row['name']} (this takes a while) ...")
        try:
            design_one(repo_dir)
            hc = harden(repo_dir)
            if hc:
                print(f"  hardened {hc} file(s): http:// -> https://")
            git_push(repo_dir)
            store.move(con, row["id"], "demo_live", note="auto-designed")
            n += 1
            print(f"  -> demo_live: {row['demo_url']}")
        except Exception as e:
            print(f"  [design] #{row['id']} FAILED: {e}")
    print(f"[design] designed {n} site(s)")


def harden_all(sites_dir="output/sites"):
    """Retro-fix existing demo repos: rewrite http:// -> https:// and push (the
    preview redeploys). Cheap, no Claude — clears mixed-content blanks in bulk."""
    base = pathlib.Path(sites_dir)
    pushed = 0
    for d in sorted(base.iterdir()) if base.exists() else []:
        if not (d / ".git").exists():
            continue
        c = harden(str(d))
        if not c:
            continue
        subprocess.run(["git", "-C", str(d), "add", "-A"], capture_output=True, text=True)
        r = subprocess.run(["git", "-C", str(d), "commit", "-m", "harden: https assets"],
                           capture_output=True, text=True)
        if "nothing to commit" in (r.stdout + r.stderr):
            continue
        subprocess.run(["git", "-C", str(d), "push", "origin", "main"], capture_output=True, text=True)
        pushed += 1
        print(f"  hardened+pushed {d.name} ({c} file(s))")
    print(f"[harden-all] {pushed} repo(s) updated")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=int(os.environ.get("DESIGN_LIMIT", "2")))
    ap.add_argument("--harden-all", action="store_true",
                    help="rewrite http->https in all existing demo repos and push")
    a = ap.parse_args()
    if a.harden_all:
        harden_all()
    else:
        run(a.limit)
