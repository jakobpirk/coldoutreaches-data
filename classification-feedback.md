# Classification feedback (learning loop)

Your corrections to the vision classifier live here. Each correction is a training signal: the overnight `claude -p` prep injects this file into its prompt, so the classifier drifts toward your taste over time. Same idea for `design-preferences.md` and `email-style.md`.

How to use: tell me "lead #N is actually X because …" and I'll add a line below. Format:

```
- #<id> <name>: <my verdict> → <your verdict>. Why: <your reason / rule to learn>.
```

## Corrections

- #4 Antikhjørnet: my verdict "borderline" (image) → **invalid lead**. Why: the image *is* ugly and the visual call was fine, but the scored/screenshotted URL is a **subpage on the antikvitet.net marketplace** (`m.antikvitet.net/apudstiller.asp?kunr=192`), not the business's own site — so there is nothing to redesign. This is a *targeting* error, one layer below the vision call. **Now enforced in code:** `store.is_marketplace()` disqualifies marketplace/directory/social hosts in `qualify()` (caught 8 listings across the scan; qualified 39 → 38).

## Rules distilled so far

- A listing on a **marketplace / directory / social host** (antikvitet.net, dba.dk, facebook.com, instagram.com, …) is **not the business's own site** → invalid target regardless of how dated it looks. *(Enforced: `MARKETPLACE_HOSTS` in store.py — extend as new ones appear.)*
- A high heuristic score with a booking-aggregator / "offers count" page = **parked/hijacked domain**, not a target (e.g. #1 China House — still caught only by the vision layer, since the domain itself is the business's).
- A page that is mostly a **cookie/age modal** should be **blocked**, not judged — flag for re-shot rather than guess.
