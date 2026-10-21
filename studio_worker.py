#!/usr/bin/env python3
"""Dedicated generation worker — pulls jobs from Supabase and runs up to N in parallel."""

from __future__ import annotations

import os
import socket
import sys
import time


def main() -> int:
    os.environ.setdefault("STUDIO_QUEUE_BACKEND", "postgres")
    os.environ.setdefault("STUDIO_INLINE_WORKERS", "0")

    import app as app_module
    from studio_jobs import StudioJobRunner

    worker_id = f"{socket.gethostname()}-{os.getpid()}"
    runner = StudioJobRunner(app_module.supabase, app_module.app)

    slots = runner.max_slots
    app_module.app.logger.info("studio worker %s starting — %s parallel slots", worker_id, slots)
    if slots < 1:
        app_module.app.logger.error("No worker slots (set XAI_API_KEYS and STUDIO_MAX_CONCURRENT_JOBS).")
        return 1

    runner.run_worker_pool(worker_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())