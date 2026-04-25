"""
LinkedIn Bot Backend API
Minimal Flask server to receive cookies, config, and control bot execution.
Supports multi-account operation with per-account config, PID files, and template management.

All persistent paths are resolved via state_paths.py so that cookies, config,
flags, status, logs, and uploaded templates survive container rebuilds.
"""

import os
import sys
import json
import glob as glob_module
import signal
from datetime import datetime, timezone
from flask import Flask, request, jsonify
from flask_cors import CORS

# Make the project root importable so we can use state_paths.py
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from state_paths import (  # noqa: E402
    cookies_path,
    storage_path,
    config_path,
    enabled_flag_path,
    pid_path,
    phase_status_path,
    run_log_path,
    template_path,
    template_glob,
    slugify,
)

app = Flask(__name__)
CORS(app)

API_KEY = "linkedin-bot-beta-2024"


def check_api_key():
    key = request.headers.get("X-Api-Key", "")
    if key != API_KEY:
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    return None


@app.before_request
def auth_middleware():
    if request.method == "OPTIONS":
        from flask import make_response
        resp = make_response("", 200)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Api-Key"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return resp
    result = check_api_key()
    if result:
        return result


def _account_slug(account_name):
    """Convert account name to a filesystem-safe slug."""
    return slugify(account_name)


def _pid_file(slug):
    """Path to PID file for an account."""
    return pid_path(slug)


