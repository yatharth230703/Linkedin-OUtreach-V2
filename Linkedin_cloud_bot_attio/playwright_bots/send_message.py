## Send first message to LinkedIn connections - Playwright version
## Scrape connections, tally against Attio entries, send first messages

import os
import time
import random
import json
import sys
from datetime import datetime
from difflib import SequenceMatcher
from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from proxy_requests import get_proxy_session
from playwright_bots.login_credentials import (
    ensure_linkedin_login,
    human_pause,
    human_move_click,
    log_action,
    _safe_goto,
)
from playwright_bots.msg_draft_connection_bot1 import (
    human_scroll,
    human_sleep_with_activity,
    SessionFailureError,
)
from attio_client import get_attio_client, set_active_account
from notifier import notify_message_sent, notify_error, notify_login_failed
from notifier import set_active_account as set_notifier_account

load_dotenv()


def validate_lead_match(scraped_name, scraped_headline, db_lead_data, similarity_threshold=0.7):
    """
    Validate that scraped LinkedIn data matches Attio database entry.

    When the database headline is EMPTY (common for leads added by the
    connection bot before headline scraping was fixed), we trust the name
    match alone — we simply don't have headline data to compare.
    """
    db_name = db_lead_data.get('full_name', '').strip()
    db_headline = db_lead_data.get('headline', '').strip()

    name_similarity = SequenceMatcher(None, scraped_name.lower(), db_name.lower()).ratio()

    # If database headline is empty, headline comparison is meaningless —
    # don't penalise the match score for missing data.
    if not db_headline:
        headline_similarity = 1.0 if not scraped_headline else 0.5  # neutral
        confidence = name_similarity  # name-only confidence
        if name_similarity > 0.9:
            is_match = True
            should_proceed = True
            reason = f"Strong name match, no headline in DB (name: {name_similarity:.2f})"
        else:
            is_match = False
            should_proceed = False
            reason = f"Weak name match, no headline in DB (name: {name_similarity:.2f})"
    else:
        headline_similarity = SequenceMatcher(None, scraped_headline.lower(), db_headline.lower()).ratio()
        confidence = (name_similarity * 0.7) + (headline_similarity * 0.3)
        is_match = name_similarity > 0.9 and headline_similarity > similarity_threshold
        should_proceed = is_match or (name_similarity > 0.95 and headline_similarity > 0.5)

        if is_match:
            reason = f"Strong match (name: {name_similarity:.2f}, headline: {headline_similarity:.2f})"
        elif should_proceed:
            reason = f"Acceptable match with manual review (name: {name_similarity:.2f}, headline: {headline_similarity:.2f})"
        else:
            reason = f"Poor match - potential mismatch (name: {name_similarity:.2f}, headline: {headline_similarity:.2f})"

    return {
        'is_match': is_match,
        'confidence': confidence,
        'reason': reason,
        'should_proceed': should_proceed,
        'name_similarity': name_similarity,
        'headline_similarity': headline_similarity
    }


def update_lead_status_to_sent(full_name, headline):
    """Update the status of a lead to 'first message sent' and set last_contacted_at."""
    try:
        current_timestamp = datetime.now().isoformat()
        client = get_attio_client()
        return client.update_lead_status(full_name, "first message sent", current_timestamp)
    except Exception as e:
        print(f"   Error updating status for {full_name}: {e}")
        return False


def get_attio_leads_data(lead_manager):
    """
    Fetch all leads from Attio for the given lead_manager.
    """
    try:
        print(f"   Fetching leads data from Attio for '{lead_manager}'...")
        client = get_attio_client()
        leads_data, contacted_leads = client.get_all_leads_for_manager(lead_manager)

        print(f"   Found {len(leads_data)} total leads in Attio")
        print(f"   - {len(contacted_leads)} with 'first message sent' status")
        print(f"   - {len(leads_data) - len(contacted_leads)} available for messaging")

        return leads_data, contacted_leads

    except Exception as e:
        print(f"   Error fetching Attio data: {e}")
        return {}, set()


