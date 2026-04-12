---
name: Playwright headful interaction blocked
description: Playwright 1.58 headful mode does not allow manual clicking/typing in the browser window — only scrolling works. Both channel=chrome and bundled Chromium have this issue. Parked for now.
type: feedback
---

Playwright 1.58 headful browser windows cannot be manually interacted with (clicking, typing, moving window) — only scrolling works. This applies to both `channel="chrome"` and Playwright's bundled Chromium, and to both `launch_persistent_context` and regular contexts.

**Why:** Unknown root cause. Possibly a Playwright 1.57+ regression related to Chrome for Testing CDP changes. User confirms this was never an issue in older Playwright versions.

**How to apply:** Don't promise manual browser interaction in simulate_bot.py. Use the terminal-based URL navigation prompt instead. The bot's automated Playwright clicks still work fine — only manual human interaction is blocked.
