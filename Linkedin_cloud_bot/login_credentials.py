"""LinkedIn Login Handler - Simple login to save session cookies"""
import time
import random
import os
from datetime import datetime
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from dotenv import load_dotenv

load_dotenv()

def human_pause(min_s: float = 0.3, max_s: float = 0.9):
    """Human-like pause between actions"""
    time.sleep(random.uniform(min_s, max_s))

def human_move_click(driver, element, max_retries=3):
    """Robust clicker that handles scrolling and moving targets"""
    try:
        driver.execute_script(
            "arguments[0].scrollIntoView({behavior: 'auto', block: 'center'});",
            element
        )
        time.sleep(0.2)
        driver.execute_script("window.scrollBy(0, -50);")
    except Exception:
        pass

    human_pause(1.0, 1.5)

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
                .click()
                .perform()
            )

            print(f"✅ Click successful on attempt {attempt + 1}")
            human_pause(0.5, 1.0)
            return True

        except Exception as e:
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

def log_action(driver, action_name):
    """Log screenshots and page source for debugging"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshots_dir = "screenshots"
    if not os.path.exists(screenshots_dir):
        os.makedirs(screenshots_dir)

    screenshot_path = f"{screenshots_dir}/{timestamp}_{action_name}.png"
    try:
        driver.save_screenshot(screenshot_path)
        print(f"📸 Screenshot saved: {screenshot_path}")
    except Exception as e:
        print(f"⚠️ Could not save screenshot: {e}")

    html_path = f"{screenshots_dir}/{timestamp}_{action_name}_page_source.html"
    try:
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(driver.page_source)
        print(f"📄 Page source saved: {html_path}")
    except Exception as e:
        print(f"⚠️ Could not save page source: {e}")

def human_type(element, text, typing_delay=0.1):
    """Human-like typing with random delays"""
    element.clear()
    human_pause(0.5, 1.0)
    
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(0.05, typing_delay))
    
    human_pause(0.5, 1.0)

def find_element_with_fallback(driver, xpath, css_selector, element_name):
    """Find element using XPath first, then CSS selector as fallback"""
    try:
        # Try XPath first
        element = driver.find_element(By.XPATH, xpath)
        if element.is_displayed():
            print(f"✅ Found {element_name} using XPath")
            return element
    except:
        pass
    
    try:
        # Fallback to CSS selector
        element = driver.find_element(By.CSS_SELECTOR, css_selector)
        if element.is_displayed():
            print(f"✅ Found {element_name} using CSS selector")
            return element
    except:
        pass
    
    print(f"❌ Could not find {element_name}")
    return None

def check_if_logged_in(driver):
    """
    Sanity check function to determine if user is logged in
    Goes to https://www.linkedin.com/ and checks for the presence of the heading element
    If the heading element exists (regardless of content), we're NOT logged in
    If the heading element doesn't exist, we're logged in
    Returns True if logged in, False if not logged in
    """
    try:
        print("🔍 Checking if already logged in...")
        driver.get("https://www.linkedin.com/")
        human_pause(3, 4)  # Wait exactly 3-4 seconds as requested
        
        # Check for the presence of the heading element that indicates we're NOT logged in
        try:
            heading_element = driver.find_element(By.XPATH, "/html/body/main/section[1]/div/h1")
            # If we found the heading element, we're NOT logged in (regardless of its content)
            heading_text = heading_element.text.strip()
            print(f"📝 Found login page heading: '{heading_text}'")
            print("❌ Not logged in - login page heading element exists")
            return False
                
        except Exception:
            # If we can't find the heading element, we're logged in (different page structure)
            print("✅ Could not find login page heading element - user is logged in")
            return True
            
    except Exception as e:
        print(f"⚠️ Error checking login status: {e}")
        # If there's an error, assume not logged in to be safe
        return False

def setup_chrome_driver():
    """Setup Chrome driver with user data directory - creates directory if it doesn't exist"""
    try:
        print("🚀 Setting up Chrome driver...")
        
        options = uc.ChromeOptions()
        
        # Create user data directory if it doesn't exist
        script_dir = os.path.dirname(os.path.abspath(__file__))
        user_data_path = os.path.join(script_dir, "user_data_yatharth")
        
        # Create directory if it doesn't exist
        if not os.path.exists(user_data_path):
            os.makedirs(user_data_path)
            print(f"📁 Created user data directory: {user_data_path}")
        
        options.add_argument(f"--user-data-dir={user_data_path}")
        options.add_argument("--profile-directory=Default")
        
        # Security and stealth options
        options.add_argument('--ignore-certificate-errors')
        options.add_argument('--ignore-ssl-errors')
        options.add_argument('--disable-webrtc')
        options.set_capability('acceptInsecureCerts', True)

        # User agent
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ]
        options.add_argument(f'--user-agent={user_agents[0]}')

        # Create driver
        driver = uc.Chrome(options=options)

        # Anti-detection
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        })
        
        print("✅ Chrome driver setup complete")
        return driver
        
    except Exception as e:
        print(f"❌ Failed to setup Chrome driver: {e}")
        return None