def scroll_to_top(page):
    """Scroll back to the top of the connections page"""
    print("   Scrolling back to top of page...")
    page.evaluate("window.scrollTo(0, 0)")
    human_pause(2, 4)


def scroll_to_load_all_connections(page):
    """Scroll down to force LinkedIn to lazy-load ALL connection cards.

    Instead of checking scrollHeight (unreliable — LinkedIn's React may not
    change document height immediately), we count actual profile links
    (`a[href*="/in/"]`) after each scroll. When the count stabilizes for
    3 consecutive scrolls, all connections are loaded.
    """
    print("   Scrolling to load all connections...")
    prev_count = 0
    stable_rounds = 0
    max_scrolls = 50  # safety limit

    for _ in range(max_scrolls):
        page.evaluate("window.scrollBy(0, 800)")
        time.sleep(random.uniform(0.8, 1.5))

        # Count unique profile links currently rendered
        curr_count = page.evaluate("""
        () => {
            const links = document.querySelectorAll('a[href*="/in/"]');
            const unique = new Set();
            for (const l of links) {
                const href = l.getAttribute('href') || '';
                if (href.match(/\\/in\\/[\\w-]+\\/?$/)) unique.add(href);
            }
            return unique.size;
        }
        """)

        if curr_count == prev_count:
            stable_rounds += 1
            if stable_rounds >= 3:
                break
        else:
            stable_rounds = 0
        prev_count = curr_count

    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(random.uniform(1.5, 2.5))
    print(f"   All connections loaded ({prev_count} profiles found), back at top.")


def _check_page_is_linkedin(page):
    """Verify the page is actually LinkedIn, not a proxy firewall block page.

    iproyal residential IPs can land behind corporate firewalls (FortiGate,
    Palo Alto, etc.) that block social media. If we detect a block page,
    raise SessionFailureError so the run aborts and the proxy session gets
    regenerated.
    """
    try:
        title = (page.title() or "").lower()
        body_text = page.evaluate("() => (document.body?.innerText || '').substring(0, 500)") or ""
        body_lower = body_text.lower()

        block_signals = [
            "fortigate", "application blocked", "fortinet",
            "palo alto", "access denied", "web filter",
            "blocked by", "internet usage policy",
            "content filtering", "websense",
        ]
        for signal in block_signals:
            if signal in body_lower or signal in title:
                msg = f"Proxy exit IP is behind a firewall ({signal}). Page is NOT LinkedIn."
                print(f"   🛑 {msg}")
                try:
                    from playwright_bots.login_credentials import log_action
                    log_action(page, "proxy_blocked")
                except Exception:
                    pass
                raise SessionFailureError(msg)
    except SessionFailureError:
        raise
    except Exception:
        pass  # Can't check → proceed


