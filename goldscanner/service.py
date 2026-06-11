"""Builds and wires the app's components, and owns the scan loop.

Shared by the web server (which serves the UI) and the background scanner thread.
"""

from __future__ import annotations

import logging
import threading
import time

from .activity import SUCCESS, WARN, ActivityLog
from .client import ShopGoodwillClient
from .config import Config, db_is_persistent
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
        self.activity = ActivityLog()
        self.client = ShopGoodwillClient()
        self.store = SeenStore(config.db_path)
        self._log_persistence()
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
            activity=self.activity,
        )

        if config.seed_defaults:
            self._seed_default_guidance()

        self._scan_lock = threading.Lock()
        self._stop = threading.Event()
        self.last_scan_at: float | None = None
        self.last_scan_matches: int = 0
        self.scanning: bool = False

    def _log_persistence(self) -> None:
        path = self.config.db_path
        examples = self.store.example_counts()["total"]
        if db_is_persistent(path):
            self.activity.add(
                f"💾 Database is on a persistent volume ({path}) — your favorites "
                f"and {examples} training example(s) are saved across deploys.",
                SUCCESS,
            )
        else:
            self.activity.add(
                f"⚠️ Database is at '{path}', which is NOT on a persistent volume. "
                "Favorites and training examples will reset on the next redeploy. "
                "Add a Railway Volume mounted at /data to fix this permanently.",
                WARN,
            )

    def _build_sources(self, config: Config) -> list:
        sources: list = []
        self.source_notes: dict[str, str] = {}
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
                self.source_notes["etsy"] = (
                    "scrape mode — set ETSY_API_KEY (free at etsy.com/developers) "
                    "for reliable results; cloud IPs are usually bot-blocked"
                )
                log.warning("Etsy is in scrape mode (no ETSY_API_KEY); results may be empty.")
        elif config.etsy_enabled:
            self.source_notes["etsy"] = "disabled — no ETSY_API_KEY or URLs configured"

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
            self.source_notes["ebay"] = (
                "not configured — set EBAY_CLIENT_ID and EBAY_CLIENT_SECRET "
                "(free at developer.ebay.com)"
            )
            log.warning(
                "eBay is enabled but EBAY_CLIENT_ID/EBAY_CLIENT_SECRET are not "
                "set — skipping eBay."
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
                        self.activity.add(
                            f"📧 Emailed you a digest of {len(matches)} match(es).",
                            SUCCESS,
                        )
                    except Exception as exc:  # noqa: BLE001
                        log.error("Failed to send email digest: %s", exc)
                        self.activity.add(
                            "📧 Couldn't send the email digest "
                            "(Railway blocks outbound email) — set "
                            "GOLDSCANNER_EMAIL_ENABLED=false to silence this.",
                            WARN,
                        )
                self.last_scan_at = time.time()
                self.last_scan_matches = len(matches)
                return len(matches)
            finally:
                self.scanning = False

    def run_loop(self) -> None:
        """Blocking scan loop until stop() is called."""
        srcs = ", ".join(self._source_names())
        self.activity.add(
            f"🚀 goldscanner is up and watching: {srcs}. "
            f"Scanning automatically every {self._mins()} minute(s).",
            SUCCESS,
        )
        while not self._stop.is_set():
            try:
                self.scan_once()
            except Exception as exc:  # noqa: BLE001
                log.exception("Scan cycle failed: %s", exc)
                self.activity.add(f"❌ Scan hit an error: {exc}", WARN)
            if self._stop.is_set():
                break
            self.activity.add(
                f"😴 Resting for {self._mins()} minute(s) until the next scan.",
                "muted",
            )
            # Wait interval, but wake immediately on stop.
            self._stop.wait(self.config.interval_seconds)

    def _mins(self) -> int:
        return max(1, round(self.config.interval_seconds / 60))

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
            "source_stats": self.scanner.last_source_stats,
            "source_notes": self.source_notes,
        }

    def _source_names(self) -> list[str]:
        names = ["shopgoodwill"]
        for source in self.extra_sources:
            if isinstance(source, EtsyClient):
                names.append("etsy" + ("" if source.api_key else " (scrape)"))
            elif isinstance(source, EbayClient):
                names.append("ebay")
        return names
