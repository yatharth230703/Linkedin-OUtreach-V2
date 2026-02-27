"""LinkedIn Lead Scraper Bot with Apify Posts & Gemini Outreach Integration - Playwright version"""
import json
import time
import random
import os
import sys
from datetime import datetime
from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apify_scraper import scrape_linkedin_posts
from gemini_outreach import GeminiLinkedInMessager
from proxy_requests import get_proxy_session
from attio_client import get_attio_client
from playwright_bots.login_credentials import (
    ensure_linkedin_login,
    human_pause,
    human_move_click,
    smooth_scroll_to_element,
    log_action,
    PlaywrightDriver,
    _safe_goto,
)

load_dotenv()


def human_scroll(page, max_offset: int = 100):
    offset = random.randint(-max_offset, max_offset)
    page.evaluate(f"window.scrollBy(0, {offset})")
    human_pause()


def human_sleep_with_activity(page, total_sleep_time: int):
    """
    Sleep with random scrolling activity to mimic human behavior.
    Breaks sleep into chunks with occasional scrolling.
    """
    remaining_time = total_sleep_time

    while remaining_time > 0:
        chunk_time = min(random.randint(10, 45), remaining_time)
        time.sleep(chunk_time)
        remaining_time -= chunk_time

        if remaining_time > 0:
            activity_type = random.choice(['scroll', 'pause', 'small_scroll'])

            try:
                if activity_type == 'scroll':
                    human_scroll(page, max_offset=100)
                elif activity_type == 'small_scroll':
                    offset = random.randint(-150, 150)
                    page.evaluate(f"window.scrollBy(0, {offset})")
                    human_pause(0.5, 1.5)
                else:
                    human_pause(2, 5)
            except Exception:
                pass


def get_leads_from_attio(lead_manager, limit=25):
    """Fetch leads from Attio bot_inputs for the given lead_manager."""
    try:
        client = get_attio_client()
        records = client.query_bot_inputs(lead_manager, limit=limit)
        print(f"   Fetched {len(records)} bot_input records for '{lead_manager}'")
        return records
    except Exception as e:
        print(f"   Error fetching bot_inputs from Attio: {e}")
        return []


def check_if_exists(url):
    try:
        client = get_attio_client()
        return client.check_lead_exists(url)
    except Exception as e:
        print(f"   Attio Read Error: {e}")
        return False, None


def scrape_profile_data(page):
    profile_data = {
        "full_name": "Unknown",
        "headline": "",
        "about": "",
        "experience": ""
    }

    try:
        name_elem = page.locator("h1").first
        if name_elem.is_visible():
            profile_data["full_name"] = name_elem.inner_text().strip()
    except: pass

    try:
        headline_elem = page.locator("xpath=//div[contains(@class, 'text-body-medium')]").first
        if headline_elem.is_visible():
            profile_data["headline"] = headline_elem.inner_text().strip()
    except: pass

    try:
        about_section = page.locator("#about")
        if about_section.count() > 0:
            ancestor_section = about_section.locator("xpath=./ancestor::section")
            if ancestor_section.count() > 0:
                profile_data["about"] = ancestor_section.first.inner_text()
    except: pass

    try:
        exp_section = page.locator("#experience")
        if exp_section.count() > 0:
            ancestor_section = exp_section.locator("xpath=./ancestor::section")
            if ancestor_section.count() > 0:
                profile_data["experience"] = ancestor_section.first.inner_text()
    except: pass

    return profile_data


def fetch_profile_posts(linkedin_url: str) -> list[dict]:
    """Fetch LinkedIn posts using Apify scraper"""
    try:
        print("      Fetching profile posts via Apify...")
        posts = scrape_linkedin_posts(linkedin_url, limit=20)
        print(f"      Fetched {len(posts)} posts")
        return posts
    except Exception as e:
        print(f"      Could not fetch posts: {e}")
        return []


