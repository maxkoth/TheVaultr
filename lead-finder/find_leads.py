#!/usr/bin/env python3
"""find_leads.py — Find local businesses WITHOUT a website.

Uses the Google Places API (v1, *not* the legacy API) in two stages:

  Stage 1  places:searchText   -> place IDs + basic fields (cheap, paginated)
  Stage 2  places/{id}         -> websiteUri + contact fields (billed per call)

Businesses are kept only when they have no websiteUri, so you can cold-call
them. Stage 2 is cost-gated: you confirm the spend before any Details calls.
"""

import argparse
import csv
import os
import sys
import time
from datetime import datetime

import requests

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv is optional at runtime
    load_dotenv = None


# --- Constants ---------------------------------------------------------------

PLACES_BASE = "https://places.googleapis.com/v1"
TEXT_SEARCH_URL = f"{PLACES_BASE}/places:searchText"
DETAILS_URL = f"{PLACES_BASE}/places/{{place_id}}"

# Field masks — request ONLY what we need so we are not billed for extra SKUs.
SEARCH_FIELD_MASK = (
    "places.id,"
    "places.displayName,"
    "places.formattedAddress,"
    "places.rating,"
    "places.userRatingCount,"
    "nextPageToken"
)
DETAILS_FIELD_MASK = (
    "id,"
    "displayName,"
    "websiteUri,"
    "nationalPhoneNumber,"
    "formattedAddress,"
    "rating,"
    "userRatingCount"
)

# Text Search returns up to 20 results per page.
PAGE_SIZE = 20

# Rough, approximate per-call cost of a Place Details request (USD). This is
# only used to show you an estimate before spending — confirm current pricing
# at https://developers.google.com/maps/billing-and-pricing/pricing
DETAILS_COST_PER_CALL_USD = 0.017

# Retry config for 429 / 5xx responses.
MAX_RETRIES = 5
BACKOFF_BASE_SECONDS = 2

# Counter for billed Details calls so spend is always visible.
_billed_details_calls = 0


# --- HTTP helpers ------------------------------------------------------------

def _request_with_retry(method, url, *, headers, json=None):
    """Issue an HTTP request, retrying on 429/5xx with exponential backoff."""
    attempt = 0
    while True:
        try:
            resp = requests.request(method, url, headers=headers, json=json, timeout=30)
        except requests.RequestException as exc:
            if attempt >= MAX_RETRIES:
                raise
            wait = BACKOFF_BASE_SECONDS * (2 ** attempt)
            print(f"  network error ({exc}); retrying in {wait}s...", file=sys.stderr)
            time.sleep(wait)
            attempt += 1
            continue

        if resp.status_code == 429 or resp.status_code >= 500:
            if attempt >= MAX_RETRIES:
                _fail_on_response(resp)
            wait = BACKOFF_BASE_SECONDS * (2 ** attempt)
            print(
                f"  HTTP {resp.status_code}; retrying in {wait}s "
                f"(attempt {attempt + 1}/{MAX_RETRIES})...",
                file=sys.stderr,
            )
            time.sleep(wait)
            attempt += 1
            continue

        if resp.status_code in (401, 403):
            _fail_on_response(resp, key_hint=True)

        if not resp.ok:
            _fail_on_response(resp)

        return resp


def _fail_on_response(resp, key_hint=False):
    """Print a clear error from a failed response and exit."""
    detail = ""
    try:
        body = resp.json()
        detail = body.get("error", {}).get("message", "") or ""
    except ValueError:
        detail = resp.text[:300]

    msg = f"Places API request failed: HTTP {resp.status_code}"
    if detail:
        msg += f" — {detail}"
    if key_hint:
        msg += (
            "\nThis usually means GOOGLE_PLACES_API_KEY is missing, invalid, "
            "or the Places API (New) is not enabled / not authorized for this "
            "key. See the README for setup steps."
        )
    sys.exit(msg)


# --- Stage 1: Text Search ----------------------------------------------------

def text_search(api_key, query, max_pages):
    """Return a list of basic place dicts for `query`, following pagination."""
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": SEARCH_FIELD_MASK,
    }

    results = []
    page_token = None
    page = 0

    while page < max_pages:
        body = {"textQuery": query, "pageSize": PAGE_SIZE}
        if page_token:
            body["pageToken"] = page_token

        resp = _request_with_retry("POST", TEXT_SEARCH_URL, headers=headers, json=body)
        data = resp.json()

        places = data.get("places", [])
        results.extend(places)
        page += 1
        print(f"  Stage 1 page {page}: {len(places)} results (total {len(results)})")

        page_token = data.get("nextPageToken")
        if not page_token:
            break
        # nextPageToken needs a brief moment to become valid.
        time.sleep(2)

    return results


# --- Stage 2: Place Details --------------------------------------------------

def place_details(api_key, place_id):
    """Fetch full details for a single place. Increments the billed counter."""
    global _billed_details_calls

    headers = {
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": DETAILS_FIELD_MASK,
    }
    url = DETAILS_URL.format(place_id=place_id)
    resp = _request_with_retry("GET", url, headers=headers)

    _billed_details_calls += 1
    return resp.json()


