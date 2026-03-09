# LinkedIn Outreach Bot — User Manual

## What This Is

An automated LinkedIn outreach system that runs on a Google Cloud VM. It sends connection requests, first messages, and follow-ups to leads from your Attio CRM — completely hands-free. You control everything from a Chrome extension on your laptop.

**You never need to touch a terminal or CLI.** The Chrome extension is the only interface.

---

## Architecture at a Glance

```
Your laptop (Chrome Extension)
        |
        | HTTP (port 8080)
        v
Google Cloud VM (Docker container)
   ├── Flask API (receives commands from extension)
   ├── Cron (hourly scheduler)
   ├── Orchestrator (runs 3 bots in sequence)
   │     ├── Connection Bot  — sends connection requests
   │     ├── Message Bot     — sends first messages
   │     └── Follow-up Bot   — sends follow-ups 1-4
   ├── Attio CRM client (reads leads, updates statuses)
   ├── Gemini AI (generates personalized messages)
   └── Slack notifier (real-time alerts)
```

---

## One-Time Setup

### 1. GCP Secrets

Store these in Google Cloud Secret Manager (the VM fetches them automatically on boot):

| Secret Name             | What It Is                                  |
|------------------------|---------------------------------------------|
| `ATTIO_API`            | Attio API key (primary account)             |
| `ATTIO_API_ALT`        | Attio API key (other accounts)              |
| `GEMINI_API_KEY_TEST`  | Google Gemini API key for AI messages       |
| `APIFY_API`            | Apify API key for LinkedIn scraping         |
| `PROXY_HOST`           | Residential proxy host                      |
| `PROXY_PORT`           | Proxy port                                  |
| `PROXY_USERNAME`       | Proxy username                              |
| `PROXY_PASSWORD_BASE`  | Proxy password                              |
| `USE_PROXY`            | `true` or `false`                           |
| `SLACK_WEBHOOK_URL`    | Slack incoming webhook (primary account)    |
| `SLACK_WEBHOOK_URL_ALT`| Slack incoming webhook (other accounts)     |

### 2. Deploy the VM

```bash
cd terraform

# Create terraform.tfvars:
# project_id   = "your-gcp-project-id"
# docker_image = "asia-south1-docker.pkg.dev/PROJECT/linkedin-bot/bot:latest"

terraform init
terraform apply
```

This creates the VM, persistent disk, firewall rule (port 8080 open), and service account.

### 3. Build and Push Docker Image

```bash
# From the project root
docker build -t asia-south1-docker.pkg.dev/YOUR_PROJECT/linkedin-bot/bot:latest .
docker push asia-south1-docker.pkg.dev/YOUR_PROJECT/linkedin-bot/bot:latest
```

The VM's startup script pulls this image and runs it automatically.

### 4. Install the Chrome Extension

1. Open Chrome and go to `chrome://extensions`
2. Turn on **Developer mode** (top right toggle)
3. Click **Load unpacked**
4. Select the `extension/` folder from this project
5. The extension icon appears in your toolbar — pin it for easy access

### 5. Set Up Slack Notifications

