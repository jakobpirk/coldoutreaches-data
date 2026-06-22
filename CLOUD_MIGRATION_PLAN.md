# Cloud migration plan — ColdOutreaches

Goal: take the local Cowork pipeline (scan → score → screenshot → redesign → deploy → outreach) off your laptop so the funnel runs on a schedule, you make the decisions from **one interface (Notion)** in a short evening session at your keyboard, and the whole thing leans on the **Max subscription you already pay for** rather than metered API.

This document is the plan. §1–§7 are the reasoning; §8 is the locked spec; §9 is the end-to-end operator flow. The whole document reflects the decisions we settled on — there are no open forks left.

---

## Build status (Phase 1 — underway, before Phase 0)

The deterministic spine is built and tested against the real Svendborg/Sydfyn scan (399 leads, 321 screenshots). None of it needed your accounts.

**Done & verified:**
- `store.py` — SQLite lead store + lifecycle state machine + event log. Dedup, screenshot linking, and legal/illegal transitions all tested. → `output/leads.db`.
- `run_scan.py` — single overnight runner chaining discover→score→screenshot→ingest (the command n8n will call). Smoke-tested.
- `notion_sync.py` + `NOTION_SCHEMA.md` — Notion board schema, view definitions, and upsert sync. Field mapping verified against real data; guarded until Phase 0 creds exist.
- `review_demo.py` → `output/review.html` — in-session vision classification of all 38 qualified leads (a preview of what the overnight `claude -p` step will produce). `classification-feedback.md` seeds the learning loop.

**Pending Phase 0 (your accounts/credentials):** creating the actual Notion board, the VPS + n8n, Simply mail wiring, and the automated `claude -p` prep. Code for these is written or specced; they are config-and-credential steps, not build steps.

**Key finding from the classification pass:** of 38 heuristic-"qualified" leads, only ~7 are clearly strong redesign targets; 14 are actually modern (heuristic false positives), 1 is a parked domain, and 5 were unjudgeable behind cookie/age modals. Vision classification roughly halves the funnel to real targets — and surfaces a screenshot-capture gap (modals).

---

## 1. The decision the architecture hangs on

The Perplexity thread circles a single knot: *something has to invoke Claude to generate the redesigns, and Anthropic's billing isn't built for unattended subscription use.* 

The resolution is to split Claude into two lanes and treat the **design step** differently from everything else, because design is:

