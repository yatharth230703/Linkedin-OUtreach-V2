## Follow-up message automation for LinkedIn connections
## Sends follow-up messages (message_2_draft) to leads where:
## - status = "first message sent"
## - last_contacted_at is more than 3 days ago

import os
import time
import random
from datetime import datetime, timedelta
from difflib import SequenceMatcher
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from supabase import create_client, Client
from dotenv import load_dotenv

# Import main automation functions from msg_draft_connection
from msg_draft_connection_bot1 import (
    human_pause, 
    human_scroll, 
    human_move_click, 
    human_sleep_with_activity,
    log_action,
    SUPABASE_URL,
    SUPABASE_KEY,
    supabase
)

# Import proxy session for HTTP requests
from proxy_requests import get_proxy_session 

# Import login functionality
from login_credentials import ensure_linkedin_login 


def validate_lead_match(scraped_name, scraped_headline, db_lead_data, similarity_threshold=0.7):
    """
    Validate that scraped LinkedIn data matches Supabase database entry.
    
    Args:
        scraped_name: Name scraped from LinkedIn
        scraped_headline: Headline scraped from LinkedIn  
        db_lead_data: Lead data from Supabase database
        similarity_threshold: Minimum similarity score (0.0-1.0)
    
    Returns:
        dict: {
            'is_match': bool,
            'confidence': float,
            'reason': str,
            'should_proceed': bool,
            'name_similarity': float,
            'headline_similarity': float
        }
    """
    db_name = db_lead_data.get('full_name', '').strip()
    db_headline = db_lead_data.get('headline', '').strip()
    
    # Name matching (should be exact or very close)
    name_similarity = SequenceMatcher(None, scraped_name.lower(), db_name.lower()).ratio()
    
    # Headline matching (can be more flexible)
    headline_similarity = SequenceMatcher(None, scraped_headline.lower(), db_headline.lower()).ratio()
    
    # Overall confidence score
    confidence = (name_similarity * 0.7) + (headline_similarity * 0.3)
    
    # Determine if it's a match
    is_match = name_similarity > 0.9 and headline_similarity > similarity_threshold
    
    # Determine if we should proceed
    should_proceed = is_match or (name_similarity > 0.95 and headline_similarity > 0.5)
    
    # Reason for decision
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


def update_lead_status_to_followup_sent(full_name, headline):
    """
    Update the status of a lead to "follow-up sent" and set last_contacted_at timestamp in Supabase.
    Matches by full_name only for reliability.
    """
    try:
        # Get current timestamp in ISO format
        current_timestamp = datetime.now().isoformat()
        
        # Update the lead's status and last_contacted_at where full_name matches
        response = supabase.table('leads').update({
            'status': 'follow-up sent',
            'last_contacted_at': current_timestamp
        }).eq('full_name', full_name).execute()
        
        if response.data:
            print(f"✅ Updated status for {full_name} to 'follow-up sent' with timestamp {current_timestamp}")
            return True
        else:
            print(f"⚠️ No matching lead found in database for {full_name}")
            return False
            
    except Exception as e:
        print(f"❌ Error updating status for {full_name}: {e}")
        return False


