# Notion lead board — schema & setup

The Notion board is your one operator interface. It holds **only qualified, non-rejected leads** (the full scan stays in SQLite) so you stay under Notion's free limits. `notion_sync.py` pushes leads in and keeps them updated; it upserts on the **Lead ID** property so re-runs never duplicate.

## Properties

| Property | Type | Source (SQLite) | Notes |
|---|---|---|---|
| Name | Title | `name` | The business |
| Lead ID | Number | `id` | Sync key — don't edit |
| State | Select | `state` | The lifecycle (options = the 11 states) |
| Score | Number | `score` | Heuristic ugliness score |
| Qualified | Checkbox | `qualified` | Passed pre-filter |
| Verdict | Select | `cls_verdict` | Vision call: ugly / borderline / fine (filled overnight) |
| Confidence | Number | `cls_confidence` | 0–1 (filled overnight) |
| Original site | URL | `final_url`/`website` | Their current site |
| Demo site | URL | `demo_url` | Render preview, once built |
| Screenshot | URL | `screenshot_path` | Needs a hosted URL — see note |
| Contact person | Text | `contact_person` | From overnight research |
| Email address | Email | `email` | |
| Phone | Phone | `phone` | |
| City | Text | `city` | |
| Category | Text | `category/subcategory` | |
| Email draft | Text | `email_draft` | Drafted overnight; you approve |
| Reasons | Text | `cls_reasons` | Why the verdict |

`python3 notion_sync.py --print-schema` dumps this as ready-to-use Notion property JSON.

## Views (set up once in the Notion UI — the API can't create views)

- **Needs review** (your evening surface) — Table or Gallery, filter `State is queued OR (Qualified is checked AND State is scored)`, sort Score ↓. This is where you pick keepers.
- **Pipeline** — Board (Kanban) grouped by `State`. Your funnel at a glance.
- **Screenshots** — Gallery, card preview = Screenshot, so you batch-eyeball 10 sites fast.
- **Ready to send** — Table, filter `State is drafted`, showing Email draft inline. Multi-select → set State to a "sent" trigger, which n8n watches.
- **Won / live** — filter `State is won OR live` for active customers.

## Screenshot note

Notion's image preview needs a *hosted URL*, not a local file path. Options for the real build: serve the `output/screenshots/` folder from the VPS (or a cheap bucket) and store that URL in `screenshot_path`, or upload to Notion as a file via the API. For now the column holds the local path; we'll swap it to a URL when the VPS is up.

## How sync fits the daily flow

Overnight: the prep job writes verdict, contact, draft email, etc. into SQLite, then `notion_sync.py` pushes qualified leads to the board. Evening: you work the **Needs review** view. When you change a lead's State in Notion (e.g. approve to send), n8n reads that change and acts — and writes the resulting state back so SQLite and Notion stay in agreement (SQLite is the source of truth; Notion is the working surface).
