"""FastAPI app over the store (T8b).

create_app(store, runtime=None): with a Runtime, the app's lifespan runs the
scheduler as a background task for as long as the server is up -- one process,
as 00-overview.md says. Without one (tests), nothing polls; handlers just read
and write the store they were given.

Every handler that touches the store is `async def`: the store's sqlite3
connection belongs to the event loop's thread, and FastAPI runs a plain `def`
handler in a worker thread.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

log = logging.getLogger(__name__)


def _log_crash(task):
    if not task.cancelled() and task.exception() is not None:
        log.error("scheduler stopped", exc_info=task.exception())


def create_app(store, runtime=None):
    @asynccontextmanager
    async def lifespan(app):
        stop, task = asyncio.Event(), None
        if runtime is not None:
            task = asyncio.create_task(runtime.scheduler.run(stop))
            task.add_done_callback(_log_crash)
        try:
            yield
        finally:
            if task is not None:
                stop.set()  # Scheduler.run drains in-flight fetches before returning
                await asyncio.gather(task, return_exceptions=True)

    app = FastAPI(title="Drop Radar", lifespan=lifespan)
    app.state.store, app.state.runtime = store, runtime

    @app.get("/healthz")
    async def healthz():
        """Liveness only -- no data, no auth."""
        return {"ok": True}

    return app
