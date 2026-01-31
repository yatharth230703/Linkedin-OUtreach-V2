"""
Template Script for LinkedIn Experimentation
=============================================
Contains all utility functions from check_reply_manual.py
Main function opens LinkedIn, waits 30 seconds, and exits.
Add your custom code in the main() function.
"""

import os
import sys
import time
import random
from datetime import datetime
from difflib import SequenceMatcher
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from dotenv import load_dotenv


from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Add Linkedin_cloud_bot to path for imports
script_dir = os.path.dirname(os.path.abspath(__file__))
linkedin_bot_dir = os.path.join(script_dir, "Linkedin_cloud_bot")
if linkedin_bot_dir not in sys.path:
    sys.path.insert(0, linkedin_bot_dir)

# Import from Linkedin_cloud_bot modules
from msg_draft_connection_bot1 import (
    human_pause,
    human_scroll,
    human_move_click,
    log_action,
    supabase
)
from login_credentials import ensure_linkedin_login

load_dotenv()


def get_messaged_leads_from_supabase():
    """
    Fetch leads from Supabase that have been messaged (any "sent" status).
    Returns dictionary with full_name as key and lead data as value.
    """
    try:
        print("📊 Fetching messaged leads from Supabase...")

        eligible_statuses = [
            "first message sent",
            "follow-up 1 sent",
            "follow-up 2 sent",
            "follow-up 3 sent",
            "follow-up 4 sent"
        ]

        response = supabase.table('leads').select(
            'full_name, headline, status, last_contacted_at'
        ).in_('status', eligible_statuses).execute()

        leads_data = {}
        status_breakdown = {}

        for lead in response.data:
            full_name = lead.get('full_name', '').strip()
            headline = lead.get('headline', '').strip()
            status = lead.get('status', '').strip()
            last_contacted_at = lead.get('last_contacted_at', '')

            if full_name:
                leads_data[full_name] = {
                    'full_name': full_name,
                    'headline': headline,
                    'status': status,
                    'last_contacted_at': last_contacted_at
                }

                # Track status breakdown
                status_breakdown[status] = status_breakdown.get(status, 0) + 1

        print(f"✅ Found {len(leads_data)} leads with 'sent' statuses")
        print("   Status breakdown:")
        for status, count in status_breakdown.items():
            print(f"      - {status}: {count}")

        return leads_data

    except Exception as e:
        print(f"❌ Error fetching Supabase data: {e}")
        return {}


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

    return {
        'is_match': is_match,
        'confidence': confidence,
        'should_proceed': should_proceed,
        'name_similarity': name_similarity,
        'headline_similarity': headline_similarity
    }


def update_lead_status_to_replied(full_name):
    """
    Update lead status to REPLIED when reply is detected.
    """
    try:
        response = supabase.table('leads').update({
            'status': 'REPLIED'
        }).eq('full_name', full_name).execute()

        if response.data:
            print(f"   ✅ Updated {full_name} status to REPLIED")
            return True
        else:
            print(f"   ⚠️ No matching lead found for {full_name}")
            return False

    except Exception as e:
        print(f"   ❌ Error updating status for {full_name}: {e}")
        return False


def scroll_to_top(driver):
    """Scroll back to the top of the connections page"""
    print("⬆️ Scrolling back to top of page...")
    driver.execute_script("window.scrollTo(0, 0);")
    human_pause(2, 4)


