"""Job dispatch: Celery + Redis in production, a thread pool for local dev/tests."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from .config import settings

log = logging.getLogger(__name__)
_pool: ThreadPoolExecutor | None = None


def _run_inline(name: str, *args):
    from .tasks import TASKS

    try:
        TASKS[name](*args)
    except Exception:
        log.exception("inline task %s failed", name)


def enqueue(name: str, *args) -> None:
    global _pool
    if settings.queue_backend == "inline":
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="studio-job")
        _pool.submit(_run_inline, name, *args)
        return
    from .worker import celery_app

    queue_name = "render" if name == "render_scene" else "default"
    celery_app.send_task(f"studio.{name}", args=list(args), queue=queue_name)


def health() -> dict:
    if settings.queue_backend == "inline":
        return {"backend": "inline", "ok": True}
    try:
        import redis

        redis.Redis.from_url(settings.redis_url, socket_timeout=1).ping()
        return {"backend": "celery", "ok": True}
    except Exception as e:
        return {"backend": "celery", "ok": False, "error": str(e)}
