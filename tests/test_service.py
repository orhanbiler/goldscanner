"""Tests for Service-level behavior (default guidance seeding)."""

import os
import tempfile

from goldscanner.config import Config
from goldscanner.service import _GUIDANCE_V1, DEFAULT_GUIDANCE, GUIDANCE_VERSION, Service
from goldscanner.store import SETTING_GUIDANCE


def _cfg(path, **kw):
    base = dict(queries=["bangle"], use_ai=False, email_enabled=False, db_path=path)
    base.update(kw)
    return Config(**base)


def test_seeds_default_guidance_on_first_run():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        svc = Service(_cfg(path, seed_defaults=True))
        assert svc.store.get_setting(SETTING_GUIDANCE) == DEFAULT_GUIDANCE
        assert "taille d'épargne" in svc.store.get_setting(SETTING_GUIDANCE)
        svc.store.close()
    finally:
        os.remove(path)


def test_does_not_overwrite_user_guidance():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        svc = Service(_cfg(path, seed_defaults=False))
        svc.store.set_setting(SETTING_GUIDANCE, "my own notes")
        svc.store.close()

        # Re-open with seeding ON — must not clobber the user's text.
        svc2 = Service(_cfg(path, seed_defaults=True))
        assert svc2.store.get_setting(SETTING_GUIDANCE) == "my own notes"
        svc2.store.close()
    finally:
        os.remove(path)


def test_seed_disabled_leaves_guidance_empty():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        svc = Service(_cfg(path, seed_defaults=False))
        assert svc.store.get_setting(SETTING_GUIDANCE) == ""
        svc.store.close()
    finally:
        os.remove(path)


def test_unedited_v1_guidance_upgrades_to_v2():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        # Simulate a DB seeded by the previous version of the app.
        svc = Service(_cfg(path, seed_defaults=False))
        svc.store.set_setting(SETTING_GUIDANCE, _GUIDANCE_V1)
        svc.store.set_setting("guidance_seeded", "1")
        svc.store.close()

        svc2 = Service(_cfg(path, seed_defaults=True))
        assert svc2.store.get_setting(SETTING_GUIDANCE) == DEFAULT_GUIDANCE
        assert "GEM-SET" in svc2.store.get_setting(SETTING_GUIDANCE)
        assert svc2.store.get_setting("guidance_seeded") == GUIDANCE_VERSION
        svc2.store.close()
    finally:
        os.remove(path)


def test_edited_guidance_survives_upgrade():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        svc = Service(_cfg(path, seed_defaults=False))
        svc.store.set_setting(SETTING_GUIDANCE, _GUIDANCE_V1 + "\nMY EDIT")
        svc.store.set_setting("guidance_seeded", "1")
        svc.store.close()

        svc2 = Service(_cfg(path, seed_defaults=True))
        assert svc2.store.get_setting(SETTING_GUIDANCE).endswith("MY EDIT")
        assert svc2.store.get_setting("guidance_seeded") == GUIDANCE_VERSION
        svc2.store.close()
    finally:
        os.remove(path)
