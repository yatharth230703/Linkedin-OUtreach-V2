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


def _highlight(page, element, color="red", label="", duration_ms=1500):
    """Flash a colored border + label on an element for visual debugging."""
    try:
        element.evaluate(f"""(el) => {{
            el.style.outline = '3px solid {color}';
            el.style.outlineOffset = '2px';
            const lbl = document.createElement('div');
            lbl.textContent = '{label}';
            lbl.style.cssText = 'position:fixed;top:0;left:0;background:{color};color:white;' +
                'padding:4px 12px;font-size:14px;font-weight:bold;z-index:999999;border-radius:4px;';
            const r = el.getBoundingClientRect();
            lbl.style.top = Math.max(0, r.top - 28) + 'px';
            lbl.style.left = r.left + 'px';
            document.body.appendChild(lbl);
            setTimeout(() => {{ el.style.outline = ''; lbl.remove(); }}, {duration_ms});
        }}""")
    except Exception:
        pass


def _highlight_in_shadow(page, js_selector_code, color="red", label=""):
    """Highlight an element found via shadow DOM JS."""
    try:
        page.evaluate(f"""
        () => {{
            const host = document.querySelector('#interop-outlet');
            if (!host || !host.shadowRoot) return;
            const el = {js_selector_code};
            if (!el) return;
            el.style.outline = '3px solid {color}';
            el.style.outlineOffset = '2px';
            setTimeout(() => {{ el.style.outline = ''; }}, 1500);
        }}
        """)
    except Exception:
        pass


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

    # ── 0. JS card walk — PRIMARY approach for all names ──────────────────
    # Finds the card container with the lead's name, scrolls it into view,
    # highlights it (green = card, yellow = button), returns the Message
    # button. Works for ALL names including "A. Khan", hyphens, unicode.
    try:
        handle = page.evaluate_handle("""
        (nameAndHeadline) => {
            const [name, headline] = nameAndHeadline;
            const lower = name.toLowerCase();
            const hlLower = (headline || '').toLowerCase();
            const links = document.querySelectorAll('a[href*="/in/"]');
            for (const link of links) {
                const linkText = (link.innerText || '').split('\\n')[0].trim().toLowerCase();
                if (linkText !== lower && !linkText.includes(lower)) continue;

                // Walk up to card container
                let card = link;
                for (let d = 0; d < 8; d++) {
                    card = card.parentElement;
                    if (!card) break;
                    if (card.tagName === 'LI' || card.tagName === 'ARTICLE') break;
                    if (card.children.length >= 3) break;
                }
                if (!card) continue;

                // If headline provided, verify the card contains it (disambiguation)
                if (hlLower && hlLower.length > 10) {
                    const cardText = (card.innerText || '').toLowerCase();
                    const hlSnippet = hlLower.substring(0, 30);
                    if (!cardText.includes(hlSnippet)) continue;
                }

                // Scroll card into view
                card.scrollIntoView({ behavior: 'smooth', block: 'center' });

                // Find Message button inside THIS card
                const btns = card.querySelectorAll('a, button');
                for (const btn of btns) {
                    const label = (btn.getAttribute('aria-label') || '').toLowerCase();
                    const text = (btn.innerText || '').toLowerCase().trim();
                    if ((label.includes('message') || text === 'message' ||
                         label.includes('nachricht') || text === 'nachricht') &&
                        btn.getBoundingClientRect().width > 0) {
                        card.style.outline = '3px solid lime';
                        card.style.outlineOffset = '4px';
                        btn.style.outline = '3px solid yellow';
                        setTimeout(() => { card.style.outline = ''; btn.style.outline = ''; }, 2500);
                        return btn;
                    }
                }
            }
            return null;
        }
        """, [lead_name, lead_headline or ""])
        if handle:
            elem = handle.as_element()
            if elem:
                print(f"      [{ident}] found card + scrolled + Message button for '{lead_name}'")
                _pause(0.8, 1.2)  # let scroll settle
                return elem
    except Exception as e:
        print(f"      [{ident}] JS card walk error: {e}")

    # ── 1. Card scoped by name + headline snippet (STRONG disambiguation) ──
    if snippet:
        try:
            # Iterate candidate cards that visibly contain the name.
            # Use exact=False to handle names with special chars (periods,
            # hyphens, middle initials like "Ammar A. Khan").
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
                    _highlight(page, msg.first, color="green", label=f"MSG BTN: {lead_name}")
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
        _highlight(page, el, color="orange", label=f"MSG BTN (aria-label): {lead_name}")
        return el

    # ── 4. JS-based card walk — works for ALL names including special chars.
    # This is the PRIMARY approach: find the card with the lead's name,
    # scroll it into view, then return the Message button inside it.
    try:
        handle = page.evaluate_handle("""
        (name) => {
            const lower = name.toLowerCase();
            // Find all profile links on the connections page
            const links = document.querySelectorAll('a[href*="/in/"]');
            for (const link of links) {
                const linkText = (link.innerText || '').split('\\n')[0].trim().toLowerCase();
                if (linkText !== lower && !linkText.includes(lower)) continue;

                // Walk up to find the card container
                let card = link;
                for (let d = 0; d < 8; d++) {
                    card = card.parentElement;
                    if (!card) break;
                    if (card.tagName === 'LI' || card.tagName === 'ARTICLE') break;
                    // Stop at divs that look like a card (have multiple children)
                    if (card.children.length >= 3) break;
                }
                if (!card) continue;

                // SCROLL the card into view first
                card.scrollIntoView({ behavior: 'smooth', block: 'center' });

                // Find the Message button INSIDE this specific card
                const btns = card.querySelectorAll('a, button');
                for (const btn of btns) {
                    const label = (btn.getAttribute('aria-label') || '').toLowerCase();
                    const text = (btn.innerText || '').toLowerCase().trim();
                    if ((label.includes('message') || text === 'message' ||
                         label.includes('nachricht') || text === 'nachricht') &&
                        btn.getBoundingClientRect().width > 0) {
                        // Highlight the card and button for debug visibility
                        card.style.outline = '3px solid lime';
                        card.style.outlineOffset = '4px';
                        btn.style.outline = '3px solid yellow';
                        setTimeout(() => {
                            card.style.outline = '';
                            btn.style.outline = '';
                        }, 2000);
                        return btn;
                    }
                }
            }
            return null;
        }
        """, lead_name)
        if handle:
            elem = handle.as_element()
            if elem:
                print(f"      [{ident}] found card + Message button for '{lead_name}'")
                _pause(0.5, 1.0)  # let scroll settle
                return elem
    except Exception as e:
        print(f"      [{ident}] JS card walk error: {e}")

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
        result = page.evaluate(js, lower_name)
        if not result:
            # Debug: dump what the shadow DOM actually contains
            try:
                debug_info = page.evaluate("""
                () => {
                    const info = { shadowHostExists: false, dialogCount: 0, dialogTexts: [] };
                    const host = document.querySelector('#interop-outlet');
                    if (host && host.shadowRoot) {
                        info.shadowHostExists = true;
                        const dialogs = host.shadowRoot.querySelectorAll('[role="dialog"]');
                        info.dialogCount = dialogs.length;
                        for (const d of dialogs) {
                            const min = d.getAttribute('data-msg-overlay-conversation-bubble-is-minimized');
                            const text = (d.innerText || '').substring(0, 200);
                            info.dialogTexts.push({ minimized: min, text: text });
                        }
                    }
                    // Also check light DOM
                    const lightDialogs = document.querySelectorAll('[role="dialog"]');
                    info.lightDialogCount = lightDialogs.length;
                    return info;
                }
                """)
                print(f"      [verify-debug] shadow={debug_info.get('shadowHostExists')}, "
                      f"dialogs={debug_info.get('dialogCount')}, "
                      f"light_dialogs={debug_info.get('lightDialogCount')}")
                for i, d in enumerate(debug_info.get('dialogTexts', [])):
                    print(f"      [verify-debug] dialog[{i}] minimized={d.get('minimized')} text={d.get('text', '')[:100]!r}")
            except Exception as e:
                print(f"      [verify-debug] could not inspect: {e}")
        return bool(result)
    except Exception as e:
        print(f"      [verify-debug] evaluate failed: {e}")
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

    # 2. Close ALL conversation bubbles + draft composes via shadow DOM
    try:
        closed = page.evaluate("""
        () => {
            const report = { found: 0, clicked: 0, labels: [] };
            const closeIn = (root) => {
                // Scan ALL buttons and log what we find
                root.querySelectorAll('button').forEach(btn => {
                    const label = (btn.getAttribute('aria-label') || '').toLowerCase();
                    const text = (btn.innerText || btn.textContent || '').toLowerCase().trim();
                    const r = btn.getBoundingClientRect();
                    const visible = r.width > 0 && r.height > 0;

                    // Click ANY button that looks like close/minimize/discard
                    if (visible && (
                        label.includes('close') || label.includes('minimize') ||
                        label.includes('discard') || label.includes('schließen') ||
                        label.includes('minimieren') || label.includes('verwerfen') ||
                        text.includes('close') || text.includes('discard')
                    )) {
                        report.found++;
                        report.labels.push(label || text);
                        try { btn.click(); report.clicked++; } catch {}
                    }
                });
            };
            const host = document.querySelector('#interop-outlet');
            if (host && host.shadowRoot) closeIn(host.shadowRoot);
            closeIn(document);
            return report;
        }
        """)
        if closed:
            print(f"      [close-debug] found={closed.get('found',0)} clicked={closed.get('clicked',0)} labels={closed.get('labels',[])[: 5]}")
    except Exception as e:
        print(f"      [close-debug] error: {e}")
    _pause(1.0, 1.5)

    # If a "discard" confirmation dialog appeared, confirm it
    try:
        page.evaluate("""
        () => {
            const closeIn = (root) => {
                root.querySelectorAll('button').forEach(btn => {
                    const text = (btn.innerText || '').toLowerCase().trim();
                    if (text === 'discard' || text === 'verwerfen') {
                        const r = btn.getBoundingClientRect();
                        if (r.width > 0 && r.height > 0) {
                            try { btn.click(); } catch {}
                        }
                    }
                });
            };
            const host = document.querySelector('#interop-outlet');
            if (host && host.shadowRoot) closeIn(host.shadowRoot);
            closeIn(document);
        }
        """)
    except Exception:
        pass
    _pause(0.5, 0.8)

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


