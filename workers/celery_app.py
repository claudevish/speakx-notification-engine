"""Celery application configuration — broker, queues, beat schedule for all periodic tasks."""

from celery import Celery
from celery.schedules import crontab
from kombu import Queue

from app.config.settings import settings

celery_app = Celery("speakx_notifications")

celery_app.conf.update(
    include=[
        "workers.ingestion_worker",
        "workers.notification_worker",
        "workers.temporal_worker",
    ],
    broker_url=settings.redis_url,
    result_backend=settings.redis_url,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_queues=(
        Queue("default"),
        Queue("notifications"),
        Queue("ingestion"),
    ),
    task_routes={
        "workers.notification_worker.*": {"queue": "notifications"},
        "workers.ingestion_worker.*": {"queue": "ingestion"},
    },
    beat_schedule={
        "dormancy-scan": {
            "task": "workers.temporal_worker.run_dormancy_scan",
            "schedule": crontab(minute=0),
        },
        "chapter-transition-scan": {
            "task": "workers.temporal_worker.run_chapter_transition_scan",
            "schedule": crontab(minute=30),
        },
        "notification-slot-1": {
            "task": "workers.notification_worker.run_notification_slot",
            "schedule": crontab(minute=0, hour=7),
            "args": (1,),
        },
        "notification-slot-2": {
            "task": "workers.notification_worker.run_notification_slot",
            "schedule": crontab(minute=30, hour=12),
            "args": (2,),
        },
        "notification-slot-3": {
            "task": "workers.notification_worker.run_notification_slot",
            "schedule": crontab(minute=0, hour=18),
            "args": (3,),
        },
        "notification-slot-4": {
            "task": "workers.notification_worker.run_notification_slot",
            "schedule": crontab(minute=30, hour=19),
            "args": (4,),
        },
        "notification-slot-5": {
            "task": "workers.notification_worker.run_notification_slot",
            "schedule": crontab(minute=0, hour=21),
            "args": (5,),
        },
        "clevertap-sync": {
            "task": "workers.temporal_worker.sync_clevertap_events",
            "schedule": crontab(minute="*/30"),
        },
        "daily-snapshots": {
            "task": "workers.temporal_worker.run_daily_snapshots",
            "schedule": crontab(minute=0, hour=2),
        },
        "process-pending-notifications": {
            "task": "workers.notification_worker.process_pending_notifications",
            "schedule": 60.0,
        },
    },
)