def scrape_connections_for_reply_check(driver):
    """
    Scrape connections page and identify leads that need reply checking.
    Returns list of leads to check (maintaining LinkedIn page order).
    """
    print("🔍 Starting connection scraping for reply check...")

    # Get messaged leads from Supabase
    supabase_leads = get_messaged_leads_from_supabase()

    if not supabase_leads:
        print("⚠️ No messaged leads found in database")
        return []

    # Scrape names from connections page
    names_list = []
    i = 1
    while i < 90:
        try:
            names_xp = f"/html/body/div/div[2]/div[2]/div[2]/div/main/div/div/div[1]/section/div/div[2]/div/div[{i}]/div/div[1]/div/a/div/p/a"
            name_elem = driver.find_element(By.XPATH, names_xp)
            names_list.append(name_elem.text.strip())
            i += 2
        except:
            print(f"📋 Reached end of names at position {i}")
            break

    print(f"✅ Found {len(names_list)} names on connections page")
    human_pause(2, 3)

    # Scrape headlines from connections page
    headline_list = []
    j = 1
    while j < 90:
        try:
            headlines_xp = f"/html/body/div/div[2]/div[2]/div[2]/div/main/div/div/div[1]/section/div/div[2]/div/div[{j}]/div/div[1]/div/a/div/div/p"
            headline_elem = driver.find_element(By.XPATH, headlines_xp)
            headline_list.append(headline_elem.text.strip())
            j += 2
        except:
            print(f"📋 Reached end of headlines at position {j}")
            break

    print(f"✅ Found {len(headline_list)} headlines on connections page")
    human_pause(2, 3)

    # Match connections against Supabase leads
    leads_to_check = []
    skipped_not_in_db = 0
    skipped_poor_match = 0

    min_length = min(len(names_list), len(headline_list))

    for idx in range(min_length):
        name = names_list[idx]
        headline = headline_list[idx]
        k = 2 * idx + 1  # Position value for message button

        # Check if in database
        if name not in supabase_leads:
            skipped_not_in_db += 1
            continue

        # Validate match
        lead_db_data = supabase_leads[name]
        validation = validate_lead_match(name, headline, lead_db_data)

        if not validation['should_proceed']:
            print(f"⚠️ Skipping {name} - poor match (confidence: {validation['confidence']:.2f})")
            skipped_poor_match += 1
            continue

        lead_data = {
            'name': name,
            'headline': headline,
            'position_k': k,
            'status': lead_db_data['status'],
            'last_contacted_at': lead_db_data['last_contacted_at']
        }

        leads_to_check.append(lead_data)
        print(f"🎯 Lead to check (position {k}): {name} - {lead_db_data['status']}")

    print(f"\n📊 Summary:")
    print(f"   Total connections scraped: {min_length}")
    print(f"   Skipped (not in database): {skipped_not_in_db}")
    print(f"   Skipped (poor match): {skipped_poor_match}")
    print(f"   Leads to check for replies: {len(leads_to_check)}")

    return leads_to_check


def is_dialog_open(driver):
    """
    Check if a message dialog is currently open.
    """
    dialog_indicators = [
        ".msg-overlay-conversation-bubble",
        ".msg-overlay-bubble-header",
        "div[data-control-name='overlay.close_conversation_window']",
        ".msg-form"
    ]

    for selector in dialog_indicators:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            for elem in elements:
                if elem.is_displayed():
                    return True
        except:
            continue

    return False


def close_dialog_safely(driver, lead_name):
    """
    Safely close the message dialog using multiple fallback methods.
    """
    print(f"   🚪 Closing message dialog for {lead_name}...")

    # Method 1: Press Escape key
    try:
        actions = ActionChains(driver)
        actions.send_keys(Keys.ESCAPE).perform()
        human_pause(1, 2)
        print(f"   ✅ Pressed Escape to close dialog")
    except Exception as e:
        print(f"   ⚠️ Escape key failed: {e}")

    # Check if still open
    if is_dialog_open(driver):
        print(f"   ⚠️ Dialog still open, trying close button...")

        # Method 2: Try clicking close button
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
                close_button = driver.find_element(By.CSS_SELECTOR, selector)
                if close_button.is_displayed():
                    driver.execute_script("arguments[0].click();", close_button)
                    human_pause(1, 2)
                    print(f"   ✅ Closed via button: {selector}")
                    break
            except:
                continue

    # Check again and try clicking outside
    if is_dialog_open(driver):
        print(f"   ⚠️ Dialog still open, clicking outside...")
        try:
            page_body = driver.find_element(By.TAG_NAME, "body")
            driver.execute_script("arguments[0].click();", page_body)
            human_pause(1, 2)
        except:
            pass

    # Final check - multiple Escape presses
    if is_dialog_open(driver):
        print(f"   ⚠️ Dialog still open, pressing Escape multiple times...")
        try:
            for _ in range(3):
                actions = ActionChains(driver)
                actions.send_keys(Keys.ESCAPE).perform()
                human_pause(0.5, 1)
        except:
            pass

    dialog_closed = not is_dialog_open(driver)
    if dialog_closed:
        print(f"   ✅ Dialog closed successfully for {lead_name}")
    else:
        print(f"   ❌ Could not close dialog for {lead_name}")

    human_pause(1, 2)
    return dialog_closed


