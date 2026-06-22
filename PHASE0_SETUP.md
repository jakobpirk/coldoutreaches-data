# Phase 0 — setup guide

These are the accounts, the server, and the credentials the built code needs in order to run. **They're all yours to create** — I can't make accounts or handle your credentials, so this is the one stretch that's hands-on for you. After each block, I take over and write the code/workflows that use it.

Two golden rules:
- **Never paste a secret into chat.** Put tokens straight into n8n's credential store or the VPS env. I never need to see them.
- Do **Track A first** — it's ~20 minutes and you'll see your real leads land in Notion. Track B (~1–2 h) is the always-on backbone.

---

## Track A — Quick win: your leads in Notion (no server needed)

Goal: see the 38 qualified leads (screenshots, scores, verdicts) on a real board.

1. **Create a Notion account + workspace** — free plan, one user. https://notion.so
2. **Connect Notion to Cowork.** In Claude, add the **Notion connector** and approve access. That's it — once it's connected, *I* create the lead database with all the right columns and populate it from `output/leads.db`. No manual column setup, no token for you to copy.

That's the whole quick win. You'll have the Kanban/gallery/"needs review" board from `NOTION_SCHEMA.md`, filled with real data.

*(Later, for the **automated nightly** sync from the VPS, you'll also make a Notion "internal integration": Settings → Connections → Develop or manage integrations → New integration → copy the `secret_…` token, then open the lead database → ••• → Connect to → your integration. That token goes into n8n. Not needed for the quick win.)*

---

## Track B — The always-on backbone

### B1. GitHub
- Create an account / org (free). https://github.com
- Create one **private repo** named e.g. `coldoutreaches-data` — this holds the SQLite store + state so nightly runs persist. (Customer-site repos get created automatically later.)
- Create a **Personal Access Token** (fine-grained, repo read/write): Settings → Developer settings → Tokens. **Capture it** for n8n.

### B2. A small VPS (~$5/mo)
- Pick one: **Hetzner CX22** (~€4/mo, best value) or **DigitalOcean** / **Hostinger** ($5–6). 
- OS: **Ubuntu 24.04**. Add your SSH key during creation.
- This one box runs n8n + the Python scripts + the Claude CLI + the SQLite file.

### B3. Install the stack on the VPS
SSH in, then (I'll give you exact copy-paste commands once the box exists — roughly):
- Install **Docker**.
- Run **n8n** in Docker (reachable at `http://localhost:5678`, or behind a domain). — https://docs.n8n.io/hosting/installation/docker/
- Install **Python 3** + clone the project repo.
- Install the **Claude Code CLI**.

### B4. Authenticate Claude on the server (the "use my subscription budget" key)
- On your **laptop** (where a browser works), run: `claude setup-token`
- It walks you through login and prints a **1-year OAuth token** (works on your Max plan).
- On the **VPS**, set it: `export CLAUDE_CODE_OAUTH_TOKEN=<token>` (put it in n8n's env / the service config).
- Now `claude -p "…"` on the server runs on your subscription — this is what spends your idle nightly budget. **Capture the token.**

### B5. Render (hosting)
- Create an account, **connect your GitHub**. https://render.com
- Get a **Render API key** (Account Settings → API Keys) so n8n can create static sites + trigger deploys. **Capture it.**
- (Per-customer sites are configured automatically later. Optional now: buy an agency demo domain like `demos.dinbureau.dk`, ~10 €/yr, for staging URLs.)

### B6. Simply.com email
- You already have the mailbox. Grab the settings from Simply's control panel:
  - **SMTP** (send): `smtp.simply.com`, port **587** + your mail username/password.
  - **IMAP** (read replies): `mail.simply.com`, port **143**.
- Check Simply's **"outgoing mail server for scripts"** guidance and any **send-rate limits**.
- Make sure **SPF / DKIM / DMARC** are set on your domain (Simply usually handles hosted mail) so outreach doesn't land in spam. **Capture the mail user + password** for n8n.

---

## Secrets checklist (capture these — into n8n / VPS env, never chat)

| Secret | From | Used by |
|---|---|---|
| Notion integration token + database ID | B-later / Track A note | n8n nightly sync |
| GitHub Personal Access Token | B1 | n8n (create repos, push) |
| `CLAUDE_CODE_OAUTH_TOKEN` | B4 (`claude setup-token`) | `claude -p` overnight prep |
| Render API key | B5 | n8n (create site, deploy) |
| Simply mail user + password | B6 | n8n (send + read email) |

---

## What I do after each block

- **After Track A (Notion connector):** I create and populate the board — you see real leads immediately.
- **After B2–B4 (VPS + n8n + Claude token):** I write the docker-compose, the nightly cron, and the n8n workflows (scan → `claude -p` classify/enrich/draft → Notion sync).
- **After B5 (Render):** I write the scaffold → seed → preview-deploy scripts.
- **After B6 (Simply):** I wire batch send-on-approval and the daily reply-read → state update.

---

## Suggested order & effort

1. **Track A** (~20 min) — Notion + connector → board populated. *Immediate payoff.*
2. **B1 GitHub** (~10 min) and **B6 Simply settings** (~10 min) — quick, no server.
3. **B2–B4 VPS + n8n + Claude token** (~1 h) — the heart of it.
4. **B5 Render** (~15 min).

Do them in that order and tell me when each block is done — I'll wire up the code against it as we go, so you see the system come alive piece by piece rather than in one big bang.
