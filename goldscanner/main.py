"""Entry point.

Default: start the background scanner thread AND serve the web UI (Railway).
With GOLDSCANNER_RUN_ONCE=true: run a single scan and exit (cron / testing).
"""

from __future__ import annotations

import logging
import os
import sys

from .config import Config
from .service import Service


def build_logger() -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    return logging.getLogger("goldscanner")


def main() -> int:
    log = build_logger()
    config = Config.from_env()

    problems = config.validate()
    if problems:
        for p in problems:
            log.error("Config problem: %s", p)
        return 2

    service = Service(config)
    log.info(
        "goldscanner ready. queries=%s ai=%s email=%s db=%s (%d listings known)",
        config.queries,
        config.use_ai,
        config.email_enabled,
        config.db_path,
        service.store.count(),
    )

    if config.run_once:
        matches = service.scan_once()
        log.info("RUN_ONCE: single scan complete, %d match(es).", matches)
        service.store.close()
        return 0

    # Long-running: background scanner + web server.
    import uvicorn

    from .web import create_app

    service.start_background()
    app = create_app(service)
    port = int(os.environ.get("PORT", "8000"))
    log.info("Serving web UI on 0.0.0.0:%d", port)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
