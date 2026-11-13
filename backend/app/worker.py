"""Celery worker.

    celery -A app.worker worker -Q default,render --concurrency 2 --loglevel info

Tasks are acknowledged only after they finish (acks_late) and are re-delivered if a
worker dies mid-task, and every task is idempotent, so interrupted renders resume.
"""
from __future__ import annotations

import logging

from celery import Celery
from celery.signals import worker_ready

from .config import settings
from .db import init_db

celery_app = Celery("studio", broker=settings.redis_url, backend=None)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_default_queue="default",
    broker_transport_options={"visibility_timeout": 4 * 3600},
)


def _register(name: str):
    @celery_app.task(name=f"studio.{name}")
    def _t(*args):
        from .tasks import TASKS

        TASKS[name](*args)

    return _t


for _n in ("storyboard", "render_scene", "assemble", "director_plan"):
    _register(_n)


@worker_ready.connect
def _on_ready(**_):
    init_db()
    from .tasks import recover

    n = recover()
    logging.getLogger(__name__).info("recovery re-queued %d task(s)", n)
    # Fetch the default English narrator voices in the background, so the first
    # render does not have to wait for a download.
    import threading

    from .providers import tts

    threading.Thread(target=tts.preload, daemon=True, name="voice-preload").start()
