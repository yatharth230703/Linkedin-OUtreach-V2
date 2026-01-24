"""LinkedIn Login Handler - Simple login to save session cookies with proxy support"""
import time
import random
import os
import zipfile
import string
import math
from datetime import datetime
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from dotenv import load_dotenv

# Import proxy configuration
from proxy_config import get_proxy_options
from proxy_requests import get_proxy_session

load_dotenv()

def human_pause(min_s: float = 0.3, max_s: float = 0.9):
    """Human-like pause between actions"""
    time.sleep(random.uniform(min_s, max_s))

def bezier_curve(p0, p1, p2, p3, n_steps=20):
    """Generate points for a Bezier curve"""
    points = []
    for t in [i / n_steps for i in range(n_steps + 1)]:
        x = (1 - t)**3 * p0[0] + 3 * (1 - t)**2 * t * p1[0] + 3 * (1 - t) * t**2 * p2[0] + t**3 * p3[0]
        y = (1 - t)**3 * p0[1] + 3 * (1 - t)**2 * t * p1[1] + 3 * (1 - t) * t**2 * p2[1] + t**3 * p3[1]
        points.append((x, y))
    return points

def human_like_mouse_move(driver, start_element, end_element):
    """Moves mouse from start_element to end_element in a human-like curve.
    If start_element is None, moves from current mouse position (requires tracking).
    For simplicity, this function moves from a random point near the target to the target."""
    try:
        # Get target coordinates
        end_rect = end_element.rect
        target_x = end_rect['x'] + (end_rect['width'] / 2) + random.randint(-5, 5)
        target_y = end_rect['y'] + (end_rect['height'] / 2) + random.randint(-5, 5)
        
        # Get viewport size
        viewport_width = driver.execute_script("return window.innerWidth;")
        viewport_height = driver.execute_script("return window.innerHeight;")
        
        # Fake a start point (random location in viewport)
        start_x = random.randint(0, viewport_width // 2)
        start_y = random.randint(0, viewport_height // 2)
        
        # Define control points for the curve (randomized)
        control1_x = random.randint(min(start_x, int(target_x)), max(start_x, int(target_x)))
        control1_y = random.randint(0, viewport_height)
        control2_x = random.randint(min(start_x, int(target_x)), max(start_x, int(target_x)))
        control2_y = random.randint(0, viewport_height)
        
        path = bezier_curve(
            (start_x, start_y), 
            (control1_x, control1_y), 
            (control2_x, control2_y), 
            (target_x, target_y)
        )
        
        # Execute movement via ActionChains
        actions = ActionChains(driver)
        actions.move_to_element(end_element)
        # Add slight jitter before clicking
        actions.move_by_offset(random.randint(-2, 2), random.randint(-2, 2))
        actions.pause(random.uniform(0.1, 0.3))
        actions.click()
        actions.perform()
    except Exception as e:
        print(f"⚠️ Curve move failed, falling back to standard: {e}")
        # Fallback to JS click
        driver.execute_script("arguments[0].click();", end_element)

def smooth_scroll_to_element(driver, element):
    """Scrolls to an element using window.scrollTo with 'smooth' behavior and random offsets to mimic human imprecision."""
    try:
        driver.execute_script("""
            const element = arguments[0];
            const elementRect = element.getBoundingClientRect();
            const absoluteElementTop = elementRect.top + window.pageYOffset;
            const middle = absoluteElementTop - (window.innerHeight / 2);
            // Add random offset so we don't scroll exactly to center every time
            const randomOffset = Math.floor(Math.random() * 100) - 50; 
            window.scrollTo({
                top: middle + randomOffset,
                behavior: 'smooth'
            });
        """, element)
        # Wait for scroll to finish (variable time based on distance)
        time.sleep(random.uniform(0.8, 1.5))
    except Exception:
        # Fallback
        driver.execute_script("arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", element)

def human_move_click(driver, element, max_retries=3):
    """Robust clicker that handles scrolling and moving targets with human-like behavior"""
    try:
        # Use smooth scrolling instead of instant scroll
        smooth_scroll_to_element(driver, element)
    except Exception:
        pass

    human_pause(1.0, 1.5)

    for attempt in range(max_retries):
        try:
            if not element.is_enabled() or not element.is_displayed():
                print(f"⚠️ Element not clickable on attempt {attempt + 1}")
                human_pause(0.5, 1.0)
                continue

            # Use Bézier curve mouse movement for more human-like behavior
            try:
                human_like_mouse_move(driver, None, element)
                print(f"✅ Click successful on attempt {attempt + 1} (Bézier curve)")
                human_pause(0.5, 1.0)
                return True
            except Exception as e:
                # Fallback to standard ActionChains
                print(f"⚠️ Bézier move failed, using standard: {e}")
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

def create_proxy_auth_extension(proxy_host, proxy_port, proxy_user, proxy_pass):
    """
    Create a Chrome extension for proxy authentication
    This is the only reliable way to use authenticated proxies with undetected-chromedriver
    """
    manifest_json = """
    {
        "version": "1.0.0",
        "manifest_version": 2,
        "name": "Chrome Proxy",
        "permissions": [
            "proxy",
            "tabs",
            "unlimitedStorage",
            "storage",
            "<all_urls>",
            "webRequest",
            "webRequestBlocking"
        ],
        "background": {
            "scripts": ["background.js"]
        },
        "minimum_chrome_version":"22.0.0"
    }
    """

    background_js = """
    var config = {
        mode: "fixed_servers",
        rules: {
            singleProxy: {
                scheme: "http",
                host: "%s",
                port: parseInt(%s)
            },
            bypassList: ["localhost"]
        }
    };

    chrome.proxy.settings.set({value: config, scope: "regular"}, function() {});

    function callbackFn(details) {
        return {
            authCredentials: {
                username: "%s",
                password: "%s"
            }
        };
    }

    chrome.webRequest.onAuthRequired.addListener(
        callbackFn,
        {urls: ["<all_urls>"]},
        ['blocking']
    );
    """ % (proxy_host, proxy_port, proxy_user, proxy_pass)

    # Create extension directory
    pluginfile = 'proxy_auth_plugin.zip'
    
    with zipfile.ZipFile(pluginfile, 'w') as zp:
        zp.writestr("manifest.json", manifest_json)
        zp.writestr("background.js", background_js)
    
    return pluginfile

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

def setup_chrome_driver():
    """Setup Chrome driver with advanced anti-detection for VMs"""
    try:
        print("🚀 Setting up Chrome driver with Stealth Config...")
        
        # Test proxy connection first
        test_proxy_connection()
        
        options = uc.ChromeOptions()
        
        # --- 1. Basic Persistence & UI ---
        script_dir = os.path.dirname(os.path.abspath(__file__))
        user_data_path = os.path.join(script_dir, "user_data_yath")
        
        # Create directory if it doesn't exist
        if not os.path.exists(user_data_path):
            os.makedirs(user_data_path)
            print(f"📁 Created user data directory: {user_data_path}")
        
        options.add_argument(f"--user-data-dir={user_data_path}")
        options.add_argument("--profile-directory=Default")
        options.add_argument("--start-maximized")  # Real users rarely run windowed mode on login
        
        # --- 2. Advanced Anti-Detection Flags ---
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-infobars")
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-popup-blocking")
        
        # IMPORTANT: Force a standard resolution. VMs often default to weird sizes like 800x600.
        options.add_argument("--window-size=1920,1080")
        
        # Language matching (Ensure this matches your Proxy's location ideally, or generic US)
        options.add_argument("--lang=en-US")
        
        # --- 3. WebRTC Handling (Better than disabling) ---
        # Instead of --disable-webrtc (which is a flag in itself), 
        # we tell Chrome to handle WebRTC routing securely.
        prefs = {
            "webrtc.ip_handling_policy": "default_public_interface_only",
            "webrtc.multiple_routes_enabled": False,
            "webrtc.nonproxied_udp_enabled": False
        }
        options.add_experimental_option("prefs", prefs)
        
        # Proxy configuration with authentication via extension
        use_proxy = os.getenv("USE_PROXY", "false").lower() == "true"
        proxy_extension_path = None
        
        if use_proxy:
            proxy_host = os.getenv("PROXY_HOST")
            proxy_port = os.getenv("PROXY_PORT")
            proxy_username = os.getenv("PROXY_USERNAME")
            proxy_password = os.getenv("PROXY_PASSWORD")
            
            if all([proxy_host, proxy_port, proxy_username, proxy_password]):
                print(f"🌐 Configuring proxy: {proxy_host}:{proxy_port}")
                
                # Create proxy authentication extension
                try:
                    proxy_extension_path = create_proxy_auth_extension(
                        proxy_host, proxy_port, proxy_username, proxy_password
                    )
                    print("✅ Proxy authentication extension created")
                except Exception as e:
                    print(f"⚠️ Could not create proxy extension: {e}")
                    proxy_extension_path = None
            else:
                print("⚠️ Proxy credentials incomplete, proceeding without proxy")
        else:
            print("ℹ️ Proxy disabled in configuration")
        
        # Security and stealth options
        options.add_argument('--ignore-certificate-errors')
        options.add_argument('--ignore-ssl-errors')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--no-sandbox')
        options.set_capability('acceptInsecureCerts', True)

        # User agent - Updated to match Windows platform
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ]
        options.add_argument(f'--user-agent={user_agents[0]}')
        
        # Add proxy extension if created
        if proxy_extension_path and os.path.exists(proxy_extension_path):
            options.add_extension(proxy_extension_path)
            print("✅ Proxy extension added to Chrome options")

        # Create driver
        driver = uc.Chrome(options=options)
        
        # Clean up the extension file after driver creation
        if proxy_extension_path and os.path.exists(proxy_extension_path):
            import atexit
            def cleanup():
                try:
                    if os.path.exists(proxy_extension_path):
                        os.remove(proxy_extension_path)
                        print("🧹 Cleaned up proxy extension file")
                except:
                    pass
            atexit.register(cleanup)

        # --- 4. DEEP STEALTH INJECTION via CDP ---
        # This is the most important part for VM evasion.
        # A. Spoof WebGL Vendor (Hide "VMware" or "SwiftShader")
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                // Overwrite WebGL Renderer
                const getParameter = WebGLRenderingContext.prototype.getParameter;
                WebGLRenderingContext.prototype.getParameter = function(parameter) {
                    if (parameter === 37445) { return 'Google Inc. (NVIDIA)'; }
                    if (parameter === 37446) { return 'ANGLE (NVIDIA, NVIDIA GeForce GTX 1050 Ti Direct3D11 vs_5_0 ps_5_0, D3D11)'; }
                    return getParameter.call(this, parameter);
                };
                
                // Also handle WebGL2
                if (typeof WebGL2RenderingContext !== 'undefined') {
                    const getParameter2 = WebGL2RenderingContext.prototype.getParameter;
                    WebGL2RenderingContext.prototype.getParameter = function(parameter) {
                        if (parameter === 37445) { return 'Google Inc. (NVIDIA)'; }
                        if (parameter === 37446) { return 'ANGLE (NVIDIA, NVIDIA GeForce GTX 1050 Ti Direct3D11 vs_5_0 ps_5_0, D3D11)'; }
                        return getParameter2.call(this, parameter);
                    };
                }
                
                // Overwrite Navigator Hardware Concurrency (VMs often return 1 or 2)
                Object.defineProperty(navigator, 'hardwareConcurrency', {
                    get: () => 4,
                });
                
                // Overwrite Device Memory (VMs often return low RAM)
                Object.defineProperty(navigator, 'deviceMemory', {
                    get: () => 8,
                });
                
                // Overwrite Platform (Ensure it matches your User Agent)
                Object.defineProperty(navigator, 'platform', {
                    get: () => 'Win32',
                });
                
                // Remove 'webdriver' property
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined,
                });
                
                // Spoof Chrome runtime
                window.chrome = {
                    runtime: {}
                };
                
                // Spoof permissions
                const originalQuery = window.navigator.permissions.query;
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications' ?
                        Promise.resolve({ state: Notification.permission }) :
                        originalQuery(parameters)
                );
                
                // Spoof plugins
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5],
                });
                
                // Spoof languages
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['en-US', 'en'],
                });
            """
        })
        
        print("✅ Chrome driver setup complete with advanced VM evasion")
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
        
        # If not logged in yet, check if OTP/2FA is required by looking for verification input element
        print("🔍 Checking if OTP/2FA or email verification is required...")
        print("⏳ Waiting for verification page to load...")
        human_pause(3, 5)  # Give page time to load
        
        # Log current URL for debugging
        current_url = driver.current_url
        print(f"📍 Current URL: {current_url}")
        
        # Try multiple selectors for verification input (both OTP and suspicious login)
        # Prioritized by specificity - most specific first
        otp_element = None
        verification_selectors = [
            # Most specific - exact ID match with type and name
            ("//input[@id='input__email_verification_pin'][@name='pin'][@type='number']", "ID+name+type: input__email_verification_pin"),
            # ID only (most common)
            ("//input[@id='input__email_verification_pin']", "ID: input__email_verification_pin"),
            ("#input__email_verification_pin", "CSS: #input__email_verification_pin"),
            # Name and type combination
            ("//input[@name='pin'][@type='number']", "name=pin type=number"),
            ("//input[@name='pin']", "name=pin"),
            # Class-based
            ("//input[@class='form__input--text input_verification_pin']", "class: input_verification_pin"),
            # Generic form input
            ("/html/body/div[1]/main/form/div[1]/input", "XPath: main form input"),
            # 2FA alternatives
            ("#input__phone_verification_pin", "CSS: #input__phone_verification_pin (2FA)"),
            ("/html/body/div[1]/main/form/div[1]/input[18]", "XPath: OTP input (2FA)"),
        ]
        
        print(f"🔎 Trying {len(verification_selectors)} different selectors...")
        for idx, (selector, description) in enumerate(verification_selectors, 1):
            try:
                print(f"   [{idx}/{len(verification_selectors)}] Trying: {description}")
                if selector.startswith("//") or selector.startswith("/html"):
                    # XPath selector
                    element = driver.find_element(By.XPATH, selector)
                else:
                    # CSS selector
                    element = driver.find_element(By.CSS_SELECTOR, selector)
                
                if element and element.is_displayed():
                    otp_element = element
                    print(f"✅ Found verification input using: {description}")
                    break
                else:
                    print(f"   ⚠️ Element found but not displayed")
            except Exception as e:
                print(f"   ❌ Not found: {str(e)[:50]}")
                continue
        
        if not otp_element:
            print("❌ Could not find verification input field with any selector")
            print("📄 Saving page source for debugging...")
            log_action(driver, "verification_field_not_found")
        
        if otp_element:
            print("\n🔐 STEP 4: Verification Required")
            
            # Check if this is suspicious login verification or regular 2FA
            try:
                # Look for suspicious login indicators
                page_text = driver.page_source.lower()
                if "suspicious" in page_text or "quick verification" in page_text or "login attempt seems suspicious" in page_text:
                    print("⚠️ LinkedIn detected suspicious login activity")
                    print("📧 Verification code sent to your email address")
                    verification_code = input("Enter the verification code sent to your email: ").strip()
                else:
                    print("⚠️ Two-Factor Authentication (2FA) required")
                    print("📱 Verification code sent to your device")
                    verification_code = input("Enter the OTP/2FA code sent to your device: ").strip()
            except:
                # Fallback - ask for verification code generically
                print("⚠️ Verification required")
                verification_code = input("Enter the verification code (from email or device): ").strip()
            
            print("🔑 Entering verification code...")
            human_type(otp_element, verification_code)
            
            # Find and click submit button - try multiple selectors
            print("\n✅ Looking for Submit Button...")
            
            # Try specific selectors - prioritized by specificity
            submit_button = None
            submit_selectors = [
                # Most specific - exact ID with type and class
                ("//button[@id='email-pin-submit-button'][@type='submit']", "ID+type: email-pin-submit-button"),
                # ID only (most reliable)
                ("//button[@id='email-pin-submit-button']", "ID: email-pin-submit-button"),
                ("#email-pin-submit-button", "CSS: #email-pin-submit-button"),
                # Type-based
                ("//button[@type='submit']", "type=submit"),
                # XPath position-based
                ("/html/body/div[1]/main/form/div[2]/button", "XPath: form submit button"),
                # Text-based (less reliable but good fallback)
                ("//button[contains(text(), 'Submit')]", "text contains Submit"),
                # 2FA alternative
                ("#two-step-submit-button", "CSS: #two-step-submit-button"),
            ]
            
            for selector, description in submit_selectors:
                try:
                    if selector.startswith("//") or selector.startswith("/html"):
                        # XPath selector
                        submit_button = driver.find_element(By.XPATH, selector)
                    else:
                        # CSS selector
                        submit_button = driver.find_element(By.CSS_SELECTOR, selector)
                    
                    if submit_button and submit_button.is_displayed():
                        print(f"✅ Found submit button using: {description}")
                        break
                    else:
                        submit_button = None
                except:
                    submit_button = None
                    continue
            
            if submit_button:
                print("🚀 Clicking submit button...")
                human_move_click(driver, submit_button)
                
                # Wait for verification
                human_pause(5, 8)
                log_action(driver, "verification_submitted")
                
                # Check final login status using sanity check
                if check_if_logged_in(driver):
                    print("✅ Login successful with verification! Session cookies saved.")
                    log_action(driver, "login_success_with_verification")
                    return driver
                else:
                    print("❌ Verification may have failed")
                    log_action(driver, "verification_failed")
            else:
                print("❌ Could not find submit button")
                log_action(driver, "submit_button_not_found")
            
            # Manual fallback for verification issues
            print("👉 If verification is still pending, please complete it manually in the browser")
            print("👉 Press ENTER once you see your LinkedIn feed...")
            input()
            
            # Final check after manual intervention
            if check_if_logged_in(driver):
                print("✅ Login successful after manual verification completion!")
                log_action(driver, "login_success_manual_verification")
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

