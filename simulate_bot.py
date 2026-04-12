#!/usr/bin/env python3
"""
simulate_bot.py — Local simulation of the VM bot environment.

Replicates the exact conditions the bot runs under in the Docker container
on the VM, but on your laptop so you can watch the browser, inspect pages,
and debug each step interactively.

Usage:
    # Step 1: Set up env vars (one-time, or add to your shell profile)
    export STATE_DIR="$(pwd)/backend"
    export USE_PROXY=true
    export PROXY_HOST=geo.iproyal.com
    export PROXY_PORT=12321
    export PROXY_USERNAME=YvweObwSeV1H9PEu
    export PROXY_PASSWORD_BASE=aFCTd3w0bSimAaEp
    export ATTIO_API=<your key>
    export GEMINI_API_KEY=<your key>
    export YATH_LINKEDIN_EMAIL=<your email>
    export YATH_LINKEDIN_PASSWORD=<your password>

    # Step 2: Run the simulation
    python3 simulate_bot.py --bot connection --account "Yatharth Bisht"
    python3 simulate_bot.py --bot message --account "Yatharth Bisht"
    python3 simulate_bot.py --bot followup --account "Yatharth Bisht"

    # Or run login-only to debug authentication:
    python3 simulate_bot.py --bot login-only --account "Yatharth Bisht"

    # Skip cookie login attempts and go straight to password login:
    python3 simulate_bot.py --bot login-only --account "Yatharth Bisht" --password-only

    # Pause after login so you can inspect the browser manually:
    python3 simulate_bot.py --bot login-only --account "Yatharth Bisht" --pause-after-login

    # Disable proxy (test direct connection):
    python3 simulate_bot.py --bot login-only --account "Yatharth Bisht" --no-proxy

What this file does:
    - Sets up sys.path exactly like the Docker container layout
    - Imports the REAL bot modules (no mocks, no stubs)
    - Calls the REAL ensure_linkedin_login / _password_login / bot main()
    - Runs Playwright in HEADFUL mode so you can see the browser window
    - Pauses at key points (optional) so you can inspect the state
    - Prints all the same log output you'd see in daily_log.txt

What this file does NOT do:
    - It does NOT modify any bot code
    - It does NOT mock Attio, Gemini, or LinkedIn
    - It does NOT run in Docker — it runs natively on your Mac
    - It does NOT use cron or the orchestrator — it calls bot main() directly
"""

import os
import sys
import argparse
import time
from dotenv import load_dotenv

# Load .env BEFORE anything else so all env vars are available
load_dotenv(override=True)

# ---------------------------------------------------------------------------
# Path setup — replicate the container's /app layout
# ---------------------------------------------------------------------------

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
BOTS_DIR = os.path.join(PROJECT_ROOT, "Linkedin_cloud_bot_attio", "playwright_bots")
ATTIO_DIR = os.path.join(PROJECT_ROOT, "Linkedin_cloud_bot_attio")