def _scrape_connections_robust(page):
    """Scrape ALL connection names + headlines by scrolling and collecting.

    LinkedIn uses VIRTUAL SCROLLING on the connections page — only ~20 cards
    are in the DOM at any time. As you scroll, new cards render and old ones
    are recycled. Scrolling back to top only shows the first ~20 again.

    Strategy: scroll incrementally, collecting visible profile links at each
    position into a cumulative set. Stop when no new names appear for 3
    consecutive scrolls. Never scroll back to top before we're done.
    """
    print("   Scrolling to load all connections...")
    all_connections = {}  # name → {name, headline, position}
    stable_rounds = 0
    max_scrolls = 80

    for scroll_idx in range(max_scrolls):
        # Collect visible connections at current scroll position
        batch = page.evaluate("""
        () => {
            const connections = [];
            const links = document.querySelectorAll('a[href*="/in/"]');
            for (const link of links) {
                const href = link.getAttribute('href') || '';
                if (!href.match(/\\/in\\/[\\w-]+\\/?$/)) continue;

                const fullText = (link.innerText || link.textContent || '').trim();
                if (!fullText || fullText.length < 2) continue;

                const lines = fullText.split('\\n').map(l => l.trim()).filter(l => l.length > 0);
                const name = lines[0] || '';
                if (!name || name.length < 2) continue;

                let headline = '';
                for (let li = 1; li < lines.length; li++) {
                    const line = lines[li];
                    if (line.match(/^(1st|2nd|3rd|\\d+th)$/i)) continue;
                    headline = line;
                    break;
                }
                connections.push({ name, headline });
            }
            return connections;
        }
        """)

        prev_count = len(all_connections)
        for c in (batch or []):
            name = c.get('name', '')
            if name and name not in all_connections:
                all_connections[name] = {
                    'name': name,
                    'headline': c.get('headline', ''),
                    'position': len(all_connections) + 1,
                }

        new_count = len(all_connections)
        if new_count == prev_count:
            stable_rounds += 1
            if stable_rounds >= 3:
                break
        else:
            stable_rounds = 0

        # Scroll down for next batch.
        # LinkedIn's connections list may scroll inside its own container
        # (not the window). Try the container that holds the profile links,
        # falling back to window scroll.
        page.evaluate("""
        () => {
            // Find the scrollable ancestor of the first profile link
            const link = document.querySelector('a[href*="/in/"]');
            if (link) {
                let el = link;
                for (let i = 0; i < 10; i++) {
                    el = el.parentElement;
                    if (!el) break;
                    const style = getComputedStyle(el);
                    const isScrollable = el.scrollHeight > el.clientHeight &&
                        (style.overflowY === 'auto' || style.overflowY === 'scroll');
                    if (isScrollable) {
                        el.scrollBy(0, 600);
                        return;
                    }
                }
            }
            // Fallback: try main, then window
            const main = document.querySelector('main');
            if (main && main.scrollHeight > main.clientHeight) {
                main.scrollBy(0, 600);
            } else {
                window.scrollBy(0, 600);
            }
        }
        """)
        time.sleep(random.uniform(0.6, 1.2))

    # Scroll back to top (needed for card-walk message button clicks later)
    page.evaluate("""
    () => {
        const link = document.querySelector('a[href*="/in/"]');
        if (link) {
            let el = link;
            for (let i = 0; i < 10; i++) {
                el = el.parentElement;
                if (!el) break;
                const style = getComputedStyle(el);
                if (el.scrollHeight > el.clientHeight &&
                    (style.overflowY === 'auto' || style.overflowY === 'scroll')) {
                    el.scrollTo(0, 0);
                    return;
                }
            }
        }
        const main = document.querySelector('main');
        if (main) main.scrollTo(0, 0);
        window.scrollTo(0, 0);
    }
    """)
    time.sleep(random.uniform(1.0, 2.0))
    print(f"   All connections loaded ({len(all_connections)} total), back at top.")

    return list(all_connections.values())