- the **most expensive** to run (a bespoke site burns far more tokens than glue work),
- the **most quality-sensitive** (a mediocre auto-demo emailed to a prospect is worse than none — it's your brand),
- and the **most taste-dependent** (it's the part you're good at and want a hand on).

So **design generation stays a human-triggered creative step**: you fire it in the evening from **Claude Code on the web**, which runs in Anthropic's cloud sandboxes on your *interactive* subscription, persists after you close the browser, and finishes overnight. No headless design, no API bill, no ToS-grey proxy for the expensive part.

Everything *around* design — discovery, scoring, the vision "is this ugly" call, business research, content cleanup, writing each design brief, drafting emails, triaging replies — **is automated and runs overnight** via the official **Claude Code CLI (`claude -p`)** logged into your Max account on the VPS. This deliberately spends your otherwise-idle nightly budget. So the cloud *does* call Claude — just never for design.

The net: you wake to a fully-worked queue; your hands only ever touch the *creative* (firing designs), the *irreversible* (sends, go-live, domain), and the *commercial* (payment).

---

## 2. Target architecture

```
   OVERNIGHT (cloud — deterministic scan + cheap claude -p prep)
  ┌─────────────────────────────────────────────────────────┐
  │ discover.py → scorer.py → screenshot → content extract   │
  │   → claude -p: vision-classify, research, clean seed,    │
  │     write design brief, draft outreach email             │
  │   → SQLite lead store; push qualified leads into Notion  │
  │   → finish any design sessions fired the prior evening   │
  └─────────────────────────────────────────────────────────┘
                           │
        EVENING (~2h, you, at the keyboard — Notion is the surface)
                           │  review prepped queue, pick keepers
                           ▼
   ON FIRE (n8n, deterministic — instant, no budget)
  ┌─────────────────────────────────────────────────────────┐
  │ create {client}-site GitHub repo (scaffold, no design)   │
  │   → seed prepped content/photos + CLAUDE.md brief        │
  │   → Render preview deploy → staging URL ready            │
  └─────────────────────────────────────────────────────────┘
                           │
                           ▼
   DESIGN (you fire it; runs in Anthropic's cloud, Max sub)
  ┌─────────────────────────────────────────────────────────┐
  │ open the keepers in parallel Claude Code web sessions    │
  │   → frontend-design skill designs each site BESPOKE      │
  │     (no template — from scratch off the seed + brief)    │
  │   → commit → Render previews update (finish overnight)   │
  └─────────────────────────────────────────────────────────┘
                           │  glance next morning, keep/bin
                           ▼
   OUTREACH (n8n drafts in Notion; you batch-approve; n8n sends)
  ┌─────────────────────────────────────────────────────────┐
  │ draft email (live demo link) shown inline in Notion      │
  │   → you multi-select keepers → flip to Approved          │
  │   → n8n sends via Simply SMTP → status Sent              │
  └─────────────────────────────────────────────────────────┘
                           │  they reply → IMAP read → state update
                           ▼
   CONVERT (semi-manual)
  ┌─────────────────────────────────────────────────────────┐
  │ tweak content → merge to main (= production)             │
  │   → connect customer's domain (DNS: needs them or you)   │
  └─────────────────────────────────────────────────────────┘
```

- **Hosting:** **Render** — one repo per customer, PR previews = staging, `main` = production. Existing Netlify demos (paskram, vinfruen, svendborg_vingaard) stay live as-is; no big-bang migration.
- **Orchestrator:** **n8n, self-hosted on a ~$5/mo VPS** that also runs the Python scripts and the Claude Code CLI. (Not GitHub Actions — n8n fits the event-driven work: send-on-approval, daily inbox read, status changes.)

---

## 3. Every step: where it runs, and whether Claude touches it

| Step | Today | Runs in cloud? | Claude? | Notes |
|---|---|---|---|---|
| Discover (OSM) | `discover.py` | Yes | No | Only needs `requests`. Pure. |
| Score (heuristics) | `scorer.py` | Yes | No | `requests` + `bs4`. Cheap pre-filter. |
| Screenshot | `screenshot.py` (thum.io) | Yes | No | Hosted API; already cloud. Reliability gap → §7. |
| Content extract / clean seed | partial (`incremental_scrape.py`) | Yes | **Yes (`claude -p`)** | Claude tidies messy HTML into a clean seed. |
| Vision "is this ugly?" | new | Yes | **Yes (`claude -p`, overnight)** | Runs only on heuristic survivors. Feeds learning loop. |
| Research / enrich lead | new | Yes | **Yes (`claude -p`, overnight)** | Contact name, what's wrong, pitch angle. |
| Write design brief (`CLAUDE.md`) | new | Yes | **Yes (`claude -p`, overnight)** | So the evening design session starts rich. |
| **Redesign generation** | you, in Cowork | Runs in Anthropic's cloud, **not headless** | **Yes (Claude Code web, evening, parallel)** | Bespoke via `frontend-design` — no template. §1. |
| Repo create + seed | manual now | Yes (n8n, on fire) | No | GitHub API + thin scaffold. Instant, no budget. |
| Deploy (preview/prod) | Netlify CLI | Yes | No | → Render git-based deploys. |
| Draft outreach email | you / Claude | Yes (`claude -p`, overnight) | **Yes** | In your tone; shown in Notion for approval. |
| **Send email** | you | n8n sends on your batch approval | No | Via Simply SMTP. Never auto-sent without approval. §5. |
| Reply triage → state update | manual | Yes (daily, IMAP + `claude -p`) | **Yes** | Classifies replies, updates Notion status. |
| Connect customer domain | n/a | Partly | No | DNS step needs a human. §5. |

The deterministic scripts port almost as-is (~2,600 lines, only `requests` + `bs4`). The genuinely new builds: durable state + Notion board, the overnight `claude -p` prep, the n8n scaffold→Render rail, and the Simply send/read wiring.

---

## 4. Phased rollout

### Phase 0 — Accounts & secrets *(you; I can't do these)*
Account creation, billing, OAuth and credentials are user-only:
- Create/confirm: GitHub account/org, Render account, the **$5 VPS**, a **Notion** workspace, and your **Simply.com** mail credentials.
- Log the Claude Code CLI into your Max account on the VPS (one-time).
- Put all secrets in the **VPS / n8n credential store** — never committed. The current `.netlify-token`-in-a-repo pattern doesn't carry over.

### Phase 1 — Lead store + Notion board + first overnight job *(I build next)*
- Wrap discover→score→screenshot→extract into one entry script.
- **SQLite lead store** (raw scan + full state) with the **lifecycle state machine**:
  `discovered → scored → queued → demo_building → demo_live → drafted → sent → replied → won/lost`.
- Dedup by OSM id + normalized URL; a lead already `sent` never resurfaces.
- **Notion board** (qualified leads only, to stay under free limits): Kanban by state, gallery of screenshots, a "needs review" filter, and the fields in §9.
- First overnight job: **scan + vision-classify + enrich**, writing to both stores — so you watch real budget spent on a real scan.

### Phase 2 — Deploy rail + design brief *(I build the scripts; you wire Render/GitHub once)*
**No design template.** Plumbing only, in three layers:
1. **Scaffold** — empty repo + Render static-site config. Zero markup, zero design opinion.
2. **Seed** — the business's real content/photos, prepped overnight, dropped in as raw material.
3. *(Design happens when you fire it — Phase 3 of the daily flow; nothing here predetermines the look.)*
- n8n action on fire: create `{client}-site`, seed it, add the overnight-written `CLAUDE.md` brief, push, trigger a Render preview.

### Phase 3 — Email: draft, batch-send, reply-read *(I build; you provide Simply creds)*
- Overnight `claude -p` drafts the outreach email per qualified lead → shown inline in Notion.
- You multi-select and flip to **Approved** → n8n sends the batch via **Simply SMTP (`smtp.simply.com:587`)** from your business address.
- Daily **IMAP read (`mail.simply.com:143`)** → `claude -p` classifies replies → Notion status auto-updates. **No send without your batch approval.**

### Phase 4 — Learning loop + extras
- Versioned `design-preferences.md`, `classification-feedback.md`, `email-style.md` injected into every run; a nightly reflection distills your corrections into them.
- Then: smart follow-ups (you still approve sends), before/after pitch images, win-weighted lead ranking.

### Phase 5 — Ticket system *(later; deliberately deferred)*
- Email-to-ticket → ticket DB → AI triage → optional internal GitHub Issue; customers only see email or a branded page. A whole second product — don't build it until the funnel earns.

---

## 5. Where human action is genuinely unavoidable

Not "nice to have a human" — *structurally impossible to automate from here*:

1. **Account creation, billing, credentials** (GitHub, Render, VPS, Notion, Simply) — user-only; I don't create accounts or handle your secrets.
2. **Approving sends** — done in batch in Notion, but it is always your explicit go.
3. **Approving go-to-production** and **connecting a customer's domain** — irreversible / DNS owned by someone else.
4. **Firing the design sessions + final taste pass** — by design (§1).

Everything else runs unattended.

## 6. The psychology problem (you flagged this — it's the real risk)

The tech here is easy. **Autonomous outreach systems don't die on tech; they die on the human-in-the-loop steps that fight how people actually behave.** A plan that ignores this looks great on paper and is abandoned in three weeks. Each behaviour the plan asks of you needs a design answer:

- **The daily review.** Nobody reliably does daily homework. → It's one short **evening session at your keyboard** — a time you're already at the computer — not a chore bolted onto a busy morning. The Notion queue is small (qualified leads only) and pre-worked, so reviewing is glancing, not labour.
- **Reviewing changes on a phone.** Mobile diff-review is miserable and you'll stop. → You judge the **Render live preview** as a page, not a diff. The phone is only for a quick morning glance and tapping approvals.
- **Trusting automation.** People over-trust silent automation and under-trust noisy automation. → You approve *only* the consequential, irreversible actions; the boring 80% runs silently overnight.
- **Letting it send cold emails.** This triggers loss aversion, rightly (reputation, spam, the wrong business). → Sends are **batch-approved by you**, never auto-fired. The psychologically safe choice is also the legally and operationally correct one.
- **Spending effort on leads you don't care about.** Kills motivation. → You only *fire designs* for leads you pick, so effort tracks excitement and budget tracks intent.
- **Over-building first.** The urge to build a portal/ticket system before the funnel earns. → Deferred to Phase 5.

The throughline: **automate the boring and the scary-but-reversible; keep you in the loop only for the creative and the irreversible; make your touchpoints quick and pleasant, concentrated in one evening session.**

## 7. Gaps & risks (self-critique)

- **Subscription billing for the overnight lane.** Today `claude -p` / Agent SDK authenticated with your Max login draws from your rolling subscription limits (the June-15 metering split was *postponed*). We rely on that to spend idle nightly budget — but build so swapping `claude -p` ↔ a metered API key is a **config change**, because Anthropic may reintroduce the split. A heavy night can also exhaust your weekly cap → throttle (cap N leads/night).
- **Design is the one manual step.** Intentional (§1), but it means throughput is bounded by your evening attention. Acceptable, and the overnight prep makes each firing fast.
- **Screenshot reliability** — thum.io chokes on JS-heavy sites and login walls, sometimes the very "broken" ones you target. Mitigation later: a headless Chromium (Playwright) step on the VPS. Keep thum.io for now.
- **Cold-email law** — Danish *markedsføringsloven* §10 restricts unsolicited commercial email; B2B to a general business address advertising relevant services has more room, but it's not a free pass. GDPR applies to scraped contact data. Keep volume low, personal, opt-out-friendly, batch-approved. *(I'm not a lawyer — worth a check before scaling sends.)*
- **State durability & idempotency** — the biggest new engineering need. Without it, scheduled runs re-spam and lose track. Phase 1 is non-negotiable groundwork.
- **Image rights** — reusing a prospect's own photos in their demo is normal for a pitch; flagging it as a conscious choice.
- **Render free-tier limits** — custom-domain and bandwidth limits at the workspace level; fine at low volume, re-check before scaling.
- **Secrets** — all live in the VPS / n8n credential store, nothing committed.

