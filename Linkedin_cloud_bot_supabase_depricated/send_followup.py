## Follow-up message automation for LinkedIn connections
## Sends follow-up messages (message_2_draft) to leads where:
## - status = "first message sent"
## - last_contacted_at is more than 3 days ago

import os
import time
import random
import json
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


def determine_next_followup_message(lead_data):
    """
    Determine which follow-up message to send next based on status.
    
    Status progression:
    - "first message sent" -> send message_2_draft (follow-up 1)
    - "follow-up 1 sent" -> send message_3_draft (follow-up 2)
    - "follow-up 2 sent" -> send message_4_draft (follow-up 3)
    - "follow-up 3 sent" -> send message_5_draft (follow-up 4)
    - "follow-up 4 sent" -> no more follow-ups
    
    Returns:
        tuple: (message_text, next_status, followup_number) or (None, None, None) if no more follow-ups
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
        # No more follow-ups or unknown status
        return (None, None, None)


def update_lead_status_to_followup_sent(full_name, headline, next_status):
    """
    Update the status of a lead to the next follow-up status and set last_contacted_at timestamp in Supabase.
    Matches by full_name only for reliability.
    
    Args:
        full_name: Lead's full name
        headline: Lead's headline (for logging)
        next_status: The new status to set (e.g., "follow-up 1 sent", "follow-up 2 sent", etc.)
    """
    try:
        # Get current timestamp in ISO format
        current_timestamp = datetime.now().isoformat()
        
        # Update the lead's status and last_contacted_at where full_name matches
        response = supabase.table('leads').update({
            'status': next_status,
            'last_contacted_at': current_timestamp
        }).eq('full_name', full_name).execute()
        
        if response.data:
            print(f"✅ Updated status for {full_name} to '{next_status}' with timestamp {current_timestamp}")
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
    - status in ["first message sent", "follow-up 1 sent", "follow-up 2 sent", "follow-up 3 sent"]
    - last_contacted_at is more than 3 days ago
    - has the appropriate message draft available
    
    Returns a dictionary with full_name as key and lead data as value.
    """
    try:
        print("📊 Fetching follow-up leads data from Supabase...")
        
        # Calculate the cutoff date (3 days ago)
        three_days_ago = (datetime.now() - timedelta(days=3)).isoformat()
        
        # Fetch leads with eligible statuses and last_contacted_at more than 3 days ago
        eligible_statuses = ["first message sent", "follow-up 1 sent", "follow-up 2 sent", "follow-up 3 sent"]
        
        response = supabase.table('leads').select(
            'full_name, headline, status, message_2_draft, message_3_draft, message_4_draft, message_5_draft, last_contacted_at'
        ).in_('status', eligible_statuses).lt('last_contacted_at', three_days_ago).execute()
        
        leads_data = {}
        eligible_leads = []
        total_leads = 0
        skipped_no_draft = 0
        status_breakdown = {
            "first message sent": 0,
            "follow-up 1 sent": 0,
            "follow-up 2 sent": 0,
            "follow-up 3 sent": 0
        }
        
        for lead in response.data:
            total_leads += 1
            full_name = lead.get('full_name', '').strip()
            headline = lead.get('headline', '').strip()
            status = lead.get('status', '').strip()
            last_contacted_at = lead.get('last_contacted_at', '')
            
            # Count by status
            if status in status_breakdown:
                status_breakdown[status] += 1
            
            if full_name:
                # Store all message drafts
                lead_info = {
                    'full_name': full_name,
                    'headline': headline,
                    'status': status,
                    'message_2_draft': lead.get('message_2_draft', '').strip() if lead.get('message_2_draft') else '',
                    'message_3_draft': lead.get('message_3_draft', '').strip() if lead.get('message_3_draft') else '',
                    'message_4_draft': lead.get('message_4_draft', '').strip() if lead.get('message_4_draft') else '',
                    'message_5_draft': lead.get('message_5_draft', '').strip() if lead.get('message_5_draft') else '',
                    'last_contacted_at': last_contacted_at
                }
                
                # Determine which message they need
                message_text, next_status, followup_num = determine_next_followup_message(lead_info)
                
                if message_text:
                    leads_data[full_name] = lead_info
                    eligible_leads.append(full_name)
                    print(f"   ✅ {full_name} - needs follow-up #{followup_num}")
                else:
                    skipped_no_draft += 1
                    print(f"   ⏭️ Skipping {full_name} - no message draft available for next follow-up")
        
        print(f"\n✅ Found {total_leads} leads with eligible status (>3 days ago)")
        print(f"   Status breakdown:")
        for status, count in status_breakdown.items():
            print(f"      - {status}: {count}")
        print(f"   - {len(eligible_leads)} have next message draft available")
        print(f"   - {skipped_no_draft} skipped (no message draft)")
        
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
            # Determine which follow-up they need
            message_text, next_status, followup_num = determine_next_followup_message(lead_db_data)
            
            # Append to list to maintain order from LinkedIn page
            leads_to_message.append(connection_data)
            print(f"🎯 Follow-up lead identified (position {k}): {name}")
            print(f"   📅 Last contacted: {lead_db_data['last_contacted_at']}")
            print(f"   📊 Current status: {lead_db_data['status']}")
            print(f"   📝 Next follow-up: #{followup_num}")
            print(f"   🎯 Match confidence: {validation_result['confidence']:.2f}")
            if message_text:
                print(f"   💬 Message preview: {message_text[:50]}...")
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


