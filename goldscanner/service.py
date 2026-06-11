"""Builds and wires the app's components, and owns the scan loop.

Shared by the web server (which serves the UI) and the background scanner thread.
"""

from __future__ import annotations

import logging
import threading
import time

from .client import ShopGoodwillClient
from .config import Config
from .ebay import EbayClient
from .emailer import Emailer
from .etsy import EtsyClient
from .scanner import Scanner
from .store import SETTING_GUIDANCE, SeenStore
from .vision import VisionScorer

log = logging.getLogger(__name__)

# Seeded into the DB on first run (describes the user's reference pieces:
# antique gold / gold-filled bangles with black taille d'épargne enamel).
DEFAULT_GUIDANCE = """\
I am looking for ANTIQUE / VICTORIAN-era gold and gold-filled hinged BANGLE
bracelets.

WHAT MATCHES (say YES):
- Wide, rigid HINGED bangle bracelets, usually with a hinge on one side and a
  box clasp plus a thin safety chain on the other.
- Warm YELLOW or ROSE gold tone. Solid karat gold, gold-filled, and rolled gold
  plate (RGP) all count.
- Decorated with BLACK enamel in the "taille d'épargne" technique: black enamel
  set into engraved channels forming scrollwork, arabesques, foliate vine-and-leaf
  patterns, or symmetric geometric medallions.
- Usually over a finely hand-engraved or engine-turned (machine-stippled) ground.
- Ornately HAND-ENGRAVED antique gold bangles with this same Victorian medallion /
  scroll / floral styling ALSO count even when there is little or no enamel.
- Antique, estate, Victorian, Edwardian, Etruscan-revival styling.

WHAT DOES NOT MATCH (say NO):
- Modern, plain, minimalist, thin-wire, or stacking bangles.
- Costume jewelry, brass, copper, base metal, stainless steel, or fashion gold-tone.
- Bright COLORFUL painted / epoxy "enamel" or modern cloisonné flowers.
- Cuffs that aren't bangle-shaped, charm/chain/tennis bracelets, or watches.
- Bangles set primarily with gemstones or diamonds rather than enamel/engraving.

When unsure between a genuine antique engraved/enamel gold bangle and a modern
look-alike, lean YES if the engraving is fine and Victorian in character.
"""


class Service:
    def __init__(self, config: Config):
        self.config = config
        self.client = ShopGoodwillClient()
        self.store = SeenStore(config.db_path)
        self.scorer = (
            VisionScorer(
                client=self.client,
                store=self.store,
                target_description=config.target_description,
                api_key=config.anthropic_api_key,
                model=config.model,
                max_images=config.max_images_per_item,
                max_examples_each=config.max_examples_each,
            )
            if config.use_ai
            else None
        )
        self.emailer = (
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
        self.extra_sources = self._build_sources(config)
        self.scanner = Scanner(
            config, self.client, self.store, self.scorer,
            extra_sources=self.extra_sources,
        )

        if config.seed_defaults:
            self._seed_default_guidance()

        self._scan_lock = threading.Lock()
        self._stop = threading.Event()
        self.last_scan_at: float | None = None
        self.last_scan_matches: int = 0
        self.scanning: bool = False

    @staticmethod
    def _build_sources(config: Config) -> list:
        sources: list = []
        if config.etsy_enabled and (config.etsy_api_key or config.etsy_urls):
            sources.append(
                EtsyClient(
                    urls=config.etsy_urls,
                    api_key=config.etsy_api_key,
                    queries=config.etsy_queries,
                    limit=config.etsy_limit,
                )
            )
            if not config.etsy_api_key:
                log.warning(
                    "Etsy is in scrape mode (no ETSY_API_KEY) — Etsy's bot "
                    "protection often blocks cloud IPs, so results may be empty. "
                    "Set ETSY_API_KEY for reliable results."
                )
        if config.ebay_enabled and config.ebay_client_id and config.ebay_client_secret:
            sources.append(
                EbayClient(
                    client_id=config.ebay_client_id,
                    client_secret=config.ebay_client_secret,
                    queries=config.ebay_queries,
                    limit=config.ebay_limit,
                    marketplace=config.ebay_marketplace,
                )
            )
        elif config.ebay_enabled:
            log.warning(
                "eBay is enabled but EBAY_CLIENT_ID/EBAY_CLIENT_SECRET are not "
                "set — skipping eBay. Get free keys at https://developer.ebay.com"
            )
        return sources

    def _seed_default_guidance(self) -> None:
        """Populate the guidance once, on first run, without clobbering the user."""
        if self.store.get_setting("guidance_seeded") == "1":
            return
        if not self.store.get_setting(SETTING_GUIDANCE).strip():
            self.store.set_setting(SETTING_GUIDANCE, DEFAULT_GUIDANCE)
            log.info("Seeded default guidance for antique enamel gold bangles.")
        self.store.set_setting("guidance_seeded", "1")

    def scan_once(self) -> int:
        """Run one scan, email new matches, return how many matched.

        Guarded so the periodic loop and a manual "scan now" can't overlap.
        """
        with self._scan_lock:
            self.scanning = True
            try:
                matches = self.scanner.scan_once()
                if matches and self.emailer is not None:
                    try:
                        self.emailer.send_digest(matches)
                    except Exception as exc:  # noqa: BLE001
                        log.error("Failed to send email digest: %s", exc)
                self.last_scan_at = time.time()
                self.last_scan_matches = len(matches)
                return len(matches)
            finally:
                self.scanning = False

    def run_loop(self) -> None:
        """Blocking scan loop until stop() is called."""
        log.info(
            "Scan loop starting. queries=%s ai=%s email=%s interval=%ds",
            self.config.queries,
            self.config.use_ai,
            self.config.email_enabled,
            self.config.interval_seconds,
        )
        while not self._stop.is_set():
            try:
                self.scan_once()
            except Exception as exc:  # noqa: BLE001
                log.exception("Scan cycle failed: %s", exc)
            # Wait interval, but wake immediately on stop.
            self._stop.wait(self.config.interval_seconds)

    def start_background(self) -> threading.Thread:
        thread = threading.Thread(target=self.run_loop, name="scanner", daemon=True)
        thread.start()
        return thread

    def stop(self) -> None:
        self._stop.set()

    def status(self) -> dict:
        counts = self.store.counts()
        return {
            "counts": counts,
            "last_scan_at": self.last_scan_at,
            "last_scan_matches": self.last_scan_matches,
            "scanning": self.scanning,
            "interval_seconds": self.config.interval_seconds,
            "use_ai": self.config.use_ai,
            "queries": self.config.queries,
            "sources": self._source_names(),
        }

    def _source_names(self) -> list[str]:
        names = ["shopgoodwill"]
        for source in self.extra_sources:
            if isinstance(source, EtsyClient):
                names.append("etsy" + ("" if source.api_key else " (scrape)"))
            elif isinstance(source, EbayClient):
                names.append("ebay")
        return names
