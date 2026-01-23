"""LinkedIn Lead Scraper Bot with Apify Posts & Gemini Outreach Integration"""
import json
import time
import random
import os
from datetime import datetime
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from supabase import create_client, Client
from dotenv import load_dotenv

from apify_scraper import scrape_linkedin_posts
from gemini_outreach import GeminiLinkedInMessager
from proxy_requests import get_proxy_session

load_dotenv()

# --- Supabase Configuration ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def human_pause(min_s: float = 0.3, max_s: float = 0.9):
    time.sleep(random.uniform(min_s, max_s))


def human_scroll(driver, max_offset: int = 100):
    offset = random.randint(-max_offset, max_offset)
    driver.execute_script("window.scrollBy(0, arguments[0]);", offset)
    human_pause()


def human_move_click(driver, element, max_retries=3):
    """
    Robust clicker that handles scrolling, sticky headers, and moving targets.
    """
    # 1. Force Scroll to Element (Instant, no animation)
    try:
        driver.execute_script(
            "arguments[0].scrollIntoView({behavior: 'auto', block: 'center'});",
            element
        )
        # 2. Safety Scroll: Move up 100px to ensure element isn't under LinkedIn's sticky header
        # (Sometimes block: 'center' is weird on small viewports)
        time.sleep(0.2)
        driver.execute_script("window.scrollBy(0, -50);")
    except Exception:
        pass

    # 3. Wait for layout to settle completely
    human_pause(1.0, 1.5)

    for attempt in range(max_retries):
        try:
            # Re-check visibility just in case
            if not element.is_enabled() or not element.is_displayed():
                print(f"⚠️ Element not clickable on attempt {attempt + 1}")
                human_pause(0.5, 1.0)
                continue

            # 4. Use ActionChains with a fresh reference
            actions = ActionChains(driver)
            offset_x = random.randint(-5, 5)
            offset_y = random.randint(-5, 5)
            
            (
                actions.move_to_element(element)
                .pause(random.uniform(0.1, 0.4))
                .move_by_offset(offset_x, offset_y)
                .click()
                .perform()
            )

            print(f"✅ Click successful on attempt {attempt + 1}")
            human_pause(0.5, 1.0)
            return True

        except Exception as e:
            # If ActionChains fails, try a direct JS click as a fallback for the last attempt
            if attempt == max_retries - 1:
                print(f"⚠️ ActionChains failed. Trying JS Fallback.")
                try:
                    driver.execute_script("arguments[0].click();", element)
                    return True
                except:
                    pass
            
            print(f"❌ Click failed on attempt {attempt + 1}: {str(e)}")
            human_pause(1.0, 2.0)

    print(f"❌ Failed to click element after {max_retries} attempts")
    return False


def human_sleep_with_activity(driver, total_sleep_time: int):
    """
    Sleep with random scrolling activity to mimic human behavior.
    Breaks sleep into chunks with occasional scrolling.
    """
    remaining_time = total_sleep_time
    
    while remaining_time > 0:
        # Sleep for a random chunk (10-45 seconds)
        chunk_time = min(random.randint(10, 45), remaining_time)
        time.sleep(chunk_time)
        remaining_time -= chunk_time
        
        # If there's still time left, do some random activity
        if remaining_time > 0:
            activity_type = random.choice(['scroll', 'pause', 'small_scroll'])
            
            try:
                if activity_type == 'scroll':
                    # Random scroll (up or down)
                    human_scroll(driver, max_offset=100)
                elif activity_type == 'small_scroll':
                    # Small scroll movement
                    offset = random.randint(-150, 150)
                    driver.execute_script("window.scrollBy(0, arguments[0]);", offset)
                    human_pause(0.5, 1.5)
                else:  # pause
                    # Just a longer pause
                    human_pause(2, 5)
                    
            except Exception:
                # If scrolling fails (page changed, etc.), just continue sleeping
                pass