def generate_ai_messages(profile_data: dict, posts_data: list[dict], template_name: str = "template_1", template_dict: dict = None) -> tuple[str, str, str, str, str]:
    """Generate outreach and 4 followup messages using Gemini with specified template or dict"""
    try:
        if template_dict:
            print(f"      Generating AI messages using per-lead template...")
            messager = GeminiLinkedInMessager(template_dict=template_dict)
        else:
            print(f"      Generating AI messages using {template_name}...")
            messager = GeminiLinkedInMessager(template_name=template_name)
        messages = messager.generate_messages(profile_data, posts_data)
        print("      All messages generated (1 outreach + 4 follow-ups)")
        return (
            messages.outreach_message,
            messages.followup_message_1,
            messages.followup_message_2,
            messages.followup_message_3,
            messages.followup_message_4
        )
    except Exception as e:
        print(f"      AI generation failed: {e}")
        first_name = profile_data['full_name'].split(' ')[0]
        fallback = f"Hi {first_name}, I saw your experience in {profile_data['headline']}..."
        return fallback, fallback, fallback, fallback, fallback


def save_lead_to_db(url, data, posts_data, outreach_msg, followup_msg_1, followup_msg_2, followup_msg_3, followup_msg_4, status="SCRAPED", last_contacted=None, lead_manager="", prompt_template=""):
    """Save lead data including posts and AI messages to Attio leads_sources"""
    values_dict = {
        "linkedin_url": url,
        "full_name": data["full_name"],
        "headline": data["headline"],
        "about_section": data["about"],
        "experience_text": data["experience"],
        "message_1_draft": outreach_msg,
        "lead_status": status,
        "connection_status": status,
        "lead_last_scraped_at": last_contacted or datetime.now().isoformat(),
        "lead_created_at": datetime.now().isoformat(),
        "message_2_draft": followup_msg_1,
        "message_3_draft": followup_msg_2,
        "message_4_draft": followup_msg_3,
        "message_5_draft": followup_msg_4,
        "profile_posts": json.dumps(posts_data) if posts_data else "",
        "lead_manager": lead_manager,
        "prompt_template": prompt_template,
    }

    try:
        client = get_attio_client()
        client.save_lead(values_dict)
        print(f"   Saved to Attio: {data['full_name']} (with posts & 4 follow-ups)")
    except Exception as e:
        print(f"   Attio Save Error: {e}")


