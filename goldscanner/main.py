"""Entry point: build everything from env and run the scan loop."""

from __future__ import annotations

import logging
import sys
import time

from .client import ShopGoodwillClient
from .config import Config
from .emailer import Emailer
from .scanner import Scanner
from .store import SeenStore
from .vision import VisionScorer


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

    client = ShopGoodwillClient()
    store = SeenStore(config.db_path)
    scorer = (
        VisionScorer(
            client=client,
            target_description=config.target_description,
            api_key=config.anthropic_api_key,
            model=config.model,
            max_images=config.max_images_per_item,
        )
        if config.use_ai
        else None
    )
    emailer = (
        Emailer(
            host=config.smtp_host,
            port=config.smtp_port,
            user=config.smtp_user,
            password=config.smtp_pass,
            sender=config.email_from,
            recipient=config.email_to,
        )
        if config.email_enabled
        else None
    )
    scanner = Scanner(config, client, store, scorer)

    log.info(
        "goldscanner starting. queries=%s ai=%s email=%s db=%s (%d items known)",
        config.queries,
        config.use_ai,
        config.email_enabled,
        config.db_path,
        store.count(),
    )

    while True:
        try:
            matches = scanner.scan_once()
            if matches and emailer is not None:
                try:
                    emailer.send_digest(matches)
                except Exception as exc:  # noqa: BLE001
                    log.error("Failed to send email digest: %s", exc)
        except Exception as exc:  # noqa: BLE001
            log.exception("Scan cycle failed: %s", exc)

        if config.run_once:
            log.info("RUN_ONCE set; exiting after a single scan.")
            break

        log.info("Sleeping %ds until next scan.", config.interval_seconds)
        time.sleep(config.interval_seconds)

    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
