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
    """Find the open message composer's textbox.

    LinkedIn's message composer is a contenteditable div (not <textarea>).
    Stable signals:
      - role="textbox"
      - contenteditable="true"
      - aria-label containing "message" / "write"
    """
    return _visible_first(
        page,
        '[role="textbox"][aria-label*="message" i]',
        '[role="textbox"][aria-label*="nachricht" i]',
        '[role="textbox"][contenteditable="true"]',
        'div[contenteditable="true"][aria-label*="message" i]',
        'div[contenteditable="true"][aria-label*="write" i]',
        'div[contenteditable="true"][aria-label*="nachricht" i]',
        # Last resort: any contenteditable inside a visible dialog/overlay
        '[role="dialog"] div[contenteditable="true"]',
        'form div[contenteditable="true"]',
    )


def _find_send_button(page):
    """Find the Send button for the open message composer.

    Stable signals:
      - aria-label="Send"
      - button with text "Send" (exact, to avoid "Send invitation" etc.)
      - type="submit" inside an active dialog
    """
    return _visible_first(
        page,
        'button[aria-label="Send"]',
        'button[aria-label="Senden"]',
        'button[aria-label*="Send" i]:not([aria-label*="invitation" i]):not([aria-label*="note" i])',
        # Strict text match to avoid "Send without a note", "Send invitation"
        'button:text-is("Send")',
        'button:text-is("Senden")',
        '[role="dialog"] button[type="submit"]',
    )


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
    # ── 1. Locate textbox and focus it ────────────────────────────
    textbox = _find_message_textbox(page)
    if not textbox:
        print(f"      ✗ [{lead_name}] message textbox not found — cannot send")
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

    # Quick sanity check: did any text actually land in the textbox?
    try:
        typed_ok = page.evaluate(
            "() => { const a = document.activeElement; "
            "return a && (a.innerText || '').trim().length > 0; }"
        )
    except Exception:
        typed_ok = True  # can't tell → assume OK
    if not typed_ok:
        print(f"      ⚠️ [{lead_name}] textbox appears empty after typing — focus likely lost")

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
    # Signals of success:
    #   a) thread message count increased
    #   b) textbox is empty (LinkedIn clears it on successful send)
    #   c) a fresh element contains (part of) our message text
    deadline = time.time() + verify_timeout_s
    snippet = (message_text or "")[:40].strip()
    success_signal = None
    while time.time() < deadline:
        after_count = _count_thread_messages(page)
        if after_count > before_count:
            success_signal = f"message_count {before_count}→{after_count}"
            break

        # Textbox empty?
        try:
            empty = page.evaluate(
                "() => { const a = document.activeElement; "
                "if (!a) return false; return (a.innerText || '').trim().length === 0; }"
            )
        except Exception:
            empty = False
        if empty:
            success_signal = "textbox_cleared"
            break

        # Our text appears in the thread?
        if snippet and len(snippet) >= 5:
            try:
                appears = page.locator(f':text("{snippet}")').count() > 0
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
