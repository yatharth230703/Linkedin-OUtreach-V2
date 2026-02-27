"""
LinkedIn Bot Backend API
Minimal Flask server to receive cookies, config, and control bot execution.
Supports multi-account operation with per-account config, PID files, and template management.
"""

import os
import sys
import json
import glob as glob_module
import signal
from datetime import datetime, timezone
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

API_KEY = "linkedin-bot-beta-2024"
DATA_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(DATA_DIR)
COOKIES_FILE = os.path.join(DATA_DIR, "cookies.json")
STORAGE_FILE = os.path.join(DATA_DIR, "browser_storage.json")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
ENABLED_FLAG = os.path.join(DATA_DIR, "bot_enabled")
RUN_LOG = os.path.join(DATA_DIR, "run_log.txt")
TEMPLATES_DIR = os.path.join(PROJECT_DIR, "Linkedin_cloud_bot_attio")


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
    return account_name.strip().lower().replace(" ", "_") if account_name else ""


def _pid_file(slug):
    """Path to PID file for an account."""
    return os.path.join(DATA_DIR, f"pid_{slug}.txt") if slug else os.path.join(DATA_DIR, "pid.txt")


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
    with open(COOKIES_FILE, "w") as f:
        json.dump(data["cookies"], f, indent=2)

    if data.get("browserStorage"):
        with open(STORAGE_FILE, "w") as f:
            json.dump(data["browserStorage"], f, indent=2)

    # Save per-account files if account_name provided
    if slug:
        per_account_cookies = os.path.join(DATA_DIR, f"cookies_{slug}.json")
        with open(per_account_cookies, "w") as f:
            json.dump(data["cookies"], f, indent=2)

        if data.get("browserStorage"):
            per_account_storage = os.path.join(DATA_DIR, f"browser_storage_{slug}.json")
            with open(per_account_storage, "w") as f:
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
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)

    # Write per-account config
    if slug:
        with open(os.path.join(DATA_DIR, f"config_{slug}.json"), "w") as f:
            json.dump(config, f, indent=2)

    return jsonify({"success": True, "config": config})


@app.route("/api/start", methods=["POST"])
def start_bot():
    data = request.get_json() or {}
    account_name = data.get("account_name", "").strip()

    # Try to get account_name from config if not in request body
    if not account_name:
        try:
            with open(CONFIG_FILE, "r") as cf:
                config_data = json.load(cf)
                account_name = config_data.get("account_name", "")
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    if not account_name:
        return jsonify({"success": False, "error": "No account name configured. Set it in the extension first."}), 400

    slug = _account_slug(account_name)

    # Check cookies exist
    cookies_file = os.path.join(DATA_DIR, f"cookies_{slug}.json")
    if not os.path.exists(cookies_file) and not os.path.exists(COOKIES_FILE):
        return jsonify({"success": False, "error": "No cookies synced yet. Sync cookies first."}), 400

    # Check if already running
    pid, alive = _read_pid(slug)
    if alive:
        return jsonify({"success": False, "error": f"Bot is already running for {account_name} (PID: {pid})."}), 400

    # Write enabled flag for cron to pick up
    enabled_flag = os.path.join(DATA_DIR, f"bot_enabled_{slug}")
    with open(enabled_flag, "w") as f:
        f.write(datetime.now(timezone.utc).isoformat())

    # Also write default flag for backward compat
    with open(ENABLED_FLAG, "w") as f:
        f.write(datetime.now(timezone.utc).isoformat())

    with open(RUN_LOG, "a") as rl:
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
            with open(CONFIG_FILE, "r") as cf:
                config_data = json.load(cf)
                account_name = config_data.get("account_name", "")
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    slug = _account_slug(account_name)

    # Kill process if running
    _kill_pid(slug)

    # Remove enabled flags
    for flag_path in [
        os.path.join(DATA_DIR, f"bot_enabled_{slug}") if slug else None,
        ENABLED_FLAG,
    ]:
        if flag_path and os.path.exists(flag_path):
            os.remove(flag_path)

    with open(RUN_LOG, "a") as f:
        f.write(f"\n--- Bot stopped for {account_name or 'default'} at {datetime.now(timezone.utc).isoformat()} ---\n")

    return jsonify({"success": True, "message": "Bot stopped."})


