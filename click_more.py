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

   
    print("🚀 Opening LinkedIn...")
    driver.get("https://www.linkedin.com/in/deepali25a/")
    
    log_action(driver, "linkedin_homepage")
    human_pause(3, 5)

    connect = ""
    for i in range(3,8):
        try:
            connect = f"/html/body/div[{i}]/div[3]/div/div/div[2]/div/div/main/section[1]/div[2]/div[3]/div/button"
            connect_click = driver.find_element(By.XPATH , connect)
            if(connect_click.text == "Connect"):
                human_move_click(driver,connect_click)
                human_pause(3,5)
        except Exception as e: 
            print("Error  : " )

            
    
    more_xp =""    
    for i in range(3,8):
        try:
            more_xp = f"/html/body/div[{i}]/div[3]/div/div/div[2]/div/div/main/section[1]/div[2]/div[3]/div/div[2]/button"
            more_button = driver.find_element(By.XPATH,more_xp)
            if(more_button.text == "More"):
                human_move_click(driver,more_button)
                human_pause(3,4)
        except Exception as e :
            print("Error encountered ,choosing something else : " )
    
    more_connect = "" 
    for i in range(3,8):
        try : 
            more_connect =f"/html/body/div[{i}]/div[3]/div/div/div[2]/div/div/main/section[1]/div[2]/div[3]/div/div[2]/div/div/ul/li[3]/div"
            connect_click = driver.find_element(By.XPATH , more_connect)
            if(connect_click.text == "Connect") :
                human_move_click(driver,connect_click)
                human_pause(3,5)       
        except Exception as e : 
            print("Error occured : " )
    
    snd = driver.find_element(By.XPATH, "/html/body/div[4]/div/div/div[3]/button[2]")
    if(snd.text == "Send without a note"):
        human_move_click(driver, snd)
        human_pause(3,4)
    driver.quit()

if __name__ == "__main__":
    main()
