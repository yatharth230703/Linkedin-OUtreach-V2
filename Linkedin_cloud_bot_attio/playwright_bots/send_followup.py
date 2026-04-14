## Follow-up message automation for LinkedIn connections - Playwright version
## Sends follow-up messages to leads based on status progression (Attio CRM)

import os
import time
import random
import json
import sys
from datetime import datetime, timedelta
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
from attio_client import get_attio_client, set_active_account
from notifier import notify_followup_sent, notify_lead_replied, notify_error, notify_login_failed
from notifier import set_active_account as set_notifier_account

load_dotenv()


def validate_lead_match(scraped_name, scraped_headline, db_lead_data, similarity_threshold=0.7):
    """
    Validate that scraped LinkedIn data matches Attio database entry.
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


def determine_next_followup_message(lead_data):
    """
    Determine which follow-up message to send next based on status.

    Status progression:
    - "first message sent" -> send message_2_draft (follow-up 1)
    - "follow-up 1 sent" -> send message_3_draft (follow-up 2)
    - "follow-up 2 sent" -> send message_4_draft (follow-up 3)
    - "follow-up 3 sent" -> send message_5_draft (follow-up 4)
    - "follow-up 4 sent" -> no more follow-ups
    """
    status = lead_data.get('status', '').strip()

    if status == "first message sent":
        message = lead_data.get('message_2_draft', '').strip()
        return (message, "follow-up 1 sent", 1) if message else (None, None, None)

    elif status == "follow-up 1 sent":
        message = lead_data.get('message_3_draft', '').strip()
        return (message, "follow-up 2 sent", 2) if message else (None, None, None)

    elif status == "follow-up 2 sent":
        message = lead_data.get('message_4_draft', '').strip()
        return (message, "follow-up 3 sent", 3) if message else (None, None, None)

    elif status == "follow-up 3 sent":
        message = lead_data.get('message_5_draft', '').strip()
        return (message, "follow-up 4 sent", 4) if message else (None, None, None)

    else:
        return (None, None, None)


def update_lead_status_to_followup_sent(full_name, headline, next_status):
    """Update the status of a lead to the next follow-up status and set last_contacted_at."""
    try:
        current_timestamp = datetime.now().isoformat()
        client = get_attio_client()
        return client.update_lead_status(full_name, next_status, current_timestamp)
    except Exception as e:
        print(f"   Error updating status for {full_name}: {e}")
        return False


def get_attio_followup_leads_data(lead_manager):
    """
    Fetch leads from Attio that need follow-up messages.
    Uses client-side 3-day gap filter.
    """
    try:
        print(f"   Fetching follow-up leads data from Attio for '{lead_manager}'...")

        client = get_attio_client()
        raw_leads = client.get_leads_for_followup(lead_manager)

        leads_data = {}
        eligible_leads = []
        skipped_no_draft = 0
        status_breakdown = {
            "first message sent": 0,
            "follow-up 1 sent": 0,
            "follow-up 2 sent": 0,
            "follow-up 3 sent": 0
        }

        for full_name, lead_info in raw_leads.items():
            status = lead_info.get('status', '').strip()

            if status in status_breakdown:
                status_breakdown[status] += 1

            message_text, next_status, followup_num = determine_next_followup_message(lead_info)

            if message_text:
                leads_data[full_name] = lead_info
                eligible_leads.append(full_name)
                print(f"      {full_name} - needs follow-up #{followup_num}")
            else:
                skipped_no_draft += 1
                print(f"      Skipping {full_name} - no message draft available for next follow-up")

        print(f"\n   Found {len(raw_leads)} leads with eligible status (>3 days ago)")
        print(f"   Status breakdown:")
        for status, count in status_breakdown.items():
            print(f"      - {status}: {count}")
        print(f"   - {len(eligible_leads)} have next message draft available")
        print(f"   - {skipped_no_draft} skipped (no message draft)")

        return leads_data, set(eligible_leads)

    except Exception as e:
        print(f"   Error fetching Attio data: {e}")
        import traceback
        traceback.print_exc()
        return {}, set()


def scroll_to_top(page):
    """Scroll back to the top of the connections page"""
    print("   Scrolling back to top of page...")
    page.evaluate("document.querySelector('main#workspace').scrollTo(0, 0)")
    human_pause(2, 4)


def scroll_to_load_all_connections(page):
    """Scroll down incrementally to force LinkedIn to lazy-load all connection cards, then scroll back to top."""
    print("   Scrolling to load all connections...")
    prev_height = 0
    stable_count = 0
    while stable_count < 3:
        page.evaluate("document.querySelector('main#workspace').scrollBy(0, 800)")
        time.sleep(random.uniform(0.8, 1.5))
        curr_height = page.evaluate("document.querySelector('main#workspace').scrollHeight")
        if curr_height == prev_height:
            stable_count += 1
        else:
            stable_count = 0
        prev_height = curr_height
    page.evaluate("document.querySelector('main#workspace').scrollTo(0, 0)")
    time.sleep(random.uniform(1.5, 2.5))
    print("   All connections loaded, back at top.")


def scrape_all_connections_for_followup(page, lead_manager=""):
    """
    Multi-level framework to scrape connections and identify leads needing follow-up.
    Only processes connections that exist in Attio database and need follow-up.
    Returns dictionary with connection data and their positions for messaging.

    IMPORTANT: The order of leads_to_message follows the order scraped from LinkedIn
    (top to bottom), NOT the order in Attio.
    """
    print("   Starting connection scraping and follow-up lead identification...")

    attio_leads_data, eligible_leads = get_attio_followup_leads_data(lead_manager)

    scroll_to_load_all_connections(page)

    ## Scrape names
    names_list = []
    i = 1
    while i < 90:
        try:
            names_xp = f"xpath= /html/body/div[1]/div[2]/div[2]/div[2]/div/main/div/div/div[1]/section/div/div[2]/div/div/div[{i}]/div/div[1]/div/a/div/p"
            name_elem = page.locator(names_xp)
            if name_elem.count() > 0:
                names_list.append(name_elem.first.inner_text().strip())
            else:
                print(f"   Reached end of names at position {i}")
                break
            i += 2
        except Exception as e:
            print(f"   Reached end of names at position {i} (exception: {e})")
            break

    print(f"   Found {len(names_list)} names")
    if len(names_list) == 0:
        print("   ⚠️ XPATH FAILURE: Could not find any connection name elements!")
        print("   LinkedIn may have changed their DOM structure. XPaths need updating.")
        try:
            notify_error("Follow-up Bot XPATH FAILURE: Found 0 connection names on page. LinkedIn DOM may have changed — XPaths need updating.", lead_manager)
        except Exception:
            pass
    print("*" * 80)
    human_pause(3, 5)

    ## Scrape headlines
    headline_list = []
    j = 1
    while j < 90:
        try:
            headlines_xp = f"xpath=/html/body/div[1]/div[2]/div[2]/div[2]/div/main/div/div/div[1]/section/div/div[2]/div/div/div[{j}]/div/div[1]/div/a/div/div/p"
            headline_elem = page.locator(headlines_xp)
            if headline_elem.count() > 0:
                headline_list.append(headline_elem.first.inner_text().strip())
            else:
                print(f"   Reached end of headlines at position {j}")
                break
            j += 2
        except Exception as e:
            print(f"   Reached end of headlines at position {j} (exception: {e})")
            break

    print(f"   Found {len(headline_list)} headlines")
    if len(headline_list) == 0:
        print("   ⚠️ XPATH FAILURE: Could not find any connection headline elements!")
    print("*" * 80)
    human_pause(3, 5)

    # Create combined dictionary and identify leads to message
    connections_dict = {}
    leads_to_message = []
    skipped_not_in_db = 0
    skipped_not_eligible = 0
    skipped_poor_match = 0

    min_length = min(len(names_list), len(headline_list))

    for idx in range(min_length):
        name = names_list[idx]
        headline = headline_list[idx]

        k = 2 * idx + 1

        if name not in attio_leads_data:
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
            'message_2_draft': lead_db_data['message_2_draft'],
            'status': lead_db_data['status'],
            'last_contacted_at': lead_db_data['last_contacted_at'],
            'validation_result': validation_result
        }

        if name in eligible_leads:
            message_text, next_status, followup_num = determine_next_followup_message(lead_db_data)

            leads_to_message.append(connection_data)
            print(f"   Follow-up lead identified (position {k}): {name}")
            print(f"      Last contacted: {lead_db_data['last_contacted_at']}")
            print(f"      Current status: {lead_db_data['status']}")
            print(f"      Next follow-up: #{followup_num}")
            print(f"      Match confidence: {validation_result['confidence']:.2f}")
            if message_text:
                print(f"      Message preview: {message_text[:50]}...")
        else:
            skipped_not_eligible += 1

        connections_dict[name] = connection_data

    print(f"\n   Summary:")
    print(f"   Total connections scraped: {min_length}")
    print(f"   Skipped (not in database): {skipped_not_in_db}")
    print(f"   Skipped (poor match): {skipped_poor_match}")
    print(f"   Found in database: {len(connections_dict)}")
    print(f"   Not eligible for follow-up: {skipped_not_eligible}")
    print(f"   Leads needing follow-up: {len(leads_to_message)}")

    if leads_to_message:
        print(f"\n   Follow-up message order (top to bottom):")
        for i, lead in enumerate(leads_to_message, 1):
            print(f"   {i}. {lead['name']} (position k={lead['position_k']})")

    return connections_dict, leads_to_message


def get_all_linkedin_messages_shadow(page):
    """
    Extract all messages from a LinkedIn conversation thread, including those inside shadow DOM.
    Playwright handles shadow DOM piercing natively, so we use page.evaluate() for the JS extraction.
    """
    messages = []

    # Try shadow DOM first
    try:
        shadow_host = page.locator('#interop-outlet')
        if shadow_host.count() > 0:
            js_code = """
            () => {
                const shadowHost = document.querySelector('#interop-outlet');
                if (!shadowHost || !shadowHost.shadowRoot) return [];
                const shadowRoot = shadowHost.shadowRoot;
                const messages = [];

                const messageElements = shadowRoot.querySelectorAll('.msg-s-message-list__event');

                messageElements.forEach((element, index) => {
                    try {
                        let sender = '';
                        const nameLinks = element.querySelectorAll('a[data-attribute-name="profile"]');
                        if (nameLinks.length > 0) {
                            sender = nameLinks[0].innerText.trim();
                        } else {
                            const allLinks = element.querySelectorAll('a');
                            for (let link of allLinks) {
                                if (link.innerText && link.innerText.trim() &&
                                    !link.innerText.includes('View') &&
                                    !link.innerText.includes('profile')) {
                                    sender = link.innerText.trim();
                                    break;
                                }
                            }
                        }

                        let timestamp = '';
                        const timeElements = element.querySelectorAll('time');
                        if (timeElements.length > 0) {
                            timestamp = timeElements[0].innerText.trim();
                        } else {
                            const allText = element.innerText;
                            const timeMatch = allText.match(/\\d{1,2}:\\d{2}\\s*(?:AM|PM)/i);
                            if (timeMatch) {
                                timestamp = timeMatch[0];
                            }
                        }

                        let messageText = '';
                        const messageBody = element.querySelector('.msg-s-event-listitem__body');
                        if (messageBody) {
                            messageText = messageBody.innerText.trim();
                            messageText = messageText.replace(timestamp, '').trim();
                            messageText = messageText.replace(sender, '').trim();
                        } else {
                            const textNodes = [];
                            const walker = document.createTreeWalker(
                                element,
                                NodeFilter.SHOW_TEXT,
                                null,
                                false
                            );
                            let node;
                            while (node = walker.nextNode()) {
                                const text = node.textContent.trim();
                                if (text && text.length > 0) {
                                    textNodes.push(text);
                                }
                            }
                            messageText = textNodes.join(' ').trim();
                        }

                        let messageType = 'unknown';
                        if (element.innerText.includes('You:') ||
                            element.querySelector('.msg-s-message-group__profile-link--you')) {
                            messageType = 'sent';
                        } else if (sender && sender !== 'You') {
                            messageType = 'received';
                        }

                        let dateLabel = '';
                        const dateElement = element.querySelector('.msg-s-message-list-event__time-heading');
                        if (dateElement) {
                            dateLabel = dateElement.innerText.trim();
                        } else {
                            let prevElement = element.previousElementSibling;
                            while (prevElement) {
                                if (prevElement.classList.contains('msg-s-message-list__time-heading')) {
                                    dateLabel = prevElement.innerText.trim();
                                    break;
                                }
                                prevElement = prevElement.previousElementSibling;
                            }
                        }

                        messages.push({
                            index: index,
                            sender: sender,
                            timestamp: timestamp,
                            date_label: dateLabel,
                            message_text: messageText,
                            message_type: messageType,
                            full_text: element.innerText.trim(),
                            source: 'shadow_dom'
                        });
                    } catch (e) {
                        console.error('Error parsing message:', e);
                    }
                });

                return messages;
            }
            """

            shadow_messages = page.evaluate(js_code)
            if isinstance(shadow_messages, list):
                messages.extend(shadow_messages)

    except Exception as e:
        print(f"Could not access shadow DOM: {e}")

    # Also check regular DOM for messages
    js_code_regular = """
    () => {
        const messages = [];
        const messageElements = document.querySelectorAll('.msg-s-message-list__event');

        messageElements.forEach((element, index) => {
            try {
                let sender = '';
                const nameLinks = element.querySelectorAll('a[data-attribute-name="profile"]');
                if (nameLinks.length > 0) {
                    sender = nameLinks[0].innerText.trim();
                } else {
                    const allLinks = element.querySelectorAll('a');
                    for (let link of allLinks) {
                        if (link.innerText && link.innerText.trim() &&
                            !link.innerText.includes('View') &&
                            !link.innerText.includes('profile')) {
                            sender = link.innerText.trim();
                            break;
                        }
                    }
                }

                let timestamp = '';
                const timeElements = element.querySelectorAll('time');
                if (timeElements.length > 0) {
                    timestamp = timeElements[0].innerText.trim();
                } else {
                    const allText = element.innerText;
                    const timeMatch = allText.match(/\\d{1,2}:\\d{2}\\s*(?:AM|PM)/i);
                    if (timeMatch) {
                        timestamp = timeMatch[0];
                    }
                }

                let messageText = '';
                const messageBody = element.querySelector('.msg-s-event-listitem__body');
                if (messageBody) {
                    messageText = messageBody.innerText.trim();
                    messageText = messageText.replace(timestamp, '').trim();
                    messageText = messageText.replace(sender, '').trim();
                } else {
                    const textNodes = [];
                    const walker = document.createTreeWalker(
                        element,
                        NodeFilter.SHOW_TEXT,
                        null,
                        false
                    );
                    let node;
                    while (node = walker.nextNode()) {
                        const text = node.textContent.trim();
                        if (text && text.length > 0) {
                            textNodes.push(text);
                        }
                    }
                    messageText = textNodes.join(' ').trim();
                }

                let messageType = 'unknown';
                if (element.innerText.includes('You:') ||
                    element.querySelector('.msg-s-message-group__profile-link--you')) {
                    messageType = 'sent';
                } else if (sender && sender !== 'You') {
                    messageType = 'received';
                }

                let dateLabel = '';
                const dateElement = element.querySelector('.msg-s-message-list-event__time-heading');
                if (dateElement) {
                    dateLabel = dateElement.innerText.trim();
                } else {
                    let prevElement = element.previousElementSibling;
                    while (prevElement) {
                        if (prevElement.classList.contains('msg-s-message-list__time-heading')) {
                            dateLabel = prevElement.innerText.trim();
                            break;
                        }
                        prevElement = prevElement.previousElementSibling;
                    }
                }

                messages.push({
                    index: index,
                    sender: sender,
                    timestamp: timestamp,
                    date_label: dateLabel,
                    message_text: messageText,
                    message_type: messageType,
                    full_text: element.innerText.trim(),
                    source: 'regular_dom'
                });
            } catch (e) {
                console.error('Error parsing message:', e);
            }
        });

        return messages;
    }
    """

    try:
        regular_messages = page.evaluate(js_code_regular)
        if isinstance(regular_messages, list):
            messages.extend(regular_messages)
    except Exception as e:
        print(f"Error getting regular DOM messages: {e}")

    # Deduplicate
    seen_texts = set()
    unique_messages = []

    for msg in messages:
        msg_key = f"{msg.get('sender', '')}_{msg.get('timestamp', '')}_{msg.get('message_text', '')[:50]}"

        if msg_key not in seen_texts:
            seen_texts.add(msg_key)
            unique_messages.append(msg)

    return unique_messages


def check_if_lead_replied(page, lead_name):
    """
    Check if a lead has replied by parsing conversation messages.
    Returns True if lead's name appears as sender in any message.
    """
    try:
        print(f"      Checking if {lead_name} has replied...")

        human_pause(2, 3)

        messages = get_all_linkedin_messages_shadow(page)

        if not messages:
            print(f"      No messages found in conversation")
            return False

        print(f"      Found {len(messages)} messages in conversation")

        for msg in messages:
            sender = msg.get('sender', '').strip()
            message_type = msg.get('message_type', '')

            if sender and lead_name.lower() in sender.lower():
                if message_type == 'received' or (message_type != 'sent' and 'you' not in sender.lower()):
                    print(f"      REPLY DETECTED! {sender} sent a message")
                    print(f"      Message preview: {msg.get('message_text', '')[:100]}")
                    return True

        print(f"      No reply detected from {lead_name}")
        return False

    except Exception as e:
        print(f"      Error checking for reply: {e}")
        import traceback
        traceback.print_exc()
        return False


def update_lead_status_to_replied(full_name):
    """Update lead status to 'LEAD REPLIED' when reply is detected."""
    try:
        client = get_attio_client()
        return client.mark_lead_replied(full_name)
    except Exception as e:
        print(f"      Error updating status for {full_name}: {e}")
        return False


def message_relay(page, message_text, lead_name):
    """
    Send a follow-up after the conversation dialog has been opened.

    Uses robust_messaging.send_message_in_open_thread which:
      - Explicitly focuses the textbox (no more void-typing)
      - Prefers clicking the Send button over Ctrl+Enter
      - VERIFIES the send by watching the thread message count / textbox clearing
      - Returns a specific failure reason instead of silent-success
    """
    try:
        print(f"   Starting message relay for {lead_name}")
        human_pause(3, 4)

        # CRITICAL: check if lead has already replied — skip sending in that case
        has_replied = check_if_lead_replied(page, lead_name)
        if has_replied:
            print(f"      {lead_name} has already replied! Skipping follow-up message.")
            update_lead_status_to_replied(lead_name)
            close_dialog_safely(page, lead_name)
            return "REPLIED"

        print(f"      No reply detected. Proceeding to send follow-up message...")

        from playwright_bots.robust_messaging import send_message_in_open_thread
        result = send_message_in_open_thread(page, message_text, lead_name)

        human_pause(2, 3)
        close_dialog_safely(page, lead_name)

        if result == "SENT":
            return True

        try:
            from notifier import notify_error
            notify_error(f"Follow-up NOT sent to {lead_name} — reason: {result}")
        except Exception:
            pass
        print(f"   ❌ [{lead_name}] follow-up failed ({result}) — DB status will NOT be updated")
        return False

    except Exception as e:
        print(f"   Error in message relay for {lead_name}: {e}")
        import traceback
        traceback.print_exc()
        close_dialog_safely(page, lead_name)
        try:
            from notifier import notify_error
            notify_error(f"Follow-up exception for {lead_name}: {str(e)[:200]}")
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


def send_followup_to_lead(page, lead_data):
    """
    Send follow-up message to a specific lead.
    Determines which follow-up message to send based on current status.
    """
    print(f"   Preparing to send follow-up message to: {lead_data['name']}")
    print(f"      Position K: {lead_data['position_k']}")
    print(f"      Headline: {lead_data['headline']}")
    print(f"      Current status: {lead_data['status']}")
    print(f"      Last contacted: {lead_data['last_contacted_at']}")

    message_text, next_status, followup_num = determine_next_followup_message(lead_data)

    if not message_text:
        print(f"   No follow-up message available for {lead_data['name']}")
        return False

    print(f"      Sending follow-up #{followup_num}: {message_text[:100]}...")

    result = message_relay(page, message_text, lead_data['name'])

    if result == "REPLIED":
        print(f"      Lead has replied! Status updated to 'LEAD REPLIED'")
        notify_lead_replied(lead_data['name'])
        return "REPLIED"

    if result:
        db_success = update_lead_status_to_followup_sent(lead_data['name'], lead_data['headline'], next_status)
        if db_success:
            notify_followup_sent(lead_data['name'], followup_num)
        return db_success

    return False


def message_all_followup_leads(page, leads_to_message):
    """
    Iterate through all identified leads and send follow-up messages.
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
            daily_limit = config.get("daily_followup", daily_limit)
            print(f"   Loaded follow-up limit from config: {daily_limit}")
    except (FileNotFoundError, json.JSONDecodeError):
        print(f"   Using default follow-up limit: {daily_limit}")
    print(f"   Starting to send follow-up messages (Daily limit: {daily_limit})...")
    print(f"   Found {len(leads_to_message)} leads available for follow-up")

    leads_to_process = leads_to_message[:daily_limit]

    if len(leads_to_message) > daily_limit:
        print(f"   Limiting to {daily_limit} follow-ups today (out of {len(leads_to_message)} available)")

    scroll_to_top(page)

    successful_messages = 0
    failed_messages = 0
    replied_leads = 0

    for idx, lead_data in enumerate(leads_to_process):
        try:
            name = lead_data['name']
            print(f"\n   Processing follow-up lead {idx + 1}/{len(leads_to_process)}: {name}")

            k = lead_data['position_k']

            # Force-close any lingering message overlays before opening a
            # new conversation — otherwise typing can leak into the wrong thread.
            from playwright_bots.robust_messaging import (
                find_message_button_for, lead_identity_hash, close_all_message_overlays
            )
            close_all_message_overlays(page)

            lead_hash = lead_identity_hash(name, lead_data.get('headline', ''))
            print(f"   Lead identity: {name} [{lead_hash}]")
            message_button_el = find_message_button_for(
                page, name, lead_headline=lead_data.get('headline', ''))

            # NO legacy XPath fallback — caused messages to go to wrong people.
            # If scoped lookup fails, SKIP the lead rather than risk mis-sending.
            if not message_button_el:
                print(f"   ⚠️ [{name}] message button not found via name+headline scoping — SKIPPING lead to avoid wrong-recipient send")
                failed_messages += 1
                continue

            try:
                message_button_el.scroll_into_view_if_needed()
                human_scroll(page)
                human_pause(1, 2)

                try:
                    message_button_el.click(timeout=5000)
                except Exception:
                    # Fall back to human_move_click if native click fails
                    human_move_click(page, message_button_el)
                human_pause(3, 4)

                result = send_followup_to_lead(page, lead_data)

                if result == "REPLIED":
                    replied_leads += 1
                    print(f"   {name} has already replied! Skipped follow-up.")
                elif result:
                    successful_messages += 1
                    print(f"   Successfully processed follow-up message for {name}")
                else:
                    failed_messages += 1
                    print(f"   Failed to send follow-up message to {name}")

            except Exception as e:
                print(f"   Error clicking message button for {name}: {e}")
                failed_messages += 1
                continue

            human_pause(5, 7)

        except Exception as e:
            print(f"   Error processing lead {lead_data.get('name', 'unknown')}: {e}")
            failed_messages += 1
            continue

    print(f"\n   Follow-up Messaging Summary:")
    print(f"      Successful follow-ups sent: {successful_messages}")
    print(f"      Leads who already replied: {replied_leads}")
    print(f"      Failed: {failed_messages}")
    print(f"      Total processed: {successful_messages + replied_leads + failed_messages}")

    return successful_messages, failed_messages, replied_leads


