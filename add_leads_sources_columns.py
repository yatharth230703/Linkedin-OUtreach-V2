"""
Add lead_manager and prompt_template attributes to the Leads_sources object.

Usage:
  export ATTIO_API="your_token_here"
  python add_leads_sources_columns.py
"""

import os
import sys
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

NEW_ATTRIBUTES = [
    ("lead_manager",    "Lead Manager",    False),
    ("prompt_template", "Prompt Template", False),
]


def create_attribute(slug, title, is_unique):
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
    resp = requests.post(f"{BASE_URL}/objects/{OBJECT_SLUG}/attributes", json=payload, headers=HEADERS)
    if resp.status_code in (200, 201):
        print(f"  + Created '{slug}'")
    elif resp.status_code == 409:
        print(f"  ~ '{slug}' already exists")
    else:
        print(f"  ! Failed '{slug}': {resp.status_code} {resp.text[:300]}")


def main():
    if not ATTIO_API_KEY:
        print("Error: Set ATTIO_API environment variable first.")
        sys.exit(1)

    print(f"Adding columns to '{OBJECT_SLUG}'...\n")
    for slug, title, is_unique in NEW_ATTRIBUTES:
        create_attribute(slug, title, is_unique)

    print("\nDone.")


if __name__ == "__main__":
    main()
