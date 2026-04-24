# LinkedIn Bot Robustness Guide

## 1. Session Protection (Don't Get Logged Out)

### Current State
The bot creates separate Playwright browser sessions for each of the 3 bots (connection, message, followup). Each session injects cookies and navigates LinkedIn. LinkedIn's security detects multiple rapid session creations from a proxy IP and may revoke ALL sessions globally — including your personal MacBook browser.

### Implemented Mitigations
- **Browser profile reuse**: The first bot creates a Chromium profile (`user_data_<account>/`). Subsequent bots in the same campaign REUSE that profile without wiping, so LinkedIn sees 1 continuous session, not 3 separate "new device" events.
- **Cookie persistence**: After every successful login, cookies are saved to `cookies_<account>.json`. Next run loads these instead of doing a fresh password login.
- **Proxy session persistence**: The iproyal sticky session ID is saved to `proxy_session_<account>.txt`. Same session = same exit IP = cookies stay valid (no IP-cookie mismatch).

### Remaining Risks
- **Concurrent usage**: If you browse LinkedIn on your MacBook WHILE the bot runs on the VM, LinkedIn sees the same account from 2 IPs simultaneously. This can trigger session revocation.
- **Activity volume**: 3 bots running sequentially with aggressive page navigation (scraping connections, clicking Message buttons, sending messages) generates unusual traffic patterns.
- **Fingerprint mismatch**: The bot's headless Chromium has a different TLS fingerprint (JA3) than real Chrome. LinkedIn's security vendors (Arkose Labs) can detect this at the network level.

### Recommendations
| Priority | Action | Impact |
|----------|--------|--------|
| HIGH | Run the bot ONLY when you're NOT actively using LinkedIn (e.g., overnight, early morning) | Eliminates concurrent-session detection |
| HIGH | Add 30-60s of random feed browsing at the start of each bot before any automation actions | Establishes "normal user" behavior pattern before bot pattern |
| MEDIUM | Increase break time between the 3 bots from 5-15 min to 20-30 min | Reduces session-creation velocity |
| MEDIUM | Reduce daily limits (connections, messages, follow-ups) to more conservative numbers (5-8 instead of 12-18) | Stays within LinkedIn's unwritten rate limits |
| LOW | Migrate to a single-session orchestrator where one browser instance runs all 3 bots sequentially (requires refactoring `orchestrator.py` from subprocess-per-bot to function-call-per-bot) | 1 session instead of 3, eliminates "multiple device" detection entirely |
| ASPIRATIONAL | Use a stealth browser service (Multilogin, GoLogin, Bright Data Scraping Browser) instead of raw Playwright Chromium | Pre-warmed browser profiles with real TLS fingerprints, undetectable by LinkedIn's anti-bot vendors |

---

## 2. Multi-Region Proxy Management

### Current State
Proxy geo-targeting is per-account in `get_proxy_password_for_account()`:
- `yatharth_bisht` → `_country-in_city-delhi` (India)
- `maurice` / `leon` → `_country-de_city-hamburg` (Germany)

Browser timezone is matched in `setup_playwright_browser()`:
- `yatharth_bisht` → `Asia/Kolkata`
- `maurice` / `leon` → `Europe/Berlin`

### How to Add a New Region/Client
1. **Add geo suffix** in `login_credentials.py` → `get_proxy_password_for_account()`:
   ```python
   elif slug == "new_client":
       geo = "_country-us_city-newyork"
   ```
2. **Add timezone** in `setup_playwright_browser()`:
   ```python
   elif slug == "new_client":
       tz_id = "America/New_York"
   ```
3. **Add credentials** to Google Secret Manager:
   - `NEWCLIENT_LINKEDIN_EMAIL`
   - `NEWCLIENT_LINKEDIN_PASSWORD`
4. **Add to `run_container.sh`** — fetch secrets and pass as env vars
5. **Add to `entrypoint.sh`** — include in the env-var regex for cron

### Proxy Health Monitoring
- `_proxy_diag.py` in the repo root tests proxy connectivity (run manually)
- `_check_page_is_linkedin()` detects FortiGate/Palo Alto firewall blocks at runtime
- `SessionFailureError` is raised on `ERR_TOO_MANY_REDIRECTS` / `ERR_TUNNEL_CONNECTION_FAILED` — bot aborts and preserves leads for retry
- iproyal bandwidth quota exhaustion returns HTTP 402 — detected by the proxy diagnostic tool

### Known Proxy Issues
| Issue | Cause | Detection | Mitigation |
|-------|-------|-----------|------------|
| FortiGate "Application Blocked" | Residential exit IP is behind a corporate firewall | `_check_page_is_linkedin()` detects it | `SessionFailureError` → proxy session regenerates on next run |
| ERR_TUNNEL_CONNECTION_FAILED | iproyal bandwidth exhausted (402) or exit node died | Detected at navigation time | Top up iproyal dashboard; `_proxy_diag.py` for diagnosis |
| Geo mismatch (Tamil Nadu instead of Delhi) | iproyal pool scarcity for requested city | Browser timezone still matches country (India) | Acceptable — LinkedIn checks country-level, not city-level |
| Sticky session TTL expiry | iproyal rotates exit after ~10-30 min | New exit might be in same city or behind firewall | Persisted session ID means same session = same exit within TTL; across runs, TTL may expire |

