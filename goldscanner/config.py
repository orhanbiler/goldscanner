"""Environment-driven configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _list(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return [part.strip() for part in raw.split(",") if part.strip()]


# Mounted persistent volumes to prefer for the database, in order.
_VOLUME_DIRS = ("/data", "/var/data", "/mnt/data")


def resolve_db_path(raw: str) -> str:
    """Keep the database on a persistent volume when one is mounted.

    A bare/relative path (e.g. "goldscanner.db") inside an ephemeral container
    gets wiped on every redeploy — taking favorites and training examples with
    it. If a volume is mounted (Railway's /data), put the DB there even when the
    configured path is relative. Absolute paths are always respected as-is.
    """
    if os.path.isabs(raw):
        return raw
    for vol in _VOLUME_DIRS:
        if os.path.isdir(vol) and os.access(vol, os.W_OK):
            return os.path.join(vol, os.path.basename(raw))
    return raw


def db_is_persistent(path: str) -> bool:
    abspath = os.path.abspath(path)
    return any(abspath.startswith(vol + os.sep) for vol in _VOLUME_DIRS)


@dataclass
class Config:
    # What to look for
    queries: list[str] = field(default_factory=list)
    target_description: str = ""
    # Cheap title pre-filter: an item must contain at least one of these tokens
    # in its title before we spend an AI call on it. Empty = no pre-filter.
    title_keywords: list[str] = field(default_factory=list)
    min_confidence: float = 0.6
    use_ai: bool = True
    max_images_per_item: int = 3
    # Multi-item lots get more photos so the model can hunt for a bangle inside.
    lot_max_images: int = 6
    # Title tokens that suggest a listing is a multi-item lot.
    lot_keywords: list[str] = field(
        default_factory=lambda: [
            "lot", "jewelry", "jewellery", "estate", "collection", "bundle",
        ]
    )
    # Max labeled reference photos of each kind (positive/negative) fed to the
    # model per scored item.
    max_examples_each: int = 4

    # Claude
    anthropic_api_key: str | None = None
    model: str = "claude-haiku-4-5"

    # Cadence
    interval_seconds: int = 900
    pages_per_query: int = 2
    run_once: bool = False

    # Etsy source (official API when ETSY_API_KEY is set, else best-effort scrape).
    etsy_enabled: bool = True
    etsy_urls: list[str] = field(default_factory=list)
    etsy_api_key: str = ""
    etsy_queries: list[str] = field(default_factory=list)
    etsy_limit: int = 50

    # eBay source (official Browse API; needs client id/secret).
    ebay_enabled: bool = True
    ebay_client_id: str = ""
    ebay_client_secret: str = ""
    ebay_queries: list[str] = field(default_factory=list)
    ebay_marketplace: str = "EBAY_US"
    ebay_limit: int = 50

    # Max previously-rejected items re-evaluated per "re-score" run.
    rescore_limit: int = 150

    # Two-tier vision: matches/borderline calls from the cheap screening model
    # get a final verdict from this stronger vision model (high-res detail).
    # Empty string disables the second pass.
    verify_model: str = "claude-opus-4-8"
    verify_threshold: float = 0.35

    # Seed the built-in guidance (antique enamel bangles) into the DB on first run.
    seed_defaults: bool = True

    # Persistence
    db_path: str = "goldscanner.db"

    # Email
    email_enabled: bool = True
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    email_from: str = ""
    email_to: str = ""

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            queries=_list(
                "GOLDSCANNER_QUERIES",
                [
                    "gold bangle",
                    "gold bracelet",
                    "gold filled bangle",
                    "gold filled bracelet",
                    "gold filled antique jewelry lot",
                    "gold filled victorian jewelry lot",
                    "gold lot",
                    "gold filled lot",
                ],
            ),
            target_description=os.environ.get(
                "GOLDSCANNER_TARGET_DESCRIPTION",
                "An antique / Victorian-era gold or gold-filled hinged bangle "
                "bracelet with ornate engraving, typically decorated with BLACK "
                "taille d'épargne enamel in scrollwork, foliate/vine, or geometric "
                "patterns over a finely engine-turned ground. Ornately hand-engraved "
                "antique gold bangles, and antique GEM-SET gold bangles (seed "
                "pearls, emeralds, garnets, opals) with Victorian filigree or "
                "Etruscan-revival styling, also count even without enamel.",
            ),
            title_keywords=_list(
                "GOLDSCANNER_TITLE_KEYWORDS",
                ["bangle", "bracelet", "lot", "jewelry", "jewellery", "estate"],
            ),
            min_confidence=_float("GOLDSCANNER_MIN_CONFIDENCE", 0.6),
            use_ai=_bool("GOLDSCANNER_USE_AI", True),
            max_images_per_item=_int("GOLDSCANNER_MAX_IMAGES_PER_ITEM", 3),
            lot_max_images=_int("GOLDSCANNER_MAX_IMAGES_LOT", 6),
            lot_keywords=_list(
                "GOLDSCANNER_LOT_KEYWORDS",
                ["lot", "jewelry", "jewellery", "estate", "collection", "bundle"],
            ),
            max_examples_each=_int("GOLDSCANNER_MAX_EXAMPLES", 4),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
            model=os.environ.get("GOLDSCANNER_MODEL", "claude-haiku-4-5"),
            interval_seconds=_int("GOLDSCANNER_INTERVAL_SECONDS", 900),
            pages_per_query=_int("GOLDSCANNER_PAGES_PER_QUERY", 2),
            run_once=_bool("GOLDSCANNER_RUN_ONCE", False),
            etsy_enabled=_bool("GOLDSCANNER_ETSY_ENABLED", True),
            etsy_urls=_list(
                "GOLDSCANNER_ETSY_URLS",
                [
                    "https://www.etsy.com/market/antique_victorian_gold_bangle",
                    "https://www.etsy.com/market/antique_victorian_gold_bangle?ref=pagination&page=2",
                ],
            ),
            etsy_api_key=os.environ.get("ETSY_API_KEY", ""),
            etsy_queries=_list(
                "GOLDSCANNER_ETSY_QUERIES",
                ["antique victorian gold bangle", "victorian enamel gold bangle"],
            ),
            etsy_limit=_int("GOLDSCANNER_ETSY_LIMIT", 50),
            ebay_enabled=_bool("GOLDSCANNER_EBAY_ENABLED", True),
            ebay_client_id=os.environ.get("EBAY_CLIENT_ID", ""),
            ebay_client_secret=os.environ.get("EBAY_CLIENT_SECRET", ""),
            ebay_queries=_list(
                "GOLDSCANNER_EBAY_QUERIES",
                ["antique victorian gold bangle enamel", "victorian gold filled bangle"],
            ),
            ebay_marketplace=os.environ.get("EBAY_MARKETPLACE", "EBAY_US"),
            ebay_limit=_int("GOLDSCANNER_EBAY_LIMIT", 50),
            rescore_limit=_int("GOLDSCANNER_RESCORE_LIMIT", 150),
            verify_model=os.environ.get("GOLDSCANNER_VERIFY_MODEL", "claude-opus-4-8"),
            verify_threshold=_float("GOLDSCANNER_VERIFY_THRESHOLD", 0.35),
            seed_defaults=_bool("GOLDSCANNER_SEED_DEFAULTS", True),
            db_path=resolve_db_path(
                os.environ.get("GOLDSCANNER_DB_PATH", "goldscanner.db")
            ),
            email_enabled=_bool("GOLDSCANNER_EMAIL_ENABLED", True),
            smtp_host=os.environ.get("SMTP_HOST", ""),
            smtp_port=_int("SMTP_PORT", 587),
            smtp_user=os.environ.get("SMTP_USER", ""),
            smtp_pass=os.environ.get("SMTP_PASS", ""),
            email_from=os.environ.get("EMAIL_FROM", os.environ.get("SMTP_USER", "")),
            email_to=os.environ.get("EMAIL_TO", ""),
        )

    def validate(self) -> list[str]:
        """Return a list of human-readable configuration problems."""
        problems: list[str] = []
        if not self.queries:
            problems.append("No search queries set (GOLDSCANNER_QUERIES).")
        if self.use_ai and not self.anthropic_api_key:
            problems.append(
                "AI scoring is on but ANTHROPIC_API_KEY is not set. "
                "Set the key or disable with GOLDSCANNER_USE_AI=false."
            )
        if self.email_enabled:
            missing = [
                n
                for n, v in [
                    ("SMTP_HOST", self.smtp_host),
                    ("SMTP_USER", self.smtp_user),
                    ("SMTP_PASS", self.smtp_pass),
                    ("EMAIL_TO", self.email_to),
                ]
                if not v
            ]
            if missing:
                problems.append(
                    "Email is enabled but missing: "
                    + ", ".join(missing)
                    + " (or set GOLDSCANNER_EMAIL_ENABLED=false)."
                )
        return problems