def get_all_linkedin_messages_shadow(driver):
    """
    Extract all messages from a LinkedIn conversation thread, including those inside shadow DOM.
    
    Args:
        driver: Selenium WebDriver instance
        
    Returns:
        list: List of dictionaries containing message information
    """
    
    messages = []
    
    # First, try to access shadow DOM
    try:
        shadow_host = driver.find_element(By.CSS_SELECTOR, '#interop-outlet')
        shadow_root = shadow_host.shadow_root
        
        # JavaScript code to find all message elements within shadow DOM
        js_code = """
        return (function(shadowRoot) {
            const messages = [];
            
            // Find all elements that could be message events
            const messageElements = shadowRoot.querySelectorAll('.msg-s-message-list__event');
            
            messageElements.forEach((element, index) => {
                try {
                    // Extract sender name
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
                    
                    // Extract timestamp
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
                    
                    // Extract message content
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
                    
                    // Determine message type
                    let messageType = 'unknown';
                    if (element.innerText.includes('You:') || 
                        element.querySelector('.msg-s-message-group__profile-link--you')) {
                        messageType = 'sent';
                    } else if (sender && sender !== 'You') {
                        messageType = 'received';
                    }
                    
                    // Extract date label
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
        })(arguments[0]);
        """
        
        shadow_messages = driver.execute_script(js_code, shadow_root)
        if isinstance(shadow_messages, list):
            messages.extend(shadow_messages)
            
    except Exception as e:
        print(f"Could not access shadow DOM: {e}")
    
    # Also check regular DOM for messages
    js_code_regular = """
    return (function() {
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
    })();
    """
    
    try:
        regular_messages = driver.execute_script(js_code_regular)
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


def check_if_lead_replied(driver, lead_name):
    """
    Check if a lead has replied by parsing conversation messages.
    Returns True if lead's name appears as sender in any message.
    
    Args:
        driver: Selenium WebDriver instance
        lead_name: Full name of the lead to check
        
    Returns:
        bool: True if lead has replied, False otherwise
    """
    try:
        print(f"   🔍 Checking if {lead_name} has replied...")
        
        # Wait for conversation to load
        human_pause(2, 3)
        
        # Get all messages from conversation
        messages = get_all_linkedin_messages_shadow(driver)
        
        if not messages:
            print(f"   ⚠️ No messages found in conversation")
            return False
        
        print(f"   📊 Found {len(messages)} messages in conversation")
        
        # Check if lead's name appears as sender in any message
        for msg in messages:
            sender = msg.get('sender', '').strip()
            message_type = msg.get('message_type', '')
            
            # Check for exact match or partial match with lead's name
            if sender and lead_name.lower() in sender.lower():
                # Make sure it's not our own message
                if message_type == 'received' or (message_type != 'sent' and 'you' not in sender.lower()):
                    print(f"   ✅ REPLY DETECTED! {sender} sent a message")
                    print(f"   📩 Message preview: {msg.get('message_text', '')[:100]}")
                    return True
        
        print(f"   ❌ No reply detected from {lead_name}")
        return False
        
    except Exception as e:
        print(f"   ⚠️ Error checking for reply: {e}")
        import traceback
        traceback.print_exc()
        return False


def update_lead_status_to_replied(full_name):
    """
    Update lead status to 'LEAD REPLIED' when reply is detected.
    
    Args:
        full_name: Lead's full name
        
    Returns:
        bool: True if update successful, False otherwise
    """
    try:
        current_timestamp = datetime.now().isoformat()
        
        response = supabase.table('leads').update({
            'status': 'LEAD REPLIED'
        }).eq('full_name', full_name).execute()
        
        if response.data:
            print(f"   ✅ Updated {full_name} status to 'LEAD REPLIED'")
            return True
        else:
            print(f"   ⚠️ No matching lead found for {full_name}")
            return False
            
    except Exception as e:
        print(f"   ❌ Error updating status for {full_name}: {e}")
        return False