def scrape_all_connections_brute(page, lead_manager=""):
    """
    Scrape connections and identify leads to message.
    Uses robust JS-based scraping (no XPaths) with FortiGate/firewall detection.

    IMPORTANT: The order of leads_to_message follows the order scraped from LinkedIn
    (top to bottom), NOT the order in Attio.
    """
    print("   Starting connection scraping and lead identification...")

    # Check the page is actually LinkedIn (not a firewall block)
    _check_page_is_linkedin(page)

    attio_leads_data, contacted_leads = get_attio_leads_data(lead_manager)

    # Combined scroll + scrape — handles LinkedIn's virtual scrolling by
    # collecting names at each scroll position into a cumulative set.
    scraped = _scrape_connections_robust(page)
    names_list = [c['name'] for c in scraped]
    headline_list = [c['headline'] for c in scraped]

    print(f"   Found {len(names_list)} names")
    if len(names_list) == 0:
        print("   ⚠️ Found 0 connections on page!")
        print("   Possible causes: page didn't load, proxy blocked, or DOM changed")
        try:
            log_action(page, "scrape_zero_connections")
            notify_error(f"Message Bot: Found 0 connections on page. Check proxy health + page screenshot.", lead_manager)
        except Exception:
            pass
    print("*" * 80)
    human_pause(3, 5)

    # Create combined dictionary and identify leads to message
    connections_dict = {}
    leads_to_message = []
    skipped_not_in_db = 0
    skipped_poor_match = 0

    min_length = min(len(names_list), len(headline_list))

    for idx in range(min_length):
        name = names_list[idx]
        headline = headline_list[idx]

        k = idx + 1  # 1-based position (for logging only, not used for XPath)

        if name not in attio_leads_data:
            print(f"   Skipping {name} - not found in Attio database")
            skipped_not_in_db += 1
            continue

        lead_db_data = attio_leads_data[name]

        validation_result = validate_lead_match(name, headline, lead_db_data)

        if not validation_result['should_proceed']:
            print(f"   Skipping {name} - {validation_result['reason']}")
            print(f"      Scraped headline: {headline}")
            print(f"      Database headline: {lead_db_data['headline']}")
            skipped_poor_match += 1
            continue

        if not validation_result['is_match']:
            print(f"   Proceeding with caution for {name} - {validation_result['reason']}")
            print(f"      Scraped headline: {headline}")
            print(f"      Database headline: {lead_db_data['headline']}")

        connection_data = {
            'name': name,
            'headline': headline,
            'headline_db': lead_db_data['headline'],
            'position_k': k,
            'contacted': False,
            'message_1_draft': lead_db_data['message_1_draft'],
            'status': lead_db_data['status'],
            'linkedin_url': lead_db_data.get('linkedin_url', ''),
            'validation_result': validation_result
        }

        if name in contacted_leads:
            connection_data['contacted'] = True
            print(f"   Skipping {name} - already has 'first message sent' status")
        else:
            leads_to_message.append(connection_data)
            print(f"   New lead identified (position {k}): {name} - needs first message")
            print(f"      Match confidence: {validation_result['confidence']:.2f}")
            if lead_db_data['message_1_draft']:
                print(f"      Message draft: {lead_db_data['message_1_draft'][:50]}...")

        connections_dict[name] = connection_data

    print(f"\n   Summary:")
    print(f"   Total connections scraped: {min_length}")
    print(f"   Skipped (not in database): {skipped_not_in_db}")
    print(f"   Skipped (poor match): {skipped_poor_match}")
    print(f"   Found in database: {len(connections_dict)}")
    print(f"   Previously contacted: {len(connections_dict) - len(leads_to_message)}")
    print(f"   New leads to message: {len(leads_to_message)}")

    if leads_to_message:
        print(f"\n   Message order (top to bottom):")
        for i, lead in enumerate(leads_to_message, 1):
            print(f"   {i}. {lead['name']} (position k={lead['position_k']})")

    return connections_dict, leads_to_message


def message_relay(page, message_text, lead_name):
    """
    Send an initial message after the conversation dialog has been opened.

    Uses robust_messaging.send_message_in_open_thread which:
      - Explicitly focuses the textbox (no more void-typing)
      - Prefers clicking the Send button over Ctrl+Enter
      - VERIFIES the send by watching the thread message count / textbox clearing
      - Returns a specific failure reason instead of silent-success
    """
    try:
        print(f"   Starting message relay for {lead_name}")
        human_pause(3, 4)

        from playwright_bots.robust_messaging import send_message_in_open_thread
        result = send_message_in_open_thread(page, message_text, lead_name)

        human_pause(2, 3)
        close_dialog_safely(page, lead_name)

        if result == "SENT":
            return True

        # Loud failure — notify so we're never silent about a skipped lead
        try:
            from notifier import notify_error
            notify_error(f"Message NOT sent to {lead_name} — reason: {result}")
        except Exception:
            pass
        print(f"   ❌ [{lead_name}] send failed ({result}) — DB status will NOT be updated")
        return False

    except Exception as e:
        print(f"   Error in message relay for {lead_name}: {e}")
        import traceback
        traceback.print_exc()
        close_dialog_safely(page, lead_name)
        try:
            from notifier import notify_error
            notify_error(f"Message exception for {lead_name}: {str(e)[:200]}")
        except Exception:
            pass
        return False


