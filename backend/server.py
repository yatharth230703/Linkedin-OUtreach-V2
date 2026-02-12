"""
LinkedIn Bot Backend API
Minimal Flask server to receive cookies, config, and control bot execution.
"""

import os
import sys
import json
import subprocess
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

# Track the running bot process
bot_process = None


def check_api_key():
    key = request.headers.get("X-Api-Key", "")
    if key != API_KEY:
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    return None


@app.before_request
def auth_middleware():
    if request.method == "OPTIONS":
        # Return a proper 200 with CORS headers for preflight
        from flask import make_response
        resp = make_response("", 200)
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Api-Key"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return resp
    result = check_api_key()
    if result:
        return result


@app.route("/api/cookies", methods=["POST"])
def receive_cookies():
    data = request.get_json()
    if not data or "cookies" not in data:
        return jsonify({"success": False, "error": "No cookies provided"}), 400

    with open(COOKIES_FILE, "w") as f:
        json.dump(data["cookies"], f, indent=2)

    # Save browser storage if provided
    if data.get("browserStorage"):
        with open(STORAGE_FILE, "w") as f:
            json.dump(data["browserStorage"], f, indent=2)

    return jsonify({"success": True, "count": len(data["cookies"])})


@app.route("/api/config", methods=["POST"])
def receive_config():
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "No config provided"}), 400

    config = {
        "daily_connect": data.get("daily_connect", 20),
        "daily_message": data.get("daily_message", 15),
        "daily_followup": data.get("daily_followup", 10),
    }

    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)

    return jsonify({"success": True, "config": config})


@app.route("/api/start", methods=["POST"])
def start_bot():
    global bot_process

    if not os.path.exists(COOKIES_FILE):
        return jsonify({"success": False, "error": "No cookies synced yet. Sync cookies first."}), 400

    # Check if bot is already running
    if bot_process and bot_process.poll() is None:
        return jsonify({"success": False, "error": "Bot is already running."}), 400

    # Write enabled flag
    with open(ENABLED_FLAG, "w") as f:
        f.write(datetime.now(timezone.utc).isoformat())

    # Cookie injection now happens at runtime inside login_credentials.py
    # Just launch the orchestrator directly
    # Use daily_log.txt as the main log - orchestrator + all bots write here
    daily_log_path = os.path.join(PROJECT_DIR, "daily_log.txt")
    log_file = open(daily_log_path, "a")
    log_file.write(f"\n--- Bot started at {datetime.now(timezone.utc).isoformat()} ---\n")
    log_file.write("--- Launching orchestrator (cookies will be injected at runtime) ---\n")
    log_file.flush()

    # Also note in run_log
    with open(RUN_LOG, "a") as rl:
        rl.write(f"\n--- Bot started at {datetime.now(timezone.utc).isoformat()} ---\n")

    # Launch orchestrator as subprocess (-u for unbuffered output)
    cmd = [sys.executable, "-u", os.path.join(PROJECT_DIR, "orchestrator.py"), "--test", "--template_1"]

    bot_process = subprocess.Popen(
        cmd,
        cwd=PROJECT_DIR,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )

    return jsonify({
        "success": True,
        "message": f"Cookies injected, bot started (PID: {bot_process.pid}).",
    })


@app.route("/api/stop", methods=["POST"])
def stop_bot():
    global bot_process

    if bot_process and bot_process.poll() is None:
        # Terminate the bot process tree
        try:
            os.killpg(os.getpgid(bot_process.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            bot_process.terminate()
        bot_process = None

    if os.path.exists(ENABLED_FLAG):
        os.remove(ENABLED_FLAG)

    with open(RUN_LOG, "a") as f:
        f.write(f"\n--- Bot stopped at {datetime.now(timezone.utc).isoformat()} ---\n")

    return jsonify({"success": True, "message": "Bot stopped."})


@app.route("/api/status", methods=["GET"])
def get_status():
    global bot_process

    # Check if process is still alive
    process_alive = bot_process is not None and bot_process.poll() is None
    flag_exists = os.path.exists(ENABLED_FLAG)
    running = process_alive and flag_exists

    # If process died but flag exists, clean up
    if not process_alive and flag_exists:
        running = False

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
        "pid": bot_process.pid if process_alive else None,
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