class LinkedInInteractionManager:
    def __init__(self, page):
        self.page = page

    def _is_element_present(self, xpath):
        try:
            return self.page.locator(f"xpath={xpath}").count() > 0
        except:
            return False

    def get_connection_status(self):
        """
        Determines if the user is CONNECTED, NOT_CONNECTED, or PENDING.
        """
        # 1. Check for "Pending" button (English or German)
        if (self._is_element_present("//button[contains(., 'Pending')]") or
            self._is_element_present("//button[contains(., 'Ausstehend')]")):
            return "PENDING"

        # 2. Check for Visible "Connect" button (English or German)
        if (self._is_element_present("//button[.//span[text()='Connect']]") or
            self._is_element_present("//button[.//span[text()='Vernetzen']]")):
            return "NOT_CONNECTED"

        # 3. Check for "Message" button
        has_message_btn = (self._is_element_present("//button[starts-with(@aria-label, 'Message')]") or
                           self._is_element_present("//button[starts-with(@aria-label, 'Nachricht')]"))

        if has_message_btn:
            return "CONNECTED"

        return "UNKNOWN"

    def send_connection_request(self):
        """
        Handles both Visible and Hidden 'Connect' buttons + 'Send without note'.
        """
        print("      Attempting to connect...")

        # Scenario A: Try to find visible "Connect" button using dynamic XPath
        connect_found = False
        for i in range(3, 8):
            try:
                connect_xpath = f"xpath=/html/body/div[{i}]/div[3]/div/div/div[2]/div/div/main/section[1]/div[2]/div[3]/div/button"
                connect_click = self.page.locator(connect_xpath)
                if connect_click.count() > 0 and connect_click.first.is_visible():
                    text = connect_click.first.inner_text().strip()
                    if text in ["Connect", "Vernetzen"]:
                        human_move_click(self.page, connect_click.first)
                        human_pause(3, 5)
                        connect_found = True
                        break
            except Exception:
                continue

        if not connect_found:
            # Scenario B: Hidden inside "More" button
            print("      'Connect' hidden. Checking 'More' menu...")

            more_found = False
            for i in range(3, 8):
                try:
                    more_xpath = f"xpath=/html/body/div[{i}]/div[3]/div/div/div[2]/div/div/main/section[1]/div[2]/div[3]/div/div[2]/button"
                    more_button = self.page.locator(more_xpath)
                    if more_button.count() > 0 and more_button.first.is_visible():
                        text = more_button.first.inner_text().strip()
                        if text in ["More", "Mehr"]:
                            human_move_click(self.page, more_button.first)
                            human_pause(3, 4)
                            more_found = True
                            break
                except Exception:
                    continue

            if not more_found:
                print("      No 'More' button found.")
                return False

            # Find and click "Connect" in dropdown (English or German)
            connect_in_dropdown = False
            for i in range(3, 8):
                try:
                    more_connect_xpath = f"xpath=/html/body/div[{i}]/div[3]/div/div/div[2]/div/div/main/section[1]/div[2]/div[3]/div/div[2]/div/div/ul/li[3]/div"
                    connect_click = self.page.locator(more_connect_xpath)
                    if connect_click.count() > 0 and connect_click.first.is_visible():
                        text = connect_click.first.inner_text().strip()
                        if text in ["Connect", "Vernetzen"]:
                            human_move_click(self.page, connect_click.first)
                            human_pause(3, 5)
                            connect_in_dropdown = True
                            break
                except Exception:
                    continue

            if not connect_in_dropdown:
                print("      Could not find 'Connect' in More dropdown.")
                return False

        # Handle "Add a Note" Modal - Send without Note (English and German)
        human_pause(1, 2)

        # Try exact XPath first
        try:
            send_btn = self.page.locator("xpath=/html/body/div[4]/div/div/div[3]/button[2]")
            if send_btn.count() > 0 and send_btn.first.is_visible():
                text = send_btn.first.inner_text().strip()
                if text in ["Send without a note", "Ohne Notiz senden"]:
                    human_move_click(self.page, send_btn.first)
                    human_pause(3, 4)
                    print("      Connection request sent (No Note).")
                    return True
        except Exception:
            # Fallback selectors
            send_no_note_selectors = [
                "xpath=//button[@aria-label='Send without a note']",
                "xpath=//button[@aria-label='Ohne Notiz senden']",
                "xpath=//button[contains(text(), 'Send without a note')]",
                "xpath=//button[contains(text(), 'Ohne Notiz senden')]"
            ]

            for selector in send_no_note_selectors:
                try:
                    btn = self.page.locator(selector)
                    if btn.count() > 0 and btn.first.is_visible():
                        human_move_click(self.page, btn.first)
                        print("      Connection request sent (No Note).")
                        return True
                except:
                    continue

        # Also try alternative selectors for German interface
        alternative_selectors = [
            "xpath=//button[contains(text(), 'Nachricht hinzufügen')]",
            "xpath=//button[contains(text(), 'Ohne Notiz senden')]",
            "xpath=/html/body/div[3]/div/div/div[3]/button[2]",
            "xpath=/html/body/div[5]/div/div/div[3]/button[2]"
        ]

        for selector in alternative_selectors:
            try:
                elements = self.page.locator(selector)
                if elements.count() > 0:
                    for i in range(elements.count()):
                        elem = elements.nth(i)
                        if elem.is_visible():
                            text = elem.inner_text().strip()
                            if text in ["Send without a note", "Ohne Notiz senden"]:
                                human_move_click(self.page, elem)
                                print("      Connection request sent (No Note) - Alternative method.")
                                return True
            except:
                continue

        print("      No modal appeared. Assuming request sent.")
        return True