def detect_reply_in_conversation(driver, lead_name, debug=True):
    """
    Detect if the lead has replied in the conversation.
    Returns True if a reply is detected, False otherwise.

    Strategy: Count message groups - if more than 1, lead has replied.
    LinkedIn shows each person's messages in separate groups.
    """
    try:
        print(f"   🔍 Checking conversation for replies from {lead_name}...")

        # Wait for conversation to fully load
        human_pause(3, 4)

        # Debug: Save FULL page source for analysis
        if debug:
            try:
                os.makedirs("screenshots", exist_ok=True)
                debug_file = f"screenshots/debug_page_{lead_name.replace(' ', '_')}.html"
                with open(debug_file, 'w', encoding='utf-8') as f:
                    f.write(driver.page_source)
                print(f"   📄 DEBUG: Saved full page source to {debug_file}")

                # Also save screenshot
                screenshot_file = f"screenshots/debug_screenshot_{lead_name.replace(' ', '_')}.png"
                driver.save_screenshot(screenshot_file)
                print(f"   📸 DEBUG: Saved screenshot to {screenshot_file}")
            except Exception as e:
                print(f"   ⚠️ DEBUG: Could not save debug files: {e}")

        # STRATEGY 1: Count message groups (most reliable)
        # LinkedIn groups consecutive messages from the same sender
        # If there's more than 1 group, the lead has replied
        message_group_selectors = [
            ".msg-s-message-group",
            ".msg-s-message-list__event",
            "[class*='message-group']",
            ".msg-s-event-listitem--group"
        ]

        for selector in message_group_selectors:
            try:
                groups = driver.find_elements(By.CSS_SELECTOR, selector)
                if groups:
                    print(f"   📊 Found {len(groups)} message groups with selector: {selector}")
                    if len(groups) > 1:
                        print(f"   ✅ Multiple message groups detected = lead has replied!")
                        print(f"   📩 replied already")
                        return True
            except:
                continue

        # STRATEGY 2: Look for profile images in conversation (theirs vs ours)
        # If we see the lead's profile image next to a message, they replied
        profile_img_selectors = [
            ".msg-s-message-group__avatar",
            ".msg-s-event-listitem__avatar",
            ".presence-entity__image",
            "img.msg-s-message-group__avatar"
        ]

        for selector in profile_img_selectors:
            try:
                avatars = driver.find_elements(By.CSS_SELECTOR, selector)
                if avatars:
                    print(f"   📊 Found {len(avatars)} avatar images with selector: {selector}")
                    # More than 1 unique avatar means conversation has replies
                    if len(avatars) > 1:
                        print(f"   ✅ Multiple avatars detected = lead has replied!")
                        print(f"   📩 replied already")
                        return True
            except:
                continue

        # STRATEGY 3: Look for sender name elements
        sender_selectors = [
            ".msg-s-message-group__name",
            ".msg-s-message-group__profile-link",
            ".msg-s-event-listitem__name",
            "[class*='sender']",
            "[class*='author']"
        ]

        found_senders = set()
        for selector in sender_selectors:
            try:
                sender_elements = driver.find_elements(By.CSS_SELECTOR, selector)
                for elem in sender_elements:
                    sender_text = elem.text.strip()
                    if sender_text:
                        found_senders.add(sender_text.lower())
                        print(f"   📊 Found sender: '{sender_text}' with selector: {selector}")
            except:
                continue

        if found_senders:
            print(f"   📊 Unique senders found: {found_senders}")
            # Check if lead's name is among senders
            lead_first_name = lead_name.lower().split()[0]
            for sender in found_senders:
                if lead_first_name in sender:
                    print(f"   ✅ Lead's name found in senders!")
                    print(f"   📩 replied already")
                    return True
            # If we found any sender that's not "you", it's a reply
            non_you_senders = [s for s in found_senders if 'you' not in s]
            if non_you_senders:
                print(f"   ✅ Found non-'you' senders: {non_you_senders}")
                print(f"   📩 replied already")
                return True

        # STRATEGY 4: Check raw conversation text for indicators
        try:
            # Get all text in conversation area
            conv_containers = driver.find_elements(By.CSS_SELECTOR,
                ".msg-s-message-list-content, .msg-overlay-conversation-bubble__content")

            for container in conv_containers:
                conv_text = container.text.lower()

                # Check if lead's first name appears (not just in our message)
                lead_first_name = lead_name.lower().split()[0]

                # Count how many times the name appears
                # If it appears more than once (our greeting + their name label), they replied
                if conv_text.count(lead_first_name) > 2:
                    print(f"   ✅ Lead's name appears multiple times in conversation")
                    print(f"   📩 replied already")
                    return True

        except Exception as e:
            pass

        # STRATEGY 5: Count total messages (if more than our initial message)
        try:
            message_selectors = [
                ".msg-s-event-listitem__body",
                ".msg-s-message-group__content",
                "[class*='message-body']",
                ".msg-s-event__content"
            ]

            for selector in message_selectors:
                try:
                    messages = driver.find_elements(By.CSS_SELECTOR, selector)
                    if messages:
                        print(f"   📊 Found {len(messages)} message bodies with selector: {selector}")
                        # If more than 1 message body, there's likely a reply
                        if len(messages) > 1:
                            print(f"   ✅ Multiple message bodies = conversation has replies!")
                            print(f"   📩 replied already")
                            return True
                except:
                    continue
        except:
            pass

        print(f"   ❌ No reply detected from {lead_name}")
        return False

    except Exception as e:
        print(f"   ⚠️ Error detecting reply: {e}")
        import traceback
        traceback.print_exc()
        return False