## 8. Locked spec (at a glance)

- **Operator interface:** **Notion** (free, single user) — lead board + SOPs + learning-loop files + notes. Only qualified leads enter Notion; the full scan stays in SQLite.
- **Orchestrator:** **n8n on a ~$5/mo VPS**, which also runs the Python scripts + Claude Code CLI.
- **Hosting:** **Render** — repo per customer, PR previews = staging, `main` = production.
- **Lead store:** **SQLite** in a private data repo.
- **Email:** **Simply.com** — SMTP `smtp.simply.com:587` (send), IMAP `mail.simply.com:143` (read), driven by n8n. Not webmail, not Playwright. Ensure SPF/DKIM/DMARC; check Simply's scripted-sending limits.
- **Claude — design:** **Claude Code web**, you fire it in the evening, runs on your Max subscription. $0 marginal.
- **Claude — overnight prep:** **`claude -p`** on the VPS, your Max login; classify, research, clean seed, write brief, draft email, triage replies. Draws idle subscription budget today; swappable to metered API.
- **Not used:** community proxy (unneeded — n8n shells out to the CLI) and Playwright UI automation (fragile, account risk).

**Daily rhythm:** overnight prep & design-tails → optional 1-min morning glance/approve → ~2h evening session (review, fire designs, batch-approve sends).