# Add paths in the same order the container would have them
for p in [PROJECT_ROOT, ATTIO_DIR, BOTS_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

# Default STATE_DIR to backend/ for local dev (matches state_paths.py fallback)
if "STATE_DIR" not in os.environ:
    os.environ["STATE_DIR"] = os.path.join(PROJECT_ROOT, "backend")
    print(f"[simulate] STATE_DIR not set, defaulting to: {os.environ['STATE_DIR']}")


def check_env():
    """Verify required env vars are set before running."""
    required = {
        "USE_PROXY": "Proxy toggle (set to 'true' or 'false')",
        "PROXY_HOST": "iproyal proxy host",
        "PROXY_PORT": "iproyal proxy port",
        "PROXY_USERNAME": "iproyal username",
        "PROXY_PASSWORD_BASE": "iproyal base password",
    }
    optional = {
        "ATTIO_API": "Attio API key for Yatharth",
        "GEMINI_API_KEY": "Gemini API key for message generation",
        "YATH_LINKEDIN_EMAIL": "LinkedIn email for password fallback",
        "YATH_LINKEDIN_PASSWORD": "LinkedIn password for password fallback",
    }

    missing = []
    for var, desc in required.items():
        val = os.environ.get(var, "")
        if val:
            # Mask sensitive values
            display = val[:6] + "..." if len(val) > 10 else val
            print(f"  ✅ {var} = {display}")
        else:
            print(f"  ❌ {var} — MISSING ({desc})")
            missing.append(var)

    print()
    for var, desc in optional.items():
        val = os.environ.get(var, "")
        if val:
            display = val[:6] + "..." if len(val) > 10 else val
            print(f"  ✅ {var} = {display}")
        else:
            print(f"  ⚠️  {var} — not set ({desc}) — some features won't work")

    if missing:
        print(f"\n  ❌ Missing required env vars: {missing}")
        print("  Set them before running. See the docstring at the top of this file.")
        sys.exit(1)

    print()


def run_login_only(account_name, password_only=False, pause_after_login=False):
    """Test just the login flow — no Attio, no messaging, no bot logic."""
    from login_credentials import (
        ensure_linkedin_login,
        _password_login,
        _regenerate_proxy_session,
        _kill_zombie_chrome_processes,
        log_action,
    )

    print(f"\n{'='*60}")
    print(f"  LOGIN TEST for '{account_name}'")
    print(f"{'='*60}\n")

    driver = None
    if password_only:
        print("  [--password-only] Skipping cookie login, going straight to password.\n")
        _regenerate_proxy_session()
        driver = _password_login(account_name)
    else:
        driver = ensure_linkedin_login(account_name=account_name)

    if driver:
        page = driver.page
        print(f"\n  ✅ LOGIN SUCCESSFUL")
        print(f"  Current URL: {page.url}")
        print(f"  Cookies in context: {len(page.context.cookies())}")

        if pause_after_login:
            print(f"\n  Login succeeded. Now entering interactive mode.")
            print(f"  Type a URL and press ENTER to navigate (or 'quit' to exit):")
            print(f"  Examples:")
            print(f"    https://www.linkedin.com/in/vanshsachdeva/")
            print(f"    https://www.linkedin.com/mynetwork/")
            print(f"    https://www.linkedin.com/feed/")
            print()
            while True:
                try:
                    url = input("  URL> ").strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if not url or url.lower() == "quit":
                    break
                if not url.startswith("http"):
                    url = "https://www.linkedin.com" + url
                try:
                    print(f"  Navigating to {url}...")
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    print(f"  Landed on: {page.url}")
                    print(f"  Title: {page.title()}")
                    log_action(page, "manual_navigation")
                except Exception as e:
                    print(f"  ERROR: {e}")
            driver.quit()
            print("  Browser closed.")
            return

        driver.quit()
        print("  Browser closed.")
    else:
        print(f"\n  ❌ LOGIN FAILED")
        print("  Check the output above for details.")


def run_bot(bot_name, account_name):
    """Run one of the 3 bots exactly as the orchestrator would."""

    # Import and set active account before running — same as the bot's main()
    from attio_client import set_active_account
    from notifier import set_active_account as set_notifier_account
    set_active_account(account_name)
    set_notifier_account(account_name)

    # All 3 bots use main() with argparse expecting --account_name.
    # Monkeypatch sys.argv so argparse sees the right arguments.
    bot_scripts = {
        "connection": ("CONNECTION BOT", "msg_draft_connection_bot1"),
        "message":    ("MESSAGE BOT",    "send_message"),
        "followup":   ("FOLLOW-UP BOT",  "send_followup"),
    }

    if bot_name not in bot_scripts:
        print(f"  Unknown bot: {bot_name}")
        print(f"  Valid options: connection, message, followup, login-only")
        sys.exit(1)

    display_name, module_name = bot_scripts[bot_name]

    print(f"\n{'='*60}")
    print(f"  {display_name} for '{account_name}'")
    print(f"{'='*60}\n")

    # Set sys.argv before importing — some modules read it at import time
    sys.argv = [f"{module_name}.py", "--account_name", account_name]

    # Import and run
    module = __import__(module_name)
    module.main()


def main():
    parser = argparse.ArgumentParser(
        description="Simulate LinkedIn bot locally (same environment as VM container)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 simulate_bot.py --bot login-only --account "Yatharth Bisht"
  python3 simulate_bot.py --bot login-only --account "Yatharth Bisht" --password-only --pause-after-login
  python3 simulate_bot.py --bot connection --account "Yatharth Bisht"
  python3 simulate_bot.py --bot message --account "Yatharth Bisht"
  python3 simulate_bot.py --bot followup --account "Yatharth Bisht"
  python3 simulate_bot.py --bot login-only --account "Yatharth Bisht" --no-proxy
        """,
    )
    parser.add_argument(
        "--bot",
        required=True,
        choices=["connection", "message", "followup", "login-only"],
        help="Which bot to run (or 'login-only' to test authentication)",
    )
    parser.add_argument(
        "--account",
        required=True,
        help="Account name (e.g. 'Yatharth Bisht', 'maurice', 'leon')",
    )
    parser.add_argument(
        "--password-only",
        action="store_true",
        help="Skip cookie login attempts, go straight to email+password login",
    )
    parser.add_argument(
        "--pause-after-login",
        action="store_true",
        help="Keep browser open after login so you can inspect it manually",
    )
    parser.add_argument(
        "--no-proxy",
        action="store_true",
        help="Disable proxy (test direct connection from your laptop IP)",
    )
    parser.add_argument(
        "--no-stealth",
        action="store_true",
        help="Disable playwright-stealth scripts (test if they interfere with element detection)",
    )

    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"  LinkedIn Bot Local Simulator")
    print(f"  Bot: {args.bot}")
    print(f"  Account: {args.account}")
    print(f"  Proxy: {'DISABLED' if args.no_proxy else 'ENABLED'}")
    print(f"  Password-only: {args.password_only}")
    print(f"{'='*60}\n")

    if args.no_proxy:
        os.environ["USE_PROXY"] = "false"

    # Force Playwright to use its bundled Chromium instead of the installed
    # Chrome app. Playwright 1.57+ uses "Chrome for Testing" builds via CDP
    # which blocks manual user interaction in the browser window. By setting
    # CLOUD_MODE=true, our setup_playwright_browser() skips `channel="chrome"`
    # and uses the bundled Chromium, which allows manual clicking/typing.
    # This also matches the VM environment exactly (VM always uses CLOUD_MODE).
    os.environ["CLOUD_MODE"] = "true"

    # Skip cookie-based login — go straight to password login.
    # Cookie login fails on all iproyal IPs (redirect loop). Password login
    # works reliably. This avoids 3 wasted retry cycles (~3 min) on every run.
    os.environ["SKIP_COOKIE_LOGIN"] = "true"

    if args.no_stealth:
        os.environ["DISABLE_STEALTH"] = "true"

    print("  Checking environment variables...\n")
    check_env()

    if args.bot == "login-only":
        run_login_only(
            args.account,
            password_only=args.password_only,
            pause_after_login=args.pause_after_login,
        )
    else:
        run_bot(args.bot, args.account)


if __name__ == "__main__":
    main()