def check_reply_for_lead(driver, lead_data):
    """
    Check if a specific lead has replied.
    Opens conversation, detects reply, closes dialog.
    """
    name = lead_data['name']
    k = lead_data['position_k']

    print(f"\n💬 Checking reply status for: {name}")
    print(f"   Position K: {k}")
    print(f"   Current status: {lead_data['status']}")

    # Construct message button XPath
    message_button_xpath = f"/html/body/div/div[2]/div[2]/div[2]/div/main/div/div/div[1]/section/div/div[2]/div/div[{k}]/div/div[2]/div/div/a"

    try:
        # Find and click message button
        message_button = driver.find_element(By.XPATH, message_button_xpath)

        # Verify it's a message button
        button_text = message_button.get_attribute("aria-label") or message_button.text
        if not any(keyword in button_text.lower() for keyword in ["message", "nachricht"]):
            print(f"   ⚠️ Button found but not a message button: {button_text}")
            return False

        # Click the message button
        human_move_click(driver, message_button)
        human_pause(3, 4)

        # Detect if they replied
        has_reply = detect_reply_in_conversation(driver, name)

        if has_reply:
            # Update Supabase status
            update_lead_status_to_replied(name)

        # Close dialog
        close_dialog_safely(driver, name)

        return has_reply

    except Exception as e:
        print(f"   ❌ Error checking reply for {name}: {e}")
        # Try to close any open dialog
        if is_dialog_open(driver):
            close_dialog_safely(driver, name)
        return False


