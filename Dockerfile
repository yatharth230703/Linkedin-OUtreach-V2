FROM python:3.11-slim

# Install Xvfb and basic X11 dependencies for headful browser
RUN apt-get update && apt-get install -y \
    xvfb \
    cron \
    curl \
    wget \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium AND all its OS dependencies (fonts, libs, etc.)
# playwright install-deps handles all required libraries for headful mode
RUN playwright install chromium && playwright install-deps chromium

# Copy application code
COPY orchestrator.py /app/orchestrator.py
COPY Linkedin_cloud_bot_attio/ /app/Linkedin_cloud_bot_attio/
COPY backend/ /app/backend/

# Setup cron
COPY backend/crontab /etc/cron.d/bot-cron
RUN chmod 0644 /etc/cron.d/bot-cron && crontab /etc/cron.d/bot-cron

# Make scripts executable
RUN chmod +x /app/backend/entrypoint.sh /app/backend/run_daily.sh /app/backend/run_master.sh

# Cloud mode flag for Playwright to use bundled Chromium
ENV CLOUD_MODE=true
# Virtual display for headful Chromium (Xvfb started in entrypoint.sh)
ENV DISPLAY=:99

EXPOSE 8080

CMD ["/app/backend/entrypoint.sh"]