def log_action(driver, action_name):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshots_dir = "screenshots"
    if not os.path.exists(screenshots_dir):
        os.makedirs(screenshots_dir)

    screenshot_path = f"{screenshots_dir}/{timestamp}_{action_name}.png"
    try:
        driver.save_screenshot(screenshot_path)
    except: pass

    html_path = f"{screenshots_dir}/{timestamp}_{action_name}_page_source.html"
    try:
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(driver.page_source)
    except: pass


def get_leads_from_file(filename="leads.json"):
    try:
        with open(filename, 'r') as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            return list(data)
    except FileNotFoundError:
        print("⚠️ leads.json not found. Using dummy data.")
        return []


def remove_lead_from_file(url, filename="leads.json"):
    """Remove a processed lead from leads.json"""
    try:
        with open(filename, 'r') as f:
            leads = json.load(f)
        
        # Remove the URL from the list
        if url in leads:
            leads.remove(url)
            
            # Write back to file
            with open(filename, 'w') as f:
                json.dump(leads, f, indent=2)
            
            print(f"   🗑️  Removed {url} from leads.json")
            return True
    except Exception as e:
        print(f"   ⚠️ Could not remove lead from file: {e}")
        return False


def check_if_exists(url):
    try:
        response = supabase.table("leads").select("id, status").eq("linkedin_url", url).execute()
        if response.data:
            return True, response.data[0]
        return False, None
    except Exception as e:
        print(f"⚠️ DB Read Error: {e}")
        return False, None


def scrape_profile_data(driver):
    profile_data = {
        "full_name": "Unknown",
        "headline": "",
        "about": "",
        "experience": ""
    }
    
    try:
        name_elem = driver.find_element(By.TAG_NAME, "h1")
        profile_data["full_name"] = name_elem.text.strip()
    except: pass

    try:
        headline_elem = driver.find_element(By.XPATH, "//div[contains(@class, 'text-body-medium')]")
        profile_data["headline"] = headline_elem.text.strip()
    except: pass

    try:
        about_section = driver.find_element(By.ID, "about")
        profile_data["about"] = about_section.find_element(By.XPATH, "./ancestor::section").text
    except: pass

    try:
        exp_section = driver.find_element(By.ID, "experience")
        profile_data["experience"] = exp_section.find_element(By.XPATH, "./ancestor::section").text
    except: pass
    
    return profile_data


def fetch_profile_posts(linkedin_url: str) -> list[dict]:
    """Fetch LinkedIn posts using Apify scraper"""
    try:
        print("   📝 Fetching profile posts via Apify...")
        posts = scrape_linkedin_posts(linkedin_url, limit=20)
        print(f"   ✅ Fetched {len(posts)} posts")
        return posts
    except Exception as e:
        print(f"   ⚠️ Could not fetch posts: {e}")
        return []


def generate_ai_messages(profile_data: dict, posts_data: list[dict]) -> tuple[str, str]:
    """Generate outreach and followup messages using Gemini"""
    try:
        print("   🤖 Generating AI messages...")
        messager = GeminiLinkedInMessager()
        messages = messager.generate_messages(profile_data, posts_data)
        print("   ✅ Messages generated")
        return messages.outreach_message, messages.followup_message
    except Exception as e:
        print(f"   ⚠️ AI generation failed: {e}")
        first_name = profile_data['full_name'].split(' ')[0]
        fallback = f"Hi {first_name}, I saw your experience in {profile_data['headline']}..."
        return fallback, fallback