def _is_process_alive(pid):
    """Check if a process with the given PID is still running."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def _read_pid(slug):
    """Read PID from file. Returns (pid, alive) or (None, False)."""
    pid_path = _pid_file(slug)
    if not os.path.exists(pid_path):
        return None, False
    try:
        with open(pid_path, "r") as f:
            pid = int(f.read().strip())
        return pid, _is_process_alive(pid)
    except (ValueError, FileNotFoundError):
        return None, False


def _kill_pid(slug):
    """Kill the process associated with an account and clean up PID file."""
    pid, alive = _read_pid(slug)
    if pid and alive:
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                os.kill(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                pass
    pid_path = _pid_file(slug)
    if os.path.exists(pid_path):
        os.remove(pid_path)


@app.route("/api/cookies", methods=["POST"])
def receive_cookies():
    data = request.get_json()
    if not data or "cookies" not in data:
        return jsonify({"success": False, "error": "No cookies provided"}), 400

    account_name = data.get("account_name", "").strip()
    slug = _account_slug(account_name)

    # Save default (backward-compat) files
    with open(cookies_path(), "w") as f:
        json.dump(data["cookies"], f, indent=2)

    if data.get("browserStorage"):
        with open(storage_path(), "w") as f:
            json.dump(data["browserStorage"], f, indent=2)

    # Save per-account files if account_name provided
    if slug:
        with open(cookies_path(slug), "w") as f:
            json.dump(data["cookies"], f, indent=2)

        if data.get("browserStorage"):
            with open(storage_path(slug), "w") as f:
                json.dump(data["browserStorage"], f, indent=2)

    return jsonify({"success": True, "count": len(data["cookies"]), "account": account_name})


@app.route("/api/config", methods=["POST"])
def receive_config():
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "No config provided"}), 400

    account_name = data.get("account_name", "")
    slug = _account_slug(account_name)

    config = {
        "daily_connect": data.get("daily_connect", 20),
        "daily_message": data.get("daily_message", 15),
        "daily_followup": data.get("daily_followup", 10),
        "account_name": account_name,
    }

    # Always write default config for backward compat
    with open(config_path(), "w") as f:
        json.dump(config, f, indent=2)

    # Write per-account config
    if slug:
        with open(config_path(slug), "w") as f:
            json.dump(config, f, indent=2)

    return jsonify({"success": True, "config": config})


@app.route("/api/start", methods=["POST"])
def start_bot():
    data = request.get_json() or {}
    account_name = data.get("account_name", "").strip()

    # Try to get account_name from config if not in request body
    if not account_name:
        try:
            with open(config_path(), "r") as cf:
                config_data = json.load(cf)
                account_name = config_data.get("account_name", "")
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    if not account_name:
        return jsonify({"success": False, "error": "No account name configured. Set it in the extension first."}), 400

    slug = _account_slug(account_name)

    # Check cookies exist
    if not os.path.exists(cookies_path(slug)) and not os.path.exists(cookies_path()):
        return jsonify({"success": False, "error": "No cookies synced yet. Sync cookies first."}), 400

    # Check if already running
    pid, alive = _read_pid(slug)
    if alive:
        return jsonify({"success": False, "error": f"Bot is already running for {account_name} (PID: {pid})."}), 400

    # Write enabled flag for cron to pick up
    with open(enabled_flag_path(slug), "w") as f:
        f.write(datetime.now(timezone.utc).isoformat())

    # Also write default flag for backward compat
    with open(enabled_flag_path(), "w") as f:
        f.write(datetime.now(timezone.utc).isoformat())

    with open(run_log_path(), "a") as rl:
        rl.write(f"\n--- Bot enabled for {account_name} at {datetime.now(timezone.utc).isoformat()} ---\n")

    return jsonify({
        "success": True,
        "message": f"Bot enabled for {account_name}. Cron will start it in the next cycle.",
    })


@app.route("/api/stop", methods=["POST"])
def stop_bot():
    data = request.get_json() or {}
    account_name = data.get("account_name", "").strip()

    # Try to get account_name from config if not in request body
    if not account_name:
        try:
            with open(config_path(), "r") as cf:
                config_data = json.load(cf)
                account_name = config_data.get("account_name", "")
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    slug = _account_slug(account_name)

    # Kill process if running
    _kill_pid(slug)

    # Remove enabled flags
    for fpath in [
        enabled_flag_path(slug) if slug else None,
        enabled_flag_path(),
    ]:
        if fpath and os.path.exists(fpath):
            os.remove(fpath)

    with open(run_log_path(), "a") as f:
        f.write(f"\n--- Bot stopped for {account_name or 'default'} at {datetime.now(timezone.utc).isoformat()} ---\n")

    return jsonify({"success": True, "message": "Bot stopped."})


# Time windows per account (UTC hours, matches run_master.sh)
ACCOUNT_TIME_WINDOWS = {
    "yatharth_bisht": (0, 24),
    "maurice": (7, 15),
    "leon": (15, 23),
}


@app.route("/api/status", methods=["GET"])
def get_status():
    account_name = request.args.get("account_name", "").strip()

    # If no account_name in query, try from config
    if not account_name:
        try:
            with open(config_path(), "r") as cf:
                config_data = json.load(cf)
                account_name = config_data.get("account_name", "")
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    slug = _account_slug(account_name)

    pid, alive = _read_pid(slug)

    # Check enabled flag (per-account or default)
    flag_exists = os.path.exists(enabled_flag_path(slug)) or os.path.exists(enabled_flag_path())

    # Read phase status file (written by orchestrator)
    phase = None
    phase_detail = None
    phase_updated = None
    if slug:
        phase_file = phase_status_path(slug)
        if os.path.exists(phase_file):
            try:
                with open(phase_file, "r") as f:
                    phase_data = json.load(f)
                phase = phase_data.get("phase")
                phase_detail = phase_data.get("detail")
                phase_updated = phase_data.get("updated_at")
            except (json.JSONDecodeError, IOError):
                pass

    # Determine state: running (process alive), enabled (flag exists but idle), stopped
    if alive and flag_exists:
        state = "running"
    elif flag_exists:
        state = "enabled"
    else:
        state = "stopped"

    # Time window info
    time_window = ACCOUNT_TIME_WINDOWS.get(slug)
    time_window_str = f"{time_window[0]}:00-{time_window[1]}:00 UTC" if time_window else None

    # Last log line
    last_run = None
    rlog = run_log_path()
    if os.path.exists(rlog):
        try:
            with open(rlog, "r") as f:
                lines = f.readlines()
                if lines:
                    last_run = lines[-1].strip()
        except IOError:
            pass

    # Per-account config (daily limits)
    config = None
    cfg_path = config_path(slug) if slug else config_path()
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r") as f:
                config = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    return jsonify({
        "success": True,
        "state": state,
        "running": alive and flag_exists,
        "enabled": flag_exists,
        "account": account_name,
        "phase": phase,
        "phase_detail": phase_detail,
        "phase_updated": phase_updated,
        "time_window": time_window_str,
        "last_run": last_run,
        "pid": pid if alive else None,
        "config": config,
    })


# ── Template endpoints ──────────────────────────────────────────────────────

TEMPLATE_REQUIRED_KEYS = [
    "outreach_prompt", "followup_1_prompt", "followup_2_prompt",
    "followup_3_prompt", "followup_4_prompt",
]

# Keys that are allowed in a template file (required + optional)
TEMPLATE_ALLOWED_KEYS = set(TEMPLATE_REQUIRED_KEYS + ["description"])


def _validate_template(data):
    """
    Validate a template dict. Returns (ok: bool, error: str|None).
    Checks: required keys present, all values are non-empty strings, no unexpected keys.
    """
    if not isinstance(data, dict):
        return False, "Template must be a JSON object"

    # Check for unexpected keys
    extra_keys = set(data.keys()) - TEMPLATE_ALLOWED_KEYS
    if extra_keys:
        return False, f"Unexpected keys: {', '.join(sorted(extra_keys))}. Allowed: {', '.join(sorted(TEMPLATE_ALLOWED_KEYS))}"

    # Check required keys exist and are non-empty strings
    missing = []
    empty = []
    bad_type = []
    for key in TEMPLATE_REQUIRED_KEYS:
        if key not in data:
            missing.append(key)
        elif not isinstance(data[key], str):
            bad_type.append(key)
        elif not data[key].strip():
            empty.append(key)

    errors = []
    if missing:
        errors.append(f"Missing keys: {', '.join(missing)}")
    if bad_type:
        errors.append(f"Must be strings: {', '.join(bad_type)}")
    if empty:
        errors.append(f"Empty values: {', '.join(empty)}")

    if errors:
        return False, ". ".join(errors)

    return True, None


@app.route("/api/templates", methods=["POST"])
def upload_template():
    """Validate and save an uploaded JSON template.

    Accepts optional `template_number` in the request body to save as a
    specific template (e.g. template_number=5 → prompt_template_5.json).
    If not provided, auto-assigns the next available number by scanning
    BOTH the state dir AND the baked-in templates in the Docker image.
    """
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "No template data provided"}), 400

    # template_number can be passed alongside the template content
    requested_num = data.pop("template_number", None)

    ok, error = _validate_template(data)
    if not ok:
        return jsonify({"success": False, "error": error}), 400

    if requested_num is not None:
        try:
            next_num = int(requested_num)
        except (ValueError, TypeError):
            return jsonify({"success": False, "error": f"Invalid template_number: {requested_num}"}), 400
    else:
        # Auto-assign: scan state dir AND baked-in templates for highest number
        next_num = 1
        # State dir templates
        for f in glob_module.glob(template_glob()):
            try:
                num = int(os.path.basename(f).replace("prompt_template_", "").replace(".json", ""))
                next_num = max(next_num, num + 1)
            except ValueError:
                continue
        # Also check baked-in templates (inside the container image)
        baked_in_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                    "Linkedin_cloud_bot_attio")
        for f in glob_module.glob(os.path.join(baked_in_dir, "prompt_template_*.json")):
            try:
                num = int(os.path.basename(f).replace("prompt_template_", "").replace(".json", ""))
                next_num = max(next_num, num + 1)
            except ValueError:
                continue

    filepath = template_path(next_num)
    filename = os.path.basename(filepath)

    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)

    template_name = f"template_{next_num}"
    return jsonify({"success": True, "filename": filename, "template_name": template_name})



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
