"""
Backfill lead_manager and prompt_template on all leads_sources records
that are currently missing these fields.

Usage:
  python backfill_leads_sources.py
"""

import os
import sys
import json
import time
import requests
from dotenv import load_dotenv

load_dotenv()

ATTIO_API_KEY = os.getenv("ATTIO_API")
BASE_URL = "https://api.attio.com/v2"
HEADERS = {
    "Authorization": f"Bearer {ATTIO_API_KEY}",
    "Content-Type": "application/json",
}

OBJECT_SLUG = "leads_sources"
LEAD_MANAGER = "yatharth bisht"

# Load prompt_template_1.json as a string
TEMPLATE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "Linkedin_cloud_bot_attio",
    "prompt_template_1.json",
)

with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
    PROMPT_TEMPLATE_STR = json.dumps(json.load(f))


def query_all_records():
    """Fetch all leads_sources records, paginating as needed."""
    all_records = []
    offset = None

    while True:
        payload = {"limit": 50}
        if offset:
            payload["offset"] = offset

        resp = requests.post(
            f"{BASE_URL}/objects/{OBJECT_SLUG}/records/query",
            json=payload,
            headers=HEADERS,
        )

        if resp.status_code == 429:
            retry = int(resp.headers.get("Retry-After", 5))
            print(f"  Rate-limited, waiting {retry}s...")
            time.sleep(retry)
            continue

        resp.raise_for_status()
        body = resp.json()
        data = body.get("data", [])
        all_records.extend(data)

        offset = body.get("next_cursor")
        if not offset or len(data) == 0:
            break

    return all_records


def extract_value(values, slug):
    entries = values.get(slug, [])
    if not entries:
        return ""
    entry = entries[0]
    if isinstance(entry, dict):
        return entry.get("value", "")
    return str(entry)


def patch_record(record_id, values):
    payload = {"data": {"values": values}}
    resp = requests.patch(
        f"{BASE_URL}/objects/{OBJECT_SLUG}/records/{record_id}",
        json=payload,
        headers=HEADERS,
    )
    if resp.status_code == 429:
        retry = int(resp.headers.get("Retry-After", 5))
        print(f"  Rate-limited, waiting {retry}s...")
        time.sleep(retry)
        resp = requests.patch(
            f"{BASE_URL}/objects/{OBJECT_SLUG}/records/{record_id}",
            json=payload,
            headers=HEADERS,
        )
    return resp


def main():
    if not ATTIO_API_KEY:
        print("Error: Set ATTIO_API environment variable first.")
        sys.exit(1)

    print(f"Fetching all {OBJECT_SLUG} records...")
    records = query_all_records()
    print(f"Found {len(records)} records.\n")

    updated = 0
    skipped = 0

    for record in records:
        record_id = record["id"]["record_id"]
        values = record.get("values", {})
        full_name = extract_value(values, "full_name")
        current_manager = extract_value(values, "lead_manager").strip()
        current_template = extract_value(values, "prompt_template").strip()

        needs_update = {}

        if not current_manager:
            needs_update["lead_manager"] = LEAD_MANAGER

        if not current_template:
            needs_update["prompt_template"] = PROMPT_TEMPLATE_STR

        if not needs_update:
            print(f"  skip  {full_name} — already has both fields")
            skipped += 1
            continue

        resp = patch_record(record_id, needs_update)

        if resp.status_code in (200, 201):
            fields = ", ".join(needs_update.keys())
            print(f"  ok    {full_name} — set {fields}")
            updated += 1
        else:
            print(f"  FAIL  {full_name} — {resp.status_code}: {resp.text[:200]}")

        time.sleep(0.25)

    print(f"\nDone: {updated} updated, {skipped} skipped.")


if __name__ == "__main__":
    main()
