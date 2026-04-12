---
name: Bot debugging and infrastructure overhaul - April 2026
description: Comprehensive summary of all changes made to the LinkedIn outreach bot during the April 7-12 2026 debugging session. Covers CI/CD setup, persistent state, login fixes, proxy configuration, and ongoing issues.
type: project
---

## Context
User: Yatharth Bisht, running a LinkedIn outreach bot on a GCE VM (e2-medium, asia-south1-a) inside Docker. Three accounts: yatharth_bisht (India/Delhi proxy), maurice and leon (Germany/Hamburg proxy). Bot was broken since ~April 2 with ERR_TOO_MANY_REDIRECTS login failures.

## Infrastructure Changes Completed

### 1. CI/CD Pipeline (fully working)
- GitHub Actions workflow at `.github/workflows/deploy.yml`
- Builds Docker image, pushes to Artifact Registry, SSHes to VM via IAP, runs redeploy
- Uses **Workload Identity Federation** (org policy blocks SA JSON keys)
- WIF pool: `github-pool`, provider: `github-provider`, SA: `linkedin-bot-ci@optimum-beach-489223-h7.iam.gserviceaccount.com`
- GitHub repo variables: `GCP_WIF_PROVIDER`, `GCP_DEPLOY_SA`
- Auto-deploys on every push to `main`
- Auto-prunes old Docker images before each deploy (prevents disk-full)

### 2. Persistent State (`state_paths.py`)
- New module `state_paths.py` at project root — single source of truth for all persistent paths
- All cookies, config, flags, status, logs, templates stored under `STATE_DIR` (env var)
- VM: `/app/state` bind-mounted from `/mnt/bot-data/state` on persistent disk
- Local dev: falls back to `./backend/` with subdirectories
- Refactored: `server.py`, `orchestrator.py`, `login_credentials.py`, all 3 bot scripts, `gemini_outreach.py`, `entrypoint.sh`, `run_master.sh`

### 3. Terraform
- `lifecycle.ignore_changes` on `metadata_startup_script` — VM never gets recreated by terraform
- `allow-ssh-iap` firewall rule for GitHub Actions IAP tunnel
- `allow-ssh` imported into terraform state
- SSH allowed IPs variable for easy updates

### 4. Cron changed from hourly to per-minute
- `backend/crontab`: `* * * * *` instead of `0 * * * *`
- Yatharth Bisht gets zero initial delay (`MAX_INITIAL_DELAY_MINUTES = 0`)
- Maurice/Leon still have 0-30min random delay

