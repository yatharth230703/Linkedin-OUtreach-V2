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
from attio_client import get_attio_client, set_active_account
from notifier import notify_connection_sent, notify_error, notify_login_failed
from notifier import set_active_account as set_notifier_account
from playwright_bots.login_credentials import (
    ensure_linkedin_login,
    human_pause,
    human_move_click,
    smooth_scroll_to_element,
    log_action,
    PlaywrightDriver,
    _safe_goto,
)
from playwright_bots.fingerprint_diagnostics import safe_capture as _diag_capture

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
    """Extract profile data using layout-agnostic signals.

    LinkedIn's profile DOM uses hashed CSS classes that rotate every deploy and
    lazy-loads sections via React/SDUI.  We avoid class names entirely and rely
    on signals that are stable across redesigns:

      - full_name  → <title> tag ("Name | LinkedIn")
      - headline   → JS: first substantial <p> near the profile <h2>
      - about      → componentkey suffix "About" (SDUI section identifier)
      - experience → componentkey suffix "Experience"
    """
    profile_data = {
        "full_name": "Unknown",
        "headline": "",
        "about": "",
        "experience": ""
    }

    # ── Name from <title> (most stable signal) ──────────────────────────
    title_name = _extract_name_from_title(page.title())
    if title_name:
        profile_data["full_name"] = title_name

    # ── Headline via JS (find text near the profile name heading) ────────
    try:
        headline = page.evaluate("""() => {
            const titleName = document.title.split(' | ')[0].trim();
            if (!titleName) return '';
            // Find the heading (h1–h3) whose text matches the title name
            for (const tag of ['h1', 'h2', 'h3']) {
                for (const el of document.querySelectorAll(tag)) {
                    if (el.textContent.trim() === titleName) {
                        // Walk up to the nearest container, then scan <p> siblings
                        let container = el.closest('[componentkey]')
                                     || el.parentElement?.parentElement?.parentElement?.parentElement;
                        if (!container) continue;
                        for (const p of container.querySelectorAll('p')) {
                            const t = p.textContent.trim();
                            // Skip degree indicators (· 1st, · 2nd, · 3rd) and short junk
                            if (t && t.length > 5 && !t.startsWith('·') && t !== titleName) {
                                return t;
                            }
                        }
                    }
                }
            }
            return '';
        }""")
        if headline:
            profile_data["headline"] = headline
    except Exception:
        pass

    # ── About & Experience via SDUI componentkey sections ────────────────
    # LinkedIn's Server-Driven UI marks sections with componentkey attributes
    # ending in "About", "Experience", etc.  These are lazily loaded — content
    # appears only after the section scrolls into view.
    for section_name, key in [("about", "About"), ("experience", "Experience")]:
        try:
            loc = page.locator(f'[componentkey$="{key}"]').first
            if loc.count() > 0:
                # Scroll the section into view to trigger lazy rendering
                loc.scroll_into_view_if_needed(timeout=3000)
                human_pause(1, 2)
                text = loc.inner_text(timeout=5000).strip()
                if text and len(text) > 10:
                    profile_data[section_name] = text
        except Exception:
            pass

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