# --- Filtering helpers -------------------------------------------------------

def passes_prefilter(place, min_reviews, min_rating):
    """Quality gate applied to Stage 1 results before paying for Details."""
    rating = place.get("rating", 0) or 0
    reviews = place.get("userRatingCount", 0) or 0
    return reviews >= min_reviews and rating >= min_rating


def has_no_website(details):
    website = details.get("websiteUri")
    return not website or not website.strip()


# --- Cost guard --------------------------------------------------------------

def confirm_spend(num_calls, assume_yes):
    est_cost = num_calls * DETAILS_COST_PER_CALL_USD
    print()
    print("=" * 60)
    print("COST GUARD — Stage 2 (Place Details) is billed per call")
    print(f"  Details calls to make : {num_calls}")
    print(f"  Approx. cost          : ${est_cost:.2f} "
          f"(@ ~${DETAILS_COST_PER_CALL_USD:.3f}/call, estimate only)")
    print("=" * 60)

    if num_calls == 0:
        print("Nothing to do.")
        return False

    if assume_yes:
        print("--yes supplied; proceeding.")
        return True

    try:
        answer = input("Proceed with these billed calls? [y/N]: ").strip().lower()
    except EOFError:
        answer = ""
    return answer in ("y", "yes")


# --- Output ------------------------------------------------------------------

CSV_COLUMNS = [
    "name",
    "phone",
    "address",
    "rating",
    "review_count",
    "place_id",
    "social_only",
]


def write_csv(rows, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(output_dir, f"leads_{stamp}.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path


# --- Key loading -------------------------------------------------------------

def load_api_key():
    if load_dotenv is not None:
        load_dotenv()  # loads .env from cwd if present; no-op otherwise
    key = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()
    if not key:
        sys.exit(
            "ERROR: GOOGLE_PLACES_API_KEY is not set.\n"
            "Set it in your environment or a .env file. See .env.example."
        )
    return key


# --- CLI ---------------------------------------------------------------------

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Find local businesses without a website (Google Places API v1).",
    )
    parser.add_argument("--query", required=True,
                        help='Search query, e.g. "plumbers in Asheville NC".')
    parser.add_argument("--max-results", type=int, default=50,
                        help="Hard cap on Place Details (billed) calls. Default 50.")
    parser.add_argument("--min-reviews", type=int, default=5,
                        help="Skip businesses with fewer reviews. Default 5.")
    parser.add_argument("--min-rating", type=float, default=0.0,
                        help="Skip businesses below this rating. Default 0.")
    parser.add_argument("--max-pages", type=int, default=3,
                        help="Max Text Search pages to fetch (20 each). Default 3.")
    parser.add_argument("--yes", action="store_true",
                        help="Skip the interactive cost-guard confirmation.")
    parser.add_argument("--output-dir", default="./output",
                        help="Directory for the timestamped CSV. Default ./output.")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    api_key = load_api_key()

    print(f'Stage 1: Text Search for "{args.query}"')
    found = text_search(api_key, args.query, args.max_pages)
    print(f"Stage 1 complete: {len(found)} places found.")

    # Quality pre-filter (cheap — uses Stage 1 fields, saves Details spend).
    candidates = [p for p in found if passes_prefilter(p, args.min_reviews, args.min_rating)]
    skipped = len(found) - len(candidates)
    print(f"Pre-filter: {len(candidates)} pass "
          f"(min_reviews={args.min_reviews}, min_rating={args.min_rating}); "
          f"{skipped} skipped.")

    # Hard cap on billed calls.
    if len(candidates) > args.max_results:
        print(f"Capping Details calls at --max-results={args.max_results} "
              f"(from {len(candidates)} candidates).")
        candidates = candidates[:args.max_results]

    if not confirm_spend(len(candidates), args.yes):
        print("Aborted before any billed calls. No spend incurred.")
        return 0

    print(f"\nStage 2: fetching Place Details for {len(candidates)} places...")
    rows = []
    for i, place in enumerate(candidates, start=1):
        place_id = place.get("id")
        if not place_id:
            continue
        details = place_details(api_key, place_id)
        print(f"  [{i}/{len(candidates)}] billed Details call "
              f"(total billed: {_billed_details_calls})")

        if not has_no_website(details):
            continue

        name = (details.get("displayName") or {}).get("text", "")
        rows.append({
            "name": name,
            "phone": details.get("nationalPhoneNumber", ""),
            "address": details.get("formattedAddress", ""),
            "rating": details.get("rating", ""),
            "review_count": details.get("userRatingCount", ""),
            "place_id": details.get("id", place_id),
            # We cannot reliably detect social-only presence via this API,
            # so this stays FALSE; the column is here for your own triage.
            "social_only": "FALSE",
        })

    path = write_csv(rows, args.output_dir)

    print()
    print("-" * 60)
    print(f"SUMMARY: {len(candidates)} businesses checked, "
          f"{len(rows)} with no website.")
    print(f"Billed Place Details calls: {_billed_details_calls} "
          f"(~${_billed_details_calls * DETAILS_COST_PER_CALL_USD:.2f})")
    print(f"CSV written to: {path}")
    print("-" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
