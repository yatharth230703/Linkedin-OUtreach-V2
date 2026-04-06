"""
state_paths.py — Single source of truth for every persistent path the bot uses.

All cookies, config, status, flags, logs, and uploaded prompt templates live
under STATE_DIR (default: /app/state in the container, ./backend in local dev).

In production, STATE_DIR is bind-mounted from the host's persistent disk so
that container rebuilds do not lose data.

Layout:
    STATE_DIR/
    ├── cookies/      cookies.json, cookies_<slug>.json, browser_storage*.json
    ├── config/       config.json, config_<slug>.json
    ├── flags/        bot_enabled, bot_enabled_<slug>, pid_<slug>.txt
    ├── status/       phase_status_<slug>.json
    ├── logs/         run_log.txt, daily_log.txt, deploy.log
    └── templates/    prompt_template_*.json

Every consumer in the codebase imports from this module — never hard-code paths.
"""

import os

# ── Resolution ──────────────────────────────────────────────────────────────

def _resolve_state_dir():
    """Return the active STATE_DIR.

    Order of precedence:
      1. STATE_DIR environment variable (set by Dockerfile / entrypoint.sh)
      2. /app/state if running inside the container layout
      3. <project_root>/backend as a local-dev fallback

    The local-dev fallback preserves the historical layout where everything
    sat in backend/, so existing local files keep working without env vars.
    """
    env = os.environ.get("STATE_DIR")
    if env:
        return env

    if os.path.isdir("/app/state"):
        return "/app/state"

    project_root = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(project_root, "backend")


STATE_DIR = _resolve_state_dir()

COOKIES_DIR    = os.path.join(STATE_DIR, "cookies")
CONFIG_DIR     = os.path.join(STATE_DIR, "config")
FLAGS_DIR      = os.path.join(STATE_DIR, "flags")
STATUS_DIR     = os.path.join(STATE_DIR, "status")
LOGS_DIR       = os.path.join(STATE_DIR, "logs")
TEMPLATES_DIR  = os.path.join(STATE_DIR, "templates")

# Best-effort directory creation. Safe to call repeatedly.
for _d in (COOKIES_DIR, CONFIG_DIR, FLAGS_DIR, STATUS_DIR, LOGS_DIR, TEMPLATES_DIR):
    try:
        os.makedirs(_d, exist_ok=True)
    except OSError:
        # Read-only filesystem in some test contexts. Don't crash on import.
        pass


# ── Helpers ─────────────────────────────────────────────────────────────────

def slugify(account_name):
    """Convert an account name into a filesystem-safe slug."""
    if not account_name:
        return ""
    return account_name.strip().lower().replace(" ", "_")


def cookies_path(slug=""):
    """Path to the cookies JSON for an account (or default if slug empty)."""
    name = f"cookies_{slug}.json" if slug else "cookies.json"
    return os.path.join(COOKIES_DIR, name)


def storage_path(slug=""):
    """Path to the browser_storage JSON for an account."""
    name = f"browser_storage_{slug}.json" if slug else "browser_storage.json"
    return os.path.join(COOKIES_DIR, name)


def config_path(slug=""):
    """Path to per-account config JSON (daily limits, account name, template)."""
    name = f"config_{slug}.json" if slug else "config.json"
    return os.path.join(CONFIG_DIR, name)


def enabled_flag_path(slug=""):
    """Path to the bot_enabled flag file for an account."""
    name = f"bot_enabled_{slug}" if slug else "bot_enabled"
    return os.path.join(FLAGS_DIR, name)


def pid_path(slug=""):
    """Path to the running orchestrator PID file for an account."""
    name = f"pid_{slug}.txt" if slug else "pid.txt"
    return os.path.join(FLAGS_DIR, name)


def phase_status_path(slug):
    """Path to the per-account phase status JSON written by the orchestrator."""
    return os.path.join(STATUS_DIR, f"phase_status_{slug}.json")


def run_log_path():
    """Path to the cron/server run log."""
    return os.path.join(LOGS_DIR, "run_log.txt")


def daily_log_path():
    """Path to the orchestrator daily log."""
    return os.path.join(LOGS_DIR, "daily_log.txt")


def deploy_log_path():
    """Path to the deploy audit log written by the redeploy script."""
    return os.path.join(LOGS_DIR, "deploy.log")


def template_path(num):
    """Path to a numbered prompt_template file."""
    return os.path.join(TEMPLATES_DIR, f"prompt_template_{num}.json")


def template_glob():
    """Glob pattern for listing all uploaded prompt templates."""
    return os.path.join(TEMPLATES_DIR, "prompt_template_*.json")