def is_profile_accessible(page, url, max_retries=2):
    """
    Check if the LinkedIn profile URL is accessible (not 404 or deleted).
    Returns True if accessible, False if 404/not found.
    """
    for attempt in range(max_retries):
        try:
            print(f"      Checking profile accessibility (attempt {attempt + 1}/{max_retries})...")

            _safe_goto(page, url, timeout=60000)
            human_pause(6, 10)

            current_url = page.url.lower()
            original_url = url.lower()

            try:
                original_profile_id = original_url.split('/in/')[-1].rstrip('/')
            except:
                original_profile_id = None

            if '/404' in current_url or 'page-not-found' in current_url:
                print(f"      Redirected to 404 page: {current_url}")
                return False

            if '/in/' not in current_url:
                print(f"      Redirected away from profile page: {current_url}")
                return False

            if original_profile_id:
                try:
                    current_profile_id = current_url.split('/in/')[-1].rstrip('/').split('?')[0]
                    if current_profile_id != original_profile_id:
                        print(f"      Profile ID mismatch - redirected from '{original_profile_id}' to '{current_profile_id}'")
                        return False
                except:
                    pass

            # Verify profile loaded by finding name element
            try:
                human_pause(2, 3)
                name_elem = page.locator("h1").first
                if name_elem.is_visible():
                    profile_name = name_elem.inner_text().strip()
                    if profile_name and len(profile_name.strip()) >= 2:
                        print(f"      Profile accessible - found name: {profile_name}")
                        return True
                    else:
                        if attempt < max_retries - 1:
                            print(f"      Name element empty, retrying...")
                            continue
                        else:
                            print(f"      Name element empty after {max_retries} attempts")
                            return False
                else:
                    if attempt < max_retries - 1:
                        print(f"      Name element not visible, retrying...")
                        continue
                    else:
                        return False

            except Exception:
                if attempt < max_retries - 1:
                    print(f"      Could not find profile name element, retrying...")
                    continue
                else:
                    print(f"      No profile name found after {max_retries} attempts")
                    return False

        except Exception as e:
            if attempt < max_retries - 1:
                print(f"      Error on attempt {attempt + 1}: {e}, retrying...")
                human_pause(2, 3)
                continue
            else:
                print(f"      Error checking profile accessibility after {max_retries} attempts: {e}")
                return False

    return False


def handle_faulty_url(url, bot_input_record_id=None, lead_manager=""):
    """Handle faulty URLs by saving minimal data to Attio leads_sources and deleting from bot_inputs."""
    print(f"      Faulty URL detected: {url}")

    try:
        client = get_attio_client()

        faulty_values = {
            "linkedin_url": url,
            "full_name": "FAULTY LINK",
            "headline": "",
            "about_section": "",
            "experience_text": "",
            "message_1_draft": "",
            "lead_status": "FAULTY_URL",
            "connection_status": "FAULTY_URL",
            "lead_last_scraped_at": datetime.now().isoformat(),
            "lead_created_at": datetime.now().isoformat(),
            "lead_manager": lead_manager,
        }

        client.save_lead(faulty_values)
        print(f"      Faulty URL saved to Attio: {url}")

        if bot_input_record_id:
            client.delete_bot_input(bot_input_record_id)

        return True

    except Exception as e:
        print(f"      Error saving faulty URL to Attio: {e}")
        return False


