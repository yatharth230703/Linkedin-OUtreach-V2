#!/usr/bin/env python3
"""
LinkedIn Bot Orchestrator - Master Control Script
==================================================

A robust Python orchestrator that manages the execution of LinkedIn automation bots
with advanced safety features, timing controls, and user presence detection.

Features:
- 5-hour execution window with random start delays
- Sequential bot execution with human-like breaks
- User presence detection (kill switch)
- Process management with error handling
- Comprehensive logging
- Safety file monitoring

Author: Senior Python Automation Engineer
Version: 1.0
"""

import os
import sys
import time
import random
import subprocess
import psutil
import logging
from datetime import datetime, timedelta
from pathlib import Path
import json

# Add project root for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from Linkedin_cloud_bot_attio.notifier import (
    notify_campaign_started,
    notify_campaign_completed,
    notify_bot_started,
    notify_bot_completed,
    notify_bot_failed,
    notify_error,
    set_active_account as set_notifier_account,
)


class LinkedInBotOrchestrator:
    """
    Master orchestrator for LinkedIn automation bots with safety features.
    """
    
    def __init__(self, test_mode=False, cloud_mode=False, account_name=""):
        # Configuration
        self.EXECUTION_WINDOW_HOURS = 5
        self.MAX_INITIAL_DELAY_MINUTES = 180  # 3 hours
        self.MIN_BREAK_SECONDS = 300  # 5 minutes
        self.MAX_BREAK_SECONDS = 900  # 15 minutes
        self.SAFETY_FILE_PATH = "safety_stop.txt"
        self.LOG_FILE = "daily_log.txt"

        # Initialize mode flags first
        self.test_mode = test_mode
        self.cloud_mode = cloud_mode
        self.account_name = account_name

        # Initialize logging BEFORE using it
        self.setup_logging()

        # Apply test mode settings after logging is set up
        if test_mode:
            self.MAX_INITIAL_DELAY_MINUTES = 0  # No initial delay in test mode
            self.MIN_BREAK_SECONDS = 10  # 10 seconds
            self.MAX_BREAK_SECONDS = 30  # 30 seconds
            self.logger.info("🧪 TEST MODE ENABLED - No initial delay, reduced timings and safety checks")

        # Cloud mode: skip user presence checks, shorter initial delay
        if cloud_mode:
            self.MAX_INITIAL_DELAY_MINUTES = 30  # 0-30min random delay in cloud
            self.logger.info("☁️ CLOUD MODE ENABLED - Skipping user presence checks, 0-30min initial delay")

        # Set active account for notification routing
        set_notifier_account(account_name)

        # Log account selection
        self.logger.info(f"🎯 Using account: {account_name}")

        # Bot execution order and paths
        self.script_dir = Path(__file__).parent
        self.main_bots_dir = self.script_dir / "Linkedin_cloud_bot_attio" / "playwright_bots"

        self.bot_sequence = [
            {
                "name": "Connection Bot",
                "script": "msg_draft_connection_bot1.py",
                "description": "Drafts connection requests"
            },
            {
                "name": "Message Bot",
                "script": "send_message.py",
                "description": "Sends queued messages"
            },
            {
                "name": "Follow-up Bot",
                "script": "send_followup.py",
                "description": "Sends follow-up messages"
            }
        ]

        # Status file for extension visibility
        self.status_dir = self.script_dir / "backend"

        # Execution tracking
        self.start_time = None
        self.execution_stats = {
            "wake_time": None,
            "calculated_delay": None,
            "actual_start_time": None,
            "bot_executions": [],
            "total_duration": None,
            "safety_aborts": 0,
            "errors": []
        }

    def setup_logging(self):
        """Initialize logging configuration with both file and console output."""
        log_format = '%(asctime)s - %(levelname)s - %(message)s'
        
        # Create logger
        self.logger = logging.getLogger('LinkedInOrchestrator')
        self.logger.setLevel(logging.INFO)
        
        # Clear any existing handlers
        self.logger.handlers.clear()
        
        # File handler
        file_handler = logging.FileHandler(self.LOG_FILE, mode='a', encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        file_formatter = logging.Formatter(log_format)
        file_handler.setFormatter(file_formatter)
        
        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter('%(asctime)s - %(message)s')
        console_handler.setFormatter(console_formatter)
        
        # Add handlers
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

    def _write_phase_status(self, phase, detail=""):
        """Write current phase to a status file so the extension can read it."""
        slug = self.account_name.strip().lower().replace(" ", "_")
        status_path = self.status_dir / f"phase_status_{slug}.json"
        status = {
            "phase": phase,
            "detail": detail,
            "account": self.account_name,
            "updated_at": datetime.now().isoformat(),
        }
        try:
            with open(status_path, "w") as f:
                json.dump(status, f)
        except Exception:
            pass  # Non-critical

    def log_separator(self):
        """Add a visual separator to logs."""
        separator = "=" * 80
        self.logger.info(separator)

    def check_user_presence(self):
        """
        User presence detection based on actual input activity.
        Returns True if user is actively using keyboard/mouse, False if system is safe to use.
        """
        # Skip safety checks in test/cloud mode
        if self.test_mode or self.cloud_mode:
            self.logger.info("🧪 Test/cloud mode - skipping user presence checks")
            return False
            
        try:
            # Method 1: Check for safety file (manual override)
            if Path(self.SAFETY_FILE_PATH).exists():
                self.logger.warning(f"🛑 Safety file detected: {self.SAFETY_FILE_PATH}")
                return True
            
            # Method 2: Check for recent input activity (macOS)
            if sys.platform == 'darwin':
                return self._check_macos_input_activity()
            
            # Method 3: Check for recent input activity (Linux/other)
            else:
                return self._check_linux_input_activity()
            
        except Exception as e:
            self.logger.error(f"❌ Error checking user presence: {e}")
            # Err on the side of caution
            return True

    def _check_macos_input_activity(self):
        """
        Check for recent keyboard/mouse activity on macOS using system idle time.
        Returns True if user has been active recently.
        """
        try:
            # Get system idle time using ioreg (more reliable than other methods)
            result = subprocess.run(
                ['ioreg', '-c', 'IOHIDSystem'], 
                capture_output=True, 
                text=True, 
                timeout=10
            )
            
            # Parse idle time from ioreg output
            for line in result.stdout.split('\n'):
                if 'HIDIdleTime' in line:
                    # Extract idle time in nanoseconds
                    idle_ns = int(line.split('=')[1].strip())
                    idle_seconds = idle_ns / 1_000_000_000
                    
                    # Consider user active if idle time < 60 seconds
                    if idle_seconds < 60:
                        self.logger.info(f"⌨️ Recent input activity detected (idle: {idle_seconds:.1f}s)")
                        return True
                    else:
                        self.logger.info(f"✅ No recent input activity (idle: {idle_seconds:.1f}s)")
                        return False
            
            # Fallback: if we can't parse idle time, check for active Terminal sessions
            self.logger.warning("⚠️ Could not determine idle time, checking active sessions")
            return self._check_active_sessions()
            
        except subprocess.TimeoutExpired:
            self.logger.warning("⚠️ Input activity check timed out")
            return True
        except Exception as e:
            self.logger.warning(f"⚠️ macOS input check failed: {e}")
            return self._check_active_sessions()

    def _check_linux_input_activity(self):
        """
        Check for recent keyboard/mouse activity on Linux systems.
        Returns True if user has been active recently.
        """
        try:
            # Try using xprintidle if available (X11 systems)
            result = subprocess.run(
                ['xprintidle'], 
                capture_output=True, 
                text=True, 
                timeout=5
            )
            
            if result.returncode == 0:
                idle_ms = int(result.stdout.strip())
                idle_seconds = idle_ms / 1000
                
                # Consider user active if idle time < 60 seconds
                if idle_seconds < 60:
                    self.logger.info(f"⌨️ Recent input activity detected (idle: {idle_seconds:.1f}s)")
                    return True
                else:
                    self.logger.info(f"✅ No recent input activity (idle: {idle_seconds:.1f}s)")
                    return False
            
        except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
            pass
        
        # Fallback for systems without xprintidle
        self.logger.info("⚠️ xprintidle not available, checking active sessions")
        return self._check_active_sessions()

    def _check_active_sessions(self):
        """
        Fallback method: Check for active user sessions.
        This is less accurate but works as a safety net.
        """
        try:
            active_sessions = []
            for user in psutil.users():
                # Only count interactive sessions (not system/daemon users)
                if user.terminal and user.terminal not in ['console', None]:
                    active_sessions.append(f"{user.name}@{user.terminal}")
            
            if active_sessions:
                self.logger.info(f"👤 Active user sessions: {active_sessions}")
                return True
            else:
                self.logger.info("✅ No active user sessions")
                return False
                
        except Exception as e:
            self.logger.warning(f"⚠️ Session check failed: {e}")
            return True  # Err on the side of caution

    def wait_for_user_inactivity(self, max_wait_minutes=30):
        """
        Wait for user to become inactive before proceeding.
        Returns True if safe to proceed, False if timeout reached.
        """
        self.logger.info(f"⏳ Waiting for user inactivity (max {max_wait_minutes} minutes)...")
        
        start_wait = datetime.now()
        check_interval = 60  # Check every minute
        
        while (datetime.now() - start_wait).total_seconds() < (max_wait_minutes * 60):
            if not self.check_user_presence():
                self.logger.info("✅ User inactive - safe to proceed")
                return True
            
            self.logger.info(f"👤 User still active, waiting {check_interval}s...")
            time.sleep(check_interval)
        
        self.logger.warning(f"⏰ Timeout reached after {max_wait_minutes} minutes")
        return False

    def calculate_execution_timing(self):
        """
        Calculate random initial delay and validate execution window.
        Returns (initial_delay_seconds, estimated_end_time).
        """
        # Random initial delay (0 to 3 hours)
        initial_delay_minutes = random.randint(0, self.MAX_INITIAL_DELAY_MINUTES)
        initial_delay_seconds = initial_delay_minutes * 60
        
        # Estimate total execution time
        estimated_bot_time = 45 * 60  # 45 minutes per bot (conservative)
        estimated_break_time = 3 * ((self.MIN_BREAK_SECONDS + self.MAX_BREAK_SECONDS) / 2)  # Average breaks
        estimated_total_execution = (len(self.bot_sequence) * estimated_bot_time) + estimated_break_time
        
        # Calculate end time
        start_time = datetime.now() + timedelta(seconds=initial_delay_seconds)
        estimated_end_time = start_time + timedelta(seconds=estimated_total_execution)
        
        # Validate against 5-hour window
        window_end = datetime.now() + timedelta(hours=self.EXECUTION_WINDOW_HOURS)
        
        if estimated_end_time > window_end:
            # Reduce initial delay to fit in window
            max_safe_delay = (window_end - datetime.now() - timedelta(seconds=estimated_total_execution)).total_seconds()
            if max_safe_delay > 0:
                initial_delay_seconds = min(initial_delay_seconds, int(max_safe_delay))
                self.logger.warning(f"⚠️ Reduced initial delay to fit 5-hour window: {initial_delay_seconds/60:.1f} minutes")
            else:
                self.logger.error("❌ Cannot fit execution in 5-hour window!")
                return None, None
        
        return initial_delay_seconds, estimated_end_time

    def execute_bot(self, bot_config):
        """
        Execute a single bot script with error handling and logging.
        Returns (success, execution_time, error_message).
        """
        bot_name = bot_config["name"]
        script_path = self.main_bots_dir / bot_config["script"]
        
        self.logger.info(f"🚀 Starting {bot_name}: {bot_config['description']}")
        self._write_phase_status(bot_name, bot_config["description"])
        notify_bot_started(bot_name, self.account_name)

        if not script_path.exists():
            error_msg = f"Script not found: {script_path}"
            self.logger.error(f"❌ {error_msg}")
            return False, 0, error_msg
        
        start_time = datetime.now()
        
        try:
            # Build command with --account_name for all bots
            cmd = [sys.executable, "-u", str(script_path), "--account_name", self.account_name]
            self.logger.info(f"   🎯 Using account: {self.account_name}")

            # Execute bot script with real-time log streaming
            # Output goes to both the log file and is captured for summary
            log_file_path = Path(self.LOG_FILE)
            with open(log_file_path, "a", encoding="utf-8") as log_f:
                log_f.write(f"\n{'='*60}\n")
                log_f.write(f"[{bot_name}] REAL-TIME OUTPUT START\n")
                log_f.write(f"{'='*60}\n")
                log_f.flush()

                process = subprocess.Popen(
                    cmd,
                    cwd=str(self.main_bots_dir),
                    stdout=log_f,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )

                # Wait for process to complete (with timeout)
                try:
                    returncode = process.wait(timeout=3600)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                    raise

                log_f.write(f"\n{'='*60}\n")
                log_f.write(f"[{bot_name}] REAL-TIME OUTPUT END\n")
                log_f.write(f"{'='*60}\n")
                log_f.flush()

            execution_time = (datetime.now() - start_time).total_seconds()

            if returncode == 0:
                self.logger.info(f"✅ {bot_name} completed successfully in {execution_time/60:.1f} minutes")
                notify_bot_completed(bot_name, f"Finished in {execution_time/60:.1f} min", self.account_name)
                return True, execution_time, None
            else:
                error_msg = f"Exit code {returncode}"
                self.logger.error(f"❌ {bot_name} failed: {error_msg}")
                notify_bot_failed(bot_name, error_msg, self.account_name)
                return False, execution_time, error_msg
                
        except subprocess.TimeoutExpired:
            execution_time = (datetime.now() - start_time).total_seconds()
            error_msg = "Execution timeout (1 hour)"
            self.logger.error(f"⏰ {bot_name} timed out after {execution_time/60:.1f} minutes")
            notify_bot_failed(bot_name, error_msg, self.account_name)
            return False, execution_time, error_msg

        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds()
            error_msg = str(e)
            self.logger.error(f"💥 {bot_name} crashed: {error_msg}")
            notify_bot_failed(bot_name, error_msg, self.account_name)
            return False, execution_time, error_msg

    def human_break(self):
        """
        Implement human-like break between bot executions with safety checks.
        """
        break_duration = random.randint(self.MIN_BREAK_SECONDS, self.MAX_BREAK_SECONDS)
        break_minutes = break_duration / 60
        
        self._write_phase_status("Break", f"{break_minutes:.0f} min pause")
        self.logger.info(f"☕ Taking human break: {break_minutes:.1f} minutes ({break_duration}s)")
        
        # Break the sleep into chunks for safety checks
        chunk_size = 30  # Check every 30 seconds
        remaining_time = break_duration
        
        while remaining_time > 0:
            sleep_time = min(chunk_size, remaining_time)
            time.sleep(sleep_time)
            remaining_time -= sleep_time
            
            # Safety check during break
            if self.check_user_presence():
                self.logger.warning("🛑 User presence detected during break!")
                self.execution_stats["safety_aborts"] += 1
                return False
        
        self.logger.info("✅ Break completed - ready for next bot")
        return True

    def run_orchestration(self):
        """
        Main orchestration logic with full safety and timing controls.
        """
        self.log_separator()
        self.logger.info("🎬 LinkedIn Bot Orchestrator Starting")
        self.log_separator()
        
        # Record wake time
        wake_time = datetime.now()
        self.execution_stats["wake_time"] = wake_time.isoformat()
        self.logger.info(f"⏰ Wake time: {wake_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Calculate execution timing
        initial_delay, estimated_end = self.calculate_execution_timing()
        if initial_delay is None:
            self.logger.error("❌ Cannot proceed - timing calculation failed")
            return False
        
        self.execution_stats["calculated_delay"] = initial_delay / 60  # Store in minutes
        self.logger.info(f"🎲 Calculated initial delay: {initial_delay/60:.1f} minutes")
        self.logger.info(f"📅 Estimated completion: {estimated_end.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Initial safety check
        if self.check_user_presence():
            self.logger.warning("🛑 User presence detected at startup!")
            if not self.wait_for_user_inactivity():
                self.logger.error("❌ Aborting - user remained active")
                return False
        
        # Initial delay with periodic safety checks
        self._write_phase_status("Waiting", f"Initial delay: {initial_delay/60:.0f} min")
        self.logger.info(f"💤 Starting initial delay: {initial_delay/60:.1f} minutes")
        
        chunk_size = 300  # Check every 5 minutes
        remaining_delay = initial_delay
        
        while remaining_delay > 0:
            sleep_time = min(chunk_size, remaining_delay)
            time.sleep(sleep_time)
            remaining_delay -= sleep_time
            
            # Safety check during delay
            if self.check_user_presence():
                self.logger.warning("🛑 User presence detected during initial delay!")
                if not self.wait_for_user_inactivity():
                    self.logger.error("❌ Aborting - user became active")
                    return False
            
            if remaining_delay > 0:
                self.logger.info(f"⏳ Delay remaining: {remaining_delay/60:.1f} minutes")
        
        # Record actual start time
        actual_start = datetime.now()
        self.execution_stats["actual_start_time"] = actual_start.isoformat()
        self.logger.info(f"🚀 Starting bot sequence at: {actual_start.strftime('%Y-%m-%d %H:%M:%S')}")
        self._write_phase_status("Starting", "Bot sequence beginning")
        notify_campaign_started(self.account_name)

        # Execute bot sequence
        successful_bots = 0
        
        for i, bot_config in enumerate(self.bot_sequence):
            self.log_separator()
            
            # Pre-execution safety check
            if self.check_user_presence():
                self.logger.warning(f"🛑 User presence detected before {bot_config['name']}!")
                if not self.wait_for_user_inactivity():
                    self.logger.error("❌ Aborting sequence - user became active")
                    break
            
            # Execute bot
            success, exec_time, error = self.execute_bot(bot_config)
            
            # Record execution stats
            bot_stats = {
                "name": bot_config["name"],
                "script": bot_config["script"],
                "start_time": (datetime.now() - timedelta(seconds=exec_time)).isoformat(),
                "end_time": datetime.now().isoformat(),
                "duration_seconds": exec_time,
                "success": success,
                "error": error
            }
            self.execution_stats["bot_executions"].append(bot_stats)
            
            if success:
                successful_bots += 1
            else:
                self.execution_stats["errors"].append(f"{bot_config['name']}: {error}")
            
            # Break between bots (except after last bot)
            if i < len(self.bot_sequence) - 1:
                if not self.human_break():
                    self.logger.error("❌ Aborting sequence - safety break failed")
                    break
        
        # Final statistics
        total_duration = (datetime.now() - actual_start).total_seconds()
        self.execution_stats["total_duration"] = total_duration
        
        self.log_separator()
        self.logger.info("📊 EXECUTION SUMMARY")
        self.log_separator()
        self.logger.info(f"✅ Successful bots: {successful_bots}/{len(self.bot_sequence)}")
        self.logger.info(f"⏱️ Total execution time: {total_duration/60:.1f} minutes")
        self.logger.info(f"🛑 Safety aborts: {self.execution_stats['safety_aborts']}")
        self.logger.info(f"❌ Errors: {len(self.execution_stats['errors'])}")
        
        if self.execution_stats["errors"]:
            self.logger.info("🔥 Error details:")
            for error in self.execution_stats["errors"]:
                self.logger.info(f"   - {error}")
        
        # Save detailed stats to JSON
        stats_file = f"execution_stats_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        try:
            with open(stats_file, 'w') as f:
                json.dump(self.execution_stats, f, indent=2)
            self.logger.info(f"📄 Detailed stats saved to: {stats_file}")
        except Exception as e:
            self.logger.error(f"⚠️ Could not save stats file: {e}")
        
        self.log_separator()
        self.logger.info("🎬 LinkedIn Bot Orchestrator Complete")
        self.log_separator()
        self._write_phase_status("Completed", f"{successful_bots}/{len(self.bot_sequence)} bots OK")

        notify_campaign_completed(
            successful_bots, len(self.bot_sequence), total_duration / 60, self.account_name
        )

        return successful_bots == len(self.bot_sequence)


def main():
    """
    Main entry point for the orchestrator.
    """
    import argparse
    
    # Add command line argument parsing
    parser = argparse.ArgumentParser(description='LinkedIn Bot Orchestrator')
    parser.add_argument('--test', action='store_true',
                       help='Run in test mode (reduced delays, skip safety checks)')
    parser.add_argument('--cloud', action='store_true',
                       help='Run in cloud mode (skip user presence checks, shorter initial delay)')
    parser.add_argument('--account_name', type=str, required=True,
                       help='Account name (lead_manager) to process leads for')

    args = parser.parse_args()

    try:
        orchestrator = LinkedInBotOrchestrator(test_mode=args.test, cloud_mode=args.cloud, account_name=args.account_name)
        success = orchestrator.run_orchestration()
        
        # Exit with appropriate code
        sys.exit(0 if success else 1)
        
    except KeyboardInterrupt:
        print("\n🛑 Orchestrator interrupted by user")
        notify_error("Orchestrator interrupted by user", args.account_name)
        sys.exit(130)
    except Exception as e:
        print(f"💥 Critical orchestrator error: {e}")
        notify_error(f"Critical orchestrator crash: {e}", args.account_name)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()