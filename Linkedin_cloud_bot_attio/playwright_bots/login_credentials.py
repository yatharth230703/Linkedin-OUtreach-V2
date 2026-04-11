"""LinkedIn Login Handler - Playwright version with native proxy support and stealth"""
import time
import random
import os
import sys
import math
from datetime import datetime
from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext
from playwright_stealth import Stealth
from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from proxy_requests import get_proxy_session

load_dotenv()


def _account_slug(account_name):
    """Convert account name to a filesystem-safe slug."""
    return account_name.strip().lower().replace(" ", "_") if account_name else ""


# iproyal sticky-session ID — pins all proxy requests in one run to the same
# residential exit IP. Without this, iproyal rotates the IP per-connection,
# breaking LinkedIn's session continuity.
#
# Regenerated via _regenerate_proxy_session() when a login attempt fails
# (likely because the current IP is flagged by LinkedIn). The next attempt
# then gets a completely different exit IP.
import secrets as _secrets
_PROXY_SESSION_ID = _secrets.token_hex(8)


def _regenerate_proxy_session():
    """Get a new sticky proxy session ID → next browser launch uses a different exit IP."""
    global _PROXY_SESSION_ID
    old = _PROXY_SESSION_ID
    _PROXY_SESSION_ID = _secrets.token_hex(8)
    print(f"   Proxy session rotated: {old[:6]}... → {_PROXY_SESSION_ID[:6]}... (new exit IP on next browser launch)")


def get_proxy_password_for_account(account_name=""):
    """Build the full proxy password with geo-suffix and sticky session."""
    base = os.getenv("PROXY_PASSWORD_BASE", os.getenv("PROXY_PASSWORD", ""))
    slug = _account_slug(account_name)

    if slug == "yatharth_bisht":
        geo = "_country-in_city-delhi"
    elif slug in ("maurice", "leon"):
        geo = "_country-de_city-hamburg"
    else:
        # Unknown account: use raw PROXY_PASSWORD if explicitly set, else base.
        raw = os.getenv("PROXY_PASSWORD", "")
        return raw if raw else base

    # Append sticky session suffix so every request in this process exits via
    # the same residential IP. The session ID is stable per-process (regenerated
    # on each new orchestrator run) which gives us session continuity within a
    # run AND IP rotation between runs.
    return f"{base}{geo}_session-{_PROXY_SESSION_ID}"


class PlaywrightDriver:
    """Wrapper to provide a unified interface similar to Selenium's driver for cleanup"""
    def __init__(self, playwright_instance, browser, context, page):
        self._playwright = playwright_instance
        self.browser = browser
        self.context = context
        self.page = page

    def quit(self):
        try:
            self.context.close()
        except:
            pass
        try:
            self.browser.close()
        except:
            pass
        try:
            self._playwright.stop()
        except:
            pass


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