def save_lead_to_db(url, data, posts_data, outreach_msg, followup_msg, status="SCRAPED", last_contacted=None):
                    
    """Save lead data including posts and AI messages to Supabase"""
    # Base payload with required columns
    payload = {
        "linkedin_url": url,
        "full_name": data["full_name"],
        "headline": data["headline"],
        "about_section": data["about"],
        "experience_text": data["experience"],
        "message_1_draft": outreach_msg,
        "status": status,
        "connection_status": status,
        "last_scraped_at": last_contacted
    }

    
    # Try to add new columns, but continue if they don't exist
    try:
        # First attempt with all columns
        full_payload = payload.copy()
        full_payload.update({
            "profile_posts": json.dumps(posts_data) if posts_data else None,
            "message_2_draft": followup_msg,
        })
        supabase.table("leads").insert(full_payload).execute()
        print(f"✅ Saved to DB: {data['full_name']} (with posts & followup)")
    except Exception as e:
        if "profile_posts" in str(e) or "message_2_draft" in str(e):
            # Fallback: save without new columns
            try:
                supabase.table("leads").insert(payload).execute()
                print(f"✅ Saved to DB: {data['full_name']} (basic data only)")
                print(f"⚠️ Note: profile_posts and message_2_draft columns not available")
            except Exception as e2:
                print(f"❌ DB Save Error: {e2}")
        else:
            print(f"❌ DB Save Error: {e}")

class LinkedInInteractionManager:
    def __init__(self, driver):
        self.driver = driver

    def _is_element_present(self, xpath):
        try:
            return len(self.driver.find_elements(By.XPATH, xpath)) > 0
        except:
            return False

    def get_connection_status(self):
        """
        Determines if the user is CONNECTED, NOT_CONNECTED, or PENDING.
        """
        # 1. Check for "Pending" button (Invited but not accepted) - English or German
        if (self._is_element_present("//button[contains(., 'Pending')]") or
            self._is_element_present("//button[contains(., 'Ausstehend')]")):
            return "PENDING"

        # 2. Check for Visible "Connect" button (English or German)
        if (self._is_element_present("//button[.//span[text()='Connect']]") or 
            self._is_element_present("//button[.//span[text()='Vernetzen']]")):
            return "NOT_CONNECTED"

        # 3. Check for "Connect" hidden in "More" dropdown
        # We don't click "More" yet, just checking logic implies if we can't see connect 
        # but see "Message", we might be connected.
        # However, to be certain, we assume "CONNECTED" if "Message" is present 
        # AND "Connect" is NOT visible.
        
        has_message_btn = (self._is_element_present("//button[starts-with(@aria-label, 'Message')]") or
                           self._is_element_present("//button[starts-with(@aria-label, 'Nachricht')]"))
        
        if has_message_btn:
            return "CONNECTED"

        # Fallback: If we see "More", we might need to click it to be 100% sure, 
        # but for speed, if we don't see "Connect", we assume Connected or Locked.
        return "UNKNOWN"

    def send_connection_request(self):
        """
        Handles both Visible and Hidden 'Connect' buttons + 'Send without note'.
        Uses the guaranteed working mechanism from click_more.py
        """
        print("   🤝 Attempting to connect...")
        
        # Scenario A: Try to find visible "Connect" button using dynamic XPath (like click_more.py)
        connect_found = False
        for i in range(3, 8):
            try:
                connect_xpath = f"/html/body/div[{i}]/div[3]/div/div/div[2]/div/div/main/section[1]/div[2]/div[3]/div/button"
                connect_click = self.driver.find_element(By.XPATH, connect_xpath)
                # Check for both English and German text
                if connect_click.text in ["Connect", "Vernetzen"]:
                    human_move_click(self.driver, connect_click)
                    human_pause(3, 5)
                    connect_found = True
                    break
            except Exception:
                continue
        
        if not connect_found:
            # Scenario B: Hidden inside "More" button (using click_more.py approach)
            print("   🕵️ 'Connect' hidden. Checking 'More' menu...")
            
            # Find and click "More" button (English or German)
            more_found = False
            for i in range(3, 8):
                try:
                    more_xpath = f"/html/body/div[{i}]/div[3]/div/div/div[2]/div/div/main/section[1]/div[2]/div[3]/div/div[2]/button"
                    more_button = self.driver.find_element(By.XPATH, more_xpath)
                    if more_button.text in ["More", "Mehr"]:
                        human_move_click(self.driver, more_button)
                        human_pause(3, 4)
                        more_found = True
                        break
                except Exception:
                    continue
            
            if not more_found:
                print("   ❌ No 'More' button found.")
                return False
            
            # Find and click "Connect" in dropdown (English or German)
            connect_in_dropdown = False
            for i in range(3, 8):
                try:
                    more_connect_xpath = f"/html/body/div[{i}]/div[3]/div/div/div[2]/div/div/main/section[1]/div[2]/div[3]/div/div[2]/div/div/ul/li[3]/div"
                    connect_click = self.driver.find_element(By.XPATH, more_connect_xpath)
                    if connect_click.text in ["Connect", "Vernetzen"]:
                        human_move_click(self.driver, connect_click)
                        human_pause(3, 5)
                        connect_in_dropdown = True
                        break
                except Exception:
                    continue
            
            if not connect_in_dropdown:
                print("   ⚠️ Could not find 'Connect' in More dropdown.")
                return False

        # Handle "Add a Note" Modal (Always Send without Note) - Support both English and German
        human_pause(1, 2)
        
        # Try to find "Send without a note" button using the exact XPath from click_more.py (English or German)
        try:
            send_btn = self.driver.find_element(By.XPATH, "/html/body/div[4]/div/div/div[3]/button[2]")
            if send_btn.text in ["Send without a note", "Ohne Notiz senden"]:
                human_move_click(self.driver, send_btn)
                human_pause(3, 4)
                print("   ✅ Connection request sent (No Note).")
                return True
        except Exception:
            # Fallback to the original approach if the exact XPath doesn't work
            send_no_note_selectors = [
                "//button[@aria-label='Send without a note']",
                "//button[@aria-label='Ohne Notiz senden']",
                "//button[contains(text(), 'Send without a note')]",
                "//button[contains(text(), 'Ohne Notiz senden')]"
            ]
            
            for selector in send_no_note_selectors:
                if self._is_element_present(selector):
                    send_btn = self.driver.find_element(By.XPATH, selector)
                    human_move_click(self.driver, send_btn)
                    print("   ✅ Connection request sent (No Note).")
                    return True
        # Also try alternative selectors for German interface
        alternative_selectors = [
            "//button[contains(text(), 'Nachricht hinzufügen')]",  # "Add message" in German
            "//button[contains(text(), 'Ohne Notiz senden')]",     # "Send without note" in German
            "/html/body/div[3]/div/div/div[3]/button[2]",          # Alternative div structure
            "/html/body/div[5]/div/div/div[3]/button[2]"           # Another alternative
        ]
        
        for selector in alternative_selectors:
            try:
                if selector.startswith("//"):
                    elements = self.driver.find_elements(By.XPATH, selector)
                else:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                
                for elem in elements:
                    if elem.is_displayed() and elem.text in ["Send without a note", "Ohne Notiz senden"]:
                        human_move_click(self.driver, elem)
                        print("   ✅ Connection request sent (No Note) - Alternative method.")
                        return True
            except:
                continue
        
        # Sometimes it just sends without modal (rare, but possible)
        print("   ⚠️ No modal appeared. Assuming request sent.")
        return True