def get_supabase_followup_leads_data():
    """
    Fetch leads from Supabase that need follow-up messages:
    - status = "first message sent"
    - last_contacted_at is more than 3 days ago
    - has message_2_draft available
    
    Returns a dictionary with full_name as key and lead data as value.
    """
    try:
        print("📊 Fetching follow-up leads data from Supabase...")
        
        # Calculate the cutoff date (3 days ago)
        three_days_ago = (datetime.now() - timedelta(days=3)).isoformat()
        
        # Fetch leads with status "first message sent" and last_contacted_at more than 3 days ago
        response = supabase.table('leads').select(
            'full_name, headline, status, message_2_draft, last_contacted_at'
        ).eq('status', 'first message sent').lt('last_contacted_at', three_days_ago).execute()
        
        leads_data = {}
        eligible_leads = []
        total_leads = 0
        skipped_no_draft = 0
        
        for lead in response.data:
            total_leads += 1
            full_name = lead.get('full_name', '').strip()
            headline = lead.get('headline', '').strip()
            status = lead.get('status', '').strip()
            message_2_draft = lead.get('message_2_draft', '').strip() if lead.get('message_2_draft') else ''
            last_contacted_at = lead.get('last_contacted_at', '')
            
            if full_name:
                # Only include leads that have a message_2_draft
                if message_2_draft:
                    leads_data[full_name] = {
                        'full_name': full_name,
                        'headline': headline,
                        'status': status,
                        'message_2_draft': message_2_draft,
                        'last_contacted_at': last_contacted_at
                    }
                    eligible_leads.append(full_name)
                else:
                    skipped_no_draft += 1
                    print(f"⏭️ Skipping {full_name} - no message_2_draft available")
        
        print(f"✅ Found {total_leads} leads with 'first message sent' status (>3 days ago)")
        print(f"   - {len(eligible_leads)} have message_2_draft available")
        print(f"   - {skipped_no_draft} skipped (no message_2_draft)")
        
        return leads_data, set(eligible_leads)
        
    except Exception as e:
        print(f"❌ Error fetching Supabase data: {e}")
        import traceback
        traceback.print_exc()
        return {}, set()


def scroll_to_top(driver):
    """Scroll back to the top of the connections page"""
    print("⬆️ Scrolling back to top of page...")
    driver.execute_script("window.scrollTo(0, 0);")
    human_pause(2, 4)


def scrape_all_connections_for_followup(driver):
    """
    Multi-level framework to scrape connections and identify leads needing follow-up.
    Only processes connections that exist in Supabase database and need follow-up.
    Returns dictionary with connection data and their positions for messaging.
    
    IMPORTANT: The order of leads_to_message follows the order scraped from LinkedIn
    (top to bottom), NOT the order in Supabase. This ensures sequential messaging.
    Matching is done by full_name only (more reliable than name+headline).
    """
    print("🔍 Starting connection scraping and follow-up lead identification...")
    
    # Get all follow-up leads data from Supabase
    supabase_leads_data, eligible_leads = get_supabase_followup_leads_data()
    
    ## Scrape names
    names_xp = ""
    names_list = []
    i = 1
    while(i < 90):
        try:
            names_xp = f"/html/body/div/div[2]/div[2]/div[2]/div/main/div/div/div[1]/section/div/div[2]/div/div[{i}]/div/div[1]/div/a/div/p/a"
            names = driver.find_element(By.XPATH, names_xp)
            names_list.append(names.text.strip())
            i += 2
        except:
            print(f"📋 Reached end of names at position {i}")
            break 
    
    print(f"✅ Found {len(names_list)} names") 
    print("*" * 80)
    human_pause(3, 5)
    
    ## Scrape headlines
    headlines_xp = ""
    headline_list = []
    j = 1
    while(j < 90):
        try:
            headlines_xp = f"/html/body/div/div[2]/div[2]/div[2]/div/main/div/div/div[1]/section/div/div[2]/div/div[{j}]/div/div[1]/div/a/div/div/p"
            headlines = driver.find_element(By.XPATH, headlines_xp)
            headline_list.append(headlines.text.strip())
            j += 2
        except Exception as e:
            print(f"📋 Reached end of headlines at position {j}")
            break 
    
    print(f"✅ Found {len(headline_list)} headlines")
    print("*" * 80)
    human_pause(3, 5)
    
    # Create combined dictionary and identify leads to message
    # Using list to maintain order from LinkedIn page (top to bottom)
    connections_dict = {}
    leads_to_message = []  # Changed to list to preserve order
    skipped_not_in_db = 0
    skipped_not_eligible = 0
    skipped_poor_match = 0
    
    # Ensure both lists have same length (take minimum)
    min_length = min(len(names_list), len(headline_list))
    
    for idx in range(min_length):
        name = names_list[idx]
        headline = headline_list[idx]
        
        # Calculate position value k (since i and j increment by 2, k = 2*idx + 1)
        k = 2 * idx + 1
        
        # Check if this connection exists in Supabase database (by name only)
        if name not in supabase_leads_data:
            skipped_not_in_db += 1
            continue
        
        # Get lead data from Supabase
        lead_db_data = supabase_leads_data[name]
        
        # Validate that scraped data matches database data
        validation_result = validate_lead_match(name, headline, lead_db_data)
        
        if not validation_result['should_proceed']:
            print(f"⚠️ Skipping {name} - {validation_result['reason']}")
            print(f"   Scraped headline: {headline}")
            print(f"   Database headline: {lead_db_data['headline']}")
            skipped_poor_match += 1
            continue
        
        if not validation_result['is_match']:
            print(f"🔍 Proceeding with caution for {name} - {validation_result['reason']}")
            print(f"   Scraped headline: {headline}")
            print(f"   Database headline: {lead_db_data['headline']}")
        
        connection_data = {
            'name': name,
            'headline': headline,  # Use scraped headline for display
            'headline_db': lead_db_data['headline'],  # Store DB headline for reference
            'position_k': k,
            'message_2_draft': lead_db_data['message_2_draft'],
            'status': lead_db_data['status'],
            'last_contacted_at': lead_db_data['last_contacted_at'],
            'validation_result': validation_result  # Store validation info
        }
        
        # Check if this lead is eligible for follow-up
        if name in eligible_leads:
            # Append to list to maintain order from LinkedIn page
            leads_to_message.append(connection_data)
            print(f"🎯 Follow-up lead identified (position {k}): {name}")
            print(f"   📅 Last contacted: {lead_db_data['last_contacted_at']}")
            print(f"   🎯 Match confidence: {validation_result['confidence']:.2f}")
            if lead_db_data['message_2_draft']:
                print(f"   📝 Follow-up message: {lead_db_data['message_2_draft'][:50]}...")
        else:
            skipped_not_eligible += 1
        
        connections_dict[name] = connection_data
    
    print(f"\n📊 Summary:")
    print(f"   Total connections scraped: {min_length}")
    print(f"   Skipped (not in database): {skipped_not_in_db}")
    print(f"   Skipped (poor match): {skipped_poor_match}")
    print(f"   Found in database: {len(connections_dict)}")
    print(f"   Not eligible for follow-up: {skipped_not_eligible}")
    print(f"   Leads needing follow-up: {len(leads_to_message)}")
    
    if leads_to_message:
        print(f"\n📋 Follow-up message order (top to bottom):")
        for i, lead in enumerate(leads_to_message, 1):
            print(f"   {i}. {lead['name']} (position k={lead['position_k']})")
    
    return connections_dict, leads_to_message