def close_and_verify(page, max_attempts=3, page_url_fallback=None):
    """Close ALL message overlays and VERIFY they're gone.

    This is the strict version called BETWEEN leads to prevent message leakage.
    Checks shadow DOM dialog count after each attempt. If dialogs persist after
    max_attempts, refreshes the page as nuclear option.

    Args:
        page: Playwright Page
        max_attempts: number of close cycles before giving up
        page_url_fallback: URL to navigate to if close fails (nuclear refresh)
    """
    for attempt in range(max_attempts):
        close_all_message_overlays(page)
        _pause(0.5, 0.8)

        # Verify: count non-minimized dialogs in shadow DOM
        try:
            open_count = page.evaluate("""
            () => {
                let count = 0;
                const host = document.querySelector('#interop-outlet');
                if (host && host.shadowRoot) {
                    host.shadowRoot.querySelectorAll('[role="dialog"]').forEach(dlg => {
                        const min = dlg.getAttribute('data-msg-overlay-conversation-bubble-is-minimized');
                        if (min !== 'true') {
                            const r = dlg.getBoundingClientRect();
                            if (r.width > 0 && r.height > 0) count++;
                        }
                    });
                }
                return count;
            }
            """)
        except Exception:
            open_count = 0

        if open_count == 0:
            print(f"      [close-verify] ✓ all dialogs closed (attempt {attempt + 1})")
            return True
        else:
            print(f"      [close-verify] {open_count} dialog(s) still open (attempt {attempt + 1}/{max_attempts})")

        # Try harder: also handle discard confirmation
        try:
            page.evaluate("""
            () => {
                const tryRoot = (root) => {
                    root.querySelectorAll('button').forEach(btn => {
                        const t = (btn.innerText || '').toLowerCase().trim();
                        const l = (btn.getAttribute('aria-label') || '').toLowerCase();
                        if (t === 'discard' || t === 'verwerfen' ||
                            l.includes('close') || l.includes('discard') ||
                            l.includes('schließen')) {
                            const r = btn.getBoundingClientRect();
                            if (r.width > 0 && r.height > 0) {
                                try { btn.click(); } catch {}
                            }
                        }
                    });
                };
                const host = document.querySelector('#interop-outlet');
                if (host && host.shadowRoot) tryRoot(host.shadowRoot);
                tryRoot(document);
            }
            """)
        except Exception:
            pass
        _pause(0.5, 0.8)

    # Nuclear option: refresh the page to kill all overlays
    if page_url_fallback:
        print(f"      [close-verify] ⚠️ dialogs won't close — refreshing page")
        try:
            page.goto(page_url_fallback, wait_until="domcontentloaded", timeout=30000)
            _pause(3, 5)
        except Exception:
            pass
        return True
    else:
        print(f"      [close-verify] ⚠️ dialogs still open after {max_attempts} attempts — proceeding anyway")
        return False


