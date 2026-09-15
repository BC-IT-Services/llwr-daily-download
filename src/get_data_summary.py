"""Download the LLWR data summary from the Post-16 portal and upload it to Drive.

Container-oriented rewrite of the original script:

* system chromium + chromedriver (no webdriver-manager download at runtime),
* report parameters and paths come from mounted config, not hardcoded,
* failures raise instead of printing and returning, so the Celery task is
  marked FAILED and the gateway schedules a retry. The original swallowed every
  exception, which would have made a broken night look like a successful one.
"""

from __future__ import annotations

import glob
import os
import time
from datetime import datetime

from googleapiclient.http import MediaFileUpload
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

from config import settings
from google_auth import build_auth_service

PROVIDER_DROPDOWN_ID = "reportViewer_ctl08_ctl03_ddValue"
YEAR_DROPDOWN_ID = "reportViewer_ctl08_ctl05_ddValue"
THIRD_DROPDOWN_ID = "reportViewer_ctl08_ctl07_ddValue"
VIEW_BUTTON_ID = "reportViewer_ctl08_ctl00"


class LlwrDownloadError(Exception):
    """Raised when the report cannot be downloaded."""


def _build_driver(download_dir: str):
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    # Without this Chrome exhausts the container's default 64MB /dev/shm and
    # dies mid-render.
    options.add_argument("--disable-dev-shm-usage")

    binary = settings.chrome_binary
    if binary and os.path.exists(binary):
        options.binary_location = binary

    options.add_experimental_option(
        "prefs",
        {
            "download.default_directory": download_dir,
            "download.prompt_for_download": False,
            "directory_upgrade": True,
            "safebrowsing.enabled": True,
        },
    )
    return webdriver.Chrome(options=options)


def _login(driver, wait) -> None:
    username = settings.portal_username
    password = settings.portal_password
    if not username or not password:
        raise LlwrDownloadError(
            "Portal credentials missing. Set portal.username / portal.password in "
            "/config/llwr_config.json (or PORTAL_USER / PORTAL_PASS)."
        )

    print("Logging in to the Post-16 portal...")
    driver.get(settings.portal_login_url)
    wait.until(EC.visibility_of_element_located((By.ID, "f_username"))).send_keys(username)

    password_box = driver.find_element(By.ID, "f_passwd")
    password_box.send_keys(password)
    password_box.send_keys(Keys.RETURN)
    time.sleep(3)


def _select_parameters(driver, wait, year: str) -> None:
    print("Loading report page...")
    driver.get(settings.report_url)

    try:
        provider_dd = wait.until(
            EC.presence_of_element_located((By.ID, PROVIDER_DROPDOWN_ID))
        )
    except Exception as e:
        raise LlwrDownloadError(
            f"Report parameters never appeared at {driver.current_url!r} "
            f"(page title {driver.title!r}). The login most likely failed."
        ) from e

    Select(provider_dd).select_by_visible_text(settings.report_provider)
    time.sleep(2)

    year_dd = Select(driver.find_element(By.ID, YEAR_DROPDOWN_ID))
    available = [o.text.strip() for o in year_dd.options if o.text.strip()]
    if year:
        if year not in available:
            raise LlwrDownloadError(
                f"Report year {year!r} is not offered. Available: {available}. "
                "Update report.year / report.years in /config/llwr_config.json."
            )
        year_dd.select_by_visible_text(year)
    else:
        # No year pinned: take the latest the portal offers, so the job does not
        # silently keep pulling last year's data after the rollover.
        latest = sorted(available)[-1]
        print(f"No year configured - using the latest offered ({latest}).")
        year_dd.select_by_visible_text(latest)
    time.sleep(2)

    third = settings.report_third_parameter
    if third:
        Select(driver.find_element(By.ID, THIRD_DROPDOWN_ID)).select_by_visible_text(third)


