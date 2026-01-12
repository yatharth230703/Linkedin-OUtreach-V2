## since connections are a dynamically updated value I will not download a static version I will dynamically scrape them 

## scrape connections , tally against supabase entries, generate final list and iterate through all leads connections 

import os
import time
import random
from datetime import datetime
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from supabase import create_client, Client
from dotenv import load_dotenv

# Import main automation functions from msg_draft_connection
from msg_draft_connection import (
    human_pause, 
    human_scroll, 
    human_move_click, 
    human_sleep_with_activity,
    log_action,
    SUPABASE_URL,
    SUPABASE_KEY,
    supabase
) 


def scrape_all_connections(driver):
    """
    Scrape all connections from LinkedIn connections page with infinite scrolling support.
    Returns a dictionary with connection data.
    """
    print("🔍 Starting to scrape connections...")
    
    connections_dict = {}
    seen_profiles = set()  # Track unique profiles to avoid duplicates
    scroll_attempts = 0
    max_scroll_attempts = 50  # Prevent infinite loops
    no_new_connections_count = 0
    max_no_new_count = 5  # Stop if no new connections found after 5 scrolls
    
    while scroll_attempts < max_scroll_attempts and no_new_connections_count < max_no_new_count:
        try:
            # Find all connection cards on current view
            connection_elements = driver.find_elements(
                By.XPATH, 
                "//li[contains(@class, 'mn-connection-card')]"
            )
            
            # Alternative selectors in case the main one doesn't work
            if not connection_elements:
                connection_elements = driver.find_elements(
                    By.XPATH,
                    "//div[contains(@class, 'mn-connection-card')]"
                )
            
            if not connection_elements:
                connection_elements = driver.find_elements(
                    By.XPATH,
                    "//li[contains(@class, 'connection-card')]"
                )
            
            initial_count = len(connections_dict)
            
            print(f"   📋 Found {len(connection_elements)} connection elements on screen")
            
            # Process each connection element
            for element in connection_elements:
                try:
                    connection_data = {}
                    
                    # Extract name
                    name_elem = element.find_element(By.XPATH, ".//span[contains(@class, 'mn-connection-card__name')]")
                    if not name_elem:
                        name_elem = element.find_element(By.XPATH, ".//a[contains(@class, 'mn-connection-card__link')]")
                    
                    full_name = name_elem.text.strip()
                    
                    # Skip if we've already processed this person
                    if full_name in seen_profiles:
                        continue
                    
                    seen_profiles.add(full_name)
                    connection_data['full_name'] = full_name
                    
                    # Extract LinkedIn profile URL
                    try:
                        profile_link = element.find_element(By.XPATH, ".//a[contains(@href, '/in/')]")
                        linkedin_url = profile_link.get_attribute('href')
                        # Clean the URL (remove query parameters)
                        if '?' in linkedin_url:
                            linkedin_url = linkedin_url.split('?')[0]
                        connection_data['linkedin_url'] = linkedin_url
                    except:
                        connection_data['linkedin_url'] = "URL not found"
                    
                    # Extract headline/title
                    try:
                        headline_elem = element.find_element(By.XPATH, ".//span[contains(@class, 'mn-connection-card__occupation')]")
                        connection_data['headline'] = headline_elem.text.strip()
                    except:
                        connection_data['headline'] = "Headline not available"
                    
                    # Extract company (if available)
                    try:
                        company_elem = element.find_element(By.XPATH, ".//span[contains(@class, 'mn-connection-card__company')]")
                        connection_data['company'] = company_elem.text.strip()
                    except:
                        connection_data['company'] = "Company not available"
                    
                    # Extract connection date (if available)
                    try:
                        date_elem = element.find_element(By.XPATH, ".//time")
                        connection_data['connected_date'] = date_elem.get_attribute('datetime')
                    except:
                        connection_data['connected_date'] = "Date not available"
                    
                    # Use full name as key (could also use LinkedIn URL)
                    connections_dict[full_name] = connection_data
                    
                except Exception as e:
                    print(f"   ⚠️ Error processing connection element: {e}")
                    continue
            
            new_connections_found = len(connections_dict) - initial_count
            print(f"   ✅ Processed {new_connections_found} new connections (Total: {len(connections_dict)})")
            
            # Check if we found new connections
            if new_connections_found == 0:
                no_new_connections_count += 1
                print(f"   ⏳ No new connections found. Attempt {no_new_connections_count}/{max_no_new_count}")
            else:
                no_new_connections_count = 0  # Reset counter if we found new connections
            
            # Scroll down to load more connections
            print("   ⬇️ Scrolling to load more connections...")
            
            # Scroll to bottom of page
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            human_pause(2, 4)
            
            # Additional scroll with random offset for human-like behavior
            human_scroll(driver, max_offset=200)
            human_pause(1, 2)
            
            scroll_attempts += 1
            
            # Check if we've reached the end (look for "end of connections" indicator)
            try:
                end_indicators = driver.find_elements(
                    By.XPATH, 
                    "//*[contains(text(), 'You've reached the end') or contains(text(), 'No more connections')]"
                )
                if end_indicators:
                    print("   🏁 Reached end of connections list")
                    break
            except:
                pass
                
        except Exception as e:
            print(f"   ❌ Error during scrolling iteration {scroll_attempts}: {e}")
            scroll_attempts += 1
            human_pause(2, 3)
            continue
    
    print(f"\n🎉 Scraping complete! Found {len(connections_dict)} total connections")
    print(f"📊 Scroll attempts: {scroll_attempts}")
    
    return connections_dict