### 5. Secret Management
- `ATTIO_API` v1 restored (v2 was accidentally pointing to wrong workspace)
- `YATH_LINKEDIN_EMAIL` and `YATH_LINKEDIN_PASSWORD` added to Secret Manager
- `entrypoint.sh` uses `printf %q` to shell-escape values in `.env.cron` (fixed bug where password containing `"` corrupted all subsequent env vars)
- `.env.cron` grep pattern explicitly lists all env var names (fixed regex bug where `PROXY_` prefix match didn't work)

## Login Flow Changes

### Cookie injection strategy
- Changed from injecting ALL cookies → injecting all EXCEPT `JSESSIONID`
- `_COOKIES_TO_SKIP = {"JSESSIONID"}` — JSESSIONID is the only strictly single-client token
- Sharing JSESSIONID causes LinkedIn to detect session conflict and log out the user's personal Chrome
- Other cookies (liap, lidc, bcookie, etc.) are needed for LinkedIn edge routing

### Cookie login consistently fails on iproyal IPs
- ALL iproyal residential IPs cause `ERR_TOO_MANY_REDIRECTS` when cookies are injected
- Even `/login` page redirect-loops with cookies present
- Without cookies, `/login` loads fine → password login works

### Password login fallback (working)
- `_password_login(account_name)` function in `login_credentials.py`
- Reads credentials from env: `YATH_LINKEDIN_EMAIL`, `YATH_LINKEDIN_PASSWORD`
- Clears ALL cookies → navigates to about:blank → then /login (clean browser state)
- Fills email + password → clicks Sign In → waits for app challenge (push notification)
- Checks for app challenge FIRST (before navigating away — previous bug was `check_if_logged_in` navigating to linkedin.com/ which destroyed the challenge page)
- Waits up to 5 minutes for user to tap Approve on LinkedIn mobile app
- Successfully logs in and reaches /feed, /mynetwork, profile pages

### Proxy sticky sessions
- iproyal rotates exit IP per TCP connection by default → breaks LinkedIn session continuity
- Fix: append `_session-{random_hex}` to proxy password → pins exit IP for entire run
- `_PROXY_SESSION_ID` generated once per process, regenerated between login retry attempts via `_regenerate_proxy_session()`
- Confirmed working: 5 requests through sticky session → all same IP

### Login retry flow
```
ensure_linkedin_login():
  1. If SKIP_COOKIE_LOGIN=true → go straight to _password_login()
  2. Otherwise: cookie login attempts 1-3 (rotating proxy IP each time)
  3. If all fail → _password_login() as final fallback
```

### _kill_zombie_chrome_processes fix
- Was killing the bot subprocess itself because the path `playwright_bots/msg_draft_connection_bot1.py` matched `"playwright" in cmdline`
- Caused Exit code -9 (SIGKILL) before retry logic could fire
- Fixed: excludes current PID and parent PID, only matches actual browser/driver processes

## Attio Routing
- Strict per-account key routing (no fallback):
  - yatharth_bisht → `ATTIO_API` env var
  - maurice/leon → `ATTIO_API_ALT` env var
- `_explain_missing_object()` method prints detailed diagnostic when 404 occurs (workspace ID, accessible objects, which env var to check)
- `get_attio_client()` logs routing on first call: `Attio routing: account='X' -> env=Y (key Z...)`

## Ongoing Issues (not yet resolved)

### 1. Profile accessibility false positives (CRITICAL - actively debugging)
- `is_profile_accessible()` marks valid profiles as FAULTY_URL
- The `<h1>` name element is not found even though the profile page loads correctly
- Changed from static sleep (12s) to Playwright auto-wait (`wait_for(state="visible", timeout=20000)`) — still fails
- **Currently testing**: whether playwright-stealth scripts interfere with element detection
- Added `DISABLE_STEALTH=true` env var flag to toggle stealth off for debugging
- Added `SKIP_COOKIE_LOGIN=true` env var flag to skip cookie attempts

### 2. Playwright headful interaction blocked
- Playwright 1.58 headful mode does not allow manual clicking/typing in the browser window
- Both `channel="chrome"` and bundled Chromium have this issue
- Only scrolling works. Cannot click URLs, buttons, or move the window
- Parked — workaround is terminal-based URL navigation in simulate_bot.py

### 3. Cookie-based login broken on all iproyal IPs
- Every iproyal Indian residential IP causes ERR_TOO_MANY_REDIRECTS with cookies
- Password login is the working path
- Root cause unclear — could be LinkedIn flagging iproyal's IP ranges, or cookie domain/session binding issues

## Key Files Modified
- `state_paths.py` (NEW) — persistent path resolution
- `simulate_bot.py` (NEW) — local simulation harness
- `scripts/run_container.sh` (NEW) — docker run single source of truth
- `scripts/redeploy.sh` (NEW) — deploy script with logging + health check
- `.github/workflows/deploy.yml` (NEW) — CI/CD workflow
- `MIGRATION.md` (NEW) — one-time bootstrap docs
- `backend/server.py` — refactored to use state_paths
- `backend/entrypoint.sh` — printf %q escaping, new env vars
- `backend/run_master.sh` — uses STATE_DIR for flags/logs
- `backend/crontab` — per-minute instead of hourly
- `orchestrator.py` — state_paths, zero delay for yatharth
- `Linkedin_cloud_bot_attio/playwright_bots/login_credentials.py` — major changes (cookie injection, password fallback, proxy sticky sessions, browser dead error handling, stealth toggle, skip cookie login toggle)
- `Linkedin_cloud_bot_attio/playwright_bots/msg_draft_connection_bot1.py` — is_profile_accessible wait_for fix, config path fix
- `Linkedin_cloud_bot_attio/playwright_bots/send_message.py` — config path fix
- `Linkedin_cloud_bot_attio/playwright_bots/send_followup.py` — config path fix
- `Linkedin_cloud_bot_attio/attio_client.py` — strict routing, 404 diagnostics
- `Linkedin_cloud_bot_attio/gemini_outreach.py` — template path fix
- `Dockerfile` — state_paths, STATE_DIR, state subdirs
- `terraform/main.tf` — lifecycle ignore, state mount, IAP firewall, SSH firewall
- `terraform/variables.tf` — ssh_allowed_ips
- `.gitignore` — runtime state files excluded

## Environment Details
- VM: `linkedin-bot`, e2-medium, asia-south1-a, ubuntu-2204, 30GB boot, 10GB data disk
- Container: `asia-south1-docker.pkg.dev/optimum-beach-489223-h7/linkedin-bot/bot:<sha>`
- Proxy: iproyal, geo.iproyal.com:12321, residential, sticky sessions
- Project: optimum-beach-489223-h7
- GitHub: yatharth230703/Linkedin-OUtreach-V2
- Playwright: 1.58.0
