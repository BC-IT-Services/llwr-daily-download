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
| `/secrets/token.json` | Authorised user token — **must be mounted writable**. Own top-level mount, deliberately not under `/config` |

Copy `config/llwr_config.json.example` and fill it in. `PORTAL_USER` /
`PORTAL_PASS` environment variables still work as a fallback.

```yaml
services:
  llwr-worker:
    image: ghcr.io/<org>/llwr-daily-download:latest
    volumes:
      - ${CONFIG_LOCATION}:/config:ro                 # *_config.json
      - ${CREDENTIALS_LOCATION}:/secrets/token.json   # writable, NOT under /config
      - llwr_data:/data
    restart: unless-stopped
```

`/secrets` is the default token location, so no extra environment variable is
needed. Set `GOOGLE_CONFIG_DIR` only if you want it somewhere else.

Only `token.json` needs mounting at runtime — it already contains the client id,
secret and refresh token. `credentials.json` is used solely for the one-off
interactive authorisation on a workstation.

> **Do not nest a writable mount inside a read-only one.** Mounting
> `/config:ro` and then `/config/google/token.json:rw` fails at container start
> with `make mountpoint ... read-only file system`. Docker mounts the shorter
> path first, then has to create the `/config/google` mountpoint *inside* the
> already read-only `/config` — so it never even reaches the host file, and no
> amount of `chmod` on the host changes it. Nesting on the **host** side is
> fine; it is the container-side path that matters.

If you would rather keep the token under `/config`, drop the `:ro` so the
whole mount is writable and set `GOOGLE_CONFIG_DIR=/config`.

### File permissions

The container runs as `appuser`, so the token must be writable by *other*:

```bash
chmod o+rw /home/manage/api-config/llwrsync/token.json
```

A read-only token is not fatal — the job still runs, but it re-refreshes every
time and logs a warning.

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
| `report.year` | Year dropdown text for a single-year setup. **Leave blank to always take the latest year the portal offers** — otherwise the job keeps pulling the pinned year after the rollover |
| `report.years` | Download *multiple* years in one run, each to its own Drive folder — see below. Takes priority over `report.year` when set |
| `report.third_parameter` | Third dropdown, defaults to `All` |
| `output.upload_to_drive` | Set false to download only |
| `output.keep_local_copy` | Set false to delete the CSV after a successful upload |

#### Multiple years

The portal only shows one academic year as "current" — around rollover, the
year that just ended drops out of `report.year`'s "latest offered" fallback
while it may still need a daily pull (e.g. late enrolments, corrections).
`report.years` downloads each listed year in its own browser session and
uploads it to its own Drive folder:

```json
"report": {
  "provider": "Bridgend College (F0009004)",
  "years": [
    { "year": "2025", "drive_folder_id": "1sJzKUn9kLm8JPhLr7y0SB4hUd9YyqATZ" },
    { "year": "2026", "drive_folder_id": "1Td-1x1rA2Qok3MCVRi5lo1IMdBnC6cph" }
  ]
}
```

Every listed year is attempted even if an earlier one fails, so one bad year
doesn't stop the others being fetched — the task still raises (and so still
retries) if any year failed, listing which years succeeded in the error.
Each downloaded file is named `data_summary_<year>_<date>.csv` so two years
in the same run don't overwrite each other's local copy.

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