def message_relay(driver, message_text, lead_name):
    """
    Handle the actual messaging process after message button is clicked.
    Types message and sends using Ctrl+Enter, then closes dialog with Escape.
    """
    from selenium.webdriver.common.keys import Keys
    
    try:
        print(f"📝 Starting message relay for {lead_name}")
        
        # Wait for message dialog to load
        human_pause(3, 4)
        
        # Use ActionChains to type the message directly (dialog should be focused)
        actions = ActionChains(driver)
        
        print(f"   ⌨️ Typing message via ActionChains...")
        
        # Type the message with human-like character delays
        for char in message_text:
            actions = ActionChains(driver)
            actions.send_keys(char).perform()
            if random.random() < 0.1:  # 10% chance of brief pause
                time.sleep(random.uniform(0.05, 0.15))
        
        print(f"   ✅ Message typed for {lead_name}")
        human_pause(2, 3)
        
        # Send message using Ctrl+Enter
        print(f"   📤 Sending message via Ctrl+Enter...")
        actions = ActionChains(driver)
        actions.send_keys(Keys.RETURN).perform()
        
        print(f"   ✅ Message sent to {lead_name}")
        human_pause(2, 3)
        
        # Close the dialog using Escape key
        close_dialog_safely(driver, lead_name)
        
        return True
        
    except Exception as e:
        print(f"❌ Error in message relay for {lead_name}: {e}")
        import traceback
        traceback.print_exc()
        
        # Try to close any open dialog before returning
        close_dialog_safely(driver, lead_name)
        return False


