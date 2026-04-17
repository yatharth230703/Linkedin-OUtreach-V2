"""robust_messaging.py — Tag-agnostic LinkedIn messaging helpers.

Same philosophy as LinkedInInteractionManager in the connection bot:
  - NO absolute XPaths
  - NO hashed CSS classes
  - Use stable signals: aria-label, href, role, visible text
  - Explicit focus + explicit click + verification after every action

Exposes:
  - find_message_button_for(page, name) → the Message button next to a lead on
                                           the /mynetwork/connections/ page
  - send_message_in_open_thread(page, text, lead_name) → focus textbox, type,
                                                          click Send, verify
"""
from __future__ import annotations

import hashlib
import os
import random
import re
import time


def lead_identity_hash(name, headline):
    """Short stable fingerprint for a lead combining name + headline.

    Two distinct people can share a name ("Aman Kumar") but (nearly) never
    share name+headline. This hash is the canonical identity we use when
    logging / comparing / disambiguating so the bot never confuses two
    same-named connections.
    """
    blob = f"{(name or '').strip().lower()}|{(headline or '').strip().lower()}"
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:10]


def _distinctive_headline_snippet(headline, min_len=12, max_len=40):
    """Pick the most distinctive contiguous slice of the headline for
    in-page text matching. Strips short/common words at the edges.
    """
    if not headline:
        return None
    # Strip common role words at start that appear in many profiles
    trimmed = re.sub(r"^\s*(at|@|student|engineer|intern|founder|ceo|cto)\b[\s:,-]*",
                     "", headline, flags=re.IGNORECASE).strip()
    candidate = trimmed if len(trimmed) >= min_len else headline
    if len(candidate) > max_len:
        candidate = candidate[:max_len]
    candidate = candidate.strip(" ,.-|/•·")
    return candidate if len(candidate) >= min_len else None


def _visible_first(page, *selectors, timeout=0):
    """Return first visible match across selectors, or None."""
    for sel in selectors:
        try:
            loc = page.locator(sel)
            n = loc.count()
            for i in range(n):
                el = loc.nth(i)
                if el.is_visible():
                    return el
        except Exception:
            pass
    return None


