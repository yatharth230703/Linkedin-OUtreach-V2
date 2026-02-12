"""
Cookie Injector - Validates that cookies.json exists and contains the critical li_at cookie.

The actual cookie injection into the browser now happens at runtime inside
login_credentials.py's inject_extension_cookies() function, which injects cookies
directly into the running Selenium driver. This is more reliable than pre-writing
to the SQLite database because:
1. Chrome reads cookies from the running session, not just the DB
2. No profile wiping needed - preserves localStorage, IndexedDB, etc.
3. Works regardless of Chrome version or encryption settings

This script just validates the cookies are ready.
"""

import json
import os
import sys

COOKIES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.json")


def validate_cookies():
    """Check that cookies.json exists and has the critical li_at cookie."""

    if not os.path.exists(COOKIES_FILE):
        print("[inject] ERROR: No cookies.json found.")
        return False

    with open(COOKIES_FILE, "r") as f:
        cookies = json.load(f)

    if not cookies:
        print("[inject] ERROR: cookies.json is empty.")
        return False

    print(f"[inject] Found {len(cookies)} cookies in cookies.json")

    # Check for critical cookies
    li_at = next((c for c in cookies if c.get("name") == "li_at"), None)
    jsessionid = next((c for c in cookies if c.get("name") == "JSESSIONID"), None)

    if not li_at:
        print("[inject] ERROR: No 'li_at' cookie found - this is the critical session token.")
        return False

    print(f"[inject] li_at cookie: present (length: {len(li_at.get('value', ''))})")
    print(f"[inject] JSESSIONID cookie: {'present' if jsessionid else 'MISSING (may still work)'}")

    # List all cookie names for debugging
    names = [c.get("name", "?") for c in cookies]
    print(f"[inject] All cookies: {', '.join(names)}")

    print("[inject] SUCCESS: Cookies validated. They will be injected at runtime by the bot.")
    return True


if __name__ == "__main__":
    result = validate_cookies()
    print(f"\n[inject] Final result: {'SUCCESS' if result else 'FAILED'}")
    sys.exit(0 if result else 1)