def main():
    """Navigate to LinkedIn connections page and send follow-up messages"""
    import argparse
    parser = argparse.ArgumentParser(description='LinkedIn Follow-up Bot (Playwright)')
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

    print("   LinkedIn session established. Starting follow-up bot...")
    page = driver.page

    # ── DIAGNOSTIC: fingerprint baseline ──────────────────────────────
    try:
        from playwright_bots.fingerprint_diagnostics import safe_capture as _diag_capture
        _proxy_geo = "IN" if "yatharth" in account_name.lower() else (
            "DE" if any(n in account_name.lower() for n in ("maurice", "leon")) else None)
        _diag_capture(page, account_name=account_name, checkpoint="followup_post_login",
                      proxy_geo=_proxy_geo)
    except Exception:
        pass

    try:
        print("   Opening LinkedIn for follow-up messages...")
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

        connections_dict, leads_to_message = scrape_all_connections_for_followup(page, lead_manager=account_name)

        if leads_to_message:
            print(f"\n   Found {len(leads_to_message)} leads needing follow-up messages!")

            successful, failed, replied = message_all_followup_leads(page, leads_to_message)

            print(f"\n   Follow-up messaging campaign completed!")
            print(f"      Successful follow-ups: {successful}")
            print(f"      Leads who already replied: {replied}")
            print(f"      Failed follow-ups: {failed}")
        else:
            print("\n   No leads need follow-up messages at this time.")
            print("   Either all leads have been followed up, or it hasn't been 3 days yet.")

    except Exception as e:
        print(f"   Critical Script Error: {e}")
        notify_error(f"Follow-up Bot crash: {e}", account_name)
        import traceback
        traceback.print_exc()
        log_action(page, "critical_failure")

    finally:
        print("   Closing browser session...")
        try:
            driver.quit()
        except:
            pass


if __name__ == "__main__":
    main()
