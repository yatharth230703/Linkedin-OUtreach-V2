"""
Slack notification module for LinkedIn automation bot.
Sends real-time alerts to Slack via incoming webhook.
Routes to different Slack channels based on account.
"""

import os
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
SLACK_WEBHOOK_URL_ALT = os.getenv("SLACK_WEBHOOK_URL_ALT", "")

YATHARTH_SLUGS = {"yatharth_bisht", "yatharth bisht", "yatharth"}

# Module-level active account — set once per process via set_active_account()
_active_account: str = ""


def set_active_account(account_name: str):
    """Set the active account for this process so notifications route correctly."""
    global _active_account
    _active_account = account_name.strip()


def _pick_webhook(account_name: str) -> str:
    effective = account_name.strip() or _active_account
    if effective.lower() in YATHARTH_SLUGS:
        return SLACK_WEBHOOK_URL
    return SLACK_WEBHOOK_URL_ALT or SLACK_WEBHOOK_URL


def notify(message, account_name="", level="info"):
    """
    Send a notification to Slack.

    Args:
        message: The notification text.
        account_name: Which lead manager account this relates to.
        level: "info", "success", "warning", or "error" for icon prefix.
    """
    effective_account = account_name or _active_account
    webhook_url = _pick_webhook(effective_account)
    if not webhook_url:
        return

    icons = {
        "info": ":information_source:",
        "success": ":white_check_mark:",
        "warning": ":warning:",
        "error": ":x:",
    }
    icon = icons.get(level, ":robot_face:")

    timestamp = datetime.now().strftime("%H:%M:%S UTC")
    account_tag = f" [{effective_account}]" if effective_account else ""

    text = f"{icon}{account_tag} {message}  _({timestamp})_"

    try:
        requests.post(webhook_url, json={"text": text}, timeout=5)
    except Exception:
        # Never let a notification failure break the bot
        pass


def notify_bot_started(bot_name, account_name=""):
    notify(f"*{bot_name}* started", account_name, "info")


def notify_bot_completed(bot_name, summary="", account_name=""):
    msg = f"*{bot_name}* completed"
    if summary:
        msg += f"\n>{summary}"
    notify(msg, account_name, "success")


def notify_bot_failed(bot_name, error="", account_name=""):
    msg = f"*{bot_name}* failed"
    if error:
        msg += f"\n>```{error}```"
    notify(msg, account_name, "error")


def notify_campaign_started(account_name=""):
    notify("*Campaign started* — orchestrator running bot sequence", account_name, "info")


def notify_campaign_completed(successful, total, duration_min, account_name=""):
    notify(
        f"*Campaign finished* — {successful}/{total} bots succeeded in {duration_min:.0f} min",
        account_name,
        "success" if successful == total else "warning",
    )


def notify_connection_sent(lead_name, account_name=""):
    notify(f"Connected with *{lead_name}*", account_name, "success")


def notify_message_sent(lead_name, account_name=""):
    notify(f"Messaged *{lead_name}*", account_name, "success")


def notify_followup_sent(lead_name, followup_num, account_name=""):
    notify(f"Follow-up #{followup_num} sent to *{lead_name}*", account_name, "success")


def notify_lead_replied(lead_name, account_name=""):
    notify(f":tada: *{lead_name}* replied!", account_name, "success")


def notify_error(error_message, account_name=""):
    notify(f"*Error:* {error_message}", account_name, "error")


def notify_login_failed(account_name=""):
    notify("*Login failed* — could not establish LinkedIn session", account_name, "error")