def find_message_button_for(page, lead_name, lead_headline=None):
    """Find the Message button for a specific connection, disambiguating by
    name + headline to handle common-name collisions (two "Aman Kumar"s etc.).

    Strategy (most-specific first, tag-agnostic, stable):
      1. CARD SCOPED BY NAME + HEADLINE (strongest) — find a card whose
         visible text contains BOTH the lead's full name AND a distinctive
         slice of the lead's headline. Message button must be inside that card.
      2. CARD SCOPED BY NAME only (fallback when no headline provided) —
         only safe if we know the name is unique on this page.
      3. aria-label pattern — "Message {name}" — may match multiple when
         names collide, so used last.

    Returns the Playwright Locator for the Message button, or None.
    Prints the lead identity hash so logs are unambiguous.
    """
    ident = lead_identity_hash(lead_name, lead_headline or "")
    snippet = _distinctive_headline_snippet(lead_headline) if lead_headline else None

    # ── 1. Card scoped by name + headline snippet (STRONG disambiguation) ──
    if snippet:
        try:
            # Iterate candidate cards that visibly contain the name, then keep
            # only the one(s) that also contain the headline snippet.
            name_matches = page.get_by_text(lead_name, exact=False)
            n = name_matches.count()
            for i in range(n):
                nm = name_matches.nth(i)
                try:
                    if not nm.is_visible():
                        continue
                except Exception:
                    continue
                # Walk up to the card-like ancestor
                card = nm.locator(
                    "xpath=./ancestor::*[self::li or self::article or "
                    "self::section or @role='listitem'][1]"
                )
                if card.count() == 0:
                    # Fall back to a generic ancestor div with a Message descendant
                    card = nm.locator(
                        'xpath=./ancestor::div[.//*[contains(@aria-label,"Message") '
                        'or contains(@aria-label,"Nachricht")]][1]'
                    )
                if card.count() == 0:
                    continue
                card_first = card.first
                # Confirm the card ALSO contains the headline snippet
                try:
                    card_text = card_first.inner_text()
                except Exception:
                    continue
                if snippet.lower() not in (card_text or "").lower():
                    continue
                # Find Message button inside this specific card
                msg = card_first.locator(
                    ':is(button, a):has-text("Message"), '
                    ':is(button, a):has-text("Nachricht"), '
                    '[aria-label*="Message"], '
                    '[aria-label*="Nachricht"]'
                )
                if msg.count() > 0 and msg.first.is_visible():
                    print(f"      [{ident}] matched card by name+headline snippet: {snippet!r}")
                    return msg.first
        except Exception:
            pass

    # ── 2. Card scoped by name only (only when headline unavailable) ──────
    if not lead_headline:
        try:
            name_el = page.get_by_text(lead_name, exact=True).first
            if name_el.count() > 0 and name_el.is_visible():
                card = name_el.locator(
                    "xpath=./ancestor::*[self::li or self::article or "
                    "self::section or @role='listitem'][1]"
                )
                if card.count() > 0:
                    msg = card.first.locator(
                        ':is(button, a):has-text("Message"), '
                        ':is(button, a):has-text("Nachricht"), '
                        '[aria-label*="Message"], '
                        '[aria-label*="Nachricht"]'
                    )
                    if msg.count() > 0 and msg.first.is_visible():
                        print(f"      [{ident}] matched card by name only (no headline disambiguation)")
                        return msg.first
        except Exception:
            pass

    # ── 3. aria-label pattern (LAST resort — risky with common names) ─────
    el = _visible_first(
        page,
        f'[aria-label*="Message"][aria-label*="{lead_name}"]',
        f'[aria-label*="Nachricht"][aria-label*="{lead_name}"]',
    )
    if el:
        print(f"      [{ident}] matched by aria-label (fallback, name only — check for duplicates)")
        return el

    print(f"      [{ident}] no match found for Message button")
    return None


def _find_message_textbox(page):
    """Find the contenteditable textbox inside the ACTIVE conversation dialog.

    LinkedIn's messaging textbox is `div[contenteditable="true"]` inside a
    `[role="dialog"]` conversation bubble in the #interop-outlet shadow root.
    It has NO role="textbox" and NO aria-label — just contenteditable + a
    class like "msg-form__contenteditable".

    Strategy: find the NON-MINIMIZED conversation dialog → find the
    contenteditable div inside it. This is safe because we only call this
    AFTER verify_recipient_in_overlay confirmed the right thread is open.
    """
    try:
        handle = page.evaluate_handle("""
        () => {
            const findIn = (root) => {
                // Find active (not minimized) conversation dialogs
                const dialogs = root.querySelectorAll(
                    '[role="dialog"][aria-label="Messaging"], ' +
                    '[role="dialog"][aria-label*="essaging"], ' +
                    '[data-msg-overlay-conversation-bubble-open]'
                );
                for (const dlg of dialogs) {
                    const min = dlg.getAttribute('data-msg-overlay-conversation-bubble-is-minimized');
                    if (min === 'true') continue;
                    // Find the contenteditable textbox inside this dialog
                    const ce = dlg.querySelector('div[contenteditable="true"]');
                    if (ce) {
                        const r = ce.getBoundingClientRect();
                        if (r.width > 0 && r.height > 0) return ce;
                    }
                }
                return null;
            };
            // Try shadow root first (where LinkedIn puts the overlay)
            const host = document.querySelector('#interop-outlet');
            if (host && host.shadowRoot) {
                const found = findIn(host.shadowRoot);
                if (found) return found;
            }
            // Light DOM fallback
            return findIn(document);
        }
        """)
        if handle:
            elem = handle.as_element()
            if elem:
                return elem
    except Exception:
        pass
    return None


