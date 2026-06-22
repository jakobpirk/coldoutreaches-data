# Infra setup — run the pipeline on the VPS

What runs where (deliberate split):
- **Host cron → the Python/Claude pipeline** (`run_nightly.sh`: scan → `claude -p` prep → Notion sync). It lives on the host because it needs Python + the Claude CLI.
- **n8n (Docker) → the email I/O** (send-on-approval, daily reply-read). These use n8n's native Notion / SMTP / IMAP nodes — exactly what n8n is best at.

You only ever open n8n through an SSH tunnel; it's never exposed publicly.

---

## 1. Provision (once)

```bash
ssh root@<vps-ip>
# copy the project to /opt/coldoutreaches (git clone your private repo, or scp)
bash /opt/coldoutreaches/infra/setup-vps.sh https://github.com/<org>/coldoutreaches-data.git
cp infra/.env.example infra/.env && nano infra/.env      # paste your secrets
docker compose -f infra/docker-compose.yml up -d         # start n8n
```

Authenticate Claude on the box (one of):
- `claude` then log in interactively, **or**
- put `CLAUDE_CODE_OAUTH_TOKEN=...` (from `claude setup-token` on your laptop) into `/etc/environment` and re-login.

Verify the pipeline by hand once:
```bash
cd /opt/coldoutreaches
LEADS_DB=data/leads.db python3 run_scan.py --area svendborg
python3 prep.py --limit 3        # should classify/enrich a few leads
python3 notion_sync.py           # rows appear on the board
```

## 2. Schedule the nightly run (host cron)

```bash
crontab -e
# 02:30 every night, Copenhagen time:
30 2 * * *  cd /opt/coldoutreaches && /usr/bin/bash run_nightly.sh >> data/nightly.log 2>&1
```

That's the autonomous overnight engine. Tune `SCAN_AREA` / `PREP_LIMIT` in `.env`.

---

## 3. n8n email workflows (build in the UI)

Open n8n via the tunnel: `ssh -L 5678:localhost:5678 root@<vps-ip>` → http://localhost:5678 (create the owner account on first visit). Add credentials once under **Credentials**: a **Notion API** cred (your `NOTION_TOKEN`), an **SMTP** cred (Simply: host `smtp.simply.com`, port 587, your mailbox user/pass), and an **IMAP** cred (host `mail.simply.com`, port 143).

I'm giving these as build-recipes rather than import-JSON on purpose — n8n's exported JSON is brittle across versions, and the credentials must be wired in the UI anyway.

### Workflow A — Send on approval
Goal: when you flip a lead to **Approved** in Notion, send its drafted email from Simply and mark it **sent**.

1. **Schedule Trigger** — every 10 minutes.
2. **Notion → Get Many Database Pages** — database = ColdOutreaches Leads; filter `State is drafted` AND `Approved` (add an "Approved" checkbox column, or reuse a `State = approved` option). 
3. **Loop / Split In Batches** over the results.
4. **Send Email (SMTP)** — From `hej@wilbrandtworks.dk`; To = the lead's `Email address`; Subject/Body parsed from the `Email draft` field (first line `Subject:`, rest = body).
5. **Notion → Update Page** — set `State = sent`.

> Keep it human-gated: *you* set Approved in Notion; n8n only sends what you approved.

### Workflow B — Reply read → state update
Goal: detect replies and move the lead to **replied** (and surface it).

1. **IMAP Email Trigger** — Simply inbox; on new email.
2. **Code/Filter** — match the sender against open leads' `Email address` (or match the thread).
3. *(optional)* **HTTP Request → Claude** or an AI node to classify the reply (interested / not / question).
4. **Notion → Update Page** — set `State = replied`; optionally write a one-line summary.

---

## 4. Keeping SQLite + Notion in agreement
`run_nightly.sh` commits `data/leads.db` to your private data repo each night (state persists across runs / reboots). Notion is the working surface; SQLite is the source of truth. When you change a lead's State in Notion (e.g. Approved), Workflow A writes the resulting state back, and the next sync reconciles.

## 5. Later: serve screenshots
To show screenshots in the Notion gallery, serve `output/screenshots/` over HTTP (a tiny static server or bucket) and store that URL in `screenshot_path`. Until then the board links the original site instead.