def update_lead_status_to_sent(full_name, headline):
    """
    Update the status of a lead to "first message sent" in Supabase.
    Matches by full_name only for reliability.
    """
    try:
        # Update the lead's status where full_name matches
        response = supabase.table('leads').update({
            'status': 'first message sent'
        }).eq('full_name', full_name).execute()
        
        if response.data:
            print(f"✅ Updated status for {full_name} to 'first message sent'")
            return True
        else:
            print(f"⚠️ No matching lead found in database for {full_name}")
            return False
            
    except Exception as e:
        print(f"❌ Error updating status for {full_name}: {e}")
        return False


def get_supabase_leads_data():
    """
    Fetch all leads from Supabase with their full_name, headline, status, and message_1_draft.
    Returns a dictionary with full_name as key and lead data as value.
    """
    try:
        print("📊 Fetching all leads data from Supabase...")
        response = supabase.table('leads').select('full_name, headline, status, message_1_draft').execute()
        
        leads_data = {}
        contacted_leads = set()
        total_leads = 0
        
        for lead in response.data:
            total_leads += 1
            full_name = lead.get('full_name', '').strip()
            headline = lead.get('headline', '').strip()
            status = lead.get('status', '').strip()
            message_1_draft = lead.get('message_1_draft', '').strip() if lead.get('message_1_draft') else ''
            
            if full_name:
                # Store lead data using full_name as key (more reliable matching)
                leads_data[full_name] = {
                    'full_name': full_name,
                    'headline': headline,
                    'status': status,
                    'message_1_draft': message_1_draft
                }
                
                # Track contacted leads separately
                if status == "first message sent":
                    contacted_leads.add(full_name)
        
        print(f"✅ Found {total_leads} total leads in database")
        print(f"   - {len(contacted_leads)} with 'first message sent' status")
        print(f"   - {len(leads_data) - len(contacted_leads)} available for messaging")
        
        return leads_data, contacted_leads
        
    except Exception as e:
        print(f"❌ Error fetching Supabase data: {e}")
        return {}, set()


def scroll_to_top(driver):
    """Scroll back to the top of the connections page"""
    print("⬆️ Scrolling back to top of page...")
    driver.execute_script("window.scrollTo(0, 0);")
    human_pause(2, 4)