def _find_send_button(page):
    """Find the Send button inside the ACTIVE conversation dialog.

    LinkedIn's Send button is inside the same [role="dialog"] as the textbox.
    We scope to the active (non-minimized) dialog to avoid clicking Send in a
    minimized or stale bubble.
    """
    try:
        handle = page.evaluate_handle("""
        () => {
            const findIn = (root) => {
                const dialogs = root.querySelectorAll(
                    '[role="dialog"][aria-label="Messaging"], ' +
                    '[role="dialog"][aria-label*="essaging"], ' +
                    '[data-msg-overlay-conversation-bubble-open]'
                );
                for (const dlg of dialogs) {
                    const min = dlg.getAttribute('data-msg-overlay-conversation-bubble-is-minimized');
                    if (min === 'true') continue;
                    // Look for Send button inside this dialog
                    const sels = [
                        'button[aria-label="Send"]',
                        'button[aria-label="Senden"]',
                        'button[type="submit"]',
                    ];
                    for (const sel of sels) {
                        for (const btn of dlg.querySelectorAll(sel)) {
                            if (btn.disabled) continue;
                            const r = btn.getBoundingClientRect();
                            if (r.width > 0 && r.height > 0) return btn;
                        }
                    }
                    // Text fallback inside this dialog only
                    for (const btn of dlg.querySelectorAll('button')) {
                        if (btn.disabled) continue;
                        const t = (btn.innerText || btn.textContent || '').trim();
                        if (t === 'Send' || t === 'Senden') {
                            const r = btn.getBoundingClientRect();
                            if (r.width > 0 && r.height > 0) return btn;
                        }
                    }
                }
                return null;
            };
            const host = document.querySelector('#interop-outlet');
            if (host && host.shadowRoot) {
                const found = findIn(host.shadowRoot);
                if (found) return found;
            }
            return findIn(document);
        }
        """)
        if handle:
            elem = handle.as_element()
            if elem:
                return elem
    except Exception:
        pass
    return None