def linkedin_login():
    """
    Simple LinkedIn login function with CLI input prompts
    First checks if already logged in, then proceeds with login if needed
    """
    driver = setup_chrome_driver()
    if not driver:
        return None
    
    try:
        # First, check if we're already logged in
        if check_if_logged_in(driver):
            print("✅ User is already logged in! Skipping login process.")
            log_action(driver, "already_logged_in")
            return driver
        
        # If not logged in, proceed with login process
        print("🔐 User is not logged in. Starting login process...")
        
        print("🔗 Going to LinkedIn login page...")
        driver.get("https://www.linkedin.com/login")
        human_pause(3, 5)
        log_action(driver, "login_page_loaded")
        
        print("🔐 Starting login process...")
        
        # STEP 1: Find and fill email field
        print("\n📧 STEP 1: Email Input")
        email_element = find_element_with_fallback(
            driver,
            "/html/body/div[1]/main/div[2]/div[1]/form/div[1]/input",
            "#username",
            "email input field"
        )
        
        if not email_element:
            log_action(driver, "email_field_not_found")
            driver.quit()
            return None
        
        email = input("Enter your LinkedIn email: ").strip()
        print("📧 Entering email...")
        human_type(email_element, email)
        
        # STEP 2: Find and fill password field
        print("\n🔑 STEP 2: Password Input")
        password_element = find_element_with_fallback(
            driver,
            "/html/body/div[1]/main/div[2]/div[1]/form/div[2]/input",
            "#password",
            "password input field"
        )
        
        if not password_element:
            log_action(driver, "password_field_not_found")
            driver.quit()
            return None
        
        password = input("Enter your LinkedIn password: ").strip()
        print("🔑 Entering password...")
        human_type(password_element, password)
        
        # STEP 3: Find and click sign in button
        print("\n🚀 STEP 3: Sign In Button")
        signin_button = find_element_with_fallback(
            driver,
            "/html/body/div[1]/main/div[2]/div[1]/form/div[4]/button",
            "#organic-div > form > div.login__form_action_container > button",
            "sign in button"
        )
        
        if not signin_button:
            log_action(driver, "signin_button_not_found")
            driver.quit()
            return None
        
        print("🚀 Clicking sign in button...")
        human_move_click(driver, signin_button)
        
        # Wait for login to process
        human_pause(5, 8)
        log_action(driver, "login_attempted")
        
        # First, check if login was successful using our sanity check
        if check_if_logged_in(driver):
            print("✅ Login successful! Session cookies saved to user data directory.")
            log_action(driver, "login_success")
            return driver
        
        # If not logged in yet, check if OTP/2FA is required by looking for OTP input element
        print("🔍 Checking if OTP/2FA is required...")
        otp_element = find_element_with_fallback(
            driver,
            "/html/body/div[1]/main/form/div[1]/input[18]",
            "#input__phone_verification_pin",
            "OTP input field"
        )
        
        if otp_element:
            print("\n🔐 STEP 4: Two-Factor Authentication Detected")
            print("⚠️ OTP/2FA verification required")
            
            # STEP 4: Handle OTP input
            otp_code = input("Enter the OTP code sent to your device: ").strip()
            print("📱 Entering OTP code...")
            human_type(otp_element, otp_code)
            
            # Find and click submit button for OTP
            print("\n✅ OTP Submit Button")
            otp_submit_button = find_element_with_fallback(
                driver,
                "/html/body/div[1]/main/form/div[2]/button",
                "#two-step-submit-button",
                "OTP submit button"
            )
            
            if otp_submit_button:
                print("🚀 Clicking OTP submit button...")
                human_move_click(driver, otp_submit_button)
                
                # Wait for OTP verification
                human_pause(5, 8)
                log_action(driver, "otp_submitted")
                
                # Check final login status using sanity check
                if check_if_logged_in(driver):
                    print("✅ Login successful with OTP! Session cookies saved.")
                    log_action(driver, "login_success_with_otp")
                    return driver
                else:
                    print("❌ OTP verification may have failed")
                    log_action(driver, "otp_verification_failed")
            else:
                print("❌ Could not find OTP submit button")
                log_action(driver, "otp_submit_button_not_found")
            
            # Manual fallback for OTP issues
            print("👉 If OTP verification is still pending, please complete it manually in the browser")
            print("👉 Press ENTER once you see your LinkedIn feed...")
            input()
            
            # Final check after manual intervention
            if check_if_logged_in(driver):
                print("✅ Login successful after manual OTP completion!")
                log_action(driver, "login_success_manual_otp")
                return driver
        else:
            # No OTP element found, but login didn't succeed - might be other issues
            print("❌ No OTP required, but login may have failed")
            current_url = driver.current_url.lower()
            print(f"🔍 Current URL: {current_url}")
            
            # Check for common error scenarios
            if "challenge" in current_url or "captcha" in current_url:
                print("⚠️ CAPTCHA or other challenge detected")
            elif "login" in current_url:
                print("⚠️ Still on login page - credentials may be incorrect")
            
            log_action(driver, "login_failed_no_otp")
        
        # If we're still not logged in, provide manual fallback
        print("❌ Automatic login sequence completed but may need manual intervention")
        print("👉 Please check the browser window and complete any remaining steps")
        print("👉 Press ENTER once you see your LinkedIn feed...")
        input()
        
        # Final verification using sanity check
        if check_if_logged_in(driver):
            print("✅ Login successful after manual completion!")
            log_action(driver, "login_success_final")
            return driver
        else:
            print("❌ Login failed - unable to reach LinkedIn feed")
            log_action(driver, "login_failed_final")
            driver.quit()
            return None
        
    except Exception as e:
        print(f"❌ Critical error during login: {e}")
        log_action(driver, "login_critical_error")
        try:
            driver.quit()
        except:
            pass
        return None

def ensure_linkedin_login():
    """
    Convenience function for other bots to ensure LinkedIn login
    Returns a driver instance if login is successful, None otherwise
    """
    return linkedin_login()

def main():
    """Test the login functionality"""
    print("🧪 Testing LinkedIn Login...")
    
    driver = linkedin_login()
    
    if driver:
        print("✅ Login test successful!")
        print("� Current URL:", driver.current_url)
        print("🍪 Session cookies have been saved to user_data_yatharth directory")
        print("👉 Other bots can now use this saved session")
        
        # Keep browser open for testing
        print("👉 Browser will stay open for 30 seconds for testing...")
        time.sleep(30)
        
        driver.quit()
        print("🔒 Browser closed")
    else:
        print("❌ Login test failed!")

if __name__ == "__main__":
    main()