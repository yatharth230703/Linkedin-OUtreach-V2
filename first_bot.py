import time
import random
import os
from datetime import datetime
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- Helper Functions (From your snippets) ---

def human_pause(min_s: float = 0.3, max_s: float = 0.9):
    """Sleep for a random duration to mimic natural pauses."""
    time.sleep(random.uniform(min_s, max_s))

def human_scroll(driver, max_offset: int = 600):
    """Scroll the page by a random vertical offset."""
    offset = random.randint(-max_offset, max_offset)
    driver.execute_script("window.scrollBy(0, arguments[0]);", offset)
    human_pause()

def human_move_click(driver, element, max_retries=3):
    """Move the mouse with jitters and click. Retries if the click fails."""
    try:
        driver.execute_script(
            "arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});",
            element
        )
    except Exception:
        pass

    human_pause()

    for attempt in range(max_retries):
        try:
            if not element.is_enabled() or not element.is_displayed():
                print(f"⚠️ Element not clickable on attempt {attempt + 1}")
                human_pause(0.5, 1.0)
                continue

            actions = ActionChains(driver)
            offset_x = random.randint(-5, 5)
            offset_y = random.randint(-5, 5)
            
            (
                actions.move_to_element(element)
                .pause(random.uniform(0.1, 0.4))
                .move_by_offset(offset_x, offset_y)
                .pause(random.uniform(0.05, 0.2))
                .click()
                .perform()
            )

            print(f"✅ Click successful on attempt {attempt + 1}")
            human_pause()
            return True

        except Exception as e:
            print(f"❌ Click failed on attempt {attempt + 1}: {str(e)}")
            if attempt < max_retries - 1:
                human_pause(0.5, 1.0)

    print(f"❌ Failed to click element after {max_retries} attempts")
    return False

def log_action(driver, action_name):
    """Log HTML and screenshot for debugging."""
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

# --- Main Bot Logic ---

def main():
    # --- 1. Browser Configuration ---
    options = uc.ChromeOptions()
    
    # Path for Saving Cookies and Session Data
    # (Keeps you logged in across runs)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    user_data_path = os.path.join(script_dir, "user_data")
    options.add_argument(f"--user-data-dir={user_data_path}")
    
    # General Stealth & Browser Options
    options.add_argument('--ignore-certificate-errors')
    options.add_argument('--ignore-ssl-errors')
    options.add_argument('--disable-webrtc') # Helps prevent IP leaks
    options.set_capability('acceptInsecureCerts', True)

    # Use a consistent User Agent for this specific profile
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ]
    options.add_argument(f'--user-agent={user_agents[0]}')

    # Initialize Driver (undetected_chromedriver manages the binary automatically)
    driver = uc.Chrome(options=options)

    # CDP Masking: The magic line to hide the 'navigator.webdriver' flag
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    })

    try:
        # --- 2. Login & Session Verification ---
        print("🚀 Opening LinkedIn...")
        driver.get("https://www.linkedin.com/")
        
        log_action(driver, "linkedin_homepage")
        
        # Wait a bit for page load
        human_pause(3, 5)

        # Simple Check: If we are not on the 'feed' and see 'login'/'signup' buttons
        if "feed" not in driver.current_url and ("login" in driver.current_url or "signup" in driver.current_url):
            print("⚠️ User is NOT logged in.")
            print("👉 Please log in manually in the browser window now.")
            print("👉 Press ENTER in this terminal once you see your LinkedIn Feed...")
            input() # Freezes script until you press Enter
        
        print("✅ Session Active. Ready to start automation.")
        human_scroll(driver) # Warm-up scroll interaction

        # --- 3. Batch Processing Logic ---
        
        # Load targets from JSON
        target_urls = get_leads_from_file("leads.json") 
        if not target_urls:
            print("⚠️ No leads found in leads.json. Exiting.")
            return

        daily_limit = 20 # Safety cap
        count = 0
        
        print(f"📋 Found {len(target_urls)} leads. Processing max {daily_limit} today.")

        for url in target_urls:
            # Stop if we hit the daily safety limit
            if count >= daily_limit:
                print("🛑 Daily limit reached. Stopping script safely.")
                break

            print(f"\n[{count + 1}/{daily_limit}] 🔍 Checking: {url}")

            # A. Check Database (Deduplication)
            # We check Supabase BEFORE visiting the URL to save "views" and safety buffer
            exists, record = check_if_exists(url)
            if exists:
                status = record.get('status', 'UNKNOWN')
                print(f"⏭️ Skipping: Lead already in DB (Status: {status})")
                continue

            # B. Navigate to Profile
            try:
                driver.get(url)
                
                # Critical: Variable wait time for page load (never use fixed sleep)
                human_pause(4, 7) 
                
                # Critical: Scroll to bottom then up to trigger lazy-loaded elements 
                # (About/Experience sections often don't exist in DOM until scrolled to)
                human_scroll(driver, max_offset=800)
                human_pause(2, 4) 
                
                # C. Scrape Data
                print("   ⬇️  Scraping profile data...")
                profile_data = scrape_profile_data(driver)
                
                # Basic validation
                if not profile_data['full_name'] or profile_data['full_name'] == "Unknown":
                    print("   ⚠️  Warning: Could not extract name. Page might not have loaded correctly.")
                    log_action(driver, f"failed_scrape_{count}")
                
                # D. Generate Draft (Mock AI)
                draft_msg = mock_ai_draft_generator(profile_data)
                
                # E. Save to Supabase
                save_lead_to_db(url, profile_data, draft_msg)
                
                count += 1

            except Exception as e_inner:
                print(f"   ❌ Error processing this lead: {e_inner}")
                log_action(driver, "error_lead_processing")
                # We continue to the next lead instead of crashing the whole bot
                continue

            # F. Safety Cool-down (The "Human" Element)
            # This is critical. Real recruiters don't open 20 tabs in 20 seconds.
            # We wait 1-3 minutes between profiles.
            sleep_time = random.randint(60, 180) 
            minutes = round(sleep_time / 60, 1)
            print(f"💤 Resting for {minutes} min ({sleep_time}s) before next profile...")
            time.sleep(sleep_time)

        print("\n🎉 Batch job complete!")

    except Exception as e:
        print(f"❌ Critical Script Error: {e}")
        log_action(driver, "critical_failure")
        
    finally:
        # Always close the browser to free up memory
        print("🔒 Closing browser session...")
        try:
            driver.quit()
        except:
            pass

if __name__ == "__main__":
    main()