def _wait_for_download(download_dir: str, existing: set[str], timeout: int) -> str:
    waited = 0
    while waited < timeout:
        current = set(glob.glob(os.path.join(download_dir, "*.csv")))
        new_files = current - existing
        in_progress = glob.glob(os.path.join(download_dir, "*.crdownload"))
        if new_files and not in_progress:
            return next(iter(new_files))
        time.sleep(1)
        waited += 1

    raise LlwrDownloadError(
        f"No CSV appeared in {download_dir} within {timeout}s. The report may have "
        "returned no data, or the export never started."
    )


def _upload_to_drive(file_path: str, filename: str, drive_folder_id: str) -> str:
    print("Uploading to Google Drive...")
    drive_service = build_auth_service('drive')
    metadata = {"name": filename, "parents": [drive_folder_id]}
    media = MediaFileUpload(file_path, mimetype="text/csv", resumable=True)
    uploaded = drive_service.files().create(
        body=metadata, media_body=media, fields="id"
    ).execute()
    file_id = uploaded.get("id")
    print(f"Uploaded to Drive. File ID: {file_id}")
    return file_id


def _download_one(year: str, drive_folder_id: str) -> dict:
    """Download+upload a single report year in its own browser session.

    A fresh login per year (rather than re-selecting the Year dropdown and
    re-exporting within one session) mirrors the flow the portal's SSRS
    report viewer was actually exercised with, instead of assuming a second
    in-session export is reliable.
    """
    started = datetime.utcnow()
    download_dir = settings.download_dir
    os.makedirs(download_dir, exist_ok=True)

    driver = _build_driver(download_dir)
    wait = WebDriverWait(driver, settings.page_timeout_seconds)

    try:
        _login(driver, wait)
        _select_parameters(driver, wait, year)

        print("Rendering report...")
        driver.find_element(By.ID, VIEW_BUTTON_ID).click()
        time.sleep(5)

        existing = set(glob.glob(os.path.join(download_dir, "*.csv")))

        print("Triggering CSV export...")
        try:
            driver.execute_script("$find('reportViewer').exportReport('CSV');")
        except Exception as e:
            raise LlwrDownloadError(f"Export command failed: {e}") from e

        downloaded = _wait_for_download(
            download_dir, existing, settings.download_timeout_seconds
        )

        # Year is in the filename (not just the destination folder) so two
        # years downloaded in the same run don't overwrite each other's local
        # copy when keep_local_copy is on.
        label = year or "latest"
        filename = f"data_summary_{label}_{datetime.now().strftime('%y-%m-%d')}.csv"
        target = os.path.join(download_dir, filename)
        if os.path.exists(target):
            os.remove(target)
        os.rename(downloaded, target)
        size = os.path.getsize(target)
        print(f"Saved {filename} ({size} bytes)")

        summary = {
            "started_at": started.isoformat(),
            "filename": filename,
            "local_path": target,
            "bytes": size,
            "uploaded_to_drive": False,
            "drive_file_id": None,
        }

        if settings.upload_to_drive:
            summary["drive_file_id"] = _upload_to_drive(target, filename, drive_folder_id)
            summary["uploaded_to_drive"] = True

            if not settings.keep_local_copy:
                os.remove(target)
                summary["local_path"] = None
        else:
            print("Drive upload disabled by config - keeping local copy only.")

        summary["duration_seconds"] = int(
            (datetime.utcnow() - started).total_seconds()
        )
        return summary

    finally:
        driver.quit()


def get_data_summary() -> dict:
    """Run the full download for every configured report year (see
    Settings.report_years), each uploaded to its own Drive folder.

    Every configured year is attempted even if an earlier one fails, so one
    bad year does not stop the other from being fetched. If any year failed,
    this still raises once all attempts are done - a partially successful
    night must not look like a clean one to the scheduler - but the
    exception message includes which years succeeded.
    """
    results: dict[str, dict] = {}
    errors: dict[str, str] = {}

    for report in settings.report_years:
        year = report["year"]
        label = year or "latest"
        try:
            results[label] = _download_one(year, report["drive_folder_id"])
        except Exception as e:
            errors[label] = str(e)
            print(f"LLWR download failed for {label}: {e}")

    if errors:
        raise LlwrDownloadError(
            f"Failed for: {errors}. Succeeded for: {list(results.keys())}"
        )

    return results


if __name__ == '__main__':
    print(get_data_summary())