def human_like_mouse_move(page, end_element):
    """Moves mouse to element in a human-like curve using Bezier interpolation."""
    try:
        box = end_element.bounding_box()
        if not box:
            end_element.click()
            return

        target_x = box['x'] + (box['width'] / 2) + random.randint(-5, 5)
        target_y = box['y'] + (box['height'] / 2) + random.randint(-5, 5)

        viewport = page.viewport_size
        viewport_width = viewport['width'] if viewport else 1920
        viewport_height = viewport['height'] if viewport else 1080

        start_x = random.randint(0, viewport_width // 2)
        start_y = random.randint(0, viewport_height // 2)

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

        # Move mouse along the bezier path
        for point in path:
            page.mouse.move(point[0], point[1])
            time.sleep(random.uniform(0.01, 0.03))

        # Add slight jitter before clicking
        page.mouse.move(target_x + random.randint(-2, 2), target_y + random.randint(-2, 2))
        time.sleep(random.uniform(0.1, 0.3))
        page.mouse.click(target_x, target_y)
        print(f"   Click successful (Bezier curve)")

    except Exception as e:
        print(f"   Curve move failed, falling back to standard: {e}")
        try:
            end_element.click(force=True)
        except:
            page.evaluate("el => el.click()", end_element.element_handle())


def smooth_scroll_to_element(page, element):
    """Scrolls to an element using smooth scrolling with random offsets."""
    try:
        element.evaluate("""
            (element) => {
                const elementRect = element.getBoundingClientRect();
                const absoluteElementTop = elementRect.top + window.pageYOffset;
                const middle = absoluteElementTop - (window.innerHeight / 2);
                const randomOffset = Math.floor(Math.random() * 100) - 50;
                window.scrollTo({
                    top: middle + randomOffset,
                    behavior: 'smooth'
                });
            }
        """)
        time.sleep(random.uniform(0.8, 1.5))
    except Exception:
        try:
            element.scroll_into_view_if_needed()
        except:
            pass


def human_move_click(page, element, max_retries=3):
    """Robust clicker that handles scrolling and moving targets with human-like behavior"""
    try:
        smooth_scroll_to_element(page, element)
    except Exception:
        pass

    human_pause(1.0, 1.5)

    for attempt in range(max_retries):
        try:
            if not element.is_visible():
                print(f"   Element not visible on attempt {attempt + 1}")
                human_pause(0.5, 1.0)
                continue

            # Try Bezier curve mouse movement
            try:
                human_like_mouse_move(page, element)
                print(f"   Click successful on attempt {attempt + 1} (Bezier curve)")
                human_pause(0.5, 1.0)
                return True
            except Exception as e:
                print(f"   Bezier move failed, using standard: {e}")
                # Fallback: hover then click with offset
                try:
                    box = element.bounding_box()
                    if box:
                        offset_x = random.randint(-5, 5)
                        offset_y = random.randint(-5, 5)
                        page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
                        time.sleep(random.uniform(0.1, 0.4))
                        page.mouse.move(
                            box['x'] + box['width'] / 2 + offset_x,
                            box['y'] + box['height'] / 2 + offset_y
                        )
                        page.mouse.click(
                            box['x'] + box['width'] / 2 + offset_x,
                            box['y'] + box['height'] / 2 + offset_y
                        )
                    else:
                        element.click()

                    print(f"   Click successful on attempt {attempt + 1}")
                    human_pause(0.5, 1.0)
                    return True
                except Exception:
                    element.click(force=True)
                    print(f"   Click successful on attempt {attempt + 1} (force)")
                    human_pause(0.5, 1.0)
                    return True

        except Exception as e:
            if attempt == max_retries - 1:
                print(f"   ActionChains failed. Trying JS Fallback.")
                try:
                    element.evaluate("el => el.click()")
                    return True
                except:
                    pass

            print(f"   Click failed on attempt {attempt + 1}: {str(e)}")
            human_pause(1.0, 2.0)

    print(f"   Failed to click element after {max_retries} attempts")
    return False


def log_action(page, action_name):
    """Log screenshots and page source for debugging"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    screenshots_dir = os.path.join(script_dir, "screenshots")
    if not os.path.exists(screenshots_dir):
        os.makedirs(screenshots_dir)

    screenshot_path = os.path.join(screenshots_dir, f"{timestamp}_{action_name}.png")
    try:
        page.screenshot(path=screenshot_path)
        print(f"   Screenshot saved: {screenshot_path}")
    except Exception as e:
        print(f"   Could not save screenshot: {e}")

    html_path = os.path.join(screenshots_dir, f"{timestamp}_{action_name}_page_source.html")
    try:
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(page.content())
        print(f"   Page source saved: {html_path}")
    except Exception as e:
        print(f"   Could not save page source: {e}")


def human_type(page, element, text, typing_delay=0.1):
    """Human-like typing with random delays"""
    element.clear()
    human_pause(0.5, 1.0)

    # Type character by character with random delays
    for char in text:
        element.type(char, delay=0)
        time.sleep(random.uniform(0.05, typing_delay))

    human_pause(0.5, 1.0)


def find_element_with_fallback(page, xpath, css_selector, element_name):
    """Find element using XPath first, then CSS selector as fallback"""
    try:
        element = page.locator(f"xpath={xpath}")
        if element.count() > 0 and element.first.is_visible():
            print(f"   Found {element_name} using XPath")
            return element.first
    except:
        pass

    try:
        element = page.locator(css_selector)
        if element.count() > 0 and element.first.is_visible():
            print(f"   Found {element_name} using CSS selector")
            return element.first
    except:
        pass

    print(f"   Could not find {element_name}")
    return None


def check_linkedin_app_challenge(page):
    """
    Check if LinkedIn is showing the "Check your LinkedIn app" challenge screen.
    Returns True if app challenge is detected, False otherwise.
    """
    try:
        print("   Checking for LinkedIn app challenge screen...")

        app_challenge_selectors = [
            ("xpath=//h1[contains(text(), 'Check your LinkedIn app')]", "heading: Check your LinkedIn app"),
            ("xpath=//h1[@class='header__content__heading__inapp']", "class: header__content__heading__inapp"),
            ("xpath=//p[contains(text(), 'We sent a notification to your signed in devices')]", "text: notification sent"),
            ("xpath=//p[@class='header__content__subheading']", "class: header__content__subheading"),
            ("xpath=//button[@id='reset-password-submit-button']", "ID: reset-password-submit-button"),
            ("xpath=//button[@class='form__submit__inapp']", "class: form__submit__inapp"),
            ("xpath=//a[@id='try-another-way']", "ID: try-another-way"),
            ("xpath=//a[contains(text(), 'Verify using SMS')]", "text: Verify using SMS"),
        ]

        for selector, description in app_challenge_selectors:
            try:
                element = page.locator(selector)
                if element.count() > 0 and element.first.is_visible():
                    print(f"   App challenge detected using: {description}")
                    return True
            except Exception:
                continue

        print("   No app challenge screen detected")
        return False

    except Exception as e:
        print(f"   Error checking for app challenge: {e}")
        return False


def handle_linkedin_app_challenge(page):
    """
    Handle the LinkedIn app challenge screen.
    Waits for user to approve on their mobile app, then continues.
    """
    try:
        print("\n   LINKEDIN APP CHALLENGE DETECTED")
        print("=" * 60)
        print("   LinkedIn sent a notification to your signed-in devices")
        print("   Please open your LinkedIn mobile app and tap 'Yes' to confirm")
        print("   Waiting for you to approve the login on your mobile device...")
        print("=" * 60)

        log_action(page, "app_challenge_detected")

        max_wait_time = 120
        check_interval = 3

        for i in range(0, max_wait_time, check_interval):
            print(f"   Waiting... ({i + check_interval}s / {max_wait_time}s)")
            human_pause(check_interval - 0.5, check_interval + 0.5)

            if not check_linkedin_app_challenge(page):
                print("   App challenge completed! Continuing with login flow...")
                log_action(page, "app_challenge_completed")
                return True

            current_url = page.url.lower()
            if "checkpoint" not in current_url and "challenge" not in current_url:
                print("   Redirected away from challenge page - assuming approved")
                log_action(page, "app_challenge_redirected")
                return True

        print("   Maximum wait time reached")
        print("   If you've approved on your mobile device, press ENTER to continue")
        input("Press ENTER when ready to continue...")

        log_action(page, "app_challenge_manual_continue")
        return True

    except Exception as e:
        print(f"   Error handling app challenge: {e}")
        log_action(page, "app_challenge_error")
        return False


def check_suspicious_login_challenge(page):
    """
    Check if LinkedIn is showing the 'Let's do a quick verification' challenge.
    This appears when using proxies and LinkedIn flags the login as suspicious.
    Returns True if the suspicious challenge is detected, False otherwise.
    """
    try:
        heading = page.locator("xpath=/html/body/div/main/h1")
        if heading.count() > 0 and heading.first.is_visible():
            text = heading.first.inner_text().strip().lower()
            if "quick verification" in text or "verification" in text:
                print(f"   Suspicious login challenge detected: '{heading.first.inner_text().strip()}'")
                return True
        return False
    except Exception:
        return False


def handle_suspicious_login_challenge(page, suspicious_otp=None):
    """
    Handle the suspicious login OTP challenge.
    Takes OTP either from argparse or prompts user via CLI input.
    """
    try:
        print("\n   SUSPICIOUS LOGIN CHALLENGE DETECTED")
        print("=" * 60)
        print("   LinkedIn flagged this login as suspicious (likely due to proxy)")
        print("   An OTP has been sent to your email/phone")
        print("=" * 60)

        log_action(page, "suspicious_challenge_detected")

        # Get OTP - from argparse or user input
        if suspicious_otp:
            otp_code = suspicious_otp
            print(f"   Using OTP from command line argument")
        else:
            otp_code = input("Enter the suspicious login OTP code: ").strip()

        if not otp_code:
            print("   No OTP provided. Cannot proceed.")
            return False

        # Input the OTP into the verification field
        otp_input = page.locator("xpath=/html/body/div/main/form/div[1]/input[16]")
        if otp_input.count() == 0 or not otp_input.first.is_visible():
            print("   Could not find OTP input field")
            log_action(page, "suspicious_otp_field_not_found")
            return False

        print("   Entering OTP code...")
        otp_input.first.click()
        human_pause(0.5, 1.0)
        for char in otp_code:
            otp_input.first.type(char, delay=0)
            time.sleep(random.uniform(0.05, 0.1))

        human_pause(1, 2)

        # Click the submit button
        submit_btn = page.locator("xpath=/html/body/div/main/form/div[2]/button")
        if submit_btn.count() == 0 or not submit_btn.first.is_visible():
            print("   Could not find submit button")
            log_action(page, "suspicious_submit_not_found")
            return False

        print("   Clicking submit button...")
        human_move_click(page, submit_btn.first)

        human_pause(5, 8)
        log_action(page, "suspicious_otp_submitted")

        print("   Suspicious login challenge completed!")
        return True

    except Exception as e:
        print(f"   Error handling suspicious login challenge: {e}")
        log_action(page, "suspicious_challenge_error")
        return False


class BrowserDeadError(Exception):
    """Raised when the underlying Chromium / Playwright driver process has died.

    Distinguished from ordinary navigation errors so callers know that retrying
    on the same `page` object is pointless and a fresh browser launch is required.
    """
    pass


_BROWSER_DEAD_MARKERS = (
    "epipe",
    "broken pipe",
    "target page, context or browser has been closed",
    "browser has been closed",
    "browser has disconnected",
    "browser closed",
    "target closed",
    "connection closed",
    "page has been closed",
    "context or browser has been closed",
    "playwright driver",
    "transport closed",
)


def _is_browser_dead_error(err_str):
    """Return True if the error string indicates the browser process is dead."""
    e = (err_str or "").lower()
    return any(marker in e for marker in _BROWSER_DEAD_MARKERS)


def _safe_goto(page, url, timeout=60000, retries=2):
    """Navigate with proxy-friendly timeout and retry on transient failures.

    Raises BrowserDeadError if the underlying browser process has died, so the
    caller can relaunch the browser instead of retrying with a dead page.
    """
    for attempt in range(retries):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            return True
        except Exception as e:
            err = str(e).lower()

            # If the browser itself died, no point retrying with the same page.
            if _is_browser_dead_error(err):
                raise BrowserDeadError(f"Browser died during goto({url}): {e}") from e

            is_transient = any(k in err for k in ("timeout", "err_timed_out", "err_tunnel_connection_failed"))
            if is_transient and attempt < retries - 1:
                wait = 3 + attempt * 2
                print(f"   Navigation to {url} failed (attempt {attempt+1}): {e}")
                print(f"   Retrying in {wait}s...")
                time.sleep(wait)
                continue
            raise
    return False


def check_if_logged_in(page, account_name="", _redirect_recovery=False):
    """
    Sanity check function to determine if user is logged in.
    Goes to linkedin.com and checks for login page heading element.
    If heading exists -> NOT logged in. If no heading -> logged in.
    Handles ERR_TOO_MANY_REDIRECTS by falling back to essential-only cookies
    loaded from the per-account cookie file.
    """
    try:
        print("   Checking if already logged in...")
        _safe_goto(page, "https://www.linkedin.com/", timeout=60000)
        human_pause(4, 6)

        try:
            heading_element = page.locator("xpath=/html/body/main/section[1]/div/h1")
            if heading_element.count() > 0 and heading_element.first.is_visible():
                heading_text = heading_element.first.inner_text().strip()
                print(f"   Found login page heading: '{heading_text}'")
                print("   Not logged in - login page heading element exists")
                return False
        except Exception:
            pass

        print("   Could not find login page heading element - user is logged in")
        return True

    except Exception as e:
        err_str = str(e).lower()
        print(f"   Error checking login status: {e}")

        # If the browser/page died entirely, no cookie tweak will save us — bubble up.
        if _is_browser_dead_error(err_str):
            print("   Browser/page is dead — cannot recover here, signalling caller.")
            raise BrowserDeadError(str(e))

        # Redirect loop recovery: clear cookies and re-inject only persistent
        # auth tokens (li_at, li_rm). Letting LinkedIn re-mint the session-bound
        # cookies on the next navigation usually breaks the loop.
        if "err_too_many_redirects" in err_str and not _redirect_recovery:
            print(f"   REDIRECT LOOP detected — recovery: dropping all cookies and re-injecting persistent auth only (account='{account_name}')...")
            try:
                context = page.context
                context.clear_cookies()

                cookies = _get_extension_cookies(account_name)
                if cookies:
                    safe = [c for c in cookies if c["name"] not in _COOKIES_TO_SKIP]
                    pw_cookies = [_convert_cookie_for_playwright(c) for c in safe]
                    if pw_cookies:
                        context.add_cookies(pw_cookies)
                        print(
                            f"   Re-injected {len(pw_cookies)} cookies (all except JSESSIONID). "
                            "LinkedIn will mint a fresh JSESSIONID on retry."
                        )

                    human_pause(2, 3)
                    return check_if_logged_in(page, account_name=account_name, _redirect_recovery=True)
                else:
                    print(f"   No cookies found for account '{account_name}' — recovery aborted.")
            except BrowserDeadError:
                raise
            except Exception as recovery_err:
                print(f"   Redirect recovery failed: {recovery_err}")

        return False


def _check_linkedin_reachability(page):
    """Quick health check — confirm proxy can reach LinkedIn via a lightweight request."""
    try:
        print("   Checking LinkedIn reachability through proxy...")
        response = page.goto("https://www.linkedin.com/robots.txt", wait_until="domcontentloaded", timeout=30000)
        if response and response.ok:
            print(f"   LinkedIn reachable (status {response.status})")
            return True
        else:
            status = response.status if response else "no response"
            print(f"   LinkedIn responded with status {status}")
            return False
    except Exception as e:
        print(f"   LinkedIn NOT reachable through proxy: {e}")
        print("   Bot will attempt to continue but may encounter issues")
        return False


def validate_proxy_with_driver(page):
    """Test proxy connection using the browser"""
    try:
        print("   Testing proxy connection via browser...")

        # 1. Get Local IP (Direct connection)
        import requests
        local_ip = None
        try:
            local_response = requests.get("https://api.ipify.org?format=json", proxies={"http": None, "https": None}, timeout=5)
            local_ip = local_response.json().get("ip")
            print(f"   Local IP: {local_ip}")
        except Exception as e:
            print(f"   Could not fetch local IP: {e}")

        # 2. Get Browser IP (Should be Proxy)
        page.goto("https://httpbin.org/ip", wait_until="domcontentloaded", timeout=60000)
        human_pause(3, 5)

        try:
            import json
            content = page.locator("body").inner_text()
            ip_data = json.loads(content)
            proxy_ip = ip_data.get("origin", "Unknown")

            if local_ip and proxy_ip:
                if local_ip in proxy_ip:
                    print(f"   PROXY LEAK DETECTED! Browser IP ({proxy_ip}) matches Local IP ({local_ip})")
                    print("   The proxy may not be configured correctly.")
                    return False
                else:
                    print(f"   Proxy working! Browser IP: {proxy_ip} (Different from Local: {local_ip})")
                    return True
            else:
                print(f"   Proxy check complete. Browser IP: {proxy_ip}")
                return True

        except:
            print(f"   Could not parse IP response. Body text: {page.locator('body').inner_text()[:100]}...")
            return False

    except Exception as e:
        print(f"   Proxy browser test failed: {e}")
        return False


def setup_playwright_browser(account_name=""):
    """Setup Playwright browser with stealth config and native proxy support"""
    try:
        print("   Setting up Playwright browser with Stealth Config...")

        script_dir = os.path.dirname(os.path.abspath(__file__))
        slug = _account_slug(account_name)
        user_data_dir_name = f"user_data_{slug}" if slug else "user_data_yath"
        user_data_path = os.path.join(script_dir, user_data_dir_name)

        if not os.path.exists(user_data_path):
            os.makedirs(user_data_path)
            print(f"   Created user data directory: {user_data_path}")

        # Proxy configuration - native Playwright support (no extension needed!)
        use_proxy = os.getenv("USE_PROXY", "false").lower() == "true"
        proxy_config = None

        if use_proxy:
            proxy_host = os.getenv("PROXY_HOST")
            proxy_port = os.getenv("PROXY_PORT")
            proxy_username = os.getenv("PROXY_USERNAME")
            proxy_password = get_proxy_password_for_account(account_name)

            if all([proxy_host, proxy_port, proxy_username, proxy_password]):
                print(f"   Configuring native proxy: {proxy_host}:{proxy_port}")
                proxy_config = {
                    "server": f"http://{proxy_host}:{proxy_port}",
                    "username": proxy_username,
                    "password": proxy_password
                }
            else:
                print("   Proxy credentials incomplete, proceeding without proxy")
        else:
            print("   Proxy disabled in configuration")

        # User agent
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"

        # Launch Playwright
        pw = sync_playwright().start()

        # Build launch args
        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            "--disable-notifications",
            "--disable-popup-blocking",
            "--lang=en-US",
            "--ignore-certificate-errors",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-automation",
            "--disable-component-update",
            "--no-default-browser-check",
            "--no-first-run",
            "--window-size=1920,1200",
        ]

        # Use persistent context for session persistence (like Chrome's user-data-dir)
        is_cloud = os.getenv("CLOUD_MODE", "").lower() == "true"
        context_options = {
            "user_data_dir": user_data_path,
            "viewport": {"width": 1920, "height": 1080},
            "user_agent": user_agent,
            "locale": "en-US",
            "ignore_https_errors": True,
            "args": launch_args,
            "headless": False,
        }
        # In cloud mode use Playwright's bundled Chromium (no Chrome install needed)
        # Locally use installed Chrome for better stealth
        if not is_cloud:
            context_options["channel"] = "chrome"

        if proxy_config:
            context_options["proxy"] = proxy_config

        context = pw.chromium.launch_persistent_context(**context_options)

        # Get the first page or create one
        if context.pages:
            page = context.pages[0]
        else:
            page = context.new_page()

        # Apply playwright-stealth (v2.0.2 API)
        stealth = Stealth()
        stealth.apply_stealth_sync(context)

        # Deep stealth injection - same CDP scripts as original
        page.add_init_script("""
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

            // Overwrite Navigator Hardware Concurrency
            Object.defineProperty(navigator, 'hardwareConcurrency', {
                get: () => 4,
            });

            // Overwrite Device Memory
            Object.defineProperty(navigator, 'deviceMemory', {
                get: () => 8,
            });

            // Overwrite Platform
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
        """)

        # WebRTC handling via page context
        context.add_init_script("""
            // WebRTC leak prevention
            if (window.RTCPeerConnection) {
                const origRTC = window.RTCPeerConnection;
                window.RTCPeerConnection = function(...args) {
                    if (args[0] && args[0].iceServers) {
                        args[0].iceServers = [];
                    }
                    return new origRTC(...args);
                };
                window.RTCPeerConnection.prototype = origRTC.prototype;
            }
        """)

        print("   Playwright browser setup complete with advanced stealth")

        # Create wrapper - context acts as both browser and context for persistent context
        driver = PlaywrightDriver(pw, context, context, page)

        # Validate proxy connection
        if use_proxy and proxy_config:
            validate_proxy_with_driver(page)
            # Verify proxy can actually reach LinkedIn
            _check_linkedin_reachability(page)

        return driver

    except Exception as e:
        print(f"   Failed to setup Playwright browser: {e}")
        import traceback
        traceback.print_exc()
        return None


def _get_extension_cookies(account_name=""):
    """Load cookies from STATE_DIR/cookies/cookies_{slug}.json (or default fallback).

    Returns a list of cookie dicts (with expired ones filtered out) or None.
    """
    import json as _json
    import sys as _sys
    _project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if _project_root not in _sys.path:
        _sys.path.insert(0, _project_root)
    from state_paths import cookies_path as _cookies_path

    slug = _account_slug(account_name)
    # Try per-account file first, fall back to default
    cookies_file = _cookies_path(slug) if slug else None
    if not cookies_file or not os.path.exists(cookies_file):
        cookies_file = _cookies_path()
    if not os.path.exists(cookies_file):
        return None
    try:
        with open(cookies_file, "r") as f:
            cookies = _json.load(f)
        if cookies and any(c.get("name") == "li_at" for c in cookies):
            # Filter out expired cookies
            now = time.time()
            valid = []
            expired_count = 0
            for c in cookies:
                exp = c.get("expirationDate")
                if exp and float(exp) < now:
                    expired_count += 1
                    continue
                valid.append(c)
            if expired_count:
                print(f"   Filtered out {expired_count} expired cookies")
            return valid
    except Exception:
        pass
    return None


def _wipe_profile(account_name=""):
    """Always wipe user data dir for a clean start with extension cookies."""
    import shutil
    script_dir = os.path.dirname(os.path.abspath(__file__))
    slug = _account_slug(account_name)
    dir_name = f"user_data_{slug}" if slug else "user_data_yath"
    user_data_path = os.path.join(script_dir, dir_name)
    if os.path.exists(user_data_path):
        print(f"   Wiping {dir_name} for clean cookie injection...")
        shutil.rmtree(user_data_path)
    os.makedirs(user_data_path, exist_ok=True)
    print("   Fresh profile directory ready.")


# Auth-critical cookies that need domain broadened to .linkedin.com.
# These are recognized by LinkedIn's auth/edge layer; we normalize their
# domain to broaden scope, but only a SUBSET (see _PERSISTENT_AUTH_COOKIES)
# is actually injected into the bot's browser.
_AUTH_COOKIES = {"li_at", "li_rm", "JSESSIONID", "liap", "li_mc"}

# Routing cookies that LinkedIn's edge proxy reads — must also be on .linkedin.com
# scope, otherwise login can fall into a redirect loop.
_ROUTING_COOKIES = {"lidc", "bcookie", "bscookie"}

# Cookies to SKIP when injecting from the user's browser into the bot.
# JSESSIONID is the only strictly single-client session token — sharing it
# across the user's browser and the bot causes LinkedIn to detect a session
# conflict and log out one side. All other cookies (li_at, li_rm, liap, lidc,
# bcookie, bscookie, li_mc, etc.) are either device-agnostic or harmless to
# share — and LinkedIn's edge routing actually NEEDS lidc/bcookie to avoid
# falling into a generic redirect path that causes ERR_TOO_MANY_REDIRECTS.
#
# Result: the bot gets the full cookie set minus JSESSIONID. LinkedIn sees
# a valid session with proper routing hints and mints a fresh JSESSIONID for
# the bot. The user's browser keeps its own JSESSIONID untouched.
_COOKIES_TO_SKIP = {"JSESSIONID"}


def _convert_cookie_for_playwright(cookie):
    """Convert a single Chrome extension cookie to Playwright format with smart domain handling."""
    domain = (cookie.get("domain") or ".linkedin.com").strip()

    # Normalize domain for auth and routing cookies. We accept any variant of
    # www.linkedin.com (with/without leading dot, with stray whitespace) and
    # broaden it to .linkedin.com so LinkedIn sees the cookie on every subdomain.
    if cookie["name"] in _AUTH_COOKIES or cookie["name"] in _ROUTING_COOKIES:
        d = domain.lower().lstrip(".")
        if d == "www.linkedin.com" or d == "linkedin.com":
            domain = ".linkedin.com"
    # Leave other non-auth cookies with original domain (prevents redirect loops)

    c = {
        "name": cookie["name"],
        "value": cookie["value"],
        "domain": domain,
        "path": cookie.get("path", "/"),
    }
    if cookie.get("expirationDate"):
        c["expires"] = int(cookie["expirationDate"])
    if cookie.get("secure"):
        c["secure"] = True
    if cookie.get("sameSite"):
        # Playwright expects "Strict", "Lax", or "None"
        same_site = cookie["sameSite"].capitalize()
        if same_site in ("Strict", "Lax", "None"):
            c["sameSite"] = same_site
    return c


def inject_extension_cookies(driver, account_name=""):
    """Inject all cookies EXCEPT JSESSIONID from the user's browser into the bot.

    JSESSIONID is the only strictly single-client token — sharing it causes
    LinkedIn to detect a session conflict and log the user out. Everything
    else (li_at, li_rm, liap, lidc, bcookie, bscookie, li_mc, etc.) is safe
    to share and actually NEEDED by LinkedIn's edge for proper routing.
    LinkedIn will mint a fresh JSESSIONID for the bot on its first navigation.

    Returns True if at least li_at was successfully injected.
    """
    cookies = _get_extension_cookies(account_name)
    if not cookies:
        print("   No extension cookies file found — nothing to inject.")
        return False

    try:
        context = driver.context

        to_inject = [c for c in cookies if c["name"] not in _COOKIES_TO_SKIP]
        skipped = [c["name"] for c in cookies if c["name"] in _COOKIES_TO_SKIP]

        if not any(c["name"] == "li_at" for c in to_inject):
            print(
                f"   ERROR: li_at not found in {len(cookies)} synced cookies. "
                "Re-sync via the extension while logged into LinkedIn."
            )
            return False

        print(f"   Injecting {len(to_inject)}/{len(cookies)} extension cookies into browser...")
        if skipped:
            print(
                f"   Skipping {skipped} to avoid session conflicts "
                "(LinkedIn will mint a fresh JSESSIONID on first navigation)."
            )

        context.clear_cookies()

        playwright_cookies = []
        for cookie in to_inject:
            try:
                playwright_cookies.append(_convert_cookie_for_playwright(cookie))
            except Exception as e:
                print(f"     Skipped cookie '{cookie.get('name', '?')}': {e}")

        if playwright_cookies:
            context.add_cookies(playwright_cookies)

        stored = context.cookies()
        auth_stored = [c["name"] for c in stored if c["name"] in _AUTH_COOKIES]
        print(f"   Readback: {len(stored)} cookies in context, auth cookies present: {auth_stored}")

        if "li_at" not in auth_stored:
            print("   WARNING: li_at not found in readback after injection! Login will fail.")
            return False

        return True

    except Exception as e:
        print(f"   Error injecting extension cookies: {e}")
        return False


def _inject_essential_cookies_only(driver, account_name=""):
    """Fallback: clear everything and re-inject all cookies except JSESSIONID."""
    cookies = _get_extension_cookies(account_name)
    if not cookies:
        return False
    try:
        context = driver.context
        context.clear_cookies()

        safe = [c for c in cookies if c["name"] not in _COOKIES_TO_SKIP]
        playwright_cookies = []
        for cookie in safe:
            try:
                playwright_cookies.append(_convert_cookie_for_playwright(cookie))
            except Exception:
                pass

        if playwright_cookies:
            context.add_cookies(playwright_cookies)
            print(f"   Essential injection: {len(playwright_cookies)} cookies (all except JSESSIONID)")
        return bool(playwright_cookies)
    except Exception as e:
        print(f"   Essential cookie injection failed: {e}")
        return False


def _inject_browser_storage(page, account_name=""):
    """Inject localStorage and sessionStorage from STATE_DIR/cookies/browser_storage_{slug}.json into a loaded page."""
    import json as _json
    import sys as _sys
    _project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if _project_root not in _sys.path:
        _sys.path.insert(0, _project_root)
    from state_paths import storage_path as _storage_path

    slug = _account_slug(account_name)
    storage_file = _storage_path(slug) if slug else None
    if not storage_file or not os.path.exists(storage_file):
        storage_file = _storage_path()
    if not os.path.exists(storage_file):
        return
    try:
        with open(storage_file, "r") as f:
            storage_data = _json.load(f)

        ls_count = 0
        if storage_data.get("localStorage"):
            for key, value in storage_data["localStorage"].items():
                try:
                    page.evaluate(
                        "(args) => localStorage.setItem(args.key, args.value)",
                        {"key": key, "value": value or ""}
                    )
                    ls_count += 1
                except Exception:
                    pass
        print(f"   Injected {ls_count} localStorage keys.")

        ss_count = 0
        if storage_data.get("sessionStorage"):
            for key, value in storage_data["sessionStorage"].items():
                try:
                    page.evaluate(
                        "(args) => sessionStorage.setItem(args.key, args.value)",
                        {"key": key, "value": value or ""}
                    )
                    ss_count += 1
                except Exception:
                    pass
        print(f"   Injected {ss_count} sessionStorage keys.")
    except Exception as e:
        print(f"   Could not inject browser storage: {e}")


def linkedin_login(suspicious_otp=None, account_name=""):
    """
    Simple LinkedIn login function with CLI input prompts.
    First checks if already logged in, then proceeds with login if needed.
    Args:
        suspicious_otp: Optional OTP for suspicious login challenge (from argparse)
        account_name: Account name for multi-account support
    """
    # If extension cookies exist, always start fresh
    ext_cookies = _get_extension_cookies(account_name)
    if ext_cookies:
        _wipe_profile(account_name)

    driver = setup_playwright_browser(account_name)
    if not driver:
        return None

    page = driver.page

    try:
        # If extension cookies exist, inject ONLY the persistent auth tokens
        # (li_at, li_rm). LinkedIn will mint a fresh session for this device on
        # the upcoming navigation, leaving the user's other browser sessions
        # untouched. See _PERSISTENT_AUTH_COOKIES for the rationale.
        if ext_cookies:
            inject_extension_cookies(driver, account_name=account_name)

        # Check if logged in (this navigates to linkedin.com — LinkedIn will
        # validate li_at and Set-Cookie back the rest of the session state).
        if check_if_logged_in(page, account_name=account_name):
            # Now that we're on LinkedIn, inject browser storage
            if ext_cookies:
                _inject_browser_storage(page, account_name)
            print("   User is already logged in! Skipping login process.")
            log_action(page, "already_logged_in")
            return driver

        # Not logged in, proceed with login
        print("   User is not logged in. Starting login process...")

        print("   Going to LinkedIn login page...")
        _safe_goto(page, "https://www.linkedin.com/login", timeout=60000)
        human_pause(4, 7)
        log_action(page, "login_page_loaded")

        print("   Starting login process...")

        # STEP 1: Find and fill email field
        print("\n   STEP 1: Email Input")
        email_element = find_element_with_fallback(
            page,
            "/html/body/div[1]/main/div[2]/div[1]/form/div[1]/input",
            "#username",
            "email input field"
        )

        if not email_element:
            log_action(page, "email_field_not_found")
            driver.quit()
            return None

        email = input("Enter your LinkedIn email: ").strip()
        print("   Entering email...")
        human_type(page, email_element, email)

        # STEP 2: Find and fill password field
        print("\n   STEP 2: Password Input")
        password_element = find_element_with_fallback(
            page,
            "/html/body/div[1]/main/div[2]/div[1]/form/div[2]/input",
            "#password",
            "password input field"
        )

        if not password_element:
            log_action(page, "password_field_not_found")
            driver.quit()
            return None

        password = input("Enter your LinkedIn password: ").strip()
        print("   Entering password...")
        human_type(page, password_element, password)

        # STEP 3: Find and click sign in button
        print("\n   STEP 3: Sign In Button")
        signin_button = find_element_with_fallback(
            page,
            "/html/body/div[1]/main/div[2]/div[1]/form/div[4]/button",
            "#organic-div > form > div.login__form_action_container > button",
            "sign in button"
        )

        if not signin_button:
            log_action(page, "signin_button_not_found")
            driver.quit()
            return None

        print("   Clicking sign in button...")
        human_move_click(page, signin_button)

        human_pause(6, 10)
        log_action(page, "login_attempted")

        # Check for suspicious login challenge (proxy-triggered OTP)
        if check_suspicious_login_challenge(page):
            if not handle_suspicious_login_challenge(page, suspicious_otp):
                print("   Failed to handle suspicious login challenge")
                log_action(page, "suspicious_challenge_failed")
                driver.quit()
                return None
            human_pause(3, 5)

            # Check if we're now logged in after suspicious challenge
            if check_if_logged_in(page, account_name=account_name):
                print("   Login successful after suspicious login verification!")
                log_action(page, "login_success_suspicious")
                return driver

        # Check for LinkedIn app challenge
        if check_linkedin_app_challenge(page):
            if not handle_linkedin_app_challenge(page):
                print("   Failed to handle app challenge")
                log_action(page, "app_challenge_failed")
                driver.quit()
                return None

            human_pause(3, 5)

        # Check if login was successful
        if check_if_logged_in(page, account_name=account_name):
            print("   Login successful! Session cookies saved.")
            log_action(page, "login_success")
            return driver

        # Check for OTP/2FA
        print("   Checking if OTP/2FA or email verification is required...")
        print("   Waiting for verification page to load...")
        human_pause(3, 5)

        current_url = page.url
        print(f"   Current URL: {current_url}")

        # Try multiple selectors for verification input
        otp_element = None
        verification_selectors = [
            ("xpath=//input[@id='input__email_verification_pin'][@name='pin'][@type='number']", "ID+name+type: input__email_verification_pin"),
            ("xpath=//input[@id='input__email_verification_pin']", "ID: input__email_verification_pin"),
            ("#input__email_verification_pin", "CSS: #input__email_verification_pin"),
            ("xpath=//input[@name='pin'][@type='number']", "name=pin type=number"),
            ("xpath=//input[@name='pin']", "name=pin"),
            ("xpath=//input[@class='form__input--text input_verification_pin']", "class: input_verification_pin"),
            ("xpath=/html/body/div[1]/main/form/div[1]/input", "XPath: main form input"),
            ("#input__phone_verification_pin", "CSS: #input__phone_verification_pin (2FA)"),
            ("xpath=/html/body/div[1]/main/form/div[1]/input[18]", "XPath: OTP input (2FA)"),
        ]

        print(f"   Trying {len(verification_selectors)} different selectors...")
        for idx, (selector, description) in enumerate(verification_selectors, 1):
            try:
                print(f"   [{idx}/{len(verification_selectors)}] Trying: {description}")
                element = page.locator(selector)
                if element.count() > 0 and element.first.is_visible():
                    otp_element = element.first
                    print(f"   Found verification input using: {description}")
                    break
                else:
                    print(f"     Element found but not displayed")
            except Exception as e:
                print(f"     Not found: {str(e)[:50]}")
                continue

        if not otp_element:
            print("   Could not find verification input field with any selector")
            log_action(page, "verification_field_not_found")

        if otp_element:
            print("\n   STEP 4: Verification Required")

            try:
                page_text = page.content().lower()
                if "suspicious" in page_text or "quick verification" in page_text or "login attempt seems suspicious" in page_text:
                    print("   LinkedIn detected suspicious login activity")
                    print("   Verification code sent to your email address")
                    verification_code = input("Enter the verification code sent to your email: ").strip()
                else:
                    print("   Two-Factor Authentication (2FA) required")
                    print("   Verification code sent to your device")
                    verification_code = input("Enter the OTP/2FA code sent to your device: ").strip()
            except:
                print("   Verification required")
                verification_code = input("Enter the verification code (from email or device): ").strip()

            print("   Entering verification code...")
            human_type(page, otp_element, verification_code)

            # Find and click submit button
            print("\n   Looking for Submit Button...")

            submit_button = None
            submit_selectors = [
                ("xpath=//button[@id='email-pin-submit-button'][@type='submit']", "ID+type: email-pin-submit-button"),
                ("xpath=//button[@id='email-pin-submit-button']", "ID: email-pin-submit-button"),
                ("#email-pin-submit-button", "CSS: #email-pin-submit-button"),
                ("xpath=//button[@type='submit']", "type=submit"),
                ("xpath=/html/body/div[1]/main/form/div[2]/button", "XPath: form submit button"),
                ("xpath=//button[contains(text(), 'Submit')]", "text contains Submit"),
                ("#two-step-submit-button", "CSS: #two-step-submit-button"),
            ]

            for selector, description in submit_selectors:
                try:
                    element = page.locator(selector)
                    if element.count() > 0 and element.first.is_visible():
                        submit_button = element.first
                        print(f"   Found submit button using: {description}")
                        break
                except:
                    continue

            if submit_button:
                print("   Clicking submit button...")
                human_move_click(page, submit_button)

                human_pause(5, 8)
                log_action(page, "verification_submitted")

                if check_if_logged_in(page, account_name=account_name):
                    print("   Login successful with verification! Session cookies saved.")
                    log_action(page, "login_success_with_verification")
                    return driver
                else:
                    print("   Verification may have failed")
                    log_action(page, "verification_failed")
            else:
                print("   Could not find submit button")
                log_action(page, "submit_button_not_found")

            print("   If verification is still pending, please complete it manually in the browser")
            print("   Press ENTER once you see your LinkedIn feed...")
            input()

            if check_if_logged_in(page, account_name=account_name):
                print("   Login successful after manual verification completion!")
                log_action(page, "login_success_manual_verification")
                return driver
        else:
            print("   No OTP required, but login may have failed")
            current_url = page.url.lower()
            print(f"   Current URL: {current_url}")

            if "challenge" in current_url or "captcha" in current_url:
                print("   CAPTCHA or other challenge detected")
            elif "login" in current_url:
                print("   Still on login page - credentials may be incorrect")

            log_action(page, "login_failed_no_otp")

        print("   Automatic login sequence completed but may need manual intervention")
        print("   Please check the browser window and complete any remaining steps")
        print("   Press ENTER once you see your LinkedIn feed...")
        input()

        if check_if_logged_in(page, account_name=account_name):
            print("   Login successful after manual completion!")
            log_action(page, "login_success_final")
            return driver
        else:
            print("   Login failed - unable to reach LinkedIn feed")
            log_action(page, "login_failed_final")
            driver.quit()
            return None

    except BrowserDeadError as e:
        print(f"   Browser died during login: {e}")
        try:
            log_action(page, "login_browser_dead")
        except Exception:
            pass
        try:
            driver.quit()
        except Exception:
            pass
        # Re-raise so ensure_linkedin_login can retry with a fresh browser.
        raise
    except Exception as e:
        err_str = str(e).lower()
        if _is_browser_dead_error(err_str):
            print(f"   Browser-dead error during login: {e}")
            try:
                driver.quit()
            except Exception:
                pass
            raise BrowserDeadError(str(e)) from e
        print(f"   Critical error during login: {e}")
        try:
            log_action(page, "login_critical_error")
        except Exception:
            pass
        try:
            driver.quit()
        except Exception:
            pass
        return None


def _get_linkedin_credentials(account_name):
    """Look up LinkedIn email + password from env vars for a given account.

    Naming convention in Secret Manager / env:
        yatharth_bisht  →  YATH_LINKEDIN_EMAIL, YATH_LINKEDIN_PASSWORD
        maurice         →  MAURICE_LINKEDIN_EMAIL, MAURICE_LINKEDIN_PASSWORD
        leon            →  LEON_LINKEDIN_EMAIL, LEON_LINKEDIN_PASSWORD

    Returns (email, password) or (None, None) if not configured.
    """
    slug = _account_slug(account_name)
    prefix_map = {
        "yatharth_bisht": "YATH",
        "maurice": "MAURICE",
        "leon": "LEON",
    }
    prefix = prefix_map.get(slug)
    if not prefix:
        return None, None
    email = os.getenv(f"{prefix}_LINKEDIN_EMAIL", "").strip()
    password = os.getenv(f"{prefix}_LINKEDIN_PASSWORD", "").strip()
    if email and password:
        return email, password
    return None, None


def _password_login(account_name):
    """Fallback login using email + password + app-approve notification.

    Used when cookie-based login fails after all proxy IP rotations are
    exhausted. Reads credentials from env vars (sourced from Secret Manager).
    After submitting credentials, waits up to 5 minutes for the user to
    approve the push notification on their LinkedIn mobile app.

    Returns a PlaywrightDriver on success, None on failure.
    """
    email, password = _get_linkedin_credentials(account_name)
    if not email or not password:
        print(f"   No LinkedIn credentials configured for '{account_name}' — cannot fall back to password login.")
        print(f"   Expected env vars: <PREFIX>_LINKEDIN_EMAIL, <PREFIX>_LINKEDIN_PASSWORD")
        return None

    print(f"\n   ========== PASSWORD LOGIN FALLBACK ==========")
    print(f"   Cookie login exhausted. Attempting password login for '{account_name}'...")
    print(f"   Email: {email[:5]}...{email[-10:]}")

    _wipe_profile(account_name)
    driver = setup_playwright_browser(account_name)
    if not driver:
        return None

    page = driver.page

    try:
        # Navigate to login page
        print("   Going to LinkedIn login page...")
        _safe_goto(page, "https://www.linkedin.com/login", timeout=60000)
        human_pause(4, 7)
        log_action(page, "password_login_page_loaded")

        # Fill email
        print("   Finding email field...")
        email_element = find_element_with_fallback(
            page,
            "/html/body/div[1]/main/div[2]/div[1]/form/div[1]/input",
            "#username",
            "email input field"
        )
        if not email_element:
            print("   Could not find email field on login page")
            log_action(page, "password_login_email_field_not_found")
            driver.quit()
            return None

        print("   Entering email...")
        human_type(page, email_element, email)

        # Fill password
        print("   Finding password field...")
        password_element = find_element_with_fallback(
            page,
            "/html/body/div[1]/main/div[2]/div[1]/form/div[2]/input",
            "#password",
            "password input field"
        )
        if not password_element:
            print("   Could not find password field on login page")
            log_action(page, "password_login_password_field_not_found")
            driver.quit()
            return None

        print("   Entering password...")
        human_type(page, password_element, password)

        # Click sign in
        print("   Finding sign in button...")
        signin_button = find_element_with_fallback(
            page,
            "/html/body/div[1]/main/div[2]/div[1]/form/div[4]/button",
            "#organic-div > form > div.login__form_action_container > button",
            "sign in button"
        )
        if not signin_button:
            print("   Could not find sign in button")
            log_action(page, "password_login_signin_not_found")
            driver.quit()
            return None

        print("   Clicking sign in...")
        human_move_click(page, signin_button)
        human_pause(6, 10)
        log_action(page, "password_login_submitted")

        # Check if we landed on the feed directly (no 2FA needed)
        if check_if_logged_in(page, account_name=account_name):
            print("   Password login successful (no 2FA required)!")
            log_action(page, "password_login_success_direct")
            return driver

        # Check for app-based approval challenge (push notification)
        if check_linkedin_app_challenge(page):
            print("\n   ============================================")
            print("   LinkedIn sent a push notification to your phone.")
            print("   Open your LinkedIn app and tap APPROVE.")
            print("   Waiting up to 5 minutes...")
            print("   ============================================")
            log_action(page, "password_login_app_challenge")

            max_wait = 300  # 5 minutes
            interval = 5
            for elapsed in range(0, max_wait, interval):
                human_pause(interval - 0.5, interval + 0.5)
                print(f"   Waiting for approval... ({elapsed + interval}s / {max_wait}s)")

                if not check_linkedin_app_challenge(page):
                    print("   App challenge cleared!")
                    break

                current_url = page.url.lower()
                if "feed" in current_url:
                    print("   Redirected to feed — login approved!")
                    break
            else:
                print("   Timed out waiting for app approval (5 minutes).")
                log_action(page, "password_login_app_challenge_timeout")
                driver.quit()
                return None

            # Final verification
            human_pause(3, 5)
            if check_if_logged_in(page, account_name=account_name):
                print("   Password login successful after app approval!")
                log_action(page, "password_login_success_app_approved")
                return driver

        # Check for suspicious login challenge
        if check_suspicious_login_challenge(page):
            print("   Suspicious login challenge detected after password login.")
            print("   This requires email/SMS verification — cannot proceed automatically.")
            log_action(page, "password_login_suspicious_challenge")
            driver.quit()
            return None

        print("   Password login failed — unknown state after credential submission.")
        log_action(page, "password_login_failed_unknown")
        driver.quit()
        return None

    except BrowserDeadError:
        try:
            driver.quit()
        except Exception:
            pass
        raise
    except Exception as e:
        print(f"   Password login error: {e}")
        log_action(page, "password_login_error")
        try:
            driver.quit()
        except Exception:
            pass
        return None


def _kill_zombie_chrome_processes():
    """Best-effort cleanup of orphaned Chromium / Playwright processes after a crash."""
    try:
        import psutil
    except ImportError:
        return
    killed = 0
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            name = (proc.info.get("name") or "").lower()
            cmdline = " ".join(proc.info.get("cmdline") or []).lower()
            if any(k in name for k in ("chrome", "chromium", "playwright")) or \
               "playwright" in cmdline or "chromium" in cmdline:
                proc.kill()
                killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if killed:
        print(f"   Cleaned up {killed} zombie chrome/playwright processes")


def ensure_linkedin_login(suspicious_otp=None, account_name="", max_attempts=3):
    """
    Convenience function for other bots to ensure LinkedIn login.
    Returns a PlaywrightDriver instance if login is successful, None otherwise.

    Retries up to `max_attempts` times. Between each retry:
      - Kills any zombie Chrome / Playwright processes
      - Rotates the iproyal proxy session ID so the next attempt gets a
        DIFFERENT residential exit IP (some IPs are flagged by LinkedIn and
        cause ERR_TOO_MANY_REDIRECTS — rotating usually lands a clean one
        within 2–3 tries)

    Args:
        suspicious_otp: Optional OTP for suspicious login challenge (from argparse)
        account_name: Account name for multi-account support
        max_attempts: Number of login attempts before giving up
    """
    last_err = None
    for attempt in range(1, max_attempts + 1):
        try:
            driver = linkedin_login(suspicious_otp=suspicious_otp, account_name=account_name)
            if driver:
                return driver

            # linkedin_login returned None — login failed (redirect loop,
            # bad cookies, captcha, etc.). Retry with a different proxy IP
            # in case the current one is flagged.
            last_err = "linkedin_login returned None"
            print(f"   Login failed on attempt {attempt}/{max_attempts} (returned None)")

        except BrowserDeadError as e:
            last_err = e
            print(f"   Browser died during login attempt {attempt}/{max_attempts}: {e}")

        except Exception as e:
            last_err = e
            print(f"   Login error on attempt {attempt}/{max_attempts}: {e}")

        # ── Prepare for next attempt ──
        if attempt < max_attempts:
            _kill_zombie_chrome_processes()
            _regenerate_proxy_session()
            wait = 5 * attempt
            print(f"   Waiting {wait}s before retrying with new proxy IP...")
            time.sleep(wait)

    print(f"   Cookie login failed after {max_attempts} attempts. Last error: {last_err}")

    # ── Final fallback: password + app-approve login ──
    # This works even on flagged proxy IPs because LinkedIn's /login endpoint
    # is designed to accept connections from anywhere (people travel, use VPNs).
    # The session is born on the current proxy IP, so subsequent navigation
    # to profiles/mynetwork won't hit redirect loops.
    print("   Attempting password login as final fallback...")
    try:
        _kill_zombie_chrome_processes()
        _regenerate_proxy_session()
        time.sleep(3)
        driver = _password_login(account_name)
        if driver:
            return driver
    except BrowserDeadError:
        pass
    except Exception as e:
        print(f"   Password login fallback failed: {e}")

    print("   All login methods exhausted. Cannot establish LinkedIn session.")
    return None


def main():
    """Test the login functionality"""
    import argparse
    parser = argparse.ArgumentParser(description='LinkedIn Login (Playwright)')
    parser.add_argument('--suspicious_otp', type=str, default=None,
                       help='OTP code for suspicious login challenge (proxy-triggered)')
    args = parser.parse_args()

    print("   Testing LinkedIn Login...")

    driver = linkedin_login(suspicious_otp=args.suspicious_otp)

    if driver:
        print("   Login test successful!")
        print("   Current URL:", driver.page.url)
        print("   Session cookies have been saved")
        print("   Other bots can now use this saved session")

        print("   Browser will stay open for 30 seconds for testing...")
        time.sleep(30)

        driver.quit()
        print("   Browser closed")
    else:
        print("   Login test failed!")


if __name__ == "__main__":
    main()