def check_all_leads_for_replies(driver, leads_to_check):
    """
    Iterate through all leads and check for replies.
    """
    # Set daily limit
    daily_limit = random.randint(10, 15)
    print(f"\n🚀 Starting reply check (Daily limit: {daily_limit})...")
    print(f"📋 Found {len(leads_to_check)} leads to check")

    # Limit leads to process
    leads_to_process = leads_to_check[:daily_limit]

    if len(leads_to_check) > daily_limit:
        print(f"⚠️ Limiting to {daily_limit} checks today (out of {len(leads_to_check)} available)")

    scroll_to_top(driver)

    replied_count = 0
    no_reply_count = 0
    error_count = 0

    for idx, lead_data in enumerate(leads_to_process):
        try:
            print(f"\n📤 Processing lead {idx + 1}/{len(leads_to_process)}: {lead_data['name']}")

            has_reply = check_reply_for_lead(driver, lead_data)

            if has_reply:
                replied_count += 1
            else:
                no_reply_count += 1

        except Exception as e:
            print(f"❌ Error processing {lead_data.get('name', 'unknown')}: {e}")
            error_count += 1
            continue

        # Human pause between checks
        human_pause(5, 7)

    print(f"\n📊 Reply Check Summary:")
    print(f"   ✅ Replied: {replied_count}")
    print(f"   ❌ No reply: {no_reply_count}")
    print(f"   ⚠️ Errors: {error_count}")
    print(f"   📋 Total processed: {replied_count + no_reply_count + error_count}")

    return replied_count, no_reply_count, error_count

def get_all_linkedin_messages_shadow(driver):
    """
    Extract sender names from LinkedIn conversation thread, including those inside shadow DOM.
    
    Args:
        driver: Selenium WebDriver instance
        
    Returns:
        list: List of sender names as strings
    """
    
    senders = []
    
    # First, try to access shadow DOM
    try:
        shadow_host = driver.find_element(By.CSS_SELECTOR, '#interop-outlet')
        shadow_root = shadow_host.shadow_root
        
        # JavaScript code to find all message elements within shadow DOM and extract sender names
        js_code = """
        return (function(shadowRoot) {
            const senderTexts = [];
            
            // Find all elements that could be message events
            const messageElements = shadowRoot.querySelectorAll('.msg-s-message-list__event');
            
            messageElements.forEach((element) => {
                try {
                    // Look for the msg-s-message-group__meta div which contains sender info
                    const metaDiv = element.querySelector('.msg-s-message-group__meta');
                    
                    if (metaDiv) {
                        // Get all text from the meta div
                        const metaText = metaDiv.innerText.trim();
                        if (metaText) {
                            senderTexts.push(metaText);
                        }
                    }
                } catch (e) {
                    console.error('Error parsing sender:', e);
                }
            });
            
            return senderTexts;
        })(arguments[0]);
        """
        
        shadow_senders = driver.execute_script(js_code, shadow_root)
        if isinstance(shadow_senders, list):
            senders.extend(shadow_senders)
            
    except Exception as e:
        print(f"Could not access shadow DOM: {e}")
    
    # Also check regular DOM for messages
    js_code_regular = """
    return (function() {
        const senderTexts = [];
        const messageElements = document.querySelectorAll('.msg-s-message-list__event');
        
        messageElements.forEach((element) => {
            try {
                // Look for the msg-s-message-group__meta div which contains sender info
                const metaDiv = element.querySelector('.msg-s-message-group__meta');
                
                if (metaDiv) {
                    // Get all text from the meta div
                    const metaText = metaDiv.innerText.trim();
                    if (metaText) {
                        senderTexts.push(metaText);
                    }
                }
            } catch (e) {
                console.error('Error parsing sender:', e);
            }
        });
        
        return senderTexts;
    })();
    """
    
    try:
        regular_senders = driver.execute_script(js_code_regular)
        if isinstance(regular_senders, list):
            senders.extend(regular_senders)
    except Exception as e:
        print(f"Error getting regular DOM messages: {e}")
    
    return senders


