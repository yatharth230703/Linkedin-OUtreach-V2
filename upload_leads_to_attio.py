"""
Upload leads from a CSV (matching the Postgres `leads` table schema) to Attio.

Targets the custom "Leads_sources" object (Leads_tally view).

Prerequisites:
  1. A custom object called "Leads_sources" must exist in Attio.
  2. Generate an API token at https://app.attio.com → Settings → Developers → API Keys
     with scopes: record_permission:read-write, object_configuration:read-write
  3. pip install requests python-dotenv

Usage:
  export ATTIO_API="your_token_here"
  python upload_leads_to_attio.py leads.csv
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

OBJECT_SLUG = "leads_sources"
MATCHING_ATTRIBUTE = "linkedin_url"

# Attributes to ensure on the custom object: (slug, title, is_unique)
CUSTOM_ATTRIBUTES = [
    ("linkedin_url",             "LinkedIn URL",          True),
    ("full_name",                "Full Name",             False),
    ("headline",                 "Headline",              False),
    ("about_section",            "About Section",         False),
    ("experience_text",          "Experience Text",       False),
    ("lead_status",              "Lead Status",           False),
    ("connection_status",        "Connection Status",     False),
    ("message_1_draft",          "Message 1 Draft",       False),
    ("message_2_draft",          "Message 2 Draft",       False),
    ("message_3_draft",          "Message 3 Draft",       False),
    ("message_4_draft",          "Message 4 Draft",       False),
    ("message_5_draft",          "Message 5 Draft",       False),
    ("profile_posts",            "Profile Posts",         False),
    ("lead_created_at",          "Lead Created At",       False),
    ("lead_last_scraped_at",     "Lead Last Scraped At",  False),
    ("lead_last_contacted_at",   "Lead Last Contacted At",False),
]

# CSV column -> Attio slug mapping
CSV_TO_SLUG = {
    "linkedin_url":      "linkedin_url",
    "full_name":         "full_name",
    "headline":          "headline",
    "about_section":     "about_section",
    "experience_text":   "experience_text",
    "status":            "lead_status",
    "connection_status": "connection_status",
    "message_1_draft":   "message_1_draft",
    "message_2_draft":   "message_2_draft",
    "message_3_draft":   "message_3_draft",
    "message_4_draft":   "message_4_draft",
    "message_5_draft":   "message_5_draft",
    "profile_posts":     "profile_posts",
    "created_at":        "lead_created_at",
    "last_scraped_at":   "lead_last_scraped_at",
    "last_contacted_at": "lead_last_contacted_at",
}

SKIP_COLUMNS = {"id"}


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
# Step 0: Verify the custom object exists
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
    print(f"      Check your Attio workspace and update OBJECT_SLUG if needed.\n")
    return False


# ---------------------------------------------------------------------------
# Step 1: Ensure custom attributes exist
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

    if not all_ok:
        print("\n      WARNING: Some attributes failed to create.")
        print(f"      Create them manually: Workspace Settings > Objects > {OBJECT_SLUG} > Attributes")
        print("      Then re-run this script.\n")
    else:
        print("      All attributes ready.\n")
    return all_ok


# ---------------------------------------------------------------------------
# Step 2: Upload records (using PUT upsert)
# ---------------------------------------------------------------------------

def build_values(row):
    values = {}
    for csv_col, attio_slug in CSV_TO_SLUG.items():
        val = row.get(csv_col, "").strip()
        if val:
            values[attio_slug] = val
    return values


def upsert_record(values):
    """
    PUT /v2/objects/{slug}/records?matching_attribute=linkedin_url
    Attio handles create-or-update in a single call.
    """
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
                name = row.get("full_name", "unknown").strip()
                print(f"   ok Row {total}: {name} -> {record_id}")
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
        print("  export ATTIO_API='your_token_here'")
        sys.exit(1)

    if len(sys.argv) < 2:
        print("Usage: python upload_leads_to_attio.py <path_to_csv>")
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