def close_dialog_safely(driver, lead_name):
    """
    Safely close the message dialog and verify it's closed.
    Uses multiple methods to ensure the dialog doesn't block subsequent interactions.
    """
    from selenium.webdriver.common.keys import Keys
    
    print(f"   🚪 Closing message dialog for {lead_name}...")
    
    # Method 1: Press Escape key
    try:
        actions = ActionChains(driver)
        actions.send_keys(Keys.ESCAPE).perform()
        human_pause(1, 2)
        print(f"   ✅ Pressed Escape to close dialog")
    except Exception as e:
        print(f"   ⚠️ Escape key failed: {e}")
    
    # Verify dialog is closed by checking if dialog elements still exist
    dialog_still_open = is_dialog_open(driver)
    
    if dialog_still_open:
        print(f"   ⚠️ Dialog still open, trying additional close methods...")
        
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
                close_button = driver.find_element(By.CSS_SELECTOR, selector)
                if close_button.is_displayed():
                    driver.execute_script("arguments[0].click();", close_button)
                    human_pause(1, 2)
                    print(f"   ✅ Closed via button: {selector}")
                    break
            except:
                continue
        
        # Check again
        dialog_still_open = is_dialog_open(driver)
    
    if dialog_still_open:
        print(f"   ⚠️ Dialog still open, trying to click outside...")
        
        # Method 3: Click outside the dialog (on the main page area)
        try:
            # Click on the connections list area to dismiss the dialog
            page_body = driver.find_element(By.TAG_NAME, "body")
            driver.execute_script("arguments[0].click();", page_body)
            human_pause(1, 2)
        except:
            pass
        
        # Check again
        dialog_still_open = is_dialog_open(driver)
    
    if dialog_still_open:
        print(f"   ⚠️ Dialog still open, pressing Escape again...")
        
        # Method 4: Press Escape multiple times
        try:
            for _ in range(3):
                actions = ActionChains(driver)
                actions.send_keys(Keys.ESCAPE).perform()
                human_pause(0.5, 1)
        except:
            pass
        
        dialog_still_open = is_dialog_open(driver)
    
    if dialog_still_open:
        print(f"   ❌ Could not close dialog for {lead_name}, may affect next lead")
    else:
        print(f"   ✅ Dialog closed successfully for {lead_name}")
    
    # Final pause to let UI settle
    human_pause(1, 2)
    return not dialog_still_open