def close_dialog_safely(page, lead_name):
    """
    Safely close the message dialog and verify it's closed.
    Uses multiple methods to ensure the dialog doesn't block subsequent interactions.
    """
    print(f"      Closing message dialog for {lead_name}...")

    # Method 1: Press Escape key
    try:
        page.keyboard.press("Escape")
        human_pause(1, 2)
        print(f"      Pressed Escape to close dialog")
    except Exception as e:
        print(f"      Escape key failed: {e}")

    dialog_still_open = is_dialog_open(page)

    if dialog_still_open:
        print(f"      Dialog still open, trying additional close methods...")

        # Method 2: Try clicking the close button (English and German labels)
        close_selectors = [
            ".msg-overlay-bubble-header__control--close-btn",
            "button[aria-label='Close your conversation']",
            "button[aria-label='Schließen Sie Ihr Gespräch']",
            "button[aria-label*='Close']",
            "button[aria-label*='Schließen']",
            ".artdeco-modal__dismiss"
        ]

        for selector in close_selectors:
            try:
                close_button = page.locator(selector)
                if close_button.count() > 0 and close_button.first.is_visible():
                    close_button.first.evaluate("el => el.click()")
                    human_pause(1, 2)
                    print(f"      Closed via button: {selector}")
                    break
            except:
                continue

        dialog_still_open = is_dialog_open(page)

    if dialog_still_open:
        print(f"      Dialog still open, trying to click outside...")

        # Method 3: Click outside the dialog
        try:
            page.locator("body").first.evaluate("el => el.click()")
            human_pause(1, 2)
        except:
            pass

        dialog_still_open = is_dialog_open(page)

    if dialog_still_open:
        print(f"      Dialog still open, pressing Escape again...")

        # Method 4: Press Escape multiple times
        try:
            for _ in range(3):
                page.keyboard.press("Escape")
                human_pause(0.5, 1)
        except:
            pass

        dialog_still_open = is_dialog_open(page)

    if dialog_still_open:
        print(f"      Could not close dialog for {lead_name}, may affect next lead")
    else:
        print(f"      Dialog closed successfully for {lead_name}")

    human_pause(1, 2)
    return not dialog_still_open


def is_dialog_open(page):
    """Check if a message dialog is currently open."""
    dialog_indicators = [
        ".msg-overlay-conversation-bubble",
        ".msg-overlay-bubble-header",
        "div[data-control-name='overlay.close_conversation_window']",
        ".msg-form"
    ]

    for selector in dialog_indicators:
        try:
            elements = page.locator(selector)
            if elements.count() > 0:
                for i in range(elements.count()):
                    if elements.nth(i).is_visible():
                        return True
        except:
            continue

    return False


def send_message_to_lead(page, lead_data):
    """Send message to a specific lead using the message_relay function."""
    print(f"   Preparing to send message to: {lead_data['name']}")
    print(f"      Position K: {lead_data['position_k']}")
    print(f"      Headline: {lead_data['headline']}")

    message_text = lead_data.get('message_1_draft', '')

    if not message_text:
        print(f"   No message draft found for {lead_data['name']}")
        return False

    print(f"      Message: {message_text[:100]}...")

    success = message_relay(page, message_text, lead_data['name'])

    if success:
        db_success = update_lead_status_to_sent(lead_data['name'], lead_data['headline'])
        if db_success:
            notify_message_sent(lead_data['name'])
        return db_success

    return False