@app.route("/api/status", methods=["GET"])
def get_status():
    account_name = request.args.get("account_name", "").strip()

    # If no account_name in query, try from config
    if not account_name:
        try:
            with open(CONFIG_FILE, "r") as cf:
                config_data = json.load(cf)
                account_name = config_data.get("account_name", "")
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    slug = _account_slug(account_name)

    pid, alive = _read_pid(slug)

    # Check enabled flag
    enabled_flag = os.path.join(DATA_DIR, f"bot_enabled_{slug}") if slug else ENABLED_FLAG
    flag_exists = os.path.exists(enabled_flag) or os.path.exists(ENABLED_FLAG)

    running = alive and flag_exists

    last_run = None
    if os.path.exists(RUN_LOG):
        with open(RUN_LOG, "r") as f:
            lines = f.readlines()
            if lines:
                last_run = lines[-1].strip()

    return jsonify({
        "success": True,
        "running": running,
        "last_run": last_run,
        "pid": pid if alive else None,
        "account": account_name,
    })


# ── Template endpoints ──────────────────────────────────────────────────────

@app.route("/api/templates", methods=["GET"])
def list_templates():
    """List all prompt_template_*.json files with descriptions."""
    templates = []
    pattern = os.path.join(TEMPLATES_DIR, "prompt_template_*.json")
    for filepath in sorted(glob_module.glob(pattern)):
        try:
            with open(filepath, "r") as f:
                data = json.load(f)
            name = os.path.basename(filepath)
            templates.append({
                "filename": name,
                "description": data.get("description", "No description"),
            })
        except (json.JSONDecodeError, IOError):
            continue

    return jsonify({"success": True, "templates": templates})


@app.route("/api/templates", methods=["POST"])
def upload_template():
    """Validate and save an uploaded JSON template as the next numbered file."""
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "No template data provided"}), 400

    # Validate required keys
    required_keys = ["outreach_prompt", "followup_1_prompt", "followup_2_prompt",
                     "followup_3_prompt", "followup_4_prompt"]
    missing = [k for k in required_keys if k not in data]
    if missing:
        return jsonify({"success": False, "error": f"Missing required keys: {', '.join(missing)}"}), 400

    # Find next template number
    existing = sorted(glob_module.glob(os.path.join(TEMPLATES_DIR, "prompt_template_*.json")))
    next_num = 1
    for f in existing:
        try:
            num = int(os.path.basename(f).replace("prompt_template_", "").replace(".json", ""))
            next_num = max(next_num, num + 1)
        except ValueError:
            continue

    filename = f"prompt_template_{next_num}.json"
    filepath = os.path.join(TEMPLATES_DIR, filename)

    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)

    return jsonify({"success": True, "filename": filename, "number": next_num})


@app.route("/api/templates/preview", methods=["POST"])
def preview_template():
    """Generate sample messages using a template with a random Attio lead."""
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "No template data provided"}), 400

    try:
        sys.path.insert(0, TEMPLATES_DIR)
        sys.path.insert(0, os.path.join(PROJECT_DIR, "Linkedin_cloud_bot_attio"))
        from gemini_outreach import GeminiLinkedInMessager

        messager = GeminiLinkedInMessager()

        # Use a sample profile for preview
        sample_profile = {
            "name": "Jane Smith",
            "headline": "VP of Engineering at TechCorp | Building scalable systems",
            "location": "San Francisco Bay Area",
            "about": "Passionate about distributed systems and team leadership. Previously at Google and Stripe.",
            "experience": "VP Engineering at TechCorp (2022-present), Senior Director at Stripe (2019-2022), Staff Engineer at Google (2015-2019)"
        }
        sample_posts = "Recent post: 'Excited to share that our team just shipped a new microservices platform serving 10M requests/day'"

        profile_str = json.dumps(sample_profile, indent=2)
        posts_str = sample_posts

        messages = {}
        prompt_keys = [
            ("outreach_prompt", "outreach"),
            ("followup_1_prompt", "followup_1"),
            ("followup_2_prompt", "followup_2"),
            ("followup_3_prompt", "followup_3"),
            ("followup_4_prompt", "followup_4"),
        ]

        for template_key, output_key in prompt_keys:
            prompt = data.get(template_key, "")
            if not prompt:
                continue
            # Fill in template variables
            filled = prompt.replace("{profile_str}", profile_str).replace("{posts_str}", posts_str)
            filled = filled.replace("{context_str}", "Previously sent a connection request that was accepted.")
            try:
                response = messager.generate_message(filled)
                messages[output_key] = response
            except Exception as e:
                messages[output_key] = f"[Error generating: {e}]"

        return jsonify({"success": True, "messages": messages, "sample_profile": sample_profile})

    except ImportError as e:
        return jsonify({"success": False, "error": f"Could not import GeminiLinkedInMessager: {e}"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
