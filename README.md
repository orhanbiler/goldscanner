# goldscanner

A small full-stack app that continuously scans [shopgoodwill.com](https://shopgoodwill.com)
for **gold-filled bangle bracelets with enamel**, scores the listing photos with
Claude's vision model, and shows the high-confidence candidates in a **friendly,
mobile-responsive web app** where you can open the item links and favorite the ones
you want to bid on. It can also email you a digest.

## How it works

```
search shopgoodwill ─▶ skip items already seen ─▶ title keyword pre-filter
        │
        ▼
  Claude vision scores each new item's photos (is it a gold-filled enamel bangle?)
        │
        ▼
  matches at/above your confidence threshold are saved to the database
        │
        ├──▶ web UI: browse candidates, open links, ★ favorite / hide  (phone-friendly)
        └──▶ optional email digest (photos, price, end time, link)
```

- **One service does both** — a background thread runs the scanner on a schedule
  while a web server serves the UI. Deploy once on Railway and you get a public URL.
- **Search is public** — no shopgoodwill login or password is needed. The tool
  only reads listings; it never bids or touches your account.
- **A SQLite database** tracks every item it has seen, so each listing is only
  examined once. New listings are anything not yet in that database. Your favorites
  and hidden items live there too.
- **Honest limitation:** whether a bangle's enamel is *actually gold* can't be
  verified from a photo — even experts struggle. This app surfaces strong
  *candidates* and scores how likely each is; you make the final call before bidding.

## The web app

- **Mobile-first** layout (works great on a phone) with three tabs: **New**,
  **★ Favorites**, and **All**.
- Each candidate is a card with the photo, price, bid count, end time, a match
  **confidence bar**, the model's one-line reasoning, a **View ↗** link straight
  to the shopgoodwill listing, and **☆ Favorite** / **Hide** buttons.
- A **Scan now** button triggers an immediate scan; the page also auto-refreshes.

### API (used by the UI)

| Method & path | Purpose |
|---|---|
| `GET /` | The web app |
| `GET /api/items?status=new\|favorite\|all` | List matched candidates |
| `POST /api/items/{id}/status` `{"status":"favorite\|new\|dismissed"}` | Favorite / unfavorite / hide |
| `POST /api/scan` | Trigger a scan now |
| `GET /api/status` | Counts + last-scan info |
| `GET /healthz` | Health check |

## Important: where it runs

This is a long-running service. It needs **open outbound network access** to reach
`buyerapi.shopgoodwill.com` and the Anthropic API. It's designed for
[Railway](https://railway.com) (or any always-on host / your own machine). It will
**not** run inside sandboxes that block shopgoodwill.

## Configuration

All settings come from environment variables. Copy `.env.example` to `.env` for
local runs, or set them as service variables on Railway. Key ones:

| Variable | What it does | Default |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude API key (required when AI scoring is on) | — |
| `GOLDSCANNER_MODEL` | Vision model | `claude-haiku-4-5` |
| `GOLDSCANNER_QUERIES` | Comma-separated search phrases | `gold filled bangle,...` |
| `GOLDSCANNER_TARGET_DESCRIPTION` | Plain-English description of what counts as a match (fed to the model) | see `.env.example` |
| `GOLDSCANNER_MIN_CONFIDENCE` | Only email matches at/above this (0–1) | `0.6` |
| `GOLDSCANNER_USE_AI` | `false` = keyword-only, no AI cost | `true` |
| `GOLDSCANNER_TITLE_KEYWORDS` | Cheap pre-filter before spending an AI call | `bangle,bracelet` |
| `GOLDSCANNER_INTERVAL_SECONDS` | Seconds between scans | `900` (15 min) |
| `GOLDSCANNER_PAGES_PER_QUERY` | Result pages per query (40/page) | `2` |
| `GOLDSCANNER_RUN_ONCE` | Run a single scan and exit | `false` |
| `GOLDSCANNER_DB_PATH` | Where the "seen" DB lives | `goldscanner.db` |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` | Email transport | Gmail-ready |
| `EMAIL_FROM` / `EMAIL_TO` | Digest sender / recipient | — |
| `GOLDSCANNER_EMAIL_ENABLED` | `false` = log matches only | `true` |

### Email via Gmail

Use `smtp.gmail.com` / port `587`, your Gmail address as `SMTP_USER`/`EMAIL_FROM`,
and a [Google **App Password**](https://myaccount.google.com/apppasswords) (not your
normal password) as `SMTP_PASS`. Any SMTP provider (Fastmail, SendGrid, etc.) works too.

## Run locally

```bash
pip install -r requirements.txt
cp .env.example .env          # then fill in your keys
set -a; source .env; set +a   # export the vars

# Run the full app (web UI + background scanner) — open http://localhost:8000
python -m goldscanner.main

# …or just do one scan and exit (no web server), handy for testing:
GOLDSCANNER_RUN_ONCE=true python -m goldscanner.main
```

The web server binds to `$PORT` (default `8000`); Railway sets `PORT` automatically.

Run the tests (no network or API key needed):

```bash
pip install pytest
python -m pytest
```

## Deploy on Railway

1. Push this repo to GitHub and create a new Railway project **from the repo**.
   Railway picks up the `Dockerfile` automatically.
2. In the service **Variables**, set at least `ANTHROPIC_API_KEY`. Optionally set
   the `SMTP_*` vars + `EMAIL_TO` for email digests (or `GOLDSCANNER_EMAIL_ENABLED=false`
   to use the web app only). Adjust `GOLDSCANNER_QUERIES` /
   `GOLDSCANNER_TARGET_DESCRIPTION` to taste.
3. Add a **Volume** mounted at `/data` so the database (seen items + your
   favorites) survives redeploys (the Dockerfile defaults
   `GOLDSCANNER_DB_PATH=/data/goldscanner.db`).
4. Under **Settings → Networking**, click **Generate Domain** to get a public URL.
   `PORT` is provided by Railway automatically — no need to set it.
5. Deploy, then open the generated URL on your phone. The scanner runs every 15
   minutes in the background; matches appear in the **New** tab.

> Don't set email vars and prefer the web app only? Set `GOLDSCANNER_EMAIL_ENABLED=false`
> and skip the `SMTP_*` variables entirely.

Tip: for your very first deploy, the database is empty, so *every* current
matching listing counts as "new" and you may get one large digest. After that you
only hear about genuinely new listings.

## Cost

Scoring uses **Claude Haiku 4.5** ($1 / $5 per 1M input/output tokens) — a few
photos per item is a fraction of a cent each. The cheap title pre-filter keeps the
number of AI calls down. Set `GOLDSCANNER_USE_AI=false` to run keyword-only for free.

## Project layout

```
goldscanner/
  config.py          env-driven settings
  client.py          shopgoodwill search / detail / image download
  store.py           SQLite store (seen items, matches, favorite/hide status)
  vision.py          Claude vision scoring (structured output)
  emailer.py         SMTP digest (plain + HTML)
  scanner.py         one scan cycle
  service.py         wires components + owns the scan loop
  web.py             FastAPI app (UI + JSON API)
  static/index.html  the mobile-responsive web app
  main.py            build from env + run web server & background scanner
tests/               unit + web tests with fakes (no network/API key)
```
