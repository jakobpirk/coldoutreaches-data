"""
deploy.py — turn a scaffolded lead into a live GitHub repo + Render preview.

  python3 deploy.py <lead_id>

Env: GITHUB_TOKEN, GITHUB_ORG, RENDER_API_KEY.
Steps: scaffold -> create GitHub repo -> push -> create Render static site ->
record demo_repo/demo_url and move the lead to 'demo_building'.

Render must have access to your GitHub repos: connect Render <-> GitHub once and
grant it access to *all* repos (so newly created ones are reachable).
"""
from __future__ import annotations
import os, sys, subprocess
import requests
import store, scaffold

GH_TOKEN = os.environ["GITHUB_TOKEN"]
GH_ORG = os.environ.get("GITHUB_ORG", "")
RENDER_KEY = os.environ["RENDER_API_KEY"]
GH = "https://api.github.com"
RENDER = "https://api.render.com/v1"


def _gh():
    return {"Authorization": f"Bearer {GH_TOKEN}", "Accept": "application/vnd.github+json"}


def _rh():
    return {"Authorization": f"Bearer {RENDER_KEY}", "Accept": "application/json",
            "Content-Type": "application/json"}


def create_github_repo(name: str) -> str:
    r = requests.post(f"{GH}/user/repos", headers=_gh(),
                      json={"name": name, "private": True, "auto_init": False})
    if r.status_code == 422:
        print(f"  repo {name} already exists — reusing")
    elif not r.ok:
        raise RuntimeError(f"GitHub repo create {r.status_code}: {r.text[:300]}")
    return f"https://github.com/{GH_ORG}/{name}"


def git_push(repo_dir: str, name: str):
    url = f"https://{GH_TOKEN}@github.com/{GH_ORG}/{name}.git"

    def g(*a, check=True):
        return subprocess.run(["git", "-C", repo_dir, *a], check=check,
                              capture_output=True, text=True)
    if not os.path.isdir(os.path.join(repo_dir, ".git")):
        g("init"); g("branch", "-M", "main")
    g("add", "-A")
    g("commit", "-m", "scaffold", check=False)
    g("remote", "remove", "origin", check=False)
    g("remote", "add", "origin", url)
    g("push", "-u", "origin", "main", "--force")


def render_owner() -> str:
    r = requests.get(f"{RENDER}/owners", headers=_rh())
    r.raise_for_status()
    return r.json()[0]["owner"]["id"]


def create_render_site(name: str, repo_url: str, owner: str) -> str:
    body = {"type": "static_site", "name": name, "ownerId": owner, "repo": repo_url,
            "branch": "main", "autoDeploy": "yes",
            "serviceDetails": {"buildCommand": "", "publishPath": "."}}
    r = requests.post(f"{RENDER}/services", headers=_rh(), json=body)
    if not r.ok:
        raise RuntimeError(f"Render create {r.status_code}: {r.text[:300]}")
    svc = r.json().get("service", r.json())
    return (svc.get("serviceDetails") or {}).get("url") or f"https://{name}.onrender.com"


def deploy(lead_id: int) -> str:
    repo_dir = scaffold.scaffold(lead_id, "output/sites")
    name = os.path.basename(repo_dir) + "-site"
    print(f"[deploy] {name}")
    repo_url = create_github_repo(name)
    git_push(repo_dir, name)
    print(f"[deploy] pushed -> {repo_url}")
    url = create_render_site(name, repo_url, render_owner())
    print(f"[deploy] render -> {url}")
    con = store.connect()
    con.execute("UPDATE leads SET demo_repo=?, demo_url=? WHERE id=?",
                (f"{GH_ORG}/{name}", url, lead_id))
    con.commit()
    try:
        store.move(con, lead_id, "demo_building", note="repo+render created")
    except SystemExit:
        pass
    print(f"[deploy] lead {lead_id} -> demo_building")
    return url


if __name__ == "__main__":
    deploy(int(sys.argv[1]))