def message_all_leads(page, leads_to_message):
    """
    Iterate through all identified leads and send messages using their position values.
    Processes leads in order from top to bottom as they appear on LinkedIn page.
    """
    # Read daily limit from per-account config, fallback to generic
    daily_limit = random.randint(10, 15)
    import sys as _sys
    _project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if _project_root not in _sys.path:
        _sys.path.insert(0, _project_root)
    from state_paths import config_path as _config_path, slugify as _slugify
    import attio_client as _ac
    slug = _slugify(_ac._active_account) if _ac._active_account else ""
    cfg_path = _config_path(slug) if slug else _config_path()
    if not os.path.exists(cfg_path):
        cfg_path = _config_path()
    try:
        with open(cfg_path, "r") as f:
            config = json.load(f)
            daily_limit = config.get("daily_message", daily_limit)
            print(f"   Loaded message limit from config: {daily_limit}")
    except (FileNotFoundError, json.JSONDecodeError):
        print(f"   Using default message limit: {daily_limit}")
    print(f"   Starting to message leads (Daily limit: {daily_limit})...")
    print(f"   Found {len(leads_to_message)} leads available for messaging")

    leads_to_process = leads_to_message[:daily_limit]

    if len(leads_to_message) > daily_limit:
        print(f"   Limiting to {daily_limit} leads today (out of {len(leads_to_message)} available)")

    scroll_to_top(page)

    successful_messages = 0
    failed_messages = 0

    for idx, lead_data in enumerate(leads_to_process):
        try:
            name = lead_data['name']
            print(f"\n   Processing lead {idx + 1}/{len(leads_to_process)}: {name}")

            k = lead_data['position_k']
                                        #    /html/body/div[1]/div[2]/div[2]/div[2]/div/main/div/div/div[1]/section/div/div[2]/div/div/div[1]/div/div[2]/div/div/a
                                        #    /html/body/div[1]/div[2]/div[2]/div[2]/div/main/div/div/div[1]/section/div/div[2]/div/div/div[3]/div/div[2]/div/div/a
                                        #    /html/body/div[1]/div[2]/div[2]/div[2]/div/main/div/div/div[1]/section/div/div[2]/div/div/div[5]/div/div[2]/div/div/a

            # Message from the CONNECTIONS PAGE (same page, no navigation).
            from playwright_bots.robust_messaging import (
                lead_identity_hash, close_all_message_overlays,
                find_message_button_for, verify_recipient_in_overlay,
            )

            lead_hash = lead_identity_hash(name, lead_data.get('headline', ''))
            print(f"   Lead identity: {name} [{lead_hash}]")

            message_button_el = find_message_button_for(
                page, name, lead_headline=lead_data.get('headline', ''))

            if not message_button_el:
                print(f"   ⚠️ [{name}] message button not found — SKIPPING")
                try:
                    from notifier import notify_error
                    notify_error(f"Message skipped for {name} — Message button not found on connections page")
                except Exception:
                    pass
                failed_messages += 1
                continue

            try:
                message_button_el.scroll_into_view_if_needed()
                human_pause(1, 2)
                try:
                    message_button_el.click(timeout=5000)
                except Exception:
                    try:
                        message_button_el.evaluate("el => el.click()")
                    except Exception:
                        human_move_click(page, message_button_el)
                human_pause(3, 5)

                # Check if a direct conversation opened (for already-messaged people)
                # or a "New message" compose opened (for first-time messages).
                import time as _time
                from playwright_bots.robust_messaging import _setup_compose_recipient
                _deadline = _time.time() + 6
                _verified = False
                while _time.time() < _deadline:
                    if verify_recipient_in_overlay(page, name):
                        _verified = True
                        break
                    _time.sleep(0.5)

                if not _verified:
                    # It's likely a "New message" compose dialog (first-time message).
                    # Set the recipient via the compose's autocomplete search.
                    print(f"   [{name}] direct thread not found — trying compose dialog recipient setup...")
                    compose_ok = _setup_compose_recipient(page, name)
                    if compose_ok:
                        _verified = True
                    else:
                        print(f"   ⚠️ [{name}] could not set recipient in compose dialog — SKIPPING")
                        try:
                            from notifier import notify_error
                            notify_error(f"Message NOT sent to {name} — could not set recipient in compose")
                        except Exception:
                            pass
                        close_all_message_overlays(page)
                        failed_messages += 1
                        continue

                human_pause(1, 2)

                success = send_message_to_lead(page, lead_data)

                if success:
                    successful_messages += 1
                    print(f"   Successfully processed message for {name}")
                else:
                    failed_messages += 1
                    print(f"   Failed to send message to {name}")

            except Exception as e:
                print(f"   Error clicking message button for {name}: {e}")
                failed_messages += 1
                continue

            # CRITICAL: close the message overlay and VERIFY it's gone
            # before proceeding to the next lead. Without this, the next
            # lead's message gets typed into the still-open overlay.
            from playwright_bots.robust_messaging import close_and_verify
            connections_url = "https://www.linkedin.com/mynetwork/invite-connect/connections/"
            close_and_verify(page, max_attempts=3, page_url_fallback=connections_url)
            human_pause(3, 5)

        except Exception as e:
            print(f"   Error processing lead {lead_data.get('name', 'unknown')}: {e}")
            failed_messages += 1
            continue

    print(f"\n   Messaging Summary:")
    print(f"   Successful: {successful_messages}")
    print(f"   Failed: {failed_messages}")
    print(f"   Total processed: {successful_messages + failed_messages}")

    return successful_messages, failed_messages