---

## 3. XPath Independence Audit

### Principle
Every interaction with LinkedIn's DOM uses ONLY:
- **ARIA attributes**: `aria-label`, `role` (accessibility contract — LinkedIn can't drop these)
- **HTML standards**: `contenteditable`, `type="submit"`, `<a href>`, `<button>`
- **URL patterns**: `/in/<slug>`, `/custom-invite/`, `/messaging/compose/`
- **Visible text**: "Connect", "Message", "Send", "Pending"
- **Page title**: `"Name | LinkedIn"` (SEO contract)
- **Shadow DOM traversal**: `#interop-outlet.shadowRoot` (LinkedIn's messaging mount point)
- **Structural invariants**: "message textbox is inside conversation dialog", "name is first text in card"

### Bot-by-Bot Audit

#### Connection Bot (`msg_draft_connection_bot1.py`)
| Action | Selector Strategy | XPath-Free? |
|--------|------------------|-------------|
| Profile detection | `page.title()` → "Name \| LinkedIn" | YES |
| Profile scraping (name) | `page.title()` | YES |
| Profile scraping (headline) | JS: find heading matching title, walk siblings | YES |
| Connect button (direct) | `[href*="custom-invite/?vanityName={slug}"]` | YES |
| Connect button (More menu) | `[aria-label="More"]` → `span:text-is("Connect")` | YES |
| Pending detection | `[aria-label*="{name}"][aria-label*="Pending"]` | YES |
| Popup dismissal | `[aria-label="Dismiss"]`, hide "Try Premium" banner via JS | YES |
| Send modal | `button[aria-label="Send without a note"]` | YES |
| Verification | `[aria-label*="{name}"][aria-label*="Withdraw"]` | YES |
| Login fields | `input[autocomplete="username"]`, `get_by_label("Email or phone")`, `get_by_role("button", name="Sign in")` | YES |

#### Message Bot (`send_message.py`)
| Action | Selector Strategy | XPath-Free? |
|--------|------------------|-------------|
| Connection scraping | JS `querySelectorAll('a[href*="/in/"]')` → virtual-scroll-aware | YES |
| Card identification | JS text walk: name in link text + headline in card | YES |
| Message button finding | JS: find card with name → find `button/a` with `aria-label*="message"` inside | YES |
| Compose recipient setup | Shadow DOM: clear chips → type name → select from autocomplete (skip groups) | YES |
| Textbox focus | Tab key navigation → verify `shadowRoot.activeElement.isContentEditable` | YES |
| Send button | `button[aria-label="Send"]` inside `[role="dialog"]` in shadow root | YES |
| Send verification | Message count increase inside shadow `[role="dialog"]` | YES |
| Dialog close | Shadow-aware: click all close buttons in `#interop-outlet.shadowRoot` → verify count=0 | YES |
| Firewall detection | Check `document.body.innerText` for "FortiGate", "Application Blocked" | YES |

#### Follow-up Bot (`send_followup.py`)
| Action | Selector Strategy | XPath-Free? |
|--------|------------------|-------------|
| Connection scraping | Imported from `send_message._scrape_connections_robust` | YES |
| Reply detection (primary) | Shadow DOM: `#interop-outlet.shadowRoot` → scan message elements | PARTIAL (uses `msg-s-*` class names as primary, robust fallback as secondary) |
| Reply detection (fallback) | `check_for_reply_robust`: find `a[href*="/in/"]` sender links in `[role="dialog"]` | YES |
| All messaging actions | Same shared `robust_messaging.py` module | YES |

### Remaining Class-Name Dependencies
| File | Class Used | Risk | Mitigation |
|------|-----------|------|------------|
| `send_followup.py` (reply detection) | `.msg-s-message-list__event`, `.msg-s-event-listitem__body` | MEDIUM — LinkedIn's BEM naming for messaging, stable since ~2020 | `check_for_reply_robust` fallback uses zero class names |
| `send_followup.py` (dialog close) | `.msg-overlay-bubble-header__control--close-btn` | LOW — only used as last-resort close button selector | Shadow-aware close function tries aria-label patterns first |

### How to Maintain XPath Independence
When LinkedIn changes their DOM:
1. **Never add XPaths** — find the element's stable signal (aria-label, role, href, visible text)
2. **Test locally first** with `simulate_bot.py` — visual highlights (green/yellow/cyan/red) show what's being clicked
3. **Check the diagnostic dumps** at `state/logs/messaging_debug/` and `state/logs/profile_debug/` — they capture full page HTML + shadow DOM + screenshots at failure points
4. **Use DevTools** to inspect the element's parent chain — find the nearest stable attribute and use that

---

## 4. Soft-Ban Protection

### What is a Soft Ban?
LinkedIn doesn't permanently ban accounts for moderate automation. Instead they apply escalating restrictions:
1. **Session revocation** — all devices logged out (you experienced this)
2. **Checkpoint challenges** — "Verify your identity" via email/SMS/app
3. **Feature restriction** — connection requests or messages limited for 24-72h
4. **Account review** — manual review warning, temporary suspension
5. **Permanent restriction** — account permanently limited (rare, requires extreme abuse)

### Current Protections
| Protection | Implementation | Effective Against |
|-----------|---------------|-------------------|
| Human-like pauses | `human_pause(min, max)` between all actions | Basic timing detection |
| Randomized delays | `random.randint(60, 180)` between profiles | Pattern detection |
| Daily limits | Configurable per account via `config.json` (default: 12 connections, 15 messages) | Volume-based flagging |
| Proxy IP persistence | Same exit IP across runs via persisted session ID | IP-cookie mismatch detection |
| Timezone matching | Browser timezone matches proxy geo | Fingerprint inconsistency |
| Cookie reuse | Cookies persisted → no fresh login each run | "New device" spam detection |
| Browser profile reuse | Same Chromium profile across bots in a campaign | Multiple session detection |
| Session failure detection | `SessionFailureError` → abort + preserve leads | Prevents cascade of failures after flag |
| Verified sends only | Every message/connection verified before marking success | Prevents false-positive status updates |
| Firewall detection | FortiGate/Palo Alto block page detection | Prevents operating on non-LinkedIn pages |

### Recommended Daily Limits
Based on LinkedIn's known thresholds (as of 2025-2026):
| Action | Safe Daily Limit | Aggressive Limit | LinkedIn Weekly Cap |
|--------|-----------------|-------------------|-------------------|
| Connection requests | 5-10 | 15-20 | ~100/week |
| Initial messages | 8-12 | 15-20 | Not hard-capped but flagged at ~50/day |
| Follow-up messages | 10-15 | 20-25 | Same as above |
| Profile views | 50-80 | 100-150 | ~250/day for free accounts |

### What to Do If Soft-Banned
1. **Stop all bot activity immediately** — disable via `rm /mnt/bot-data/state/flags/bot_enabled_<account>`
2. **Wait 24-72 hours** — LinkedIn restrictions typically auto-expire
3. **Log in manually from your real browser** — browse feed, like posts, view profiles normally for 5-10 minutes. This signals "legitimate user" activity.
4. **Reduce daily limits** when resuming — cut to 50% of previous settings for the first week
5. **Check for checkpoint challenges** — the bot handles app-approval 2FA but NOT email/SMS verification challenges. If LinkedIn sends "verify your identity" via email, you must complete it manually.

### Stealth Improvements (Not Yet Implemented)
| Improvement | Difficulty | Impact |
|-------------|-----------|--------|
| Feed warm-up browsing (30-60s of random scrolling/liking before automation) | LOW | HIGH — establishes "normal user" pattern |
| Random profile view visits between actions | LOW | MEDIUM — diversifies activity pattern |
| Bezier-curve mouse movement for message typing (not just Connect clicks) | LOW | LOW — LinkedIn doesn't check typing cursor paths |
| TLS fingerprint patching (rebrowser-patches / puppeteer-real-browser) | HIGH | HIGH — makes bot's network fingerprint match real Chrome |
| Pre-warmed browser profiles (Multilogin / GoLogin) | MEDIUM (cost) | VERY HIGH — eliminates all fingerprint detection |
| Mobile API approach instead of browser automation | HIGH | VERY HIGH — no browser fingerprint at all |

---

## File Reference

| File | Purpose |
|------|---------|
| `login_credentials.py` | Login flow, cookie management, proxy session, browser setup, stealth |
| `msg_draft_connection_bot1.py` | Connection requests: profile detection, scraping, Connect click, verification |
| `send_message.py` | Initial messages: connection scraping, card-walk Message click, compose dialog, send+verify |
| `send_followup.py` | Follow-up messages: reply detection, follow-up message selection, same send flow |
| `robust_messaging.py` | Shared module: shadow-DOM messaging, recipient verification, textbox/Send finders, compose setup, close+verify, visual highlights |
| `fingerprint_diagnostics.py` | Browser fingerprint capture at checkpoints (diagnostic only, no behavior change) |
| `state_paths.py` | All persistent file paths (cookies, config, flags, logs, templates) |
| `attio_client.py` | Attio CRM API: lead fetching, status updates, per-account routing |
| `orchestrator.py` | Runs all 3 bots in sequence with logging, breaks, and Slack notifications |
| `simulate_bot.py` | Local testing harness: replicates cloud environment exactly |
| `_proxy_diag.py` | Manual proxy health diagnostic tool |
| `scripts/run_container.sh` | Docker container launch: secrets, env vars, mount points |
| `backend/entrypoint.sh` | Container entrypoint: Xvfb, cron, env propagation |
