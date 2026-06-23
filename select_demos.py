"""
Auto-select the top redesign targets and build their demos (deploy + design),
instead of you hand-picking. Selection = qualified leads the classifier rated
`ugly`/`borderline` (which is itself steered by the Scoring guidance page),
highest score first. Throttle hard — each demo is a full site build.

  python3 select_demos.py --limit 2

Called by run_nightly.sh when DEMO_LIMIT > 0.
"""
import os, argparse
import store, deploy, design


def run(limit: int):
    con = store.connect()
    rows = con.execute(
        "SELECT id, name FROM leads WHERE qualified=1 "
        "AND state IN ('scored','queued') AND cls_verdict IN ('ugly','borderline') "
        "ORDER BY score DESC LIMIT ?", (limit,)).fetchall()
    if not rows:
        print("[select] no eligible leads")
        return
    print(f"[select] building demos for: {', '.join(r['name'] for r in rows)}")
    for r in rows:
        try:
            deploy.deploy(r["id"])          # -> demo_building (repo + Render)
        except Exception as e:
            print(f"[select] deploy #{r['id']} failed: {e}")
    design.run(limit)                       # designs all demo_building leads


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=int(os.environ.get("DEMO_LIMIT", "2")))
    a = ap.parse_args()
    run(a.limit)