def test_proxy_connection():
    """Test proxy connection and show IP information"""
    proxy_session = get_proxy_session()
    
    try:
        print("🔍 Testing proxy connection...")
        response = proxy_session.get("https://httpbin.org/ip", timeout=10)
        
        if response.status_code == 200:
            ip_data = response.json()
            proxy_ip = ip_data.get("origin", "Unknown")
            print(f"✅ Proxy working! IP: {proxy_ip}")
            return True
        else:
            print(f"⚠️ Proxy test failed with status: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ Proxy test failed: {e}")
        return False

def main():
    # Test proxy connection first
    test_proxy_connection()
    
    # Setup Chrome options (no proxy for browser)
    options = uc.ChromeOptions()
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    user_data_path = os.path.join(script_dir, "user_data_yatharth")
    options.add_argument(f"--user-data-dir={user_data_path}")
    options.add_argument("--profile-directory=Default")
    
    options.add_argument('--ignore-certificate-errors')
    options.add_argument('--ignore-ssl-errors')
    options.add_argument('--disable-webrtc')
    options.set_capability('acceptInsecureCerts', True)

    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ]
    options.add_argument(f'--user-agent={user_agents[0]}')

    # Create driver with undetected-chromedriver (no proxy issues)
    driver = uc.Chrome(options=options)

    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })

    try:
        print("🚀 Opening LinkedIn...")
        driver.get("https://www.linkedin.com/")
        #time.sleep(100)
        log_action(driver, "linkedin_homepage")
        human_pause(3, 5)

        if "feed" not in driver.current_url and ("login" in driver.current_url or "signup" in driver.current_url):
            print("⚠️ User is NOT logged in.")
            print("👉 Please log in manually in the browser window now.")
            print("👉 Press ENTER in this terminal once you see your LinkedIn Feed...")
            input()
        
        print("✅ Session Active. Ready to start automation.")
        human_scroll(driver)

        target_urls = get_leads_from_file("leads.json") 
        if not target_urls:
            print("⚠️ No leads found in leads.json. Exiting.")
            return

        daily_limit = 18
        count = 0
        
        print(f"📋 Found {len(target_urls)} leads. Processing max {daily_limit} today.")

        for url in target_urls:
            if count >= daily_limit:
                print("🛑 Daily limit reached. Stopping script safely.")
                break

            print(f"\n[{count + 1}/{daily_limit}] 🔍 Checking: {url}")

            exists, record = check_if_exists(url)
            if exists:
                status = record.get('status', 'UNKNOWN')
                print(f"⏭️ Skipping: Lead already in DB (Status: {status})")
                continue

            li_manager = LinkedInInteractionManager(driver)

            try:
                driver.get(url)
                human_pause(4, 7)

                # --- PHASE 1: DATA GATHERING (Scraping) ---
                # This naturally scrolls down to Experience/About sections
                print("   ⬇️  Scraping profile data (scrolling down)...")
                # Initial scroll to trigger lazy loading
                human_scroll(driver, max_offset=600)
                profile_data = scrape_profile_data(driver)
                posts_data = fetch_profile_posts(url)
                outreach_msg, followup_msg = generate_ai_messages(profile_data, posts_data)
                print("   ✅ Data gathering complete.")

                # --- CRITICAL FIX: RESET VIEWPORT ---
                # We are likely at the bottom of the page now. 
                # We must scroll back to TOP to see the "Connect" buttons.
                print("   ⬆️  Returning to top of profile for interaction...")
                driver.execute_script("window.scrollTo({top: 0, behavior: 'auto'});")
                human_pause(2, 3)  # Wait for scroll to finish and layout to settle

                # --- PHASE 2: INTERACTION (Connecting/Messaging) ---
                print("   🔍 Checking Connection Status...")
                status = li_manager.get_connection_status()
                print(f"   👉 Status: {status}")

                db_status_update = "SCRAPED"
                last_contacted = None

                if status == "CONNECTED":
                    print("   ✅ Already connected. Skipping message for now.")
                    db_status_update = "CONNECTED"

                elif status == "NOT_CONNECTED":
                    sent = li_manager.send_connection_request()
                    if sent:
                        db_status_update = "PENDING"
                
                elif status == "PENDING":
                    print("   ⏳ Invite pending. Skipping.")
                    db_status_update = "PENDING"

                # --- PHASE 3: SAVE TO DB ---
                save_lead_to_db(
                    url, profile_data, posts_data, outreach_msg, followup_msg, 
                    status=db_status_update, 
                    last_contacted=last_contacted
                )
                
                # --- PHASE 4: CLEANUP ---
                # Remove from leads.json since it's now processed and in DB
                remove_lead_from_file(url, "leads.json")
                
                count += 1

            except Exception as e_inner:
                print(f"   ❌ Error processing this lead: {e_inner}")
                log_action(driver, "error_lead_processing")
                continue

            sleep_time = random.randint(60, 180) 
            minutes = round(sleep_time / 60, 1)
            print(f"💤 Resting for {minutes} min ({sleep_time}s) before next profile...")
            
            # Simple sleep without activity to avoid interfering with button clicks
            time.sleep(sleep_time)

        print("\n🎉 Batch job complete!")

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
