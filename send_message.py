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


def update_lead_status_to_sent(name, headline):
    """
    Update the status of a lead to "first message sent" in Supabase.
    """
    try:
        # Update the lead's status where name and headline match
        response = supabase.table('leads').update({
            'status': 'first message sent'
        }).eq('name', name).eq('headline', headline).execute()
        
        if response.data:
            print(f"✅ Updated status for {name} to 'first message sent'")
            return True
        else:
            print(f"⚠️ No matching lead found in database for {name}")
            return False
            
    except Exception as e:
        print(f"❌ Error updating status for {name}: {e}")
        return False


def get_supabase_contacted_leads():
    """
    Fetch leads that have status "first message sent" from Supabase.
    Returns a set of (name, headline) tuples for leads already contacted.
    """
    try:
        print("📊 Fetching contacted leads from Supabase...")
        response = supabase.table('leads').select('name, headline, status').execute()
        
        contacted_leads = set()
        total_leads = 0
        
        for lead in response.data:
            total_leads += 1
            name = lead.get('name', '').strip()
            headline = lead.get('headline', '').strip()
            status = lead.get('status', '').strip()
            
            # Only consider leads with "first message sent" status as contacted
            if name and headline and status == "first message sent":
                contacted_leads.add((name, headline))
        
        print(f"✅ Found {len(contacted_leads)} leads with 'first message sent' status out of {total_leads} total leads")
        return contacted_leads
        
    except Exception as e:
        print(f"❌ Error fetching Supabase data: {e}")
        return set()


def scrape_all_connections_brute(driver):
    """
    Multi-level framework to scrape connections and identify leads to message.
    Returns dictionary with connection data and their positions for messaging.
    """
    print("🔍 Starting connection scraping and lead identification...")
    
    # Get previously contacted leads from Supabase
    contacted_leads = get_supabase_contacted_leads()
    
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
    connections_dict = {}
    leads_to_message = {}
    
    # Ensure both lists have same length (take minimum)
    min_length = min(len(names_list), len(headline_list))
    
    for idx in range(min_length):
        name = names_list[idx]
        headline = headline_list[idx]
        
        # Calculate position value k (since i and j increment by 2, k = 2*idx + 1)
        k = 2 * idx + 1
        
        connection_data = {
            'name': name,
            'headline': headline,
            'position_k': k,
            'contacted': False
        }
        
        # Check if this lead has been contacted before (status = "first message sent")
        if (name, headline) in contacted_leads:
            connection_data['contacted'] = True
            print(f"⏭️ Skipping {name} - already has 'first message sent' status")
        else:
            leads_to_message[name] = connection_data
            print(f"🎯 New lead identified: {name} - needs first message")
        
        connections_dict[name] = connection_data
    
    print(f"\n📊 Summary:")
    print(f"   Total connections found: {len(connections_dict)}")
    print(f"   Previously contacted: {len(connections_dict) - len(leads_to_message)}")
    print(f"   New leads to message: {len(leads_to_message)}")
    
    return connections_dict, leads_to_message


def scroll_to_top(driver):
    """Scroll back to the top of the connections page"""
    print("⬆️ Scrolling back to top of page...")
    driver.execute_script("window.scrollTo(0, 0);")
    human_pause(2, 4)


def send_message_to_lead(driver, lead_data):
    """
    Boilerplate function to send message to a specific lead.
    This will be implemented later with actual messaging logic.
    """
    print(f"💬 Preparing to send message to: {lead_data['name']}")
    print(f"   Position K: {lead_data['position_k']}")
    print(f"   Headline: {lead_data['headline']}")
    
    # TODO: Implement actual messaging logic here
    # This is where you'll add the message composition and sending functionality
    
    # For now, simulate successful message sending
    human_pause(1, 2)
    
    # Update status in Supabase after successful message
    success = update_lead_status_to_sent(lead_data['name'], lead_data['headline'])
    
    return success


def message_all_leads(driver, leads_to_message):
    """
    Iterate through all identified leads and send messages using their position values.
    """
    print(f"🚀 Starting to message {len(leads_to_message)} leads...")
    
    scroll_to_top(driver)
    
    successful_messages = 0
    failed_messages = 0
    
    for name, lead_data in leads_to_message.items():
        try:
            print(f"\n📤 Processing lead {successful_messages + failed_messages + 1}/{len(leads_to_message)}: {name}")
            
            k = lead_data['position_k']
            
            # Construct message button XPath using position k       
            message_button_xpath = f"/html/body/div/div[2]/div[2]/div[2]/div/main/div/div/div[1]/section/div/div[2]/div/div[{k}]/div/div[2]/div/div/a"
                                     #/html/body/div/div[2]/div[2]/div[2]/div/main/div/div/div[1]/section/div/div[2]/div/div[1]/div/div[2]/
            try:
                # Find and click the message button
                message_button = driver.find_element(By.XPATH, message_button_xpath)
                
                # Human-like click
                human_move_click(driver, message_button)
                human_pause(1, 2)
                
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
            print(f"❌ Error processing lead {name}: {e}")
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