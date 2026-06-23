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
import os, sys, subprocess, argparse
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
    "designed. Do not run git or shell commands — only create/edit files."
)


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
            git_push(repo_dir)
            store.move(con, row["id"], "demo_live", note="auto-designed")
            n += 1
            print(f"  -> demo_live: {row['demo_url']}")
        except Exception as e:
            print(f"  [design] #{row['id']} FAILED: {e}")
    print(f"[design] designed {n} site(s)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=int(os.environ.get("DESIGN_LIMIT", "2")))
    a = ap.parse_args()
    run(a.limit)
