"""Celery application for async task processing."""

from kombu import Exchange, Queue
from celery import Celery

celery_app = Celery(
    "chattrainer",
    broker="redis://127.0.0.1:6379/0",
    backend="redis://127.0.0.1:6379/1",
    include=["app.tasks.faq_tasks"],
)

faq_exchange = Exchange("faq", type="direct")

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=50,
    task_soft_time_limit=1800,
    task_time_limit=3600,
    task_default_queue="faq",
    task_queues=(
        Queue("faq", faq_exchange, routing_key="faq.default", queue_arguments={"x-max-priority": 10}),
        Queue("faq.high", faq_exchange, routing_key="faq.high", queue_arguments={"x-max-priority": 10}),
        Queue("faq.embed", faq_exchange, routing_key="faq.embed", queue_arguments={"x-max-priority": 10}),
    ),
    task_routes={
        "faq.run_pipeline": {"queue": "faq", "routing_key": "faq.default"},
        "faq.run_incremental": {"queue": "faq.high", "routing_key": "faq.high"},
        "faq.embed_batch": {"queue": "faq.embed", "routing_key": "faq.embed"},
    },
)

# Ensure FAQ tasks are always registered in worker process.
import app.tasks.faq_tasks  # noqa: E402,F401
