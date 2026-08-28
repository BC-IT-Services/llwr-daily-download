"""Celery tasks exposed by the LLWR microservice."""

import traceback

from celery_app import celery_core

app = celery_core


@app.task(name="run_llwr_download", bind=True)
def run_llwr_download(self):
    """Download the LLWR data summary and upload it to Drive.

    Exceptions propagate so Celery marks the task FAILED and the gateway
    records a failed run — that is what triggers the retry.
    """
    from get_data_summary import get_data_summary

    try:
        return get_data_summary()
    except Exception as e:
        print(f"LLWR download failed: {e}")
        traceback.print_exc()
        raise


@app.task(name="llwr_health")
def llwr_health():
    """Cheap liveness probe for the worker, its config and its Google token."""
    from config import settings
    from google_auth import load_credentials

    google_ok, google_error = False, None
    try:
        load_credentials()
        google_ok = True
    except Exception as e:
        google_error = str(e)

    return {
        "ok": True,
        "portal_configured": bool(settings.portal_username and settings.portal_password),
        "report_year": settings.report_year or "(latest offered)",
        "download_dir": settings.download_dir,
        "drive_upload_enabled": settings.upload_to_drive,
        "google_credentials_ok": google_ok,
        "google_error": google_error,
    }