def _setup_compose_recipient(page, lead_name, timeout_s=10):
    """Handle the 'New message' compose dialog: clear stale recipients, type
    the target name, and select them from the autocomplete dropdown.

    LinkedIn opens a 'New message' compose when clicking Message for someone
    you haven't messaged yet. It may have a stale recipient chip from a
    previous draft. This function cleans up and sets the correct recipient.

    Returns True if the correct recipient was selected, False otherwise.
    """
    try:
        # Step 1: Find and clear any existing recipient chips (the "×" buttons)
        cleared = page.evaluate("""
        () => {
            let cleared = 0;
            const checkRoot = (root) => {
                // Find recipient chip remove buttons ("Remove Shashvat Singhal")
                root.querySelectorAll('button').forEach(btn => {
                    const label = (btn.getAttribute('aria-label') || '').toLowerCase();
                    if (label.includes('remove') && !label.includes('formatting')) {
                        const r = btn.getBoundingClientRect();
                        if (r.width > 0 && r.height > 0) {
                            try { btn.click(); cleared++; } catch {}
                        }
                    }
                });
            };
            const host = document.querySelector('#interop-outlet');
            if (host && host.shadowRoot) checkRoot(host.shadowRoot);
            checkRoot(document);
            return cleared;
        }
        """)
        if cleared:
            print(f"      Cleared {cleared} stale recipient chip(s)")
        _pause(0.5, 1.0)

        # Verify ALL chips are gone — repeat until none remain
        for _clear_attempt in range(5):
            remaining = page.evaluate("""
            () => {
                let count = 0;
                const checkRoot = (root) => {
                    root.querySelectorAll('button').forEach(btn => {
                        const label = (btn.getAttribute('aria-label') || '').toLowerCase();
                        if (label.includes('remove') && !label.includes('formatting')) {
                            const r = btn.getBoundingClientRect();
                            if (r.width > 0 && r.height > 0) {
                                try { btn.click(); count++; } catch {}
                            }
                        }
                    });
                };
                const host = document.querySelector('#interop-outlet');
                if (host && host.shadowRoot) checkRoot(host.shadowRoot);
                checkRoot(document);
                return count;
            }
            """)
            if remaining == 0:
                break
            print(f"      Cleared {remaining} more stale chip(s)")
            _pause(0.3, 0.5)

        # Step 2: Find the recipient input field and type the target name
        # Highlight for visual debugging
        # The compose dialog has an input with placeholder like "Type a name"
        input_handle = page.evaluate_handle("""
        () => {
            const findIn = (root) => {
                // The recipient search input
                const sels = [
                    'input[aria-label*="message recipients" i]',
                    'input[aria-label*="recipients" i]',
                    'input[aria-label*="name" i][type="text"]',
                    'input[placeholder*="name" i]',
                    'input[placeholder*="recipient" i]',
                    'input[role="combobox"]',
                ];
                for (const sel of sels) {
                    for (const el of root.querySelectorAll(sel)) {
                        const r = el.getBoundingClientRect();
                        if (r.width > 0 && r.height > 0) return el;
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
        input_el = input_handle.as_element() if input_handle else None
        if not input_el:
            print(f"      ⚠️ recipient input not found in compose dialog")
            return False

        _highlight(page, input_el, color="blue", label="RECIPIENT INPUT")
        # Click to focus, then type the name using keyboard
        # (ElementHandle.fill/type can fail across shadow DOM boundaries)
        try:
            input_el.click(timeout=3000)
        except Exception:
            try:
                input_el.evaluate("el => el.focus()")
            except Exception:
                pass
        _pause(0.3, 0.5)

        # Clear existing text via keyboard (Ctrl+A, Delete), then type name
        page.keyboard.press("Control+a")
        page.keyboard.press("Delete")
        _pause(0.2, 0.3)
        page.keyboard.type(lead_name, delay=50)
        _pause(2.0, 3.0)  # wait for autocomplete dropdown

        # Step 3: Select the correct person from the autocomplete dropdown
        # The dropdown items are in shadow DOM, contain the lead's name
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            selected = page.evaluate("""
            (targetName) => {
                const lower = targetName.toLowerCase();
                const tryRoot = (root) => {
                    const sels = [
                        '[role="option"]',
                        '[role="listbox"] > *',
                        'li',
                    ];
                    let bestMatch = null;
                    for (const sel of sels) {
                        for (const el of root.querySelectorAll(sel)) {
                            const t = (el.innerText || '').toLowerCase();
                            const r = el.getBoundingClientRect();
                            if (!t.includes(lower) || r.width <= 0 || r.height <= 0) continue;

                            // SKIP group conversations — they contain phrases like
                            // "X people in this conversation", multiple names with
                            // "and", or "group" indicators
                            if (t.includes('people in this conversation') ||
                                t.includes('personen in dieser unterhaltung') ||
                                t.includes(' and you') ||
                                t.includes(' und du') ||
                                t.includes('group')) {
                                continue;
                            }

                            // Prefer EXACT name match over partial/substring
                            if (t.trim() === lower || t.startsWith(lower + '\\n')) {
                                // Best possible match — click immediately
                                try { el.click(); return 'exact'; } catch {}
                            }
                            // Store as candidate if no exact match yet
                            if (!bestMatch) bestMatch = el;
                        }
                    }
                    // Fall back to best non-group candidate
                    if (bestMatch) {
                        try { bestMatch.click(); return 'partial'; } catch {}
                    }
                    return null;
                };
                const host = document.querySelector('#interop-outlet');
                if (host && host.shadowRoot) {
                    const r = tryRoot(host.shadowRoot);
                    if (r) return r;
                }
                return tryRoot(document);
            }
            """, lead_name)
            if selected:
                print(f"      ✓ Selected '{lead_name}' from autocomplete ({selected} match)")
                _pause(1.0, 1.5)

                # Verify: exactly 1 recipient chip, matching our target name
                chip_check = page.evaluate("""
                (targetName) => {
                    const lower = targetName.toLowerCase();
                    const checkRoot = (root) => {
                        let chips = [];
                        root.querySelectorAll('button').forEach(btn => {
                            const label = (btn.getAttribute('aria-label') || '').toLowerCase();
                            if (label.includes('remove') && !label.includes('formatting')) {
                                const r = btn.getBoundingClientRect();
                                if (r.width > 0 && r.height > 0) chips.push(label);
                            }
                        });
                        return chips;
                    };
                    const chips = [];
                    const host = document.querySelector('#interop-outlet');
                    if (host && host.shadowRoot) chips.push(...checkRoot(host.shadowRoot));
                    chips.push(...checkRoot(document));
                    return { count: chips.length, labels: chips.slice(0, 5),
                             hasTarget: chips.some(c => c.includes(lower)) };
                }
                """, lead_name)
                chip_count = chip_check.get('count', 0) if chip_check else 0
                has_target = chip_check.get('hasTarget', False) if chip_check else False
                print(f"      [chip-check] count={chip_count}, hasTarget={has_target}, labels={chip_check.get('labels', [])[:3]}")

                if chip_count > 1:
                    print(f"      ⚠️ Multiple recipient chips ({chip_count}) — clearing extras to prevent group message")
                    # Clear all chips except the target
                    page.evaluate("""
                    (targetName) => {
                        const lower = targetName.toLowerCase();
                        const clearIn = (root) => {
                            root.querySelectorAll('button').forEach(btn => {
                                const label = (btn.getAttribute('aria-label') || '').toLowerCase();
                                if (label.includes('remove') && !label.includes('formatting') &&
                                    !label.includes(lower)) {
                                    const r = btn.getBoundingClientRect();
                                    if (r.width > 0 && r.height > 0) {
                                        try { btn.click(); } catch {}
                                    }
                                }
                            });
                        };
                        const host = document.querySelector('#interop-outlet');
                        if (host && host.shadowRoot) clearIn(host.shadowRoot);
                        clearIn(document);
                    }
                    """, lead_name)
                    _pause(0.5, 0.8)

                return True
            time.sleep(0.5)

        # Debug: dump what's visible in the dropdown area
        try:
            dropdown_info = page.evaluate("""
            () => {
                const info = { options: [] };
                const checkRoot = (root) => {
                    // Check for listbox, options, or any dropdown-like elements
                    root.querySelectorAll('[role="option"], [role="listbox"] > *, li').forEach(el => {
                        const t = (el.innerText || '').trim().substring(0, 100);
                        const r = el.getBoundingClientRect();
                        if (t && r.width > 0) info.options.push(t);
                    });
                };
                const host = document.querySelector('#interop-outlet');
                if (host && host.shadowRoot) checkRoot(host.shadowRoot);
                checkRoot(document);
                return info;
            }
            """)
            print(f"      [autocomplete-debug] visible options: {dropdown_info.get('options', [])[:5]}")
        except Exception:
            pass
        print(f"      ⚠️ '{lead_name}' not found in autocomplete dropdown")
        # Try pressing Enter as last resort (selects first autocomplete result)
        try:
            page.keyboard.press("Enter")
            _pause(1.0, 1.5)
            # Check if it worked
            if verify_recipient_in_overlay(page, lead_name):
                print(f"      ✓ Selected '{lead_name}' via Enter key fallback")
                return True
        except Exception:
            pass
        return False

    except Exception as e:
        print(f"      ⚠️ compose recipient setup failed: {e}")
        return False


def check_for_reply_robust(page, lead_name):
    """Check if the lead has replied in the CURRENTLY OPEN conversation.

    XPath-free, class-free approach. Scans the active dialog's text content
    for messages that appear to be FROM the lead (not from "You" / the bot).

    LinkedIn conversation threads show messages with sender names. If we find
    the lead's name as a sender of any message, they've replied.

    Returns True if reply detected, False otherwise.
    """
    lower_name = (lead_name or "").strip().lower()
    if not lower_name:
        return False

    try:
        result = page.evaluate("""
        (lowerName) => {
            const checkRoot = (root) => {
                // Find active (non-minimized) conversation dialog
                const dialogs = root.querySelectorAll('[role="dialog"]');
                for (const dlg of dialogs) {
                    const min = dlg.getAttribute('data-msg-overlay-conversation-bubble-is-minimized');
                    if (min === 'true') continue;

                    const fullText = (dlg.innerText || '').toLowerCase();

                    // Quick check: does the dialog text contain the lead's name at all?
                    if (!fullText.includes(lowerName)) continue;

                    // Scan for message-like patterns. LinkedIn renders messages as:
                    //   "SenderName\nTimestamp\nMessage text"
                    // or with profile links containing the sender's name.
                    //
                    // Strategy: find all links with /in/ href (profile links of senders),
                    // check if any match the lead's name. Profile links in messages
                    // are sender attribution — if the lead's name appears as a link,
                    // they sent at least one message.
                    const profileLinks = dlg.querySelectorAll('a[href*="/in/"]');
                    for (const link of profileLinks) {
                        const linkText = (link.innerText || link.textContent || '').toLowerCase().trim();
                        if (linkText.includes(lowerName) || lowerName.includes(linkText)) {
                            // Verify this isn't our OWN profile link (which would be in the header)
                            // Check if there's message content NEAR this link
                            const parent = link.parentElement;
                            if (parent) {
                                const parentText = (parent.innerText || '').toLowerCase();
                                // Skip if this is just the conversation header
                                if (parentText.includes('open the options') ||
                                    parentText.includes('optionen öffnen')) continue;
                                return { replied: true, sender: linkText, source: 'profile_link' };
                            }
                        }
                    }

                    // Fallback: check for "Name:" pattern in the text
                    // (some LinkedIn layouts show "Name: message text")
                    const nameColonPattern = lowerName + ':';
                    if (fullText.includes(nameColonPattern)) {
                        return { replied: true, sender: lowerName, source: 'name_colon_pattern' };
                    }
                }
                return { replied: false };
            };

            const host = document.querySelector('#interop-outlet');
            if (host && host.shadowRoot) {
                const r = checkRoot(host.shadowRoot);
                if (r.replied) return r;
            }
            return checkRoot(document);
        }
        """, lower_name)

        if result and result.get('replied'):
            print(f"      🔔 REPLY DETECTED from {lead_name} (source: {result.get('source')})")
            return True
        return False
    except Exception as e:
        print(f"      ⚠️ Reply check error: {e}")
        return False


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

    # ── 1. Focus the message body textbox ────────────────────────
    # Shadow DOM elements can't be reliably focused via Playwright's
    # ElementHandle.click() or JS el.focus() across shadow boundaries.
    # Instead: use Tab key to navigate from the recipient field (which
    # has focus after autocomplete selection) to the message body.
    # Also try direct click/focus as fallback.
    textbox = _find_message_textbox(page)

    # Strategy A: Tab into the textbox from current focus position
    for tab_attempt in range(5):
        page.keyboard.press("Tab")
        _pause(0.2, 0.3)
        try:
            focused_ok = page.evaluate("""
            () => {
                const a = document.activeElement;
                if (a && a.isContentEditable) return true;
                // Check shadow DOM — activeElement might be the shadow host
                const host = document.querySelector('#interop-outlet');
                if (host && host.shadowRoot) {
                    // Shadow root doesn't have activeElement in all browsers,
                    // but Chromium supports it
                    const sa = host.shadowRoot.activeElement;
                    if (sa && sa.isContentEditable) return true;
                }
                return false;
            }
            """)
            if focused_ok:
                print(f"      Focused message textbox via Tab (attempt {tab_attempt + 1})")
                _highlight_in_shadow(page,
                    "host.shadowRoot.activeElement",
                    color="cyan", label="TEXTBOX (Tab-focused)")
                break
        except Exception:
            pass
    else:
        # Strategy B: Direct click/focus on found textbox element
        if textbox:
            try:
                textbox.click(timeout=3000)
                _pause(0.3, 0.5)
            except Exception:
                try:
                    textbox.evaluate("el => { el.focus(); el.click(); }")
                except Exception:
                    pass

        # Final check
        try:
            focused_ok = page.evaluate(
                "() => { const a = document.activeElement; "
                "return !!a && a.isContentEditable; }"
            )
        except Exception:
            focused_ok = False

        if not focused_ok:
            print(f"      ⚠️ [{lead_name}] could not focus message textbox")
            if not textbox:
                print(f"      ✗ [{lead_name}] textbox element not found either")
                _dump_overlay_diagnostic(page, lead_name, "no_textbox")
                return "FAILED_NO_TEXTBOX"

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
    # Shadow DOM complication: document.activeElement is the shadow HOST
    # (#interop-outlet), not the contenteditable inside. We must check
    # shadowRoot.activeElement to see if text landed there.
    try:
        typed_ok = page.evaluate("""
        () => {
            // Check light DOM active element first
            const a = document.activeElement;
            if (a && a.isContentEditable && (a.innerText || '').trim().length > 0) return true;
            // Check shadow DOM — the real focused element is inside the shadow root
            const host = document.querySelector('#interop-outlet');
            if (host && host.shadowRoot) {
                const sa = host.shadowRoot.activeElement;
                if (sa && sa.isContentEditable && (sa.innerText || '').trim().length > 0) return true;
                // Walk deeper — activeElement might be a wrapper, check contenteditable children
                if (sa) {
                    const ce = sa.querySelector && sa.querySelector('[contenteditable="true"]');
                    if (ce && (ce.innerText || '').trim().length > 0) return true;
                }
                // Last resort: find any visible contenteditable with text inside the dialog
                const dialogs = host.shadowRoot.querySelectorAll('[role="dialog"]');
                for (const dlg of dialogs) {
                    const min = dlg.getAttribute('data-msg-overlay-conversation-bubble-is-minimized');
                    if (min === 'true') continue;
                    const ces = dlg.querySelectorAll('[contenteditable="true"]');
                    for (const ce of ces) {
                        if ((ce.innerText || '').trim().length > 0) return true;
                    }
                }
            }
            return false;
        }
        """)
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
        _highlight(page, send_btn, color="red", label="SEND BUTTON")
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