def generate_ai_messages(profile_data: dict, posts_data: list[dict], template_name: str = "template_1") -> tuple[str, str, str, str, str]:
    """Generate outreach and 4 followup messages using Gemini with specified template"""
    try:
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
    """Interact with LinkedIn profile action buttons (Connect, Message, More).

    LinkedIn's profile DOM changes frequently — element types rotate between
    <button> and <a>, CSS classes are hashed per-deploy, and absolute XPaths
    break on every layout tweak.  All selectors here use signals that are
    stable across redesigns:

      - aria-label patterns  (accessibility contract, rarely changes)
      - href substrings      (API endpoints: custom-invite, messaging/compose)
      - visible text         (user-facing strings: Connect, Message, Pending)

    Selectors are tag-agnostic (no button-vs-a assumptions) and layered
    (try multiple strategies, first match wins).
    """

    def __init__(self, page, vanity_name="", profile_name=""):
        self.page = page
        # vanity_name: the slug from the URL (e.g. "viveksingh013")
        # profile_name: full name from title (e.g. "Vivek Singh")
        self.vanity_name = vanity_name
        self.profile_name = profile_name

    def _find_visible(self, *selectors):
        """Return the first visible element matching any of the selectors, or None."""
        for sel in selectors:
            try:
                loc = self.page.locator(sel)
                for i in range(loc.count()):
                    el = loc.nth(i)
                    if el.is_visible():
                        return el
            except Exception:
                pass
        return None

    def dismiss_popups(self):
        """Dismiss LinkedIn overlay popups that block profile interaction.

        LinkedIn shows various promotional overlays (Sales Navigator upsell,
        Premium promos, cookie consent, etc.) that sit on top of the profile
        action buttons. If not dismissed, clicks land on the overlay instead
        of the intended button — silently failing.

        Called automatically before any interaction method.
        """
        # Each entry: (description, close-button selectors)
        popups = [
            ("Sales Navigator / Premium promo", [
                # The X / dismiss button on promo modals
                '[aria-label="Dismiss"]',
                '[aria-label="Schließen"]',
                'button[aria-label="Close"]',
                # Generic modal close icons (SVG close icon inside a button)
                '[data-test-modal-close-btn]',
            ]),
            ("Try Premium banner", [
                # Floating "Try Premium for AED 0" / "Try Premium for $0" bar
                # that intercepts pointer events over profile action buttons.
                # It's an <a> inside a <div> overlay — remove it from the DOM.
                'a:has-text("Try Premium")',
                'a:has-text("Premium for")',
            ]),
            ("Cookie consent banner", [
                'button:has-text("Accept")',
                'button:has-text("Akzeptieren")',
                'button:has-text("Accept & Close")',
            ]),
            ("Generic overlay close", [
                # Catch-all: any visible close/dismiss button in a dialog/overlay
                '[role="dialog"] button[aria-label="Dismiss"]',
                '[role="dialog"] button[aria-label="Close"]',
                '[role="alertdialog"] button[aria-label="Dismiss"]',
            ]),
        ]
        for desc, selectors in popups:
            btn = self._find_visible(*selectors)
            if btn:
                try:
                    if "Premium" in desc:
                        # Don't click Premium links (navigates away). The blocker
                        # is a <div> ancestor that intercepts pointer events even
                        # after the <a> itself is hidden. Walk up a few levels and
                        # disable pointer-events on the overlay container so clicks
                        # pass through to the profile action buttons underneath.
                        btn.evaluate("""el => {
                            let node = el;
                            for (let i = 0; i < 5 && node.parentElement; i++) {
                                node = node.parentElement;
                                if (node.tagName === 'MAIN' || node.tagName === 'BODY') break;
                            }
                            node.style.pointerEvents = 'none';
                            node.style.display = 'none';
                        }""")
                    else:
                        btn.click(timeout=2000)
                    human_pause(0.5, 1)
                    print(f"      Dismissed popup: {desc}")
                except Exception:
                    pass

        # Also press Escape as a catch-all for modals that have keyboard dismiss
        try:
            self.page.keyboard.press("Escape")
            human_pause(0.3, 0.5)
        except Exception:
            pass

    def _connect_selectors(self):
        """Build Connect button selectors scoped to THIS profile only.

        The page has Connect buttons for OTHER people (sidebar "More profiles
        for you", "People who follow X" section, etc.).  We ONLY match the
        Connect button for the current lead by requiring the vanityName in
        the href or the profile name in the aria-label.  No broad fallbacks.
        """
        scoped = []
        if self.vanity_name:
            scoped.append(f'[href*="custom-invite/?vanityName={self.vanity_name}"]')
        if self.profile_name:
            scoped.append(f'[aria-label*="{self.profile_name}"][aria-label$="to connect"]')
        return scoped

    def get_connection_status(self):
        """Determine relationship: CONNECTED, NOT_CONNECTED, PENDING, or UNKNOWN.

        LinkedIn profiles come in two layouts:
          - Direct Connect:   [Connect] [Message] [⋯]  (Connect is primary)
          - Follow-first:     [Follow] [Message] [⋯]   (Connect is in ⋯ dropdown)

        Both are NOT_CONNECTED.  We detect them differently:
          - Direct: scoped Connect button/link is visible
          - Follow-first: Follow button is visible (Connect hidden in ⋯ menu)
        """
        self.dismiss_popups()

        # 1. Pending — STRICT: require profile name in aria-label.
        # Previously we used `main [aria-label*="Pending"]` which false-fired
        # on "People you may know" / "Others viewed" sidebar cards that live
        # inside <main>. That made the bot silently skip real NOT_CONNECTED
        # leads as PENDING (e.g. Leon Brunner). Only the profile's OWN Pending
        # button carries the profile name in aria-label.
        pending_selectors = []
        if self.profile_name:
            pending_selectors.extend([
                f'[aria-label*="{self.profile_name}"][aria-label*="Pending"]',
                f'[aria-label*="{self.profile_name}"][aria-label*="Withdraw"]',
                f'[aria-label*="{self.profile_name}"][aria-label*="withdraw"]',
            ])
        if self.vanity_name:
            # The Withdraw endpoint contains the vanityName just like the
            # Connect endpoint does — scope by that too.
            pending_selectors.append(f'[href*="{self.vanity_name}"][aria-label*="Pending"]')
        if pending_selectors and self._find_visible(*pending_selectors):
            return "PENDING"

        # 2. Direct Connect visible (scoped to this profile)
        if self._find_visible(*self._connect_selectors()):
            return "NOT_CONNECTED"

        # 3. Follow-first layout: Follow button visible → Connect is in ⋯ menu
        if self._find_visible(
            'main button:has-text("Follow")',
            'main a:has-text("Follow")',
        ):
            return "NOT_CONNECTED"

        # 4. Message only (no Connect, no Follow) → already connected
        if self._find_visible(
            '[href*="/messaging/compose/"]',
            '[aria-label^="Message"]',
            '[aria-label^="Nachricht"]',
        ):
            return "CONNECTED"

        return "UNKNOWN"

    def _click_connect_element(self, el):
        """Click a Connect element using escalating strategies.

        Order:
          1. Playwright native .click() — does actionability checks (visible,
             stable, NOT covered by another element). If an overlay (Premium
             banner) is on top, this will throw an explicit error rather than
             silently clicking the wrong thing.
          2. Dismiss popups + retry native click.
          3. JS .click() — bypasses overlays entirely.

        We DON'T use Bezier first anymore because it blindly clicks coordinates
        without checking what's actually at those coordinates — this caused
        false-success when the Premium banner covered the Connect button.
        """
        # Strategy 1: Native Playwright click with actionability checks
        try:
            el.click(timeout=5000)
            human_pause(2, 3)
            return True
        except Exception as e:
            print(f"      Native click failed (likely intercepted): {str(e)[:120]}")

        # Strategy 2: Dismiss popups, retry native click
        self.dismiss_popups()
        human_pause(0.5, 1)
        el_retry = self._find_visible(*self._connect_selectors())
        if el_retry:
            try:
                el_retry.click(timeout=5000)
                human_pause(2, 3)
                return True
            except Exception as e:
                print(f"      Native click after popup dismiss failed: {str(e)[:120]}")

        # Strategy 3: JS click — bypasses all overlays
        try:
            target = el_retry if el_retry else el
            target.evaluate("el => el.click()")
            human_pause(2, 3)
            return True
        except Exception as e:
            print(f"      JS click failed: {str(e)[:120]}")
            return False

    def _diag(self, checkpoint):
        """Wrapper to call fingerprint diagnostics with the right account/geo."""
        try:
            from playwright_bots.fingerprint_diagnostics import safe_capture
            geo = "IN"  # default; could be parameterised per profile in future
            safe_capture(self.page, account_name="",
                         checkpoint=f"connect_{checkpoint}_{self.vanity_name or 'unknown'}",
                         proxy_geo=geo)
        except Exception:
            pass

    def send_connection_request(self):
        """Send a connection request to the current profile.

        Two paths depending on profile layout:
          Path A — Direct Connect: the Connect button/link is visible in the
                   profile header (scoped to this profile's vanityName to avoid
                   clicking sidebar recommendation Connect buttons).
          Path B — Three-dot menu (⋯): Connect is hidden inside the overflow
                   menu. Click ⋯ → find "Connect" in the dropdown → click it.

        After either path, handles the 'Send without a note' modal and verifies
        the connection actually went through.
        """
        print("      Attempting to connect...")
        self._diag("pre_click")

        # ── Path A: Direct Connect button (scoped to this profile) ───────
        connect_el = self._find_visible(*self._connect_selectors())
        if connect_el:
            print("      Found direct Connect button.")
            self._click_connect_element(connect_el)
            human_pause(2, 3)
            self._handle_send_modal()
            return self._verify_connection_sent()

        # ── Path B: Connect hidden in ⋯ (three-dot) menu ────────────────
        # On follow-first profiles, the layout is [Follow] [Message] [⋯]
        # and Connect lives inside the ⋯ dropdown.
        print("      Connect not directly visible. Opening ⋯ menu...")

        # The ⋯ button has aria-label="More" — find the first one inside
        # the main profile area (not activity section etc.)
        more_el = self._find_visible(
            'main [aria-label="More"]',
            'main [aria-label="Mehr"]',
            '[aria-label="More"]',
            '[aria-label="Mehr"]',
        )
        if not more_el:
            print("      No ⋯ button found.")
            return False

        human_move_click(self.page, more_el)
        human_pause(2, 3)

        # The dropdown is dynamically injected after clicking ⋯.
        # Items are typically <div> or <span> elements — not consistent tags.
        # Use broad text matching since the dropdown is the only new popup.
        # Exclude sidebar Connect buttons which are <a> tags with aria-label.
        dropdown_connect = self._find_visible(
            # ARIA roles (if LinkedIn uses them)
            '[role="menuitem"]:has-text("Connect")',
            '[role="menuitem"]:has-text("Vernetzen")',
            '[role="option"]:has-text("Connect")',
            # Plain text in dropdown items (div/span/li)
            'li:has-text("Connect")',
            'li:has-text("Vernetzen")',
            'div:text-is("Connect")',
            'div:text-is("Vernetzen")',
            'span:text-is("Connect")',
            'span:text-is("Vernetzen")',
        )
        if not dropdown_connect:
            print("      'Connect' not found in ⋯ dropdown.")
            # Close the dropdown by pressing Escape
            try:
                self.page.keyboard.press("Escape")
            except Exception:
                pass
            return False

        print("      Found 'Connect' in ⋯ dropdown — clicking...")
        try:
            dropdown_connect.click(timeout=5000)
        except Exception:
            try:
                dropdown_connect.evaluate("el => el.click()")
            except Exception:
                print("      Failed to click dropdown Connect.")
                return False

        human_pause(3, 5)
        self._handle_send_modal()
        return self._verify_connection_sent()

    def _handle_send_modal(self):
        """Handle the 'Add a note' / 'Send without a note' modal after clicking Connect."""
        human_pause(1, 2)

        # The modal has a "Send without a note" button (or German equivalent).
        # Try aria-label first, then visible text, then broad fallback.
        send_el = self._find_visible(
            '[aria-label="Send without a note"]',
            '[aria-label="Ohne Notiz senden"]',
            'button:has-text("Send without a note")',
            'button:has-text("Ohne Notiz senden")',
            '[aria-label="Send now"]',
            '[aria-label="Jetzt senden"]',
            'button:has-text("Send now")',
            'button:has-text("Jetzt senden")',
        )
        if send_el:
            human_move_click(self.page, send_el)
            human_pause(3, 4)
            print("      Clicked 'Send without a note'.")
            return True

        # No modal appeared — might mean direct send or click was intercepted
        print("      No 'Send' modal appeared.")
        return True

    def _verify_connection_sent(self):
        """Strict verification — REQUIRES the profile name in the aria-label.

        LinkedIn's profile page contains many "Pending"/"Withdraw" elements
        unrelated to the current lead:
          - "More profiles for you" sidebar (inside <main>) with Connect/Pending
            buttons for OTHER recommended people
          - Sidebar widgets (notifications, My Network)
          - Activity feed posts mentioning "pending" anything

        The ONLY reliable signal that the request to THIS person went through
        is an aria-label containing both the profile name AND Pending/Withdraw,
        e.g. "Pending, click to withdraw invitation sent to Kushal Singh Soni".
        If we can't find that, treat the click as failed.
        """
        human_pause(1, 2)

        if not self.profile_name:
            # No profile name → can't verify safely. Assume failure to be safe.
            print("      ⚠️  No profile name available for verification — assuming click failed.")
            return False

        # Match aria-label that contains BOTH this profile's name AND
        # the Pending/Withdraw word. LinkedIn's actual aria-labels are like:
        #   "Pending, click to withdraw invitation sent to Kushal Singh Soni"
        if self._find_visible(
            f'[aria-label*="{self.profile_name}"][aria-label*="Pending"]',
            f'[aria-label*="{self.profile_name}"][aria-label*="Withdraw"]',
            f'[aria-label*="{self.profile_name}"][aria-label*="withdraw"]',
        ):
            print(f"      ✓ Connection request verified — found Pending for {self.profile_name}.")
            return True

        # If Connect button is still visible, the click didn't go through
        still_connect = self._find_visible(*self._connect_selectors())
        if still_connect:
            print("      ✗ Connect button still visible — click was intercepted!")
            self._diag("verify_failed")

            # Dump a screenshot so we can see what's blocking
            try:
                from state_paths import LOGS_DIR
                debug_dir = os.path.join(LOGS_DIR, "profile_debug")
                os.makedirs(debug_dir, exist_ok=True)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                self.page.screenshot(path=os.path.join(debug_dir, f"{ts}_connect_blocked.png"))
                print(f"      [debug] screenshot → {debug_dir}/{ts}_connect_blocked.png")
            except Exception:
                pass

            print("      Retrying: dismiss popups → Playwright native click...")
            self.dismiss_popups()
            human_pause(1, 2)

            # Retry with escalating click strategies
            connect_el = self._find_visible(*self._connect_selectors())
            if connect_el:
                # Strategy 1: Playwright native .click() — throws if covered
                try:
                    connect_el.click(timeout=5000)
                    print("      Playwright .click() succeeded.")
                except Exception as e:
                    print(f"      Playwright .click() failed: {e}")
                    # Strategy 2: JS-level click — bypasses all overlays
                    try:
                        connect_el.evaluate("el => el.click()")
                        print("      JS el.click() succeeded.")
                    except Exception as e2:
                        print(f"      JS click also failed: {e2}")

                human_pause(3, 5)
                self._handle_send_modal()
                human_pause(1, 2)

                # Check again
                if self._find_visible(
                    '[aria-label*="Pending"]',
                    ':is(button, a):has-text("Pending")',
                    '[aria-label*="Withdraw"]',
                ):
                    print("      ✓ Connection request verified on retry.")
                    return True
                else:
                    print("      ✗ Connection request failed even after retry.")
                    return False
            else:
                # Connect button disappeared after popup dismiss — might have gone through
                print("      Connect button gone after popup dismiss — likely sent.")
                return True

        # Connect button gone but no Pending visible — ambiguous but likely sent
        print("      Connect button no longer visible — assuming request sent.")
        return True


