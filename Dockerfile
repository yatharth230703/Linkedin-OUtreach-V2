FROM python:3.11-slim

# Install system dependencies for Playwright Chromium and Xvfb
RUN apt-get update && apt-get install -y \
    wget \
    xvfb \
    cron \
    curl \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium (no separate Chrome install needed)
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

EXPOSE 8080

CMD ["/app/backend/entrypoint.sh"]
