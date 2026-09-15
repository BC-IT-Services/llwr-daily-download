"""Celery worker for the LLWR daily download.

The gateway owns the nightly schedule (scheduled_jobs) and dispatches
`run_llwr_download` to `llwr_service_queue`; this worker just runs it.
"""

from celery import Celery
from kombu import Queue

from config import settings

QUEUE_NAME = "llwr_service_queue"

celery_core = Celery(
    "llwr_service",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_core.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=settings.celery_task_timeout,
    # Celery's default is 24 hours, which on a shared 4 GB host meant 40,000
    # finished-task results sitting in Redis using 1.4 GB - more than a third
    # of the machine's RAM - and Redis being picked as the OOM victim.
    #
    # Nothing reads a result after the caller has taken it: the gateway's
    # dispatcher polls within a minute of completion and never looks again. The
    # floor is "longest task + polling interval", so an hour is generous even
    # for the 20-minute iTrent extract.
    result_expires=settings.celery_result_expires,
    task_soft_time_limit=max(settings.celery_task_timeout - 30, 30),
    broker_connection_retry_on_startup=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    broker_transport_options={"confirm_publish": True, "global_qos": False},
)

celery_core.conf.task_queues = [Queue(QUEUE_NAME, routing_key=QUEUE_NAME)]
celery_core.conf.task_default_queue = QUEUE_NAME

celery_core.autodiscover_tasks(["tasks"])