def _dump_overlay_diagnostic(page, lead_name, tag):
    """Dump a screenshot + the shadow-root HTML when something fails so we
    can see exactly what's on screen at the failure moment.
    """
    try:
        import sys as _sys, json as _json
        _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if _root not in _sys.path:
            _sys.path.insert(0, _root)
        from state_paths import LOGS_DIR
        from datetime import datetime
        debug_dir = os.path.join(LOGS_DIR, "messaging_debug")
        os.makedirs(debug_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = re.sub(r"[^a-z0-9]+", "_", (lead_name or "unknown").lower())[:30]
        base = os.path.join(debug_dir, f"{ts}_{slug}_{tag}")
        try:
            page.screenshot(path=base + ".png", full_page=False)
        except Exception:
            pass
        # Dump FULL page HTML (light DOM) so we can find WHERE the overlay lives
        try:
            full_html = page.content()
            with open(base + "_fullpage.html", "w") as f:
                f.write(full_html[:500_000])
        except Exception:
            pass
        # Scan ALL shadow hosts on the page and dump their shadow roots
        try:
            shadow_report = page.evaluate("""
            () => {
                const hosts = [];
                const walk = (root, path) => {
                    for (const el of root.querySelectorAll('*')) {
                        if (el.shadowRoot) {
                            const snippet = el.shadowRoot.innerHTML.substring(0, 2000);
                            hosts.push({
                                path: path + ' > ' + el.tagName + '#' + (el.id || '(no-id)'),
                                childCount: el.shadowRoot.childElementCount,
                                hasTextbox: el.shadowRoot.querySelector('[role="textbox"], [contenteditable="true"]') !== null,
                                hasMsg: (el.shadowRoot.innerHTML || '').toLowerCase().includes('message'),
                                snippet: snippet
                            });
                            walk(el.shadowRoot, path + ' > SHADOW(' + (el.id || el.tagName) + ')');
                        }
                    }
                };
                walk(document, 'document');
                return hosts;
            }
            """)
            with open(base + "_shadow_hosts.json", "w") as f:
                _json.dump(shadow_report, f, indent=2, default=str)
        except Exception:
            pass
        # Check for iframes that might contain messaging
        try:
            iframe_report = page.evaluate("""
            () => {
                const iframes = [];
                document.querySelectorAll('iframe').forEach(f => {
                    iframes.push({
                        src: f.src || '(no src)',
                        id: f.id || '(no id)',
                        name: f.name || '(no name)',
                        visible: f.getBoundingClientRect().width > 0,
                    });
                });
                return iframes;
            }
            """)
            with open(base + "_iframes.json", "w") as f:
                _json.dump(iframe_report, f, indent=2, default=str)
        except Exception:
            pass
        try:
            with open(base + "_meta.json", "w") as f:
                _json.dump({
                    "lead": lead_name, "tag": tag, "url": page.url,
                    "title": page.title(),
                }, f, indent=2)
        except Exception:
            pass
        print(f"      [debug] dumped overlay state → {base}.{{png,_shadow.html,_meta.json}}")
    except Exception as e:
        print(f"      [debug] dump failed: {e}")


def _count_thread_messages(page):
    """Count messages currently rendered in the conversation thread.

    We use this as a verification signal: message count increases by 1 after
    a successful send.
    """
    selectors = [
        'li.msg-s-message-list__event',
        '[role="listitem"][data-event-name]',
        'div[data-event-urn*="messagingMessage"]',
        '.msg-s-event-listitem',
        # Generic: listitem roles inside a messaging container
        '[role="log"] [role="listitem"]',
    ]
    best = 0
    for sel in selectors:
        try:
            n = page.locator(sel).count()
            if n > best:
                best = n
        except Exception:
            pass
    return best


def _pause(a, b):
    time.sleep(random.uniform(a, b))


def verify_recipient_in_overlay(page, expected_name):
    """Confirm the open message overlay shows the expected recipient.

    Robust strategy — uses ZERO LinkedIn-specific class names:
      1. Find the active message TEXTBOX (using only HTML/ARIA standards:
         `role="textbox"`, `contenteditable="true"`, `aria-label*="message"`).
      2. Walk UP to find the textbox's overlay container — by definition, any
         overlay containing a message textbox IS a conversation overlay.
      3. Check that container's text + aria-labels + profile links for the
         recipient's name. The conversation header MUST contain the recipient.

    This works because of an invariant: a message composer is ALWAYS inside
    a UI region that identifies its recipient — that's a UX requirement, not
    a CSS implementation detail. As long as LinkedIn keeps putting recipient
    info near the textbox (which they MUST for usability), this won't break.
    """
    lower_name = (expected_name or "").strip().lower()
    if not lower_name:
        return False

    js = """
    (lower) => {
        // LinkedIn renders the messaging overlay inside #interop-outlet's
        // shadow root. Each conversation bubble is a [role="dialog"] with
        // aria-label="Messaging". The recipient name is in the <header>
        // inside the bubble. The textbox is div[contenteditable="true"]
        // (NO role="textbox", NO aria-label="message" — just contenteditable).

        const checkRoot = (root) => {
            // Find all ACTIVE (not minimized) conversation bubbles
            // LinkedIn marks them with data-msg-overlay-conversation-bubble-is-minimized="false"
            const dialogs = root.querySelectorAll(
                '[role="dialog"][aria-label="Messaging"], ' +
                '[role="dialog"][aria-label*="essaging"], ' +
                '[data-msg-overlay-conversation-bubble-open]'
            );
            for (const dlg of dialogs) {
                // Skip minimized bubbles
                const min = dlg.getAttribute('data-msg-overlay-conversation-bubble-is-minimized');
                if (min === 'true') continue;

                // Check if the dialog's header/content contains the recipient name
                const txt = (dlg.innerText || '').toLowerCase();
                if (txt.includes(lower)) return true;

                // Also check profile links inside (LinkedIn puts /in/<slug> links in headers)
                for (const a of dlg.querySelectorAll('a[href*="/in/"]')) {
                    const at = (a.innerText || a.textContent || '').toLowerCase();
                    if (at.includes(lower)) return true;
                }
            }
            return false;
        };

        // 1. Shadow root (primary — this is where LinkedIn puts the overlay)
        const host = document.querySelector('#interop-outlet');
        if (host && host.shadowRoot) {
            if (checkRoot(host.shadowRoot)) return true;
        }

        // 2. Light DOM fallback (full-page messaging or regular dialogs)
        if (checkRoot(document)) return true;

        return false;
    }
    """
    try:
        return bool(page.evaluate(js, lower_name))
    except Exception:
        return False


def open_conversation_via_profile(page, profile_url, lead_name, lead_headline=None, timeout_s=15):
    """Open a direct conversation with `lead_name` by navigating to their
    LinkedIn profile and clicking the profile-level Message button.

    Why this exists: the Message button on /mynetwork/invite-connect/connections/
    does NOT open a direct conversation — it opens a "New message" composer
    that's pinned to whatever thread was last open (e.g. Leon Brunner).
    Clicking Message on the target's PROFILE opens their specific thread.

    Returns True on success (conversation with the right person is open),
    False otherwise. Caller should then call send_message_in_open_thread().
    """
    if not profile_url:
        print(f"   ⚠️ [{lead_name}] no profile URL available — cannot open conversation")
        return False

    # Normalise URL (accept both full URLs and vanity slugs)
    if not profile_url.startswith("http"):
        profile_url = f"https://www.linkedin.com/in/{profile_url.strip('/')}/"

    # Close any existing overlays first — they can intercept clicks / confuse navigation
    close_all_message_overlays(page)

    try:
        page.goto(profile_url, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        print(f"   ⚠️ [{lead_name}] failed to navigate to {profile_url}: {str(e)[:120]}")
        return False

    _pause(3, 5)  # let React hydrate

    # Dismiss any popups (Premium banner, Sales Navigator promo) that might cover the Message button
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    try:
        # Programmatically hide known blocking overlays so our click can reach Message
        page.evaluate("""() => {
            // Hide 'Try Premium' floating banner if present
            document.querySelectorAll('a').forEach(a => {
                const t = (a.innerText || '').toLowerCase();
                if (t.includes('try premium')) {
                    let n = a;
                    for (let i = 0; i < 5 && n.parentElement; i++) {
                        n = n.parentElement;
                        if (n.tagName === 'MAIN' || n.tagName === 'BODY') break;
                    }
                    n.style.display = 'none';
                    n.style.pointerEvents = 'none';
                }
            });
        }""")
    except Exception:
        pass

    # Find the profile-level Message button — it's an <a href="/messaging/compose/...">
    # OR a <button aria-label*="Message {name}">. Scope to main to exclude sidebar.
    name_attr = lead_name.replace('"', '').strip()
    selectors = [
        f'main a[href*="/messaging/compose/"][aria-label*="{name_attr}"]',
        f'main a[aria-label^="Message"][aria-label*="{name_attr}"]',
        'main a[href*="/messaging/compose/"]',
        'main a[aria-label^="Message"]',
        'main button[aria-label^="Message"]',
    ]
    msg_btn = _visible_first(page, *selectors)
    if not msg_btn:
        print(f"   ⚠️ [{lead_name}] Message button not found on profile page")
        return False

    try:
        msg_btn.click(timeout=5000)
    except Exception:
        try:
            msg_btn.evaluate("el => el.click()")
        except Exception as e:
            print(f"   ⚠️ [{lead_name}] Message button click failed: {str(e)[:120]}")
            return False

    # Wait for the conversation overlay to open AND show the correct recipient.
    # verify_recipient_in_overlay polls the shadow DOM for the lead's name.
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if verify_recipient_in_overlay(page, lead_name):
            print(f"   ✓ [{lead_name}] conversation opened from profile")
            return True
        time.sleep(0.5)

    print(f"   ⚠️ [{lead_name}] conversation did not verify recipient within {timeout_s}s after profile Message click")
    _dump_overlay_diagnostic(page, lead_name, "profile_msg_failed")
    return False


def close_all_message_overlays(page):
    """Force-close any open message overlays/dialogs.

    LinkedIn's bottom-right messaging overlays live in the #interop-outlet
    shadow DOM. Close buttons are INSIDE the shadow root, so regular Playwright
    selectors can't see them. We use page.evaluate to close from within.
    """
    # 1. Press Escape multiple times — closes most overlays
    for _ in range(3):
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        _pause(0.2, 0.3)

    # 2. Close ALL conversation bubbles via shadow DOM
    try:
        page.evaluate("""
        () => {
            const closeIn = (root) => {
                // Find all close buttons inside messaging dialogs
                const sels = [
                    'button[aria-label*="close" i]',
                    'button[aria-label*="Close" i]',
                    'button[aria-label*="schließen" i]',
                ];
                for (const sel of sels) {
                    root.querySelectorAll(sel).forEach(btn => {
                        const r = btn.getBoundingClientRect();
                        if (r.width > 0 && r.height > 0) {
                            try { btn.click(); } catch {}
                        }
                    });
                }
                // Also try to minimize/close all conversation bubbles
                root.querySelectorAll('[data-msg-overlay-conversation-bubble-open]').forEach(bubble => {
                    // Click the close/minimize button inside each bubble
                    bubble.querySelectorAll('button').forEach(btn => {
                        const label = (btn.getAttribute('aria-label') || '').toLowerCase();
                        if (label.includes('close') || label.includes('minimize') ||
                            label.includes('schließen') || label.includes('minimieren')) {
                            try { btn.click(); } catch {}
                        }
                    });
                });
            };
            // Shadow root
            const host = document.querySelector('#interop-outlet');
            if (host && host.shadowRoot) closeIn(host.shadowRoot);
            // Light DOM fallback
            closeIn(document);
        }
        """)
    except Exception:
        pass
    _pause(0.5, 1.0)

    # 3. Final Escape + body click to defocus
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    try:
        page.locator("body").first.click(position={"x": 5, "y": 5}, timeout=1000)
    except Exception:
        pass
    _pause(0.3, 0.5)


def send_message_in_open_thread(page, message_text, lead_name, verify_timeout_s=8):
    """Send a message in an already-open conversation, with verification.

    Flow:
      1. Find textbox via stable selectors, click to focus, wait for focus
      2. Record message count BEFORE sending
      3. Type the message using keyboard (honoring focus)
      4. Try to click a Send button (preferred — explicit, verifiable)
         Fall back to Ctrl+Enter only if no Send button found
      5. Poll message count for verify_timeout_s seconds; success if it grew
         OR if the last rendered message's text contains our text
      6. Return "SENT" / "FAILED" — DO NOT lie about success

    Args:
        page: Playwright Page (conversation must already be open)
        message_text: the message body to send
        lead_name: for logging
        verify_timeout_s: how long to poll for the new message to appear
    """
    # ── 0. Verify the OPEN conversation is for the expected recipient ──
    # Wait briefly — the messaging overlay is React-rendered and shadow-DOM
    # injected; it can take a moment to appear after the Message button click.
    deadline = time.time() + 6
    recipient_ok = False
    while time.time() < deadline:
        if verify_recipient_in_overlay(page, lead_name):
            recipient_ok = True
            break
        time.sleep(0.5)

    if not recipient_ok:
        print(f"      🚫 [{lead_name}] open conversation does NOT show '{lead_name}' — refusing to send")
        _dump_overlay_diagnostic(page, lead_name, "wrong_recipient")
        return "FAILED_WRONG_RECIPIENT"

    # ── 1. Locate textbox and focus it ────────────────────────────
    textbox = _find_message_textbox(page)
    if not textbox:
        print(f"      ✗ [{lead_name}] message textbox not found — cannot send")
        _dump_overlay_diagnostic(page, lead_name, "no_textbox")
        return "FAILED_NO_TEXTBOX"

    try:
        textbox.click(timeout=5000)
        _pause(0.3, 0.6)
    except Exception as e:
        print(f"      ✗ [{lead_name}] textbox click failed: {str(e)[:100]}")
        # Try focusing via JS as a fallback
        try:
            textbox.evaluate("el => el.focus()")
        except Exception:
            return "FAILED_NO_FOCUS"

    # Confirm focus landed on the textbox (anti-false-success check)
    try:
        focused_in_textbox = page.evaluate(
            "() => { const a = document.activeElement; "
            "return !!a && (a.getAttribute('role') === 'textbox' || a.isContentEditable); }"
        )
    except Exception:
        focused_in_textbox = False

    if not focused_in_textbox:
        print(f"      ⚠️ [{lead_name}] textbox is not the active element — forcing focus via JS")
        try:
            textbox.evaluate("el => el.focus()")
            _pause(0.3, 0.5)
        except Exception:
            pass

    # ── 2. Record baseline message count ──────────────────────────
    before_count = _count_thread_messages(page)

    # ── 3. Type the message (humanised) ───────────────────────────
    print(f"      Typing message ({len(message_text)} chars)...")
    try:
        for ch in message_text:
            page.keyboard.type(ch, delay=0)
            if random.random() < 0.08:
                time.sleep(random.uniform(0.04, 0.12))
    except Exception as e:
        print(f"      ✗ [{lead_name}] typing failed: {str(e)[:100]}")
        return "FAILED_TYPING"

    # HARD CHECK: did typing actually land in the textbox?
    # If the textbox is empty after typing, focus went to void — we MUST NOT
    # click Send because (a) nothing will send in this thread, OR (b) the
    # text went into a different open overlay. Either way: abort, don't send.
    try:
        typed_ok = page.evaluate(
            "() => { const a = document.activeElement; "
            "return a && (a.innerText || '').trim().length > 0; }"
        )
    except Exception:
        typed_ok = True  # can't tell → assume OK

    if not typed_ok:
        print(f"      🚫 [{lead_name}] textbox is EMPTY after typing — focus lost, aborting send")
        _dump_overlay_diagnostic(page, lead_name, "typing_void")
        return "FAILED_TYPING_VOID"

    _pause(1.0, 2.0)

    # ── 4. Click Send button (preferred over Ctrl+Enter) ──────────
    send_btn = _find_send_button(page)
    send_method_used = None
    if send_btn:
        try:
            send_btn.click(timeout=5000)
            send_method_used = "button_click"
            print(f"      Clicked Send button.")
        except Exception as e:
            print(f"      Send button click failed ({str(e)[:80]}), trying JS click...")
            try:
                send_btn.evaluate("el => el.click()")
                send_method_used = "button_js_click"
            except Exception:
                send_method_used = None

    if not send_method_used:
        # Fallback: Ctrl+Enter (original behaviour — only if no Send button found)
        print(f"      No Send button found — using Ctrl+Enter fallback")
        try:
            page.keyboard.press("Control+Enter")
            send_method_used = "ctrl_enter"
        except Exception as e:
            print(f"      ✗ [{lead_name}] Ctrl+Enter failed: {str(e)[:100]}")
            return "FAILED_SEND_KEY"

    # ── 5. Verify the message actually went through ───────────────
    # Only accept STRONG signals — a new rendered message in the thread.
    # We removed the "textbox_cleared" fallback because it false-fired when
    # focus was lost and the textbox was empty to begin with.
    deadline = time.time() + verify_timeout_s
    snippet = (message_text or "")[:40].strip()
    success_signal = None
    while time.time() < deadline:
        # Signal A: thread message count increased (strongest)
        after_count = _count_thread_messages(page)
        if after_count > before_count:
            success_signal = f"message_count {before_count}→{after_count}"
            break

        # Signal B: a rendered element in the thread contains our text
        if snippet and len(snippet) >= 10:
            try:
                # Scope to dialog/overlay — don't match sidebar or page text
                appears = page.locator(
                    f'[role="dialog"] :text("{snippet}"), '
                    f'.msg-s-message-list__event :text("{snippet}")'
                ).count() > 0
                if appears:
                    success_signal = "text_visible_in_thread"
                    break
            except Exception:
                pass

        time.sleep(0.5)

    if success_signal:
        print(f"      ✓ [{lead_name}] message send verified ({send_method_used}, signal={success_signal})")
        return "SENT"
    else:
        print(f"      ✗ [{lead_name}] NO verification signal within {verify_timeout_s}s — treating as failed")
        return "FAILED_NO_VERIFICATION"