def scrape_all_connections_brute(driver):
    """
    Multi-level framework to scrape connections and identify leads to message.
    Only processes connections that exist in Supabase database.
    Returns dictionary with connection data and their positions for messaging.
    
    IMPORTANT: The order of leads_to_message follows the order scraped from LinkedIn
    (top to bottom), NOT the order in Supabase. This ensures sequential messaging.
    Matching is done by full_name only (more reliable than name+headline).
    """
    print("🔍 Starting connection scraping and lead identification...")
    
    # Get all leads data from Supabase
    supabase_leads_data, contacted_leads = get_supabase_leads_data()
    
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
    
    # Ensure both lists have same length (take minimum)
    min_length = min(len(names_list), len(headline_list))
    
    for idx in range(min_length):
        name = names_list[idx]
        headline = headline_list[idx]
        
        # Calculate position value k (since i and j increment by 2, k = 2*idx + 1)
        k = 2 * idx + 1
        
        # Check if this connection exists in Supabase database (by name only)
        if name not in supabase_leads_data:
            print(f"⏭️ Skipping {name} - not found in Supabase database")
            skipped_not_in_db += 1
            continue
        
        # Get lead data from Supabase
        lead_db_data = supabase_leads_data[name]
        
        connection_data = {
            'name': name,
            'headline': headline,  # Use scraped headline for display
            'headline_db': lead_db_data['headline'],  # Store DB headline for reference
            'position_k': k,
            'contacted': False,
            'message_1_draft': lead_db_data['message_1_draft'],
            'status': lead_db_data['status']
        }
        
        # Check if this lead has been contacted before (status = "first message sent")
        if name in contacted_leads:
            connection_data['contacted'] = True
            print(f"⏭️ Skipping {name} - already has 'first message sent' status")
        else:
            # Append to list to maintain order from LinkedIn page
            leads_to_message.append(connection_data)
            print(f"🎯 New lead identified (position {k}): {name} - needs first message")
            if lead_db_data['message_1_draft']:
                print(f"   📝 Message draft: {lead_db_data['message_1_draft'][:50]}...")
        
        connections_dict[name] = connection_data
    
    print(f"\n📊 Summary:")
    print(f"   Total connections scraped: {min_length}")
    print(f"   Skipped (not in database): {skipped_not_in_db}")
    print(f"   Found in database: {len(connections_dict)}")
    print(f"   Previously contacted: {len(connections_dict) - len(leads_to_message)}")
    print(f"   New leads to message: {len(leads_to_message)}")
    
    if leads_to_message:
        print(f"\n📋 Message order (top to bottom):")
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
        actions.key_down(Keys.CONTROL).send_keys(Keys.RETURN).key_up(Keys.CONTROL).perform()
        
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
        
        # Method 2: Try clicking the close button
        close_selectors = [
            ".msg-overlay-bubble-header__control--close-btn",
            "button[aria-label='Close your conversation']",
            "button[aria-label*='Close']",
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


def find_send_button(driver):
    """Helper function to find the send button with multiple selectors"""
    send_selectors = [
        ".msg-form__send-button",
        "button.msg-form__send-button",
        "button[type='submit']",
        "button[data-control-name='send']",
    ]
    
    xpath_selectors = [
        "//button[contains(@class, 'msg-form__send')]",
        "//button[contains(text(), 'Send')]"
    ]
    
    # Try CSS selectors first
    for selector in send_selectors:
        try:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            for elem in elements:
                if elem.is_displayed() and elem.is_enabled():
                    print(f"   ✅ Found send button via: {selector}")
                    return elem
        except:
            continue
    
    # Try XPath selectors
    for xpath in xpath_selectors:
        try:
            elements = driver.find_elements(By.XPATH, xpath)
            for elem in elements:
                if elem.is_displayed() and elem.is_enabled():
                    print(f"   ✅ Found send button via XPath: {xpath}")
                    return elem
        except:
            continue
    
    return None


def close_message_dialog(driver, lead_name):
    """Helper function to close the message dialog"""
    close_selectors = [
        ".msg-overlay-bubble-header__control--close-btn",
        "button[aria-label='Close your conversation']",
        "button[aria-label*='Close']",
        ".artdeco-modal__dismiss"
    ]
    
    xpath_selectors = [
        "//button[contains(@class, 'msg-overlay-bubble-header__control') and contains(@aria-label, 'Close')]",
        "/html/body/div/div[4]//div/div[3]/div/aside[1]/div[2]/div[1]/header/div[3]/button[2]"
    ]
    
    # Try CSS selectors first
    for selector in close_selectors:
        try:
            close_button = driver.find_element(By.CSS_SELECTOR, selector)
            if close_button.is_displayed():
                human_move_click(driver, close_button)
                print(f"   ✅ Closed message dialog for {lead_name}")
                human_pause(1, 2)
                return True
        except:
            continue
    
    # Try XPath selectors
    for xpath in xpath_selectors:
        try:
            close_button = driver.find_element(By.XPATH, xpath)
            if close_button.is_displayed():
                human_move_click(driver, close_button)
                print(f"   ✅ Closed message dialog via XPath for {lead_name}")
                human_pause(1, 2)
                return True
        except:
            continue
    
    print(f"   ⚠️ Could not find close button for {lead_name}")
    return False


def send_message_to_lead(driver, lead_data):
    """
    Send message to a specific lead using the message_relay function.
    """
    print(f"💬 Preparing to send message to: {lead_data['name']}")
    print(f"   Position K: {lead_data['position_k']}")
    print(f"   Headline: {lead_data['headline']}")
    
    # Get the message draft for this lead
    message_text = lead_data.get('message_1_draft', '')
    
    if not message_text:
        print(f"⚠️ No message draft found for {lead_data['name']}")
        return False
    
    print(f"   📝 Message: {message_text[:100]}...")
    
    # Call message relay to handle the actual messaging
    success = message_relay(driver, message_text, lead_data['name'])
    
    if success:
        # Update status in Supabase after successful message
        db_success = update_lead_status_to_sent(lead_data['name'], lead_data['headline'])
        return db_success
    
    return False


def message_all_leads(driver, leads_to_message):
    """
    Iterate through all identified leads and send messages using their position values.
    Processes leads in order from top to bottom as they appear on LinkedIn page.
    """
    print(f"🚀 Starting to message {len(leads_to_message)} leads...")
    
    scroll_to_top(driver)
    
    successful_messages = 0
    failed_messages = 0
    
    # leads_to_message is now a list, maintaining order from LinkedIn page
    for idx, lead_data in enumerate(leads_to_message):
        try:
            name = lead_data['name']
            print(f"\n📤 Processing lead {idx + 1}/{len(leads_to_message)}: {name}")
            
            k = lead_data['position_k']
            
            # Construct message button XPath using position k       
            message_button_xpath = f"/html/body/div/div[2]/div[2]/div[2]/div/main/div/div/div[1]/section/div/div[2]/div/div[{k}]/div/div[2]/div/div/a"
            
            try:
                # Find and click the message button
                message_button = driver.find_element(By.XPATH, message_button_xpath)
                
                # Human-like click
                human_move_click(driver, message_button)
                human_pause(3, 4)
                
                # Call the message sending function
                success = send_message_to_lead(driver, lead_data)
                
                if success:
                    successful_messages += 1
                    print(f"✅ Successfully processed message for {name}")
                else:
                    failed_messages += 1
                    print(f"❌ Failed to send message to {name}")
                
            except Exception as e:
                print(f"❌ Error clicking message button for {name}: {e}")
                failed_messages += 1
                continue
                
            # Add delay between messages to avoid rate limiting
            human_pause(3, 6)
            
        except Exception as e:
            print(f"❌ Error processing lead {lead_data.get('name', 'unknown')}: {e}")
            failed_messages += 1
            continue
    
    print(f"\n📊 Messaging Summary:")
    print(f"   Successful: {successful_messages}")
    print(f"   Failed: {failed_messages}")
    print(f"   Total processed: {successful_messages + failed_messages}")
    
    return successful_messages, failed_messages
    
    



def main():
    """Navigate to LinkedIn connections page using the same automation setup"""
    
    # Copy exact Chrome options from msg_draft_connection.py
    options = uc.ChromeOptions()
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    user_data_path = os.path.join(script_dir, "user_data")
    options.add_argument(f"--user-data-dir={user_data_path}")
    
    options.add_argument('--ignore-certificate-errors')
    options.add_argument('--ignore-ssl-errors')
    options.add_argument('--disable-webrtc')
    options.set_capability('acceptInsecureCerts', True)

    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ]
    options.add_argument(f'--user-agent={user_agents[0]}')

    driver = uc.Chrome(options=options)

    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })

    try:
        print("🚀 Opening LinkedIn...")
        driver.get("https://www.linkedin.com/")
        
        log_action(driver, "linkedin_homepage")
        human_pause(3, 5)

        # Check if user is logged in (same logic as original)
        if "feed" not in driver.current_url and ("login" in driver.current_url or "signup" in driver.current_url):
            print("⚠️ User is NOT logged in.")
            print("👉 Please log in manually in the browser window now.")
            print("👉 Press ENTER in this terminal once you see your LinkedIn Feed...")
            input()
        
        print("✅ Session Active. Ready to navigate to connections.")
        human_scroll(driver)

        # Navigate to the connections page
        connections_url = "https://www.linkedin.com/mynetwork/invite-connect/connections/"
        print(f"🔗 Navigating to: {connections_url}")
        
        driver.get(connections_url)
        human_pause(4, 7)
        
        log_action(driver, "connections_page")
        print("✅ Successfully reached connections page!")
        
        # Scrape connections and identify leads to message
        connections_dict, leads_to_message = scrape_all_connections_brute(driver)
        
        if leads_to_message:
            print(f"\n🎯 Found {len(leads_to_message)} new leads to message!")
            
            # Start messaging process
            successful, failed = message_all_leads(driver, leads_to_message)
            
            print(f"\n🏁 Messaging campaign completed!")
            print(f"   ✅ Successful messages: {successful}")
            print(f"   ❌ Failed messages: {failed}")
        else:
            print("\n📭 No new leads to message. All connections have been contacted previously.")

    except Exception as e:
        print(f"❌ Critical Script Error: {e}")
        log_action(driver, "critical_failure")
        
    finally:
        print("🔒 Closing browser session...")
        try:
            driver.quit()
        except:
            pass


if __name__ == "__main__":
    main()