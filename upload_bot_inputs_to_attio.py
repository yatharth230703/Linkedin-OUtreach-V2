"""
Upload bot input rows from a CSV to the Attio "Bot_inputs" custom object.

Usage:
  export ATTIO_API="your_token_here"
  python upload_bot_inputs_to_attio.py bot_inputs_sample.csv
"""

import csv
import os
import sys
import time
import requests
from dotenv import load_dotenv
load_dotenv()

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
ATTIO_API_KEY = os.getenv("ATTIO_API")
BASE_URL = "https://api.attio.com/v2"
HEADERS = {
    "Authorization": f"Bearer {ATTIO_API_KEY}",
    "Content-Type": "application/json",
}

OBJECT_SLUG = "bot_inputs"
MATCHING_ATTRIBUTE = "linkedin_url"

# Attributes: (slug, title, is_unique)
CUSTOM_ATTRIBUTES = [
    ("linkedin_url",     "LinkedIn URL",     True),
    ("lead_manager",     "Lead Manager",     False),
    ("prompt_template",  "Prompt Template",  False),
]

# CSV column -> Attio slug (1:1 for this object)
CSV_TO_SLUG = {
    "linkedin_url":    "linkedin_url",
    "lead_manager":    "lead_manager",
    "prompt_template": "prompt_template",
}


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def api_get(path):
    return requests.get(f"{BASE_URL}{path}", headers=HEADERS)


def api_post(path, payload):
    return requests.post(f"{BASE_URL}{path}", json=payload, headers=HEADERS)


def api_put(path, payload, params=None):
    return requests.put(f"{BASE_URL}{path}", json=payload, headers=HEADERS, params=params)


# ---------------------------------------------------------------------------
# Step 0: Verify object exists
# ---------------------------------------------------------------------------

def verify_object():
    print(f"[0/2] Verifying '{OBJECT_SLUG}' object exists...")
    resp = api_get("/objects")
    resp.raise_for_status()
    slugs = {obj["api_slug"]: obj for obj in resp.json()["data"]}

    if OBJECT_SLUG in slugs:
        print(f"      Found: {slugs[OBJECT_SLUG].get('plural_noun', OBJECT_SLUG)}\n")
        return True

    print(f"      ERROR: Object '{OBJECT_SLUG}' not found.")
    print(f"      Available objects: {', '.join(sorted(slugs.keys()))}")
    return False


# ---------------------------------------------------------------------------
# Step 1: Ensure attributes
# ---------------------------------------------------------------------------

def get_existing_attributes():
    resp = api_get(f"/objects/{OBJECT_SLUG}/attributes")
    resp.raise_for_status()
    return {a["api_slug"] for a in resp.json()["data"]}


def create_attribute(slug, title, is_unique=False):
    payload = {
        "data": {
            "title": title,
            "description": "",
            "api_slug": slug,
            "type": "text",
            "is_required": False,
            "is_unique": is_unique,
            "is_multiselect": False,
            "config": {},
        }
    }
    resp = api_post(f"/objects/{OBJECT_SLUG}/attributes", payload)
    if resp.status_code in (200, 201):
        unique_tag = " (unique)" if is_unique else ""
        print(f"      + Created '{slug}'{unique_tag}")
        return True
    elif resp.status_code == 409:
        print(f"      ~ '{slug}' already exists")
        return True
    else:
        print(f"      ! Failed '{slug}': {resp.status_code} {resp.text[:300]}")
        return False


def ensure_attributes():
    print(f"[1/2] Ensuring custom attributes exist on {OBJECT_SLUG}...")
    existing = get_existing_attributes()
    all_ok = True

    for slug, title, is_unique in CUSTOM_ATTRIBUTES:
        if slug in existing:
            print(f"      ~ '{slug}' exists")
        else:
            if not create_attribute(slug, title, is_unique):
                all_ok = False

    if all_ok:
        print("      All attributes ready.\n")
    else:
        print(f"\n      WARNING: Some attributes failed. Create them manually in Attio.\n")
    return all_ok


# ---------------------------------------------------------------------------
# Step 2: Upload records
# ---------------------------------------------------------------------------

def build_values(row):
    values = {}
    for csv_col, attio_slug in CSV_TO_SLUG.items():
        val = row.get(csv_col, "").strip()
        if val:
            values[attio_slug] = val
    return values


def upsert_record(values):
    url = f"/objects/{OBJECT_SLUG}/records"
    payload = {"data": {"values": values}}
    resp = api_put(url, payload, params={"matching_attribute": MATCHING_ATTRIBUTE})

    if resp.status_code == 429:
        retry_after = int(resp.headers.get("Retry-After", 5))
        print(f"      ... rate-limited, waiting {retry_after}s")
        time.sleep(retry_after)
        resp = api_put(url, payload, params={"matching_attribute": MATCHING_ATTRIBUTE})

    resp.raise_for_status()
    return resp.json()


def upload_csv(csv_path):
    print(f"[2/2] Uploading records from {csv_path}...\n")

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        total, success, failed = 0, 0, 0

        for row in reader:
            total += 1
            linkedin = row.get("linkedin_url", "").strip()
            values = build_values(row)

            if not values.get("linkedin_url"):
                print(f"   !  Row {total}: missing linkedin_url, skipping")
                failed += 1
                continue

            try:
                result = upsert_record(values)
                record_id = result["data"]["id"]["record_id"]
                print(f"   ok Row {total}: {linkedin} -> {record_id}")
                success += 1
            except requests.HTTPError as e:
                print(f"   !! Row {total}: {linkedin}")
                print(f"      {e.response.status_code} {e.response.text[:250]}")
                failed += 1

            time.sleep(0.25)

    print(f"\nDone: {success}/{total} succeeded, {failed} failed.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not ATTIO_API_KEY:
        print("Error: Set ATTIO_API environment variable first.")
        sys.exit(1)

    if len(sys.argv) < 2:
        print("Usage: python upload_bot_inputs_to_attio.py <path_to_csv>")
        sys.exit(1)

    csv_path = sys.argv[1]
    if not os.path.exists(csv_path):
        print(f"Error: File not found: {csv_path}")
        sys.exit(1)

    if not verify_object():
        sys.exit(1)

    ensure_attributes()
    upload_csv(csv_path)


if __name__ == "__main__":
    main()
