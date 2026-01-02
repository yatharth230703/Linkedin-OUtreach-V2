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

load_dotenv()

# --- Supabase Configuration ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def human_pause(min_s: float = 0.3, max_s: float = 0.9):
    time.sleep(random.uniform(min_s, max_s))


def human_scroll(driver, max_offset: int = 600):
    offset = random.randint(-max_offset, max_offset)
    driver.execute_script("window.scrollBy(0, arguments[0]);", offset)
    human_pause()


def human_move_click(driver, element, max_retries=3):
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
                    human_scroll(driver, max_offset=400)
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


def save_lead_to_db(url: str, data: dict, posts_data: list[dict], outreach_msg: str, followup_msg: str):
    """Save lead data including posts and AI messages to Supabase"""
    # Base payload with required columns
    payload = {
        "linkedin_url": url,
        "full_name": data["full_name"],
        "headline": data["headline"],
        "about_section": data["about"],
        "experience_text": data["experience"],
        "message_1_draft": outreach_msg,
        "status": "SCRAPED",
        "last_scraped_at": datetime.now().isoformat()
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


def main():
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

        daily_limit = 20
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

            try:
                driver.get(url)
                human_pause(4, 7) 
                human_scroll(driver, max_offset=800)
                human_pause(2, 4) 
                
                print("   ⬇️  Scraping profile data...")
                profile_data = scrape_profile_data(driver)
                
                if not profile_data['full_name'] or profile_data['full_name'] == "Unknown":
                    print("   ⚠️  Warning: Could not extract name. Page might not have loaded correctly.")
                    log_action(driver, f"failed_scrape_{count}")
                
                # Fetch posts via Apify
                posts_data = fetch_profile_posts(url)
                
                # Generate AI messages
                outreach_msg, followup_msg = generate_ai_messages(profile_data, posts_data)
                
                # Save everything to DB
                save_lead_to_db(url, profile_data, posts_data, outreach_msg, followup_msg)
                
                count += 1

            except Exception as e_inner:
                print(f"   ❌ Error processing this lead: {e_inner}")
                log_action(driver, "error_lead_processing")
                continue

            sleep_time = random.randint(60, 180) 
            minutes = round(sleep_time / 60, 1)
            print(f"💤 Resting for {minutes} min ({sleep_time}s) before next profile...")
            
            # Human-like behavior: Random scrolling during sleep
            human_sleep_with_activity(driver, sleep_time)

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