def main():
    """
    Main function - Template for experimentation
    Opens LinkedIn, waits 30 seconds, and exits.
    Add your custom code here.
    """

    print("=" * 60)
    print("🧪 LinkedIn Template - Experimentation Mode")
    print("=" * 60)

    # Ensure LinkedIn login
    print("\n🔐 Ensuring LinkedIn login...")
    driver = ensure_linkedin_login()

    if not driver:
        print("❌ Could not establish LinkedIn session. Exiting.")
        return

    print("✅ LinkedIn session established.")

    try:
        # Open LinkedIn
        print("\n🚀 Opening LinkedIn...")
        driver.get("https://www.linkedin.com/messaging")
        log_action(driver, "linkedin_homepage")

        ## messaging1 = /html/body/div[6]/div[3]/div[2]/div/div/main/div/div[2]/div[2]/div[1]/div/div[4]/div[2]/ul/li[4]/div/div[1]/span/a/span
        ## messaging2 = /html/body/div[6]/div[3]/div[2]/div/div/main/div/div[2]/div[2]/div[1]/div/div[4]/div[2]/ul/li[5]/div/div[1]/span/a/span
        ## messaging3 = /html/body/div[6]/div[3]/div[2]/div/div/main/div/div[2]/div[2]/div[1]/div/div[4]/div[2]/ul/li[6]/div/div[1]/span/a/span
        ## messaging4 = /html/body/div[6]/div[3]/div[2]/div/div/main/div/div[2]/div[2]/div[1]/div/div[4]/div[2]/ul/li[7]/div/div[1]/span/a/span
        ## messaging5 = /html/body/div[6]/div[3]/div[2]/div/div/main/div/div[2]/div[2]/div[1]/div/div[4]/div[2]/ul/li[11]/div/div[1]/span/a/span
        ## messaging6 = /html/body/div[6]/div[3]/div[2]/div/div/main/div/div[2]/div[2]/div[1]/div/div[4]/div[1]/ul/li[11]/div/div[1]/span/a/span
        ## messaging7 = /html/body/div[6]/div[3]/div[2]/div/div/main/div/div[2]/div[2]/div[1]/div/div[4]/div[1]/ul/li[13]/div/div[1]/span/a/span
        ## messaging8 = /html/body/div[6]/div[3]/div[2]/div/div/main/div/div[2]/div[2]/div[1]/div/div[4]/div[1]/ul/li[16]/div/div[1]/span/a/span
        ## messaging9 = /html/body/div[6]/div[3]/div[2]/div/div/main/div/div[2]/div[2]/div[1]/div/div[4]/div[1]/ul/li[17]/div/div[1]/span/a/span
       ## messaging10 = /html/body/div[6]/div[3]/div[2]/div/div/main/div/div[2]/div[2]/div[1]/div/div[4]/div[1]/ul/li[19]/div[1]/div[1]/span/a/span
        #driver.execute_script("window.scrollTo(0, 0);")
        #human_pause(1.5,2.5) 
        #driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        
        time.sleep(30)
        # results = get_all_conversations_with_identifiers(driver, debug=True)
        # export_identifiers_to_json(results)
        senders = get_all_linkedin_messages_shadow(driver)
        for sender in senders:
            print(sender)
    
        print("⏳ Waiting 30 seconds...")
        time.sleep(3000)

        print("✅ Done!")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

    finally:
        print("\n🔒 Closing browser session...")
        try:
            driver.quit()
        except:
            pass


if __name__ == "__main__":
    main()



#2 css #interop-outlet
#2 xp /html/body/div/div[4]