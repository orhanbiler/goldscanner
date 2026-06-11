# goldscanner

Continuously scans [shopgoodwill.com](https://shopgoodwill.com) for **gold-filled
bangle bracelets with enamel**, scores the listing photos with Claude's vision
model, and emails you a digest of the high-confidence candidates so you can bid.

## How it works

```
search shopgoodwill ─▶ skip items already seen ─▶ title keyword pre-filter
        │
        ▼
  Claude vision scores each new item's photos (is it a gold-filled enamel bangle?)
        │
        ▼
  matches at/above your confidence threshold ─▶ email digest (photos, price, end time, link)
```

- **Search is public** — no shopgoodwill login or password is needed. The tool
  only reads listings; it never bids or touches your account.
- **A SQLite database** tracks every item it has seen, so each listing is only
  examined (and emailed) once. New listings are anything not yet in that database.
- **Honest limitation:** whether a bangle's enamel is *actually gold* can't be
  verified from a photo — even experts struggle. This tool surfaces strong
  *candidates* and scores how likely each is; you make the final call before bidding.

## Important: where it runs

This is a long-running worker. It needs **open outbound network access** to reach
`buyerapi.shopgoodwill.com` and the Anthropic API. It's designed to run on
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
GOLDSCANNER_RUN_ONCE=true python -m goldscanner.main   # one scan, then exit
```

Run the tests (no network or API key needed):

```bash
pip install pytest
python -m pytest
```

## Deploy on Railway

1. Push this repo to GitHub and create a new Railway project **from the repo**.
   Railway picks up the `Dockerfile` automatically.
2. In the service **Variables**, set at least `ANTHROPIC_API_KEY`, the `SMTP_*`
   vars, and `EMAIL_TO`. Adjust `GOLDSCANNER_QUERIES` /
   `GOLDSCANNER_TARGET_DESCRIPTION` to taste.
3. Add a **Volume** mounted at `/data` so the "already seen" database survives
   redeploys (the Dockerfile defaults `GOLDSCANNER_DB_PATH=/data/goldscanner.db`).
4. Deploy. The worker runs continuously, scanning every 15 minutes by default.

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
  config.py    env-driven settings
  client.py    shopgoodwill search / detail / image download
  store.py     SQLite "seen items" store
  vision.py    Claude vision scoring (structured output)
  emailer.py   SMTP digest (plain + HTML)
  scanner.py   one scan cycle
  main.py      build from env + run loop
tests/         unit tests with fakes (no network)
```
