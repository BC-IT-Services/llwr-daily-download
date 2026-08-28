# LLWR Daily Download

Downloads the LLWR data-summary report from the Post-16 Portal
(post16-portal-service.gov.wales) with headless Chromium and uploads the CSV to
Google Drive.

Runs as a **Celery worker microservice**. The nightly schedule lives in the
api-gateway (`scheduled_jobs` table), not here.

## Configuration

Config comes from JSON files mounted at `/config`, matching the other services:

| Path | Purpose |
|---|---|
| `/config/ipc_config.json` | Shared RabbitMQ / Redis settings |
| `/config/llwr_config.json` | Portal credentials, report parameters, Drive target |
| `/config/google/credentials.json` | Google OAuth client (read-only) |
| `/config/google/token.json` | Authorised user token — **must be mounted writable** |

Copy `config/llwr_config.json.example` and fill it in. `PORTAL_USER` /
`PORTAL_PASS` environment variables still work as a fallback.

```yaml
services:
  llwr-worker:
    image: ghcr.io/<org>/llwr-daily-download:latest
    volumes:
      - /srv/config:/config:ro
      - /srv/config/google:/config/google:rw   # token.json must be writable
      - llwr_data:/data
    restart: unless-stopped
```

### Google authentication

The original script called `InstalledAppFlow.run_local_server()`, which opens a
browser for consent — impossible in a container, where it would hang until the
task timed out rather than failing. The containerised version **only refreshes**
a mounted token and raises a clear error if it cannot.

Generate the token once on a workstation:

```bash
python src/google_auth.py --authorise
```

Then copy `token.json` into the mount. It must be writable so refreshed access
tokens persist; if it is read-only the job still runs but pays a refresh every
time, and a warning is logged. To verify a mounted token:

```bash
python src/google_auth.py
```

### Report parameters

| Setting | Notes |
|---|---|
| `report.provider` | Provider dropdown text, e.g. `Bridgend College (F0009004)` |
| `report.year` | Year dropdown text. **Leave blank to always take the latest year the portal offers** — otherwise the job keeps pulling the pinned year after the rollover |
| `report.third_parameter` | Third dropdown, defaults to `All` |
| `output.upload_to_drive` | Set false to download only |
| `output.keep_local_copy` | Set false to delete the CSV after a successful upload |

## Scheduling

The gateway dispatches `run_llwr_download` to `llwr_service_queue` when the
night's slot is due. Restarting this container never triggers a run; a missed
night runs at the earliest opportunity; failures retry after a back-off.

Manage it in sdadmin → **Scheduled Jobs**, or via the gateway API:

```bash
curl -X POST https://api.bridgend.ac.uk/api/v2/jobs/llwr_daily_download/run
```

### Tasks

| Task | Purpose |
|---|---|
| `run_llwr_download` | Download the report and upload to Drive. |
| `llwr_health` | Config probe — includes whether the mounted Google token is usable. |

## Notes

- Chromium and its matching driver are installed from apt in the image;
  `webdriver-manager` is not used, so nothing is downloaded at runtime.
- Failures raise rather than being printed and swallowed. This matters: the
  scheduler treats a task that returns normally as a successful night, so a
  swallowed exception would silently skip a day's data.
