from __future__ import annotations

import logging
import os
import socket
import time

from . import jobs, worker

logger = logging.getLogger("lux.runner")


def run() -> None:
    """Run the durable SQLite-backed worker loop."""
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    jobs.recover_on_startup()
    logger.info("Lux external worker %s is ready", worker_id)
    while True:
        job = jobs.claim_next(worker_id)
        if not job:
            time.sleep(float(os.getenv("LUX_WORKER_POLL_SECONDS", "2")))
            continue
        logger.info("Claimed job %s", job["id"])
        worker.run(job["id"])
