FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Chromium and its matching driver come from apt so nothing is downloaded at
# runtime (webdriver-manager needs network access and writable HOME, neither of
# which a locked-down container should rely on).
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Modules import each other by bare name (config, tasks, google_auth).
ENV PYTHONPATH=/app/src
ENV CHROME_BINARY=/usr/bin/chromium

RUN adduser --disabled-password --gecos '' appuser && \
    mkdir -p /data/csvs /secrets && \
    chown -R appuser:appuser /app /data /secrets

USER appuser

VOLUME ["/data"]

# Worker only. The nightly schedule lives in the gateway (scheduled_jobs),
# so a restart of this container never triggers a run.
CMD ["celery", "-A", "tasks", "worker", "--concurrency=1", "--loglevel=info", "-Q", "llwr_service_queue"]
