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
)
from attio_client import get_attio_client

load_dotenv()


def validate_lead_match(scraped_name, scraped_headline, db_lead_data, similarity_threshold=0.7):
    """
    Validate that scraped LinkedIn data matches Supabase database entry.
    """
    db_name = db_lead_data.get('full_name', '').strip()
    db_headline = db_lead_data.get('headline', '').strip()

    name_similarity = SequenceMatcher(None, scraped_name.lower(), db_name.lower()).ratio()
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


def scrape_all_connections_brute(page, lead_manager=""):
    """
    Multi-level framework to scrape connections and identify leads to message.
    Only processes connections that exist in Attio database.

    IMPORTANT: The order of leads_to_message follows the order scraped from LinkedIn
    (top to bottom), NOT the order in Attio.
    """
    print("   Starting connection scraping and lead identification...")

    attio_leads_data, contacted_leads = get_attio_leads_data(lead_manager)

    ## Scrape names
    names_list = []
    i = 1
    while i < 90:
        try:
            names_xp = f"xpath=/html/body/div/div[2]/div[2]/div[2]/div/main/div/div/div[1]/section/div/div[2]/div/div[{i}]/div/div[1]/div/a/div/p/a"
            name_elem = page.locator(names_xp)
            if name_elem.count() > 0:
                names_list.append(name_elem.first.inner_text().strip())
            else:
                print(f"   Reached end of names at position {i}")
                break
            i += 2
        except:
            print(f"   Reached end of names at position {i}")
            break

    print(f"   Found {len(names_list)} names")
    print("*" * 80)
    human_pause(3, 5)

    ## Scrape headlines
    headline_list = []
    j = 1
    while j < 90:
        try:
            headlines_xp = f"xpath=/html/body/div/div[2]/div[2]/div[2]/div/main/div/div/div[1]/section/div/div[2]/div/div[{j}]/div/div[1]/div/a/div/div/p"
            headline_elem = page.locator(headlines_xp)
            if headline_elem.count() > 0:
                headline_list.append(headline_elem.first.inner_text().strip())
            else:
                print(f"   Reached end of headlines at position {j}")
                break
            j += 2
        except:
            print(f"   Reached end of headlines at position {j}")
            break

    print(f"   Found {len(headline_list)} headlines")
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

        k = 2 * idx + 1

        if name not in attio_leads_data:
            print(f"   Skipping {name} - not found in Supabase database")
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
    Handle the actual messaging process after message button is clicked.
    Types message and sends using Ctrl+Enter, then closes dialog with Escape.
    """
    try:
        print(f"   Starting message relay for {lead_name}")

        human_pause(3, 4)

        print(f"      Typing message via keyboard...")

        # Type the message with human-like character delays
        for char in message_text:
            page.keyboard.type(char, delay=0)
            if random.random() < 0.1:
                time.sleep(random.uniform(0.05, 0.15))

        print(f"      Message typed for {lead_name}")
        human_pause(2, 3)

        # Send message using Ctrl+Enter
        print(f"      Sending message via Ctrl+Enter...")
        page.keyboard.press("Control+Enter")

        print(f"      Message sent to {lead_name}")
        human_pause(2, 3)

        close_dialog_safely(page, lead_name)

        return True

    except Exception as e:
        print(f"   Error in message relay for {lead_name}: {e}")
        import traceback
        traceback.print_exc()

        close_dialog_safely(page, lead_name)
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
        return db_success

    return False


def message_all_leads(page, leads_to_message):
    """
    Iterate through all identified leads and send messages using their position values.
    Processes leads in order from top to bottom as they appear on LinkedIn page.
    """
    # Read daily limit from config.json
    daily_limit = random.randint(10, 15)
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "backend", "config.json")
    try:
        with open(config_path, "r") as f:
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

            message_button_xpath = f"xpath=/html/body/div/div[2]/div[2]/div[2]/div/main/div/div/div[1]/section/div/div[2]/div/div[{k}]/div/div[2]/div/div/a"

            try:
                message_button = page.locator(message_button_xpath)
                if message_button.count() == 0:
                    print(f"   Message button not found for {name}")
                    failed_messages += 1
                    continue

                # Verify it's a message button (English or German)
                button_text = message_button.first.get_attribute("aria-label") or message_button.first.inner_text()
                if not any(keyword in button_text.lower() for keyword in ["message", "nachricht"]):
                    print(f"   Button found but not a message button: {button_text}")
                    failed_messages += 1
                    continue

                human_move_click(page, message_button.first)
                human_pause(3, 4)

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

            human_pause(5, 7)

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

    print("   Ensuring LinkedIn login...")
    driver = ensure_linkedin_login(suspicious_otp=args.suspicious_otp)

    if not driver:
        print("   Could not establish LinkedIn session. Exiting.")
        return

    print("   LinkedIn session established. Starting messaging bot...")
    page = driver.page

    try:
        print("   Opening LinkedIn...")
        _safe_goto(page, "https://www.linkedin.com/", timeout=60000)

        log_action(page, "linkedin_homepage")
        human_pause(4, 7)

        print("   Session Active. Ready to navigate to connections.")
        human_scroll(page)

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
        log_action(page, "critical_failure")

    finally:
        print("   Closing browser session...")
        try:
            driver.quit()
        except:
            pass


if __name__ == "__main__":
    main()
