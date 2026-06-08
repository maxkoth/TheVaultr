# Lead Finder — businesses without a website

A small Python CLI that finds local businesses with **no website** using the
**Google Places API (New, v1)** — so you can build a cold-call list.

It works in two stages because the Places **search** endpoint does not return a
website field:

1. **Stage 1 — Text Search** (`places:searchText`): cheap, paginated. Gets
   place IDs plus name, address, rating, and review count.
2. **Stage 2 — Place Details** (`places/{id}`): **billed per call**. Fetches
   `websiteUri` and the phone number. A business is kept only if it has **no
   `websiteUri`**.

Stage 2 is gated behind a **cost guard**: the tool prints how many billed calls
it will make and the rough cost, and waits for your confirmation (or `--yes`).

## Install

```bash
cd lead-finder
python3 -m venv .venv && source .venv/bin/activate   # optional
pip install -r requirements.txt
```

Dependencies are intentionally minimal: `requests` and `python-dotenv`.

## Get a Google Places API key

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create (or select) a project.
3. Enable **billing** for the project (the API requires it).
4. Under **APIs & Services → Library**, search for **"Places API (New)"** and
   click **Enable**. (Make sure it is the *New* one, not the legacy "Places
   API".)
5. Under **APIs & Services → Credentials**, click **Create credentials → API
   key**. Copy the key.
6. (Recommended) Restrict the key to the **Places API (New)**.

Then provide the key to the tool:

```bash
cp .env.example .env
# edit .env and paste your key into GOOGLE_PLACES_API_KEY
```

Or export it directly:

```bash
export GOOGLE_PLACES_API_KEY="your-key"
```

## Usage

```bash
python find_leads.py --query "plumbers in Asheville NC" \
  --max-results 40 --min-reviews 10 --yes
```

### Flags

| Flag             | Default    | Description                                         |
| ---------------- | ---------- | --------------------------------------------------- |
| `--query`        | (required) | Search text, e.g. `"plumbers in Asheville NC"`.     |
| `--max-results`  | `50`       | Hard cap on billed Place Details calls.             |
| `--min-reviews`  | `5`        | Skip businesses with fewer reviews.                 |
| `--min-rating`   | `0`        | Skip businesses below this rating.                  |
| `--max-pages`    | `3`        | Max Text Search pages to fetch (20 results each).   |
| `--yes`          | off        | Skip the interactive cost-guard prompt.             |
| `--output-dir`   | `./output` | Where the timestamped CSV is written.               |

## Output

A timestamped CSV is written to `./output/leads_YYYYMMDD_HHMMSS.csv` with columns:

```
name, phone, address, rating, review_count, place_id, social_only
```

- `social_only` is always `FALSE` — this API can't reliably tell whether a
  business has only social media, so the column is left for your own triage.

At the end you get a summary like:

```
SUMMARY: 40 businesses checked, 12 with no website.
Billed Place Details calls: 40 (~$0.68)
```

## ⚠️ Cost

Stage 2 (Place Details) is **billed per request** by Google. The tool always
prints an estimate before spending and logs a running billed-call count. The
`~$0.017/call` figure is a rough estimate only — confirm current pricing on the
[Google Maps Platform pricing page](https://developers.google.com/maps/billing-and-pricing/pricing).
The pre-filter (`--min-reviews` / `--min-rating`) and `--max-results` are there
to keep your spend down by reducing how many Details calls are made.

## Notes

- The API key is read from `GOOGLE_PLACES_API_KEY` (env var or `.env`). It is
  never hardcoded, and `.env` is gitignored.
- The tool retries automatically on `429`/`5xx` with exponential backoff and
  fails fast with a clear message if the key is missing or invalid.