def main():
    """Navigate to LinkedIn connections page using Playwright automation"""
    import argparse
    parser = argparse.ArgumentParser(description='LinkedIn Messaging Bot (Playwright)')
    parser.add_argument('--account_name', type=str, required=True,
                       help='Account name (lead_manager) to process leads for')
    parser.add_argument('--suspicious_otp', type=str, default=None,
                       help='OTP code for suspicious login challenge (proxy-triggered)')
    args = parser.parse_args()

    account_name = args.account_name
    print(f"   Using account: {account_name}")
    set_active_account(account_name)
    set_notifier_account(account_name)

    print("   Ensuring LinkedIn login...")
    driver = ensure_linkedin_login(suspicious_otp=args.suspicious_otp, account_name=account_name)

    if not driver:
        print("   Could not establish LinkedIn session. Exiting.")
        notify_login_failed(account_name)
        return

    print("   LinkedIn session established. Starting messaging bot...")
    page = driver.page

    # ── DIAGNOSTIC: fingerprint baseline ──────────────────────────────
    try:
        from playwright_bots.fingerprint_diagnostics import safe_capture as _diag_capture
        _proxy_geo = "IN" if "yatharth" in account_name.lower() else (
            "DE" if any(n in account_name.lower() for n in ("maurice", "leon")) else None)
        _diag_capture(page, account_name=account_name, checkpoint="msg_post_login",
                      proxy_geo=_proxy_geo)
    except Exception:
        pass

    try:
        print("   Opening LinkedIn...")
        _safe_goto(page, "https://www.linkedin.com/", timeout=60000)

        log_action(page, "linkedin_homepage")
        human_pause(4, 7)

        print("   Session Active. Ready to navigate to connections.")
        human_scroll(page)

        # Initialize LinkedIn's messaging app state by briefly visiting /messaging/.
        # Without this, clicking Message on connection cards creates empty dialog
        # shells (React never hydrates the messaging overlay). Visiting /messaging/
        # first forces the JS bundle to load + session state to initialize.
        print("   Initializing messaging state...")
        try:
            _safe_goto(page, "https://www.linkedin.com/messaging/", timeout=30000)
            human_pause(3, 5)
        except Exception:
            print("   ⚠️ Messaging page load timed out — proceeding anyway")

        connections_url = "https://www.linkedin.com/mynetwork/invite-connect/connections/"
        print(f"   Navigating to: {connections_url}")

        _safe_goto(page, connections_url, timeout=60000)
        human_pause(5, 8)

        log_action(page, "connections_page")
        print("   Successfully reached connections page!")

        connections_dict, leads_to_message = scrape_all_connections_brute(page, lead_manager=account_name)

        if leads_to_message:
            print(f"\n   Found {len(leads_to_message)} new leads to message!")

            successful, failed = message_all_leads(page, leads_to_message)

            print(f"\n   Messaging campaign completed!")
            print(f"      Successful messages: {successful}")
            print(f"      Failed messages: {failed}")
        else:
            print("\n   No new leads to message. All connections have been contacted previously.")

    except Exception as e:
        print(f"   Critical Script Error: {e}")
        notify_error(f"Message Bot crash: {e}", account_name)
        log_action(page, "critical_failure")

    finally:
        print("   Closing browser session...")
        try:
            driver.quit()
        except:
            pass


if __name__ == "__main__":
    main()