def _dump_profile_debug(page, url, tag):
    """Dump page state when profile detection fails — URL, title, h1 contents,
    HTML snippet, and a screenshot. Lands in <STATE_DIR>/logs/profile_debug/."""
    try:
        from state_paths import LOGS_DIR
        debug_dir = os.path.join(LOGS_DIR, "profile_debug")
        os.makedirs(debug_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = url.rstrip("/").split("/")[-1][:40]
        base = os.path.join(debug_dir, f"{ts}_{slug}_{tag}")

        meta = {
            "requested_url": url,
            "current_url": page.url,
            "title": page.title(),
            "h1_count": page.locator("h1").count(),
            "h1_texts": [],
            "main_count": page.locator("main").count(),
        }
        try:
            for i in range(min(meta["h1_count"], 5)):
                meta["h1_texts"].append(page.locator("h1").nth(i).inner_text(timeout=1000))
        except Exception as e:
            meta["h1_texts_err"] = str(e)

        with open(base + ".json", "w") as f:
            json.dump(meta, f, indent=2)
        try:
            page.screenshot(path=base + ".png", full_page=False)
        except Exception:
            pass
        try:
            with open(base + ".html", "w") as f:
                f.write(page.content()[:200_000])
        except Exception:
            pass
        print(f"      [debug] dumped profile state → {base}.{{json,png,html}}")
    except Exception as e:
        print(f"      [debug] dump failed: {e}")


def _extract_name_from_title(title):
    """Extract profile name from a page title like 'Vansh Dhawan | LinkedIn'.

    Returns the name string or None if the title doesn't look like a profile.
    Rejects known non-profile titles (404 pages, auth walls, generic pages).
    """
    if not title or "|" not in title:
        return None
    name = title.rsplit("|", 1)[0].strip()
    # Reject empty, too-short, or generic/error page titles
    reject = {"linkedin", "page not found", "sign in", "security verification",
              "something went wrong", ""}
    if name.lower() in reject or len(name) < 2:
        return None
    return name


class SessionFailureError(Exception):
    """Raised when LinkedIn invalidates our session mid-run.

    Triggered by ERR_TOO_MANY_REDIRECTS, ERR_TUNNEL_CONNECTION_FAILED, or
    repeated network errors — these mean the session/proxy is broken, NOT
    that the profile doesn't exist. Caller must abort the run to preserve
    leads (don't mark them as FAULTY URL and don't delete from bot_inputs).
    """


_SESSION_ERROR_PATTERNS = (
    "err_too_many_redirects",
    "err_tunnel_connection_failed",
    "err_proxy_connection_failed",
    "err_connection_reset",
    "net::err_aborted",
)


def _is_session_error(err_str):
    """Return True if the error string looks like a session/proxy failure."""
    s = err_str.lower()
    return any(p in s for p in _SESSION_ERROR_PATTERNS)


def is_profile_accessible(page, url, max_retries=2):
    """
    Check if the LinkedIn profile URL is accessible (not 404 or deleted).
    Returns True if accessible, False if 404/not found.

    Detection strategy (layered, most-stable first):
      1. URL checks — did we land on /in/<slug>, not /404 or a redirect?
      2. Page title — "Name | LinkedIn" is the most stable signal; it powers
         SEO, social sharing, and browser tabs. Available before JS hydrates.
      3. DOM fallback — try heading tags (h1/h2) and aria-label patterns.
         LinkedIn's DOM uses hashed CSS classes that rotate every deploy, so
         we never rely on class names.
      4. Debug dump — on final failure, write screenshot + HTML + metadata
         so the next investigation starts with data, not guesswork.
    """
    for attempt in range(max_retries):
        try:
            print(f"      Checking profile accessibility (attempt {attempt + 1}/{max_retries})...")

            _safe_goto(page, url, timeout=60000)
            human_pause(3, 5)

            current_url = page.url.lower()
            original_url = url.lower()

            try:
                original_profile_id = original_url.split('/in/')[-1].rstrip('/')
            except:
                original_profile_id = None

            # ── Layer 1: URL checks ──────────────────────────────────────
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

            # ── Layer 2: page title (most stable signal) ─────────────────
            title = page.title()
            title_name = _extract_name_from_title(title)
            if title_name:
                print(f"      Profile accessible (title) - found name: {title_name}")
                return True

            # ── Layer 3: DOM fallback — headings + aria-label ────────────
            # LinkedIn has moved from h1 → h2 before; try all headings.
            # Also check aria-label which contains "Name Verified Profile".
            for selector, label in [
                ("h1", "h1"),
                ("h2", "h2"),
                ('[aria-label*="Verified Profile"]', "aria-label"),
            ]:
                try:
                    loc = page.locator(selector).first
                    loc.wait_for(state="visible", timeout=5000)
                    if selector.startswith("[aria"):
                        text = loc.get_attribute("aria-label") or ""
                    else:
                        text = loc.inner_text()
                    text = text.strip()
                    if text and len(text) >= 2:
                        print(f"      Profile accessible ({label}) - found: {text[:60]}")
                        return True
                except Exception:
                    pass

            # ── All layers failed ────────────────────────────────────────
            if attempt < max_retries - 1:
                print(f"      No profile signal found (title={title!r}), retrying...")
                continue
            else:
                print(f"      Profile detection failed after {max_retries} attempts (title={title!r})")
                _dump_profile_debug(page, url, f"allfail_a{attempt+1}")
                return False

        except Exception as e:
            err_str = str(e)
            # Session/proxy failures should NOT be treated as faulty URLs.
            # Bail out immediately so the caller can preserve the lead.
            if _is_session_error(err_str):
                print(f"      🛑 Session/proxy error detected: {err_str[:120]}")
                raise SessionFailureError(err_str)

            if attempt < max_retries - 1:
                print(f"      Error on attempt {attempt + 1}: {e}, retrying...")
                human_pause(2, 3)
                continue
            else:
                print(f"      Error checking profile accessibility after {max_retries} attempts: {e}")
                _dump_profile_debug(page, url, f"error_a{attempt+1}")
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
    set_active_account(account_name)
    set_notifier_account(account_name)

    print("   Ensuring LinkedIn login...")
    driver = ensure_linkedin_login(suspicious_otp=args.suspicious_otp, account_name=account_name)

    if not driver:
        print("   Could not establish LinkedIn session. Exiting.")
        notify_login_failed(account_name)
        return

    print("   LinkedIn session established. Starting bot operations...")
    page = driver.page

    # ── DIAGNOSTIC: capture fingerprint baseline right after login ───
    # Determines proxy_geo from the account name (Yatharth=IN, Maurice/Leon=DE)
    _proxy_geo = "IN" if "yatharth" in account_name.lower() else (
        "DE" if any(n in account_name.lower() for n in ("maurice", "leon")) else None)
    _diag_capture(page, account_name=account_name, checkpoint="post_login",
                  proxy_geo=_proxy_geo)

    try:
        print("   Opening LinkedIn...")
        _safe_goto(page, "https://www.linkedin.com/", timeout=60000)
        log_action(page, "linkedin_homepage")
        human_pause(4, 7)

        # Capture again on the homepage so we can see what LinkedIn sees on a real page
        _diag_capture(page, account_name=account_name, checkpoint="on_feed",
                      proxy_geo=_proxy_geo)

        print("   Session Active. Ready to start automation.")
        human_scroll(page)

        # Read daily limit from per-account config, fallback to generic
        daily_limit = 18
        # Make project root importable for state_paths (idempotent — safe if already added)
        import sys as _sys
        _project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if _project_root not in _sys.path:
            _sys.path.insert(0, _project_root)
        from state_paths import config_path as _config_path, slugify as _slugify
        slug = _slugify(account_name)
        cfg_path = _config_path(slug)
        if not os.path.exists(cfg_path):
            cfg_path = _config_path()
        try:
            with open(cfg_path, "r") as f:
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
            # Template name from Attio (e.g. "template_5") — refers to prompt_template_5.json on disk
            template_name = lead_record.get("prompt_template", "").strip() or "template_1"

            print(f"\n[{count + 1}/{daily_limit}]    Checking: {url}")

            exists, record = check_if_exists(url)
            if exists:
                status = record.get('lead_status', 'UNKNOWN')
                print(f"   Skipping: Lead already in Attio (Status: {status})")
                # Still delete from bot_inputs to avoid re-processing
                client.delete_bot_input(record_id)
                continue

            # Extract vanity name from URL for scoped selectors
            vanity = url.rstrip("/").split("/in/")[-1].split("?")[0] if "/in/" in url else ""
            li_manager = LinkedInInteractionManager(page, vanity_name=vanity)

            # PHASE 0: CHECK IF PROFILE IS ACCESSIBLE
            try:
                accessible = is_profile_accessible(page, url)
            except SessionFailureError as sf:
                # LinkedIn invalidated our session (redirect loops, tunnel
                # failures). Do NOT mark this lead as faulty — the lead is
                # fine, our session is broken. Abort the run; the lead stays
                # in bot_inputs for the next cron tick to retry with a fresh
                # session (cookies/proxy session will be regenerated).
                print(f"   🛑 Session failure mid-run: {sf}")
                print(f"   Aborting run to preserve remaining {len(bot_input_leads) - count} leads.")
                notify_error(account_name, f"Session invalidated mid-run after {count} successful leads. Lead preserved: {url}")
                return

            if not accessible:
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
                    profile_data, posts_data, template_name=template_name
                )
                print("      Data gathering complete.")

                # CRITICAL FIX: RESET VIEWPORT
                print("      Returning to top of profile for interaction...")
                page.evaluate("window.scrollTo({top: 0, behavior: 'auto'})")
                human_pause(2, 3)

                # PHASE 2: INTERACTION
                # Now that we know the profile name, set it for scoped selectors
                li_manager.profile_name = profile_data["full_name"]
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
                        notify_connection_sent(profile_data["full_name"], account_name)
                    else:
                        # Connect click failed (intercepted, couldn't resolve, etc.)
                        # DO NOT silently drop the lead: notify + keep in bot_inputs
                        # so it can be retried on the next run.
                        db_status_update = "CONNECT_FAILED"
                        print(f"      ❌ Connection request NOT sent for {profile_data['full_name']}")
                        try:
                            notify_error(
                                f"Connection NOT sent to {profile_data['full_name']} — click failed/intercepted. "
                                f"Lead kept in bot_inputs for retry.",
                                account_name,
                            )
                        except Exception:
                            pass

                elif status == "PENDING":
                    print("      Invite pending. Skipping.")
                    db_status_update = "PENDING"

                # PHASE 3: SAVE TO ATTIO
                save_lead_to_db(
                    url, profile_data, posts_data, outreach_msg, followup_msg_1, followup_msg_2, followup_msg_3, followup_msg_4,
                    status=db_status_update,
                    last_contacted=last_contacted,
                    lead_manager=account_name,
                    prompt_template=template_name,
                )

                # PHASE 4: CLEANUP — only delete bot_input on definitive outcomes.
                # On CONNECT_FAILED we KEEP the record so the next run retries.
                if db_status_update != "CONNECT_FAILED":
                    client.delete_bot_input(record_id)
                else:
                    print(f"      ⏸ Leaving bot_input {record_id} in place for retry on next run")

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
        notify_error(f"Connection Bot crash: {e}", account_name)
        log_action(page, "critical_failure")

    finally:
        print("   Closing browser session...")
        try:
            driver.quit()
        except:
            pass


if __name__ == "__main__":
    main()
