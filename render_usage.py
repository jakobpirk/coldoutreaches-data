"""
Render build-minute usage this month — summed from each deploy's duration across
all services, so you get a real heads-up before the free build-pipeline allotment
runs out (rather than a guess). Logged via obs; run in the nightly pipeline.

    python3 render_usage.py
Env: RENDER_API_KEY, RENDER_FREE_BUILD_MIN (default 500).
"""
import os, datetime, requests, obs

RENDER = "https://api.render.com/v1"
H = {"Authorization": f"Bearer {os.environ['RENDER_API_KEY']}", "Accept": "application/json"}
FREE_MIN = int(os.environ.get("RENDER_FREE_BUILD_MIN", "500"))


def _parse(t):
    return datetime.datetime.fromisoformat(t.replace("Z", "+00:00")) if t else None


def _services():
    out, cursor = [], None
    while True:
        params = {"limit": 100}
        if cursor:
            params["cursor"] = cursor
        r = requests.get(f"{RENDER}/services", headers=H, params=params, timeout=30)
        if not r.ok:
            break
        d = r.json()
        out += [x["service"] for x in d]
        if len(d) < 100:
            break
        cursor = d[-1].get("cursor")
    return out


def run():
    now = datetime.datetime.now(datetime.timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    svcs = _services()
    total_sec = deploys = 0
    for s in svcs:
        cursor = None
        while True:
            params = {"limit": 50}
            if cursor:
                params["cursor"] = cursor
            r = requests.get(f"{RENDER}/services/{s['id']}/deploys", headers=H,
                             params=params, timeout=30)
            if not r.ok:
                break
            d = r.json()
            stop = False
            for x in d:
                dep = x["deploy"]
                created = _parse(dep.get("createdAt"))
                finished = _parse(dep.get("finishedAt") or dep.get("updatedAt"))
                if not created:
                    continue
                if created < month_start:
                    stop = True
                    continue
                if finished and finished > created:
                    total_sec += (finished - created).total_seconds()
                    deploys += 1
            if stop or len(d) < 50:
                break
            cursor = d[-1].get("cursor")
    mins = total_sec / 60
    pct = (mins / FREE_MIN * 100) if FREE_MIN else 0
    avg = (mins / deploys) if deploys else 0
    obs.event("render_usage", name="build_minutes",
              deploys=deploys, minutes=round(mins, 1), pct_of_free=round(pct))
    print(f"[render] {len(svcs)} services · {deploys} deploys this month · "
          f"~{mins:.0f} build-min used (~{avg:.1f} min/deploy) · {pct:.0f}% of free {FREE_MIN}")
    if pct >= 80:
        print(f"[render] ⚠️ over 80% of free build minutes — consider a paid plan")
    return {"deploys": deploys, "minutes": mins, "avg": avg, "pct": pct}


if __name__ == "__main__":
    run()