def main():
    import argparse

    parser = argparse.ArgumentParser(description='LinkedIn Connection Bot with Attio Integration (Playwright)')
    parser.add_argument('--account_name', type=str, required=True,
                       help='Account name (lead_manager) to process leads for')
    parser.add_argument('--suspicious_otp', type=str, default=None,
                       help='OTP code for suspicious login challenge (proxy-triggered)')

    args = parser.parse_args()

    account_name = args.account_name
    print(f"   Using account: {account_name}")

    print("   Ensuring LinkedIn login...")
    driver = ensure_linkedin_login(suspicious_otp=args.suspicious_otp, account_name=account_name)

    if not driver:
        print("   Could not establish LinkedIn session. Exiting.")
        return

    print("   LinkedIn session established. Starting bot operations...")
    page = driver.page

    try:
        print("   Opening LinkedIn...")
        _safe_goto(page, "https://www.linkedin.com/", timeout=60000)
        log_action(page, "linkedin_homepage")
        human_pause(4, 7)

        print("   Session Active. Ready to start automation.")
        human_scroll(page)

        # Read daily limit from config.json
        daily_limit = 18
        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "backend", "config.json")
        try:
            with open(config_path, "r") as f:
                config = json.load(f)
                daily_limit = config.get("daily_connect", 18)
                print(f"   Loaded connection limit from config: {daily_limit}")
        except (FileNotFoundError, json.JSONDecodeError):
            print(f"   Using default connection limit: {daily_limit}")

        # Fetch leads from Attio bot_inputs
        bot_input_leads = get_leads_from_attio(account_name, limit=daily_limit)
        if not bot_input_leads:
            print("   No bot_input leads found in Attio. Exiting.")
            return

        count = 0
        client = get_attio_client()

        print(f"   Found {len(bot_input_leads)} leads. Processing max {daily_limit} today.")

        for lead_record in bot_input_leads:
            if count >= daily_limit:
                print("   Daily limit reached. Stopping script safely.")
                break

            url = lead_record["linkedin_url"]
            record_id = lead_record["record_id"]
            prompt_template_str = lead_record.get("prompt_template", "")

            # Parse per-lead template
            template_dict = None
            if prompt_template_str:
                try:
                    template_dict = json.loads(prompt_template_str)
                except (json.JSONDecodeError, TypeError):
                    print(f"      Could not parse prompt_template, using default")

            print(f"\n[{count + 1}/{daily_limit}]    Checking: {url}")

            exists, record = check_if_exists(url)
            if exists:
                status = record.get('lead_status', 'UNKNOWN')
                print(f"   Skipping: Lead already in Attio (Status: {status})")
                # Still delete from bot_inputs to avoid re-processing
                client.delete_bot_input(record_id)
                continue

            li_manager = LinkedInInteractionManager(page)

            # PHASE 0: CHECK IF PROFILE IS ACCESSIBLE
            if not is_profile_accessible(page, url):
                print(f"      Profile not accessible (404 or deleted): {url}")
                handle_faulty_url(url, bot_input_record_id=record_id, lead_manager=account_name)
                count += 1

                faulty_pause = random.randint(25, 35)
                print(f"      Pausing for {faulty_pause}s after faulty link...")
                time.sleep(faulty_pause)

                continue

            try:
                # PHASE 1: DATA GATHERING
                print("      Scraping profile data (scrolling down)...")
                human_scroll(page, max_offset=600)
                profile_data = scrape_profile_data(page)

                if (profile_data["full_name"] == "Unknown" or
                    not profile_data["full_name"] or
                    len(profile_data["full_name"].strip()) < 2):

                    print(f"      Could not extract valid profile data. Treating as faulty URL.")
                    handle_faulty_url(url, bot_input_record_id=record_id, lead_manager=account_name)
                    count += 1

                    faulty_pause = random.randint(25, 35)
                    print(f"      Pausing for {faulty_pause}s after faulty link...")
                    time.sleep(faulty_pause)

                    continue

                posts_data = fetch_profile_posts(url)
                outreach_msg, followup_msg_1, followup_msg_2, followup_msg_3, followup_msg_4 = generate_ai_messages(
                    profile_data, posts_data, template_dict=template_dict
                )
                print("      Data gathering complete.")

                # CRITICAL FIX: RESET VIEWPORT
                print("      Returning to top of profile for interaction...")
                page.evaluate("window.scrollTo({top: 0, behavior: 'auto'})")
                human_pause(2, 3)

                # PHASE 2: INTERACTION
                print("      Checking Connection Status...")
                status = li_manager.get_connection_status()
                print(f"      Status: {status}")

                db_status_update = "SCRAPED"
                last_contacted = None

                if status == "CONNECTED":
                    print("      Already connected. Skipping message for now.")
                    db_status_update = "CONNECTED"

                elif status == "NOT_CONNECTED":
                    sent = li_manager.send_connection_request()
                    if sent:
                        db_status_update = "PENDING"

                elif status == "PENDING":
                    print("      Invite pending. Skipping.")
                    db_status_update = "PENDING"

                # PHASE 3: SAVE TO ATTIO
                save_lead_to_db(
                    url, profile_data, posts_data, outreach_msg, followup_msg_1, followup_msg_2, followup_msg_3, followup_msg_4,
                    status=db_status_update,
                    last_contacted=last_contacted,
                    lead_manager=account_name,
                    prompt_template=prompt_template_str,
                )

                # PHASE 4: CLEANUP - delete from bot_inputs
                client.delete_bot_input(record_id)

                count += 1

            except Exception as e_inner:
                print(f"      Error processing this lead: {e_inner}")
                print(f"      Treating as faulty URL due to processing error.")

                log_action(page, "error_lead_processing")

                handle_faulty_url(url, bot_input_record_id=record_id, lead_manager=account_name)
                count += 1

                faulty_pause = random.randint(25, 35)
                print(f"      Pausing for {faulty_pause}s after faulty link...")
                time.sleep(faulty_pause)

                continue

            sleep_time = random.randint(60, 180)
            minutes = round(sleep_time / 60, 1)
            print(f"   Resting for {minutes} min ({sleep_time}s) before next profile...")

            time.sleep(sleep_time)

        print("\n   Batch job complete!")

    except Exception as e:
        print(f"   Critical Script Error: {e}")
        log_action(page, "critical_failure")

    finally:
        print("   Closing browser session...")
        try:
            driver.quit()
        except:
            pass


if __name__ == "__main__":
    main()