**Costs (new spend on top of existing Max):** VPS ~$5/mo; n8n, Notion, Render, GitHub, OSM, thum.io = $0; Simply already paid; Claude design + prep = $0 marginal (subscription). Optional demo domain ~$10/yr. **≈ $5/mo + your Max.** Overflow (if metered split returns or weekly cap hit): API Haiku ~$1/M in, Sonnet $3/$15, Opus $5/$25, or Max 20x.

---

## 9. The operator flow, end to end (your POV)

Legend: **[auto]** system, no you · **[you]** you act · **[approve]** system prepared it, you just confirm.

**Stage A — Setup (once)**
- **[you]** Create GitHub org, Render account, $5 VPS, Notion workspace; install n8n + scripts + Claude Code CLI on the VPS; log the CLI into Max; put Simply + all secrets in n8n's credential store.

**Stage B — Overnight (you asleep)**
- **[auto]** n8n runs discover → score → screenshot → extract.
- **[auto]** `claude -p` vision-classifies, researches/enriches, cleans the seed, writes each design brief, drafts the outreach email.
- **[auto]** Writes SQLite, pushes qualified leads into the Notion board (with screenshot, score, contact, draft email). Finishes any design sessions fired the evening before.

**Stage C — Evening review (you, ~2h, keyboard, Notion)**
- **[you]** Open the "needs review" view; skim the pre-worked queue.
- **[you]** Pick the leads worth a demo.
- **[auto]** Each pick: n8n creates+seeds `{client}-site`, adds the brief, triggers a Render preview.