1. Go to [api.slack.com/apps](https://api.slack.com/apps)
2. Create a new app (or use an existing one)
3. Go to **Incoming Webhooks** > activate it > **Add New Webhook to Workspace**
4. Pick a channel (e.g. `#linkedin-bot-alerts`)
5. Copy the webhook URL — this goes into Secret Manager as `SLACK_WEBHOOK_URL`
6. Repeat for a second channel if needed (`SLACK_WEBHOOK_URL_ALT`)

---

## Daily Usage (The Extension)

### Step 1: Open the Extension

Click the extension icon in Chrome. You'll see a login screen.

**Credentials:** `beta` / `tester123`

You only need to log in once — it remembers you.

### Step 2: Set Backend URL

Enter the VM's external IP with port:
```
http://34.xxx.xxx.xxx:8080
```

This is saved permanently. You only set it once.

### Step 3: Set Account Name

Enter your account name exactly as it appears in Attio's `lead_manager` field.

Examples: `Yatharth Bisht`, `Maurice`, `Leon`

This determines:
- Which leads the bot processes (filters by `lead_manager` in Attio)
- Which Slack channel gets notifications
- Which API keys are used

### Step 4: Sync LinkedIn Cookies

1. Open LinkedIn in a browser tab and make sure you're logged in
2. Click **Sync LinkedIn Cookies** in the extension
3. Wait for the success message (e.g., "Synced 45 cookies + 12 storage keys")

**Important:** Re-sync cookies whenever LinkedIn logs you out (typically every 1-2 weeks).

### Step 5: Set Daily Limits

- **Connections:** How many connection requests per day (default: 20)
- **Messages:** How many first messages per day (default: 15)
- **Follow-ups:** How many follow-up messages per day (default: 10)

Keep these conservative to avoid LinkedIn restrictions.

### Step 6: Click Run Bot

That's it. The bot is now enabled.

---

## What Happens After You Click Run

1. The extension tells the VM: "enable the bot for this account"
2. The VM creates a flag file (`bot_enabled_<account>`)
3. The cron scheduler checks every hour — if the flag exists and the current UTC hour is within your time window, it launches the orchestrator
4. The orchestrator waits a random 0-30 minute delay (to look human), then runs 3 bots in sequence with 5-15 minute breaks between them:
   - **Connection Bot:** Reads leads from Attio `bot_inputs`, visits their LinkedIn profiles, scrapes data, generates AI messages, sends connection requests, saves everything to Attio `leads_sources`
   - **Message Bot:** Finds leads with status "connection accepted", sends the AI-drafted first message
   - **Follow-up Bot:** Finds leads contacted 3+ days ago, sends the next follow-up (up to 4 follow-ups total)
5. You get Slack notifications for every action — connections sent, messages sent, replies detected, errors

### Time Windows (UTC)

| Account        | Active Hours (UTC) |
|----------------|-------------------|
| Yatharth Bisht | 0:00 - 24:00 (always) |
| Maurice        | 7:00 - 15:00     |
| Leon           | 15:00 - 23:00    |

The bot only runs during your window. Outside the window, the cron skips your account even if enabled.

---

## Extension Status Bar

The extension shows 3 states:

| Color  | State   | Meaning |
|--------|---------|---------|
| Green  | Running | The bot process is alive and actively working |
| Amber  | Enabled | The bot is enabled but waiting for the next cron cycle or time window |
| Red    | Stopped | The bot is disabled — click Run Bot to start |

Below the status bar, you'll see:
- **Account:** Which lead manager is active
- **Phase:** What the bot is currently doing (Connection Bot, Message Bot, Follow-up Bot, Break, Waiting)
- **Time Window:** Your UTC operating hours

This information persists when you close and reopen the extension.

---

## Stopping the Bot

Click **Stop Bot** in the extension. This:
- Kills any running bot process immediately
- Removes the enabled flag so cron won't restart it
- Status turns red

You can restart anytime by clicking **Run Bot** again.

---

## Prompt Templates

Templates control how the AI writes outreach messages. Each template has 5 prompts:
- `outreach_prompt` — for the initial connection message
- `followup_1_prompt` through `followup_4_prompt` — for follow-ups

### Uploading a New Template

1. Create a JSON file with this format:
```json
{
  "description": "Template for SaaS founders",
  "outreach_prompt": "Write a short LinkedIn message to {profile_str}...",
  "followup_1_prompt": "Write follow-up 1...",
  "followup_2_prompt": "Write follow-up 2...",
  "followup_3_prompt": "Write follow-up 3...",
  "followup_4_prompt": "Write follow-up 4..."
}
```

2. Click **Upload New Template** in the extension
3. Select your JSON file
4. The extension validates the format and uploads it to the VM
5. You'll see something like: `Saved as prompt_template_5.json. Use "template_5" in Attio bot_inputs prompt_template column.`

### Assigning Templates to Leads

In Attio, go to the `bot_inputs` object. Each record has a `prompt_template` column. Enter the template name there (e.g., `template_5`). If left blank, it defaults to `template_1`.

---

## Attio CRM Setup

### `bot_inputs` Object

This is where you queue leads for outreach. Each record needs:

| Column           | What to Enter                    |
|-----------------|----------------------------------|
| `linkedin_url`  | The lead's LinkedIn profile URL  |
| `lead_manager`  | Your account name (e.g., `Yatharth Bisht`) |
| `prompt_template` | Which template to use (e.g., `template_1`) — leave blank for default |

The bot reads from here, processes each lead, then deletes the record from `bot_inputs` after processing.

### `leads_sources` Object

This is where the bot saves processed leads. It tracks:
- Profile info (name, headline, location)
- Lead status (`connection sent`, `first message sent`, `follow-up 1 sent`, etc.)
- AI-generated message drafts
- Last contacted timestamp

You don't need to manage this manually. The bot handles it.

---

## Slack Notifications

You'll receive real-time Slack messages for:

| Event | Example |
|-------|---------|
| Campaign started | "Campaign started — orchestrator running bot sequence" |
| Bot started | "Connection Bot started" |
| Connection sent | "Connected with Jane Smith" |
| Message sent | "Messaged Jane Smith" |
| Follow-up sent | "Follow-up #2 sent to Jane Smith" |
| Lead replied | "Jane Smith replied!" |
| Bot completed | "Message Bot completed — Finished in 12.3 min" |
| Bot failed | "Follow-up Bot failed — Exit code 1" |
| Login failed | "Login failed — could not establish LinkedIn session" |
| Campaign finished | "Campaign finished — 3/3 bots succeeded in 45 min" |

**Routing:** If your account is `Yatharth Bisht`, notifications go to the primary Slack channel. All other accounts go to the ALT channel.

---

## Troubleshooting

### Extension says "Connection failed"
- Check the Backend URL is correct (include `http://` and `:8080`)
- Make sure the VM is running: check GCP Console > Compute Engine
- Make sure the Docker container is running: SSH into VM and run `docker ps`

### Status stuck on "Enabled" but bot never runs
- Check the time window — are you within your UTC hours?
- SSH into the VM and check `docker exec linkedin-bot cat /app/backend/run_log.txt` for cron output
- Make sure cookies are synced (re-sync if LinkedIn logged you out)

### Bot runs but processes zero leads
- Check that leads exist in Attio `bot_inputs` with the correct `lead_manager` name (exact match, title case)
- Verify the `linkedin_url` column has valid URLs

### Cookies expired / Login failed
- Open LinkedIn in Chrome, log in manually
- Click **Sync LinkedIn Cookies** in the extension
- If LinkedIn asks for verification (OTP/captcha), complete it in the browser first, then re-sync

### Template upload rejected
- Make sure the file is valid JSON
- All 5 prompt keys are required: `outreach_prompt`, `followup_1_prompt` through `followup_4_prompt`
- All values must be non-empty strings
- Only `description` is optional

---

## Redeploying After Code Changes

```bash
# Build new image
docker build -t asia-south1-docker.pkg.dev/YOUR_PROJECT/linkedin-bot/bot:latest .

# Push to registry
docker push asia-south1-docker.pkg.dev/YOUR_PROJECT/linkedin-bot/bot:latest

# SSH into VM and restart container
gcloud compute ssh linkedin-bot --zone=asia-south1-a
sudo docker pull asia-south1-docker.pkg.dev/YOUR_PROJECT/linkedin-bot/bot:latest
sudo docker stop linkedin-bot
sudo docker rm linkedin-bot
# Re-run the docker run command from terraform startup script
```

Or simply restart the VM from GCP Console — the startup script re-pulls and runs the latest image automatically.

---

## Key Things to Remember

1. **You never need to use a terminal** — the Chrome extension is your only interface
2. **Re-sync cookies** every 1-2 weeks (or whenever LinkedIn logs you out)
3. **Keep daily limits conservative** — LinkedIn may flag aggressive automation
4. **Check Slack** for real-time updates — you'll know immediately if something breaks
5. **Templates are stored on the VM** — upload via extension, reference by name in Attio
6. **The bot survives restarts** — VM reboots, Docker restarts, laptop shutdowns — it picks back up automatically
7. **Close/reopen the extension freely** — it remembers everything (state, config, account)