def message_relay(driver, message_text, lead_name):
    """
    Handle the actual messaging process after message button is clicked.
    First checks if lead has replied - if yes, updates status and skips sending.
    If no reply, types message and sends using Ctrl+Enter, then closes dialog with Escape.
    """
    from selenium.webdriver.common.keys import Keys
    
    try:
        print(f"📝 Starting message relay for {lead_name}")
        
        # Wait for message dialog to load
        human_pause(3, 4)
        
        # CRITICAL: Check if lead has already replied
        has_replied = check_if_lead_replied(driver, lead_name)
        
        if has_replied:
            print(f"   🎉 {lead_name} has already replied! Skipping follow-up message.")
            # Update status to LEAD REPLIED
            update_lead_status_to_replied(lead_name)
            # Close dialog and return
            close_dialog_safely(driver, lead_name)
            return "REPLIED"  # Special return value to indicate reply detected
        
        # No reply detected - proceed with sending follow-up message
        print(f"   ✅ No reply detected. Proceeding to send follow-up message...")
        
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
    Determines which follow-up message to send based on current status.
    First checks if lead has replied - if yes, skips sending and updates status.
    """
    print(f"💬 Preparing to send follow-up message to: {lead_data['name']}")
    print(f"   Position K: {lead_data['position_k']}")
    print(f"   Headline: {lead_data['headline']}")
    print(f"   Current status: {lead_data['status']}")
    print(f"   Last contacted: {lead_data['last_contacted_at']}")
    
    # Determine which follow-up message to send
    message_text, next_status, followup_num = determine_next_followup_message(lead_data)
    
    if not message_text:
        print(f"⚠️ No follow-up message available for {lead_data['name']}")
        return False
    
    print(f"   📝 Sending follow-up #{followup_num}: {message_text[:100]}...")
    
    # Call message relay to handle the actual messaging (includes reply check)
    result = message_relay(driver, message_text, lead_data['name'])
    
    # Check if lead has replied (special return value)
    if result == "REPLIED":
        print(f"   🎉 Lead has replied! Status updated to 'LEAD REPLIED'")
        return "REPLIED"  # Return special value to track replied leads
    
    if result:
        # Update status in Supabase after successful message
        db_success = update_lead_status_to_followup_sent(lead_data['name'], lead_data['headline'], next_status)
        return db_success
    
    return False


def message_all_followup_leads(driver, leads_to_message):
    """
    Iterate through all identified leads and send follow-up messages using their position values.
    Processes leads in order from top to bottom as they appear on LinkedIn page.
    Checks for replies before sending - if lead has replied, updates status and skips.
    """
    # Read daily limit from config.json if available, otherwise random default
    daily_limit = random.randint(10, 15)
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend", "config.json")
    try:
        with open(config_path, "r") as f:
            config = json.load(f)
            daily_limit = config.get("daily_followup", daily_limit)
            print(f"📋 Loaded follow-up limit from config: {daily_limit}")
    except (FileNotFoundError, json.JSONDecodeError):
        print(f"📋 Using default follow-up limit: {daily_limit}")
    print(f"🚀 Starting to send follow-up messages (Daily limit: {daily_limit})...")
    print(f"📋 Found {len(leads_to_message)} leads available for follow-up")
    
    # Limit the leads to process based on daily limit
    leads_to_process = leads_to_message[:daily_limit]
    
    if len(leads_to_message) > daily_limit:
        print(f"⚠️ Limiting to {daily_limit} follow-ups today (out of {len(leads_to_message)} available)")
    
    scroll_to_top(driver)
    
    successful_messages = 0
    failed_messages = 0
    replied_leads = 0  # Track leads who have already replied
    
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
                
                # Call the follow-up message sending function (includes reply check)
                result = send_followup_to_lead(driver, lead_data)
                
                if result == "REPLIED":
                    replied_leads += 1
                    print(f"🎉 {name} has already replied! Skipped follow-up.")
                elif result:
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
    print(f"   ✅ Successful follow-ups sent: {successful_messages}")
    print(f"   🎉 Leads who already replied: {replied_leads}")
    print(f"   ❌ Failed: {failed_messages}")
    print(f"   📋 Total processed: {successful_messages + replied_leads + failed_messages}")
    
    return successful_messages, failed_messages, replied_leads


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
            successful, failed, replied = message_all_followup_leads(driver, leads_to_message)
            
            print(f"\n🏁 Follow-up messaging campaign completed!")
            print(f"   ✅ Successful follow-ups: {successful}")
            print(f"   🎉 Leads who already replied: {replied}")
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
