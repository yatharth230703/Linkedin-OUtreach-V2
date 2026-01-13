# LinkedIn Bot Orchestrator Setup Guide

## Overview
This guide will help you set up the `orchestrator.py` script to run automatically via your system scheduler (macOS Cron or Windows Task Scheduler).

## Prerequisites

### 1. Python Environment
Ensure your Python environment has all required dependencies:
```bash
pip install undetected-chromedriver selenium supabase python-dotenv psutil
```

### 2. File Structure
Your directory should look like this:
```
your_project/
├── orchestrator.py
├── main_bots/
│   ├── msg_draft_connection_bot1.py
│   ├── send_message.py
│   └── send_followup.py
├── user_data_yatharth/  (Chrome profile)
├── .env
└── daily_log.txt (created automatically)
```

### 3. Safety File (Optional)
Create a safety file mechanism to manually stop the orchestrator:
```bash
# To stop orchestrator if running
touch safety_stop.txt

# To allow orchestrator to run
rm safety_stop.txt
```

## macOS Setup (Cron)

### 1. Make Script Executable
```bash
chmod +x orchestrator.py
```

### 2. Find Python Path
```bash
which python3
# Example output: /usr/local/bin/python3
```

### 3. Edit Crontab
```bash
crontab -e
```

### 4. Add Cron Entry
Add this line to run daily at 2:00 AM:
```bash
0 2 * * * cd /path/to/your/project && /usr/local/bin/python3 orchestrator.py >> cron_output.log 2>&1
```

**Important Notes:**
- Replace `/path/to/your/project` with your actual project path
- Replace `/usr/local/bin/python3` with your Python path
- The script will wake your Mac from sleep if needed

### 5. Verify Cron Setup
```bash
crontab -l  # List current cron jobs
```

### 6. Enable Wake from Sleep (macOS)
To allow cron to wake your Mac:
```bash
sudo pmset -a womp 1  # Wake on network access
sudo pmset -a acwake 1  # Wake on power adapter connection
```

## Windows Setup (Task Scheduler)

### 1. Open Task Scheduler
- Press `Win + R`, type `taskschd.msc`, press Enter
- Or search "Task Scheduler" in Start menu

### 2. Create Basic Task
1. Click "Create Basic Task..." in the right panel
2. Name: "LinkedIn Bot Orchestrator"
3. Description: "Daily LinkedIn automation orchestrator"

### 3. Set Trigger
1. Choose "Daily"
2. Set start time: 2:00 AM
3. Recur every: 1 day

### 4. Set Action
1. Choose "Start a program"
2. Program/script: `C:\Python39\python.exe` (your Python path)
3. Arguments: `orchestrator.py`
4. Start in: `C:\path\to\your\project` (your project directory)

### 5. Configure Conditions
In the task properties:
- **Conditions tab:**
  - ✅ Wake the computer to run this task
  - ✅ Start the task only if the computer is on AC power (optional)
- **Settings tab:**
  - ✅ Allow task to be run on demand
  - ✅ Run task as soon as possible after a scheduled start is missed

### 6. Set User Account
- Run whether user is logged on or not
- Use your admin account credentials

## Testing the Setup

### 1. Manual Test
Run the orchestrator manually first:
```bash
cd /path/to/your/project
python3 orchestrator.py
```

### 2. Check Logs
Monitor the daily log:
```bash
tail -f daily_log.txt
```

### 3. Verify Timing
The orchestrator will:
- Start at your scheduled time (e.g., 2:00 AM)
- Wait 0-180 minutes randomly before beginning
- Execute bots sequentially with 5-15 minute breaks
- Complete within 5 hours total

## Safety Features

### 1. User Presence Detection
The orchestrator automatically detects:
- Active user sessions
- High CPU usage (>50%)
- GUI applications running
- Safety file existence

### 2. Manual Safety Stop
Create a safety file to stop execution:
```bash
touch safety_stop.txt
```

### 3. Execution Window
- Maximum 5-hour execution window
- Automatic timing adjustment to fit window
- Graceful abort if timing constraints can't be met

## Monitoring and Logs

### 1. Daily Log File
Check `daily_log.txt` for:
- Wake time and calculated delays
- Bot execution status
- Safety checks and aborts
- Error messages

### 2. Execution Stats
Detailed JSON stats saved as:
`execution_stats_YYYYMMDD_HHMMSS.json`

### 3. Log Rotation (Optional)
Add log rotation to prevent large files:
```bash
# Add to crontab for weekly log cleanup
0 0 * * 0 find /path/to/your/project -name "daily_log.txt" -size +10M -delete
```

## Troubleshooting

### Common Issues

1. **Script doesn't start:**
   - Check cron/task scheduler logs
   - Verify Python path and permissions
   - Ensure working directory is correct

2. **Chrome profile issues:**
   - Verify `user_data_yatharth` directory exists
   - Check Chrome isn't running when orchestrator starts
   - Ensure proper file permissions

3. **Safety aborts:**
   - Check if safety file exists
   - Verify user isn't logged in during execution
   - Review CPU usage patterns

4. **Bot execution failures:**
   - Check individual bot logs
   - Verify Supabase credentials in `.env`
   - Ensure LinkedIn session is valid

### Debug Mode
Add debug logging by modifying the orchestrator:
```python
# In setup_logging method, change level to DEBUG
self.logger.setLevel(logging.DEBUG)
```

## Security Considerations

1. **Credentials Protection:**
   - Keep `.env` file secure
   - Don't commit credentials to version control
   - Use proper file permissions (600)

2. **Chrome Profile:**
   - Store Chrome profile securely
   - Regular profile cleanup
   - Monitor for suspicious activity

3. **Network Security:**
   - Use VPN if required
   - Monitor IP reputation
   - Implement rate limiting

## Maintenance

### Weekly Tasks
- Review execution logs
- Clean up old log files
- Verify bot success rates
- Update Chrome if needed

### Monthly Tasks
- Review safety mechanisms
- Update dependencies
- Backup configuration
- Performance optimization

## Support

If you encounter issues:
1. Check the daily log file first
2. Review execution stats JSON
3. Test individual bots manually
4. Verify system scheduler configuration
5. Check user presence detection

The orchestrator is designed to be robust and self-healing, but proper setup and monitoring ensure optimal performance.