**Stage D — Fire the designs (you, Claude Code web)**
- **[you]** Open the keepers in parallel Claude Code web sessions; say "go" (brief is in `CLAUDE.md`). They run in Anthropic's cloud and finish overnight.
- **[auto]** Each commit → Render preview updates → lead → `demo_live`.

**Stage E — Glance & select (you, phone or next evening)**
- **[you]** Open each preview as a live page; bin misses, keep winners.

**Stage F — Outreach (system drafts, you batch-approve)**
- **[auto]** Draft email (live demo link) sits inline in Notion.
- **[approve]** Multi-select keepers → flip to **Approved**.
- **[auto]** n8n sends the batch via Simply SMTP → lead → `sent`; never re-enters the queue.

**Stage G — Replies (mostly auto)**
- **[auto]** Daily IMAP read → `claude -p` classifies each reply (interested / not / question / auto-reply) → updates Notion status; surfaces the ones needing you.
- **[you]** On a "yes," mark `won`.

**Stage H — Tweaks after the yes (you, Claude Code)**
- **[you]** Open a session on the repo, make the agreed changes.
- **[auto]** Commit to a branch → PR → Render PR preview = staging the customer reviews.
- **[you]** Iterate against that URL until sign-off.

**Stage I — Payment (you)**
- **[you]** Invoice and collect through your own billing tool — I don't handle money. Gate go-live on payment if you want. Mark `paid`.

**Stage J — Go to production (you approve)**
- **[approve]** Merge the PR to `main` → Render auto-deploys production.

**Stage K — Domain pointing (you + customer)**
- **[you]** Add the customer's domain to the Render production site.
- **[you/customer]** Whoever owns the domain adds the CNAME/A record Render gives you — can't be automated.
- **[auto]** Render issues SSL; once DNS propagates, the domain resolves to production. Mark `live`. Done.

**The shape of it:** the system runs the whole top of the funnel unattended overnight; your hands are only ever on three kinds of moment — the *creative* (firing designs + tweaks), the *irreversible* (approving sends, go-live, domain), and the *commercial* (payment). Everything between is automatic.