def is_dialog_open(driver):
    """
    Check if a message dialog is currently open.
    Returns True if dialog is open, False otherwise.
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


def send_followup_to_lead(driver, lead_data):
    """
    Send follow-up message to a specific lead using the message_relay function.
    """
    print(f"💬 Preparing to send follow-up message to: {lead_data['name']}")
    print(f"   Position K: {lead_data['position_k']}")
    print(f"   Headline: {lead_data['headline']}")
    print(f"   Last contacted: {lead_data['last_contacted_at']}")
    
    # Get the follow-up message draft for this lead
    message_text = lead_data.get('message_2_draft', '')
    
    if not message_text:
        print(f"⚠️ No follow-up message draft found for {lead_data['name']}")
        return False
    
    print(f"   📝 Follow-up message: {message_text[:100]}...")
    
    # Call message relay to handle the actual messaging
    success = message_relay(driver, message_text, lead_data['name'])
    
    if success:
        # Update status in Supabase after successful message
        db_success = update_lead_status_to_followup_sent(lead_data['name'], lead_data['headline'])
        return db_success
    
    return False


def message_all_followup_leads(driver, leads_to_message):
    """
    Iterate through all identified leads and send follow-up messages using their position values.
    Processes leads in order from top to bottom as they appear on LinkedIn page.
    """
    # Set daily limit randomly between 10-15 messages
    daily_limit = random.randint(10, 15)
    print(f"🚀 Starting to send follow-up messages (Daily limit: {daily_limit})...")
    print(f"📋 Found {len(leads_to_message)} leads available for follow-up")
    
    # Limit the leads to process based on daily limit
    leads_to_process = leads_to_message[:daily_limit]
    
    if len(leads_to_message) > daily_limit:
        print(f"⚠️ Limiting to {daily_limit} follow-ups today (out of {len(leads_to_message)} available)")
    
    scroll_to_top(driver)
    
    successful_messages = 0
    failed_messages = 0
    
    # leads_to_process is now a list, maintaining order from LinkedIn page
    for idx, lead_data in enumerate(leads_to_process):
        try:
            name = lead_data['name']
            print(f"\n📤 Processing follow-up lead {idx + 1}/{len(leads_to_process)}: {name}")
            
            k = lead_data['position_k']
            
            # Construct message button XPath using position k - try both English and German
            message_button_xpath = f"/html/body/div/div[2]/div[2]/div[2]/div/main/div/div/div[1]/section/div/div[2]/div/div[{k}]/div/div[2]/div/div/a"
            
            try:
                # Find and click the message button
                message_button = driver.find_element(By.XPATH, message_button_xpath)
                
                # Verify it's actually a message button (English or German)
                button_text = message_button.get_attribute("aria-label") or message_button.text
                if not any(keyword in button_text.lower() for keyword in ["message", "nachricht"]):
                    print(f"⚠️ Button found but not a message button: {button_text}")
                    failed_messages += 1
                    continue
                
                # Human-like click
                human_move_click(driver, message_button)
                human_pause(3, 4)
                
                # Call the follow-up message sending function
                success = send_followup_to_lead(driver, lead_data)
                
                if success:
                    successful_messages += 1
                    print(f"✅ Successfully processed follow-up message for {name}")
                else:
                    failed_messages += 1
                    print(f"❌ Failed to send follow-up message to {name}")
                
            except Exception as e:
                print(f"❌ Error clicking message button for {name}: {e}")
                failed_messages += 1
                continue
                
            # Add delay between messages to avoid rate limiting
            human_pause(5, 7)
            
        except Exception as e:
            print(f"❌ Error processing lead {lead_data.get('name', 'unknown')}: {e}")
            failed_messages += 1
            continue
    
    print(f"\n📊 Follow-up Messaging Summary:")
    print(f"   Successful: {successful_messages}")
    print(f"   Failed: {failed_messages}")
    print(f"   Total processed: {successful_messages + failed_messages}")
    
    return successful_messages, failed_messages


def main():
    """Navigate to LinkedIn connections page and send follow-up messages"""
    
    # Ensure LinkedIn login before starting bot operations
    print("🔐 Ensuring LinkedIn login...")
    driver = ensure_linkedin_login()
    
    if not driver:
        print("❌ Could not establish LinkedIn session. Exiting.")
        return
    
    print("✅ LinkedIn session established. Starting follow-up bot...")

    try:
        print("🚀 Opening LinkedIn for follow-up messages...")
        driver.get("https://www.linkedin.com/")
        
        log_action(driver, "linkedin_homepage")
        human_pause(3, 5)
        
        print("✅ Session Active. Ready to navigate to connections.")
        human_scroll(driver)

        # Navigate to the connections page
        connections_url = "https://www.linkedin.com/mynetwork/invite-connect/connections/"
        print(f"🔗 Navigating to: {connections_url}")
        
        driver.get(connections_url)
        human_pause(4, 7)
        
        log_action(driver, "connections_page")
        print("✅ Successfully reached connections page!")
        
        # Scrape connections and identify leads needing follow-up
        connections_dict, leads_to_message = scrape_all_connections_for_followup(driver)
        
        if leads_to_message:
            print(f"\n🎯 Found {len(leads_to_message)} leads needing follow-up messages!")
            
            # Start follow-up messaging process
            successful, failed = message_all_followup_leads(driver, leads_to_message)
            
            print(f"\n🏁 Follow-up messaging campaign completed!")
            print(f"   ✅ Successful follow-ups: {successful}")
            print(f"   ❌ Failed follow-ups: {failed}")
        else:
            print("\n📭 No leads need follow-up messages at this time.")
            print("   Either all leads have been followed up, or it hasn't been 3 days yet.")

    except Exception as e:
        print(f"❌ Critical Script Error: {e}")
        import traceback
        traceback.print_exc()
        log_action(driver, "critical_failure")
        
    finally:
        print("🔒 Closing browser session...")
        try:
            driver.quit()
        except:
            pass


if __name__ == "__main__":
    main